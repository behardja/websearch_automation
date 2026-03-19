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

import httpx

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
    Search for a license by directly hitting the Kendo grid data endpoint.
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
