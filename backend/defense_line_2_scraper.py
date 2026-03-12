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

            # Step 2: Select "License" from the business type dropdown
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
            await page.wait_for_load_state("networkidle")
            # Wait for at least one data row to appear in the grid
            try:
                await page.wait_for_selector(
                    f"#{grid_id} tbody tr.k-master-row",
                    state="visible",
                    timeout=10000,
                )
            except Exception:
                pass  # No results found — that's ok, we'll return empty

            # Step 6: Parse results from the DOM
            results = await _parse_license_grid(page, grid_id)

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


async def _parse_license_grid(page, grid_id: str) -> list[LicenseResult]:
    """Extract rows from the license Kendo UI grid (#grdLicense).

    Grid columns (visible):
      0: EncLicenceNumber (hidden via display:none)
      1: License Number (StringLicLocId)
      2: Trade Name (LicDBA)
      3: Lic/Reg Location (LicAddressLine1)
      4: City
      5: State
      6: Lic Expiration Date (LicExpirationDate)
    """
    results = []

    rows = await page.query_selector_all(f"#{grid_id} tbody tr.k-master-row")

    for row in rows:
        cells = await row.query_selector_all("td")

        # Extract visible text from each cell
        cell_texts = []
        for cell in cells:
            # Skip hidden cells (EncLicenceNumber)
            is_hidden = await cell.evaluate("el => el.style.display === 'none'")
            if is_hidden:
                continue
            text = await cell.inner_text()
            cell_texts.append(text.strip())

        if len(cell_texts) < 4:
            continue

        results.append(
            LicenseResult(
                license_number=cell_texts[0] if len(cell_texts) > 0 else None,
                trade_name=cell_texts[1] if len(cell_texts) > 1 else None,
                location_address=cell_texts[2] if len(cell_texts) > 2 else None,
                city=cell_texts[3] if len(cell_texts) > 3 else None,
                state=cell_texts[4] if len(cell_texts) > 4 else None,
                expiration_date=cell_texts[5] if len(cell_texts) > 5 else None,
            )
        )

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
