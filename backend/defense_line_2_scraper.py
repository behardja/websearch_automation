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
        context = await browser.new_context()
        page = await context.new_page()

        try:
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
            # Wait for at least one data row to appear in the grid
            try:
                await page.wait_for_selector(
                    f"#{grid_id} {row_selector}",
                    state="visible",
                    timeout=10000,
                )
            except Exception:
                pass  # No results found — that's ok, we'll return empty

            # Step 6: Parse results from the DOM
            results = await _parse_license_grid(page, grid_id, row_selector, cfg.grid_column_map)

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


async def _parse_license_grid(
    page,
    grid_id: str,
    row_selector: str = "tbody tr.k-master-row",
    column_map: list[str] | None = None,
) -> list[LicenseResult]:
    """Extract rows from the results grid using config-driven column mapping.

    column_map is a list of LicenseResult field names in display order, e.g.:
        ["license_number", "trade_name", "location_address", "city", "state", "expiration_date"]

    Hidden cells (display:none) are skipped automatically.
    """
    # Default column order (matches Texas TABC)
    if not column_map:
        column_map = [
            "license_number", "trade_name", "location_address",
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
