"""
1st Line of Defense: Direct HTTP Requests.

Bypasses the browser entirely. Sends POST requests directly to the
Kendo grid data endpoint with the search parameters, then parses
the JSON response.

This is the fastest and most efficient approach, but may fail if:
- The endpoint requires a valid session/anti-forgery token
- CAPTCHA or rate limiting is enforced
- The response format changes
"""

import argparse
import json
import re

import httpx
from bs4 import BeautifulSoup

from .config import STATE_CONFIGS, REQUEST_TIMEOUT_SECONDS
from .models import LicenseResult, VerificationResponse, DefenseLine


async def search_license(
    license_number: str,
    state: str = "TX",
    trade_name: str | None = None,
    address: str | None = None,
    city: str | None = None,
) -> VerificationResponse:
    """
    Search for a license via direct HTTP requests.
    Routes to state-specific logic based on response format.
    """
    cfg = STATE_CONFIGS.get(state)
    if not cfg:
        return VerificationResponse(
            license_number=license_number,
            state=state,
            verified=False,
            defense_line_used=DefenseLine.HTTP_DIRECT,
            error=f"No config for state: {state}",
        )

    if state == "GA":
        return VerificationResponse(
            license_number=license_number,
            state=state,
            verified=False,
            defense_line_used=DefenseLine.HTTP_DIRECT,
            error="Georgia uses a JavaScript SPA — HTTP direct is not supported. Use Playwright (Method 2).",
        )

    if state == "FL":
        return await _search_florida(license_number, cfg)

    # Default: JSON-based search (Texas / Kendo grid pattern)
    return await _search_json_grid(license_number, state, cfg, trade_name, address, city)


async def _search_json_grid(
    license_number: str,
    state: str,
    cfg,
    trade_name: str | None = None,
    address: str | None = None,
    city: str | None = None,
) -> VerificationResponse:
    """Search states that return JSON (e.g., Texas TABC Kendo grid)."""
    async with httpx.AsyncClient(
        base_url=cfg.base_url,
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        # Step 1: Get session cookies
        resp = await client.get(cfg.search_page)
        resp.raise_for_status()

        # Step 2: Build the POST payload using state-specific field mappings
        field_map = cfg.http_payload_fields
        if not field_map:
            return VerificationResponse(
                license_number=license_number,
                state=state,
                verified=False,
                defense_line_used=DefenseLine.HTTP_DIRECT,
                error=f"No HTTP payload field mappings configured for state: {state}",
            )

        input_values = {
            "license_number": license_number,
            "trade_name": trade_name or "",
            "address": address or "",
            "city": city or "",
        }
        payload = {
            field_map[k]: v
            for k, v in input_values.items()
            if k in field_map
        }

        # Step 3: POST to the data endpoint
        resp = await client.post(
            cfg.search_endpoint.replace(cfg.base_url, ""),
            data=payload,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        resp.raise_for_status()

        # Step 4: Parse the Kendo JSON response
        content_type = resp.headers.get("content-type", "")
        if "application/json" not in content_type:
            return VerificationResponse(
                license_number=license_number,
                state=state,
                verified=False,
                defense_line_used=DefenseLine.HTTP_DIRECT,
                error=f"Expected JSON but got {content_type}; endpoint may require a browser session",
            )

        try:
            data = resp.json()
        except Exception as e:
            return VerificationResponse(
                license_number=license_number,
                state=state,
                verified=False,
                defense_line_used=DefenseLine.HTTP_DIRECT,
                error=f"Failed to parse JSON response: {e}",
            )

        # The license search endpoint returns a JSON array directly
        records = data if isinstance(data, list) else data.get("Data", [])

        # Map response fields using state-specific config
        resp_map = cfg.http_response_fields
        results = []
        for rec in records:
            mapped = {}
            for resp_key, our_key in resp_map.items():
                mapped[our_key] = rec.get(resp_key)
            # Ensure license_number is a string
            if "license_number" in mapped and mapped["license_number"] is not None:
                mapped["license_number"] = str(mapped["license_number"])
            results.append(LicenseResult(**mapped))

        return VerificationResponse(
            license_number=license_number,
            state=state,
            verified=len(results) > 0,
            defense_line_used=DefenseLine.HTTP_DIRECT,
            results=results,
        )


async def _search_florida(
    license_number: str,
    cfg,
) -> VerificationResponse:
    """Search Florida DBPR — HTML form POST that returns HTML table results."""
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        # POST the search form
        payload = {
            "hSearchType": "LicNbr",
            "hDivision": "ALL",
            "hBoardType": "",
            "LicNbr": license_number,
            "Board": "",
            "LicenseType": "",
            "SpecQual": "",
            "RecsPerPage": "10",
            "Search1": "Search",
            "hSID": "",
            "hLastName": "",
            "hFirstName": "",
            "hMiddleName": "",
            "hOrgName": "",
            "hSearchOpt": "",
            "hSearchOpt2": "",
            "hSearchAltName": "",
            "hSearchPartName": "",
            "hSearchFuzzy": "",
            "hBoard": "",
            "hLicenseType": "",
            "hSpecQual": "",
            "hAddrType": "",
            "hCity": "",
            "hCounty": "",
            "hState": "",
            "hLicNbr": "",
            "hCurrPage": "",
            "hTotalPages": "",
            "hTotalRecords": "",
            "hLicTyp": "",
            "hSearchHistoric": "",
            "hRecsPerPage": "",
        }

        resp = await client.post(
            cfg.search_endpoint,
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        resp.raise_for_status()

        # Parse HTML results
        soup = BeautifulSoup(resp.text, "html.parser")
        results = _parse_florida_results(soup, license_number)

        return VerificationResponse(
            license_number=license_number,
            state="FL",
            verified=len(results) > 0,
            defense_line_used=DefenseLine.HTTP_DIRECT,
            results=results,
        )


def _parse_florida_results(soup: BeautifulSoup, license_number: str) -> list[LicenseResult]:
    """Parse Florida DBPR HTML search results into LicenseResult objects.

    The results page has rows with height="40" inside a table with bgcolor="#f1f1f1".
    Each license has two rows (DBA + Primary name) followed by an address row.
    We return the DBA row as the primary result.
    """
    results = []

    # Find all data rows (height="40")
    data_rows = soup.find_all("tr", attrs={"height": "40"})

    i = 0
    while i < len(data_rows):
        row = data_rows[i]
        cells = row.find_all("td", attrs={"align": "center"})

        # Skip address rows (they have colspan=6 and no centered cells with license data)
        if not cells or len(cells) < 4:
            i += 1
            continue

        cell_texts = [c.get_text(separator="\n", strip=True) for c in cells]

        # Columns: License Type | Name | Name Type | License Number/Rank | Status/Expires
        name_type = cell_texts[2] if len(cell_texts) > 2 else ""

        # We want the DBA row for trade_name matching
        trade_name = cell_texts[1] if len(cell_texts) > 1 else ""
        lic_info = cell_texts[3] if len(cell_texts) > 3 else ""
        status_info = cell_texts[4] if len(cell_texts) > 4 else ""

        # Parse license number and rank from "BEV1615666\n3PS"
        lic_parts = lic_info.split("\n")
        parsed_lic_number = lic_parts[0].strip() if lic_parts else ""

        # Parse status and expiration from "Current, Active\n03/31/2027"
        status_parts = status_info.split("\n")
        expiration = status_parts[-1].strip() if len(status_parts) > 1 else ""

        # Look for the address row (next row with nested table)
        address = ""
        if i + 1 < len(data_rows):
            addr_row = data_rows[i + 1]
            addr_cells = addr_row.find_all("td", attrs={"align": "left"})
            for ac in addr_cells:
                label = ac.find("b")
                if label and "License Location" in label.get_text():
                    # The address is in the next sibling td
                    addr_td = ac.find_next_sibling("td") or ac.find_parent("tr").find_all("td")[-1]
                    if addr_td:
                        address = addr_td.get_text(strip=True)
                        break

        # Only include DBA rows to avoid duplicates
        if name_type == "DBA":
            results.append(LicenseResult(
                license_number=parsed_lic_number,
                doing_business_as=trade_name,
                location_address=address,
                expiration_date=expiration,
                state="FL",
            ))

        i += 1

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
async def _main():
    parser = argparse.ArgumentParser(description="1st Line: HTTP Direct Search")
    parser.add_argument("--license", required=True, help="License number to search")
    parser.add_argument("--state", default="TX")
    parser.add_argument("--trade-name", default=None)
    parser.add_argument("--city", default=None)
    args = parser.parse_args()

    result = await search_license(
        license_number=args.license,
        state=args.state,
        trade_name=args.trade_name,
        city=args.city,
    )
    print(json.dumps(result.model_dump(), indent=2))


if __name__ == "__main__":
    import asyncio
    asyncio.run(_main())
