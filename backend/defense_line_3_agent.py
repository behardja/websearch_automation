"""
3rd Line of Defense: Gemini Computer Use Agent (ADK).

Uses Google's Agent Development Kit (ADK) with the ComputerUseToolset to
have Gemini visually navigate the state website like a human — taking
screenshots, identifying form fields, typing values, clicking buttons,
and reading results.

Based on: https://github.com/google/adk-python/tree/main/contributing/samples/computer_use

This is the most resilient approach (survives DOM changes, JS obfuscation)
but also the slowest and most expensive. Use only when Lines 1 and 2 fail.

Requirements:
- playwright install chromium
- GOOGLE_CLOUD_PROJECT env var set
- GOOGLE_GENAI_USE_VERTEXAI=1 (for Vertex AI)
"""

import argparse
import asyncio
import json
import os
import tempfile

from .config import STATE_CONFIGS, COMPUTER_USE_MODEL, COMPUTER_USE_SCREEN_SIZE
from .models import VerificationResponse, DefenseLine

# ADK imports are deferred to avoid import errors when deps aren't installed
# from google.adk import Agent
# from google.adk.tools.computer_use.computer_use_toolset import ComputerUseToolset
# from .playwright_computer import PlaywrightComputer


def _build_agent_instruction(license_number: str, state: str) -> str:
    """Build the instruction prompt for the Gemini agent."""
    cfg = STATE_CONFIGS.get(state)
    search_page = cfg.search_page if cfg else "unknown"

    return f"""You are a license verification agent. Your task is to verify an
alcohol license on a state government search website.

Follow these steps precisely:
1. Navigate to: {search_page}
2. In the "Type" dropdown, select "License"
3. Wait for the license search fields to appear
4. In the "License or Permit Number" field, type: {license_number}
5. Click the "Search" button
6. Wait for results to load in the grid below
7. Read the results grid carefully

Report back with:
- Whether any results were found (verified = true/false)
- For each result row: LabelID, ProductName, ProductType, AlcoholByVolume,
  DateRegistered, TTBColaNumber, LicenseID
- If no results found, state that the license could not be verified

Format your final answer as a JSON object with this structure:
{{
  "verified": true/false,
  "result_count": <number>,
  "results": [
    {{
      "label_id": "...",
      "product_name": "...",
      "product_type": "...",
      "alcohol_by_volume": "...",
      "date_registered": "...",
      "ttb_cola_number": "...",
      "license_id": "..."
    }}
  ]
}}
"""


async def search_license(
    license_number: str,
    state: str = "TX",
) -> VerificationResponse:
    """
    Use the Gemini Computer Use agent to verify a license.

    This is a skeleton — the full ADK runner loop is not yet wired up.
    """
    # TODO: Implement the full ADK agent session flow
    # from google.adk import Agent
    # from google.adk.tools.computer_use.computer_use_toolset import ComputerUseToolset
    # from .playwright_computer import PlaywrightComputer
    # from google.adk.runners import Runner
    # from google.adk.sessions import InMemorySessionService

    return VerificationResponse(
        license_number=license_number,
        state=state,
        verified=False,
        defense_line_used=DefenseLine.GEMINI_AGENT,
        error="3rd line agent not yet fully implemented — skeleton only",
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
async def _main():
    parser = argparse.ArgumentParser(description="3rd Line: Gemini Computer Use Agent")
    parser.add_argument("--license", required=True, help="License number to search")
    parser.add_argument("--state", default="TX")
    args = parser.parse_args()

    result = await search_license(license_number=args.license, state=args.state)
    print(json.dumps(result.model_dump(), indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
