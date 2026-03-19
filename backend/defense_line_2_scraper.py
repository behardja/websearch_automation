"""
2nd Line of Defense: Playwright Browser Automation.

Uses Playwright to launch a headless Chromium browser, navigate to the
state search page, fill in the form fields, click Search, and parse the
results from the rendered DOM.

This handles cases where:
- The site requires JavaScript rendering
- Session tokens or cookies are needed
- The 1st line (direct HTTP) is blocked

May fail if:
- CAPTCHA is presented
- IP blocking is enforced
- The DOM structure changes significantly
"""

import argparse
import asyncio
import json

from .config import STATE_CONFIGS
from .models import LicenseResult, VerificationResponse, DefenseLine


async def search_license(
    license_number: str,
    state: str = "TX",
    trade_name: str | None = None,
    address: str | None = None,
    city: str | None = None,
    headless: bool = True,
) -> VerificationResponse:
    """
    Automate the state search page using Playwright.
    """
    cfg = STATE_CONFIGS.get(state)
    if not cfg:
        return VerificationResponse(
            license_number=license_number,
            state=state,
            verified=False,
            defense_line_used=DefenseLine.PLAYWRIGHT_SCRAPER,
            error=f"No config for state: {state}",
        )

    fids = cfg.field_ids

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        try:
            if state == "GA":
                results = await _scrape_georgia(page, cfg, license_number)
            elif state == "FL":
                results = await _scrape_florida(page, cfg, license_number)
            else:
                results = await _scrape_default(page, cfg, fids, license_number, trade_name, address, city)

            return VerificationResponse(
                license_number=license_number,
                state=state,
                verified=len(results) > 0,
                defense_line_used=DefenseLine.PLAYWRIGHT_SCRAPER,
                results=results,
            )

        except Exception as e:
            return VerificationResponse(
                license_number=license_number,
                state=state,
                verified=False,
                defense_line_used=DefenseLine.PLAYWRIGHT_SCRAPER,
                error=str(e),
            )
        finally:
            await browser.close()


async def _scrape_default(
    page, cfg, fids, license_number, trade_name=None, address=None, city=None,
) -> list[LicenseResult]:
    """Default scraper for Kendo grid states (e.g., Texas)."""
    # Step 1: Navigate to search page
    await page.goto(cfg.search_page, wait_until="networkidle")

    # Step 2: Select business type from dropdown (if this state has one)
    if cfg.has_business_type_dropdown and "business_type" in fids:
        await page.select_option(
            f"#{fids['business_type']}",
            value=cfg.business_type_value,
        )

    # Wait for the license search fields to appear
    await page.wait_for_selector(f"#{fids['license_number']}", state="visible")

    # Step 3: Fill in search fields
    await page.fill(f"#{fids['license_number']}", license_number)

    if trade_name and "trade_name" in fids:
        await page.fill(f"#{fids['trade_name']}", trade_name)
    if address and "address" in fids:
        await page.fill(f"#{fids['address']}", address)
    if city and "city" in fids:
        await page.fill(f"#{fids['city']}", city)

    # Step 4: Click Search
    await page.click(f"#{fids['search_button']}")

    # Step 5: Wait for results grid to populate
    grid_id = fids.get("result_grid", "grdLicense")
    row_selector = cfg.result_row_selector or "tbody tr.k-master-row"
    await page.wait_for_load_state("networkidle")
    try:
        await page.wait_for_selector(
            f"#{grid_id} {row_selector}",
            state="visible",
            timeout=10000,
        )
    except Exception:
        pass

    # Step 6: Parse results from the DOM
    return await _parse_license_grid(page, grid_id, row_selector, cfg.grid_column_map)


async def _scrape_georgia(page, cfg, license_number: str) -> list[LicenseResult]:
    """Scraper for Georgia GTC — JavaScript SPA with AJAX-rendered results.

    After getting search results, clicks into each result's detail view
    to extract full license information including expiration date.
    """
    fids = cfg.field_ids

    # Navigate to the GTC landing page with retry (site rate-limits aggressively)
    for attempt in range(3):
        try:
            await page.goto(cfg.base_url + "/_/", wait_until="domcontentloaded", timeout=30000)
            search_link = await page.wait_for_selector(
                "text=Search for a License", state="visible", timeout=30000,
            )
            break
        except Exception:
            if attempt == 2:
                raise
            await asyncio.sleep(5 * (attempt + 1))

    # Click "Search for a License" to navigate to the search form
    await search_link.click()

    # Wait for the SPA to render the search form
    await page.wait_for_selector(f"#{fids['license_type_radio']}", state="visible", timeout=30000)

    # Select "Alcohol License" radio button (required — not selected by default)
    # Use JS click to bypass the SPA's busy overlay that intercepts pointer events
    await asyncio.sleep(2)
    await page.evaluate(f"document.querySelector('#{fids['license_type_radio']}').click()")
    await asyncio.sleep(1)

    # Fill the license number
    await page.fill(f"#{fids['license_number']}", license_number)

    # Click Search button
    await page.click(f"#{fids['search_button']}")

    # Wait for results table to appear (the results section is initially hidden)
    try:
        await page.wait_for_selector(
            "table#Dd-51 tbody.DocTableBody tr.TDR",
            state="visible",
            timeout=15000,
        )
    except Exception:
        return []  # No results

    # Collect basic info from search results rows first
    rows = await page.query_selector_all("table#Dd-51 tbody.DocTableBody tr.TDR")
    row_count = len(rows)

    results = []
    for idx in range(row_count):
        # Re-query rows each iteration (DOM refreshes after navigating back)
        rows = await page.query_selector_all("table#Dd-51 tbody.DocTableBody tr.TDR")
        if idx >= len(rows):
            break

        row = rows[idx]
        cells = await row.query_selector_all("td")
        cell_texts = []
        for cell in cells:
            text = await cell.inner_text()
            cell_texts.append(text.strip())

        if len(cell_texts) < 6:
            continue

        # Columns: Name | Address | License # | License Type | Taxing Jurisdiction | Status
        base = {
            "doing_business_as": cell_texts[0],
            "location_address": cell_texts[1],
            "license_number": cell_texts[2],
            "license_type": cell_texts[3],
            "jurisdiction": cell_texts[4],
            "state": "GA",
            "extra_details": {"status": cell_texts[5]},
        }

        # Click the name link to open detail view
        detail_fields = await _get_georgia_detail(page, row)
        # Merge core fields directly, extras into extra_details
        for k, v in detail_fields.items():
            if k in ("legal_name", "doing_business_as", "license_type",
                      "expiration_date", "jurisdiction", "location_address",
                      "license_number"):
                base[k] = v
            else:
                base["extra_details"][k] = v

        results.append(LicenseResult(**base))

    return results


async def _get_georgia_detail(page, row) -> dict:
    """Click into a Georgia result row's detail view and extract all fields."""
    detail = {}

    try:
        # Click the name link (first cell contains an anchor with class DFL DCL)
        name_link = await row.query_selector("a.DFL.DCL")
        if not name_link:
            return detail

        await name_link.click()

        # Wait for the detail panel to load
        await page.wait_for_selector("#caption2_Dd-h1", state="visible", timeout=10000)

        # Map of detail element IDs to field names
        ga_detail_map = {
            "Dd-i1": "legal_name",
            "Dd-j1": "location_address",
            "Dd-k1": "registration_year",
            "Dd-l1": "license_number",
            "Dd-m1": "license_type",
            "Dd-n1": "ownership_type",
            "Dd-o1": "status",
            "Dd-p1": "county",
            "Dd-q1": "business_type",
            "Dd-r1": "effective_date",
            "Dd-s1": "expiration_date",
            "Dd-t1": "doing_business_as",
            "Dd-u1": "alcohol_sold",
            "Dd-v1": "consumption",
            "Dd-w1": "jurisdiction_type",
            "Dd-x1": "jurisdiction",
        }

        for elem_id, field_name in ga_detail_map.items():
            el = await page.query_selector(f"#{elem_id}")
            if not el:
                continue
            raw = await el.inner_text()
            # Format is "Label:            Value" — extract the value after the colon
            if ":" in raw:
                value = raw.split(":", 1)[1].strip()
            else:
                value = raw.strip()
            if value:
                detail[field_name] = value

        # Navigate back to search results
        back_btn = await page.query_selector("#Dd-w")
        if back_btn:
            await back_btn.click()
            await page.wait_for_selector(
                "table#Dd-51 tbody.DocTableBody tr.TDR",
                state="visible",
                timeout=10000,
            )

    except Exception:
        # If detail extraction fails, we still have the base search result data
        try:
            back_btn = await page.query_selector("#Dd-w")
            if back_btn:
                await back_btn.click()
                await page.wait_for_selector(
                    "table#Dd-51 tbody.DocTableBody tr.TDR",
                    state="visible",
                    timeout=10000,
                )
        except Exception:
            pass

    return detail


async def _scrape_florida(page, cfg, license_number: str) -> list[LicenseResult]:
    """Scraper for Florida DBPR — fill license number form, parse HTML results."""
    # Navigate to the license number search page
    await page.goto(cfg.search_page, wait_until="networkidle")

    # Fill license number
    await page.fill(f"input[name='{cfg.field_ids['license_number']}']", license_number)

    # Click Search
    await page.click(f"button[name='{cfg.field_ids['search_button']}']")
    await page.wait_for_load_state("networkidle")

    # Parse results from the rendered HTML
    results = []
    rows = await page.query_selector_all("tr[height='40']")

    i = 0
    while i < len(rows):
        row = rows[i]
        cells = await row.query_selector_all("td[align='center']")

        if len(cells) < 4:
            i += 1
            continue

        cell_texts = []
        for c in cells:
            text = await c.inner_text()
            cell_texts.append(text.strip())

        # Columns: License Type | Name | Name Type | License Number/Rank | Status/Expires
        name_type = cell_texts[2] if len(cell_texts) > 2 else ""
        trade_name = cell_texts[1] if len(cell_texts) > 1 else ""
        lic_info = cell_texts[3] if len(cell_texts) > 3 else ""
        status_info = cell_texts[4] if len(cell_texts) > 4 else ""

        lic_parts = lic_info.split("\n")
        parsed_lic = lic_parts[0].strip() if lic_parts else ""

        status_parts = status_info.split("\n")
        expiration = status_parts[-1].strip() if len(status_parts) > 1 else ""

        # Get address from the next row
        address = ""
        if i + 1 < len(rows):
            addr_row = rows[i + 1]
            addr_tds = await addr_row.query_selector_all("td[align='left']")
            for td in addr_tds:
                text = await td.inner_text()
                if "License Location" in text:
                    # Address is in the paired td
                    parent_tr = await td.query_selector("xpath=..")
                    if parent_tr:
                        all_tds = await parent_tr.query_selector_all("td")
                        if len(all_tds) >= 2:
                            address = await all_tds[1].inner_text()
                            address = address.strip()
                    break

        if name_type == "DBA":
            results.append(LicenseResult(
                license_number=parsed_lic,
                doing_business_as=trade_name,
                location_address=address,
                expiration_date=expiration,
                state="FL",
            ))

        i += 1

    return results


async def _parse_license_grid(
    page,
    grid_id: str,
    row_selector: str = "tbody tr.k-master-row",
    column_map: list[str] | None = None,
) -> list[LicenseResult]:
    """Extract rows from the results grid using config-driven column mapping.

    column_map is a list of LicenseResult field names in display order, e.g.:
        ["license_number", "doing_business_as", "location_address", "city", "state", "expiration_date"]

    Hidden cells (display:none) are skipped automatically.
    """
    # Default column order (matches Texas TABC)
    if not column_map:
        column_map = [
            "license_number", "doing_business_as", "location_address",
            "city", "state", "expiration_date",
        ]

    results = []
    rows = await page.query_selector_all(f"#{grid_id} {row_selector}")

    for row in rows:
        cells = await row.query_selector_all("td")

        # Extract visible text from each cell
        cell_texts = []
        for cell in cells:
            is_hidden = await cell.evaluate("el => el.style.display === 'none'")
            if is_hidden:
                continue
            text = await cell.inner_text()
            cell_texts.append(text.strip())

        if len(cell_texts) < 2:
            continue

        # Map cell values to LicenseResult fields using column_map
        mapped = {}
        for i, field_name in enumerate(column_map):
            if i < len(cell_texts):
                mapped[field_name] = cell_texts[i]

        results.append(LicenseResult(**mapped))

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
async def _main():
    parser = argparse.ArgumentParser(description="2nd Line: Playwright Scraper")
    parser.add_argument("--license", required=True, help="License number to search")
    parser.add_argument("--state", default="TX")
    parser.add_argument("--trade-name", default=None)
    parser.add_argument("--city", default=None)
    parser.add_argument("--headed", action="store_true", help="Run with visible browser")
    args = parser.parse_args()

    result = await search_license(
        license_number=args.license,
        state=args.state,
        trade_name=args.trade_name,
        city=args.city,
        headless=not args.headed,
    )
    print(json.dumps(result.model_dump(), indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
