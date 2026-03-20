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
import logging
import re

from google.adk import Agent
from google.adk.tools.computer_use.computer_use_toolset import ComputerUseToolset
from google.adk.tools.computer_use.computer_use_tool import ComputerUseTool
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .config import STATE_CONFIGS, COMPUTER_USE_MODEL, COMPUTER_USE_SCREEN_SIZE, PARSER_MODEL
from .models import LicenseResult, VerificationResponse, DefenseLine
from .playwright_computer import PlaywrightComputer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patch ComputerUseTool to handle the model's safety_decision protocol.
# The Computer Use model may include a 'safety_decision' dict in function call
# args when it wants user confirmation before acting. The API requires
# the function response to acknowledge it. The ADK doesn't handle this yet.
# ---------------------------------------------------------------------------
_original_computer_use_run_async = ComputerUseTool.run_async


async def _patched_run_async(self, *, args, tool_context):
    safety_decision = args.pop("safety_decision", None)
    result = await _original_computer_use_run_async(self, args=args, tool_context=tool_context)
    if safety_decision and isinstance(result, dict):
        result["safety_acknowledgement"] = True
    return result


ComputerUseTool.run_async = _patched_run_async


def _build_agent_instruction(license_number: str, state: str) -> str:
    """Build the instruction prompt for the Gemini agent."""
    cfg = STATE_CONFIGS.get(state)

    if state == "TX":
        return f"""You are a license verification agent. Your ONLY task is to search for
license number {license_number} on the Texas TABC website and report what you find.

The browser is already open to the TABC License Search page.
DO NOT navigate to any other website. DO NOT use Google. Stay on this page.

DO THESE EXACT STEPS IN ORDER:

STEP 1: Look at the current page. You should see a search form with a "Type" dropdown.
Click on the "Type" dropdown and select "License" from the list.

STEP 2: After selecting "License", find the input field labeled "License or Permit Number".
Click on that field and type exactly this value: {license_number}
Do NOT press Enter. Do NOT type in any other field. Do NOT search Google.

STEP 3: Click the blue "Search" button on the form.

STEP 4: Wait for results. Read the results grid carefully.

STEP 5: Your FINAL answer must be ONLY a JSON object, nothing else. No explanation.
Format:
{{
  "verified": true,
  "results": [
    {{
      "license_number": "the License/Location ID value",
      "doing_business_as": "the DBA/Trade Name",
      "location_address": "the full address",
      "city": "city",
      "state": "state",
      "expiration_date": "expiration date",
      "license_type": "license type if shown",
      "extra_details": {{"status": "Active or Inactive"}}
    }}
  ]
}}

If no results found: {{"verified": false, "results": []}}

CRITICAL: Your final response must contain ONLY the JSON. No other text before or after it.
CRITICAL: Do NOT navigate away from the TABC website. Do NOT go to Google.
CRITICAL: Search ONLY by license number {license_number}. Do not search by any other field.
"""

    elif state == "FL":
        return f"""You are a license verification agent. Your task is to verify an
alcohol license on the Florida DBPR website.

Follow these steps precisely:
1. You should already be on: {cfg.search_page}
2. In the "License Number" field, type: {license_number}
3. Click the "Search" button
4. Wait for results to load
5. Read the results table carefully
6. Look for rows where the Name Type column says "DBA" (Doing Business As)

For each DBA result row, read these columns:
- License Type
- Name (this is the DBA name)
- License Number/Rank
- Status/Expires

Format your final answer as a JSON object with this exact structure:
{{
  "verified": true,
  "results": [
    {{
      "license_number": "the license number",
      "doing_business_as": "the DBA name",
      "license_type": "the license type",
      "expiration_date": "the expiration/status date"
    }}
  ]
}}

If no results are found, return:
{{"verified": false, "results": []}}

IMPORTANT: Return ONLY the JSON object as your final answer, no other text.
"""

    elif state == "GA":
        return f"""You are a license verification agent. Your task is to verify an
alcohol license on the Georgia Department of Revenue website.

Follow these steps precisely:
1. You should already be on: {cfg.base_url}/_/
2. Look for and click the "Search for a License" link on the page
3. Wait for the search form to appear
4. Click the "Alcohol License" radio button
5. In the "License Number" field, type: {license_number}
6. Click the "Search" button
7. Wait for results to load
8. Read the results table carefully
9. If there is a clickable name/link in the results, click on it to see the detail view
10. Read all detail fields

For each result, gather:
- Business/Licensee Name (this is the DBA)
- Address
- License Number
- License Type
- Taxing Jurisdiction
- Status
- Any other detail fields visible

Format your final answer as a JSON object with this exact structure:
{{
  "verified": true,
  "results": [
    {{
      "license_number": "the license number",
      "doing_business_as": "the business name",
      "license_type": "the license type",
      "location_address": "the address",
      "jurisdiction": "the taxing jurisdiction",
      "extra_details": {{
        "status": "the status value",
        "any_other_field": "its value"
      }}
    }}
  ]
}}

If no results are found, return:
{{"verified": false, "results": []}}

IMPORTANT: Return ONLY the JSON object as your final answer, no other text.
"""

    else:
        state_name = cfg.name if cfg else state
        search_page = cfg.search_page if cfg else "unknown"
        return f"""You are a license verification agent. Your ONLY task is to search for
alcohol license number {license_number} on the {state_name} alcohol license search website.

The browser is already open to: {search_page}
DO NOT navigate to any other website. DO NOT use Google. Stay on this page.

DO THESE STEPS IN ORDER:

STEP 1: Look at the current page. You should see a search form for looking up licenses.
Examine the form carefully. Identify any dropdowns, radio buttons, or tabs that need to
be set before searching. If there is a license type selector, choose the option related
to alcohol licenses. If there is a search-by selector, choose to search by license number.

STEP 2: Find the input field for license number (it may be labeled "License Number",
"License or Permit Number", "License No", or similar).
Click on that field and type exactly this value: {license_number}
Do NOT press Enter. Do NOT type in any other field.

STEP 3: Click the "Search" button (or "Submit", "Find", "Go" — whatever button submits the form).

STEP 4: Wait for results to load. Read the results carefully.
If the results are in a table/grid, read every column of every row.
If there is a clickable link to a detail view, click it to get more information.
Look for these fields: business name / DBA name, address, license type, expiration date, status.

STEP 5: Your FINAL answer must be ONLY a JSON object, nothing else. No explanation.
Format:
{{
  "verified": true,
  "results": [
    {{
      "license_number": "the license number",
      "doing_business_as": "the business/DBA name",
      "location_address": "the full address",
      "city": "the city if shown separately",
      "state": "{state}",
      "expiration_date": "the expiration date",
      "license_type": "the license type",
      "extra_details": {{"status": "Active or Inactive", "any_other_field": "its value"}}
    }}
  ]
}}

If no results found: {{"verified": false, "results": []}}

CRITICAL: Your final response must contain ONLY the JSON. No other text before or after it.
CRITICAL: Do NOT navigate away from this website. Do NOT go to Google.
CRITICAL: Search ONLY by license number {license_number}. Do not search by any other field.
"""


def _extract_json(text: str) -> dict | None:
    """Extract JSON object from agent response text (may be wrapped in markdown fences)."""
    # Try to find JSON in markdown code fences first
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find a raw JSON object
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


# ---------------------------------------------------------------------------
# Narrative-to-JSON parser sub-agent
# Uses a fast/cheap model to convert free-text agent output into structured JSON.
# ---------------------------------------------------------------------------

_PARSER_PROMPT = """\
You are a data extraction assistant. The text below is the output of a browser
automation agent that searched a government website for alcohol license information.

Extract the license data from the text and return ONLY a JSON object with this structure:
{{
  "verified": true,
  "results": [
    {{
      "license_number": "...",
      "doing_business_as": "...",
      "location_address": "...",
      "city": "...",
      "state": "...",
      "expiration_date": "...",
      "license_type": "...",
      "extra_details": {{"status": "...", "any_other_field": "..."}}
    }}
  ]
}}

If the text indicates no results were found, return: {{"verified": false, "results": []}}

Return ONLY the JSON. No explanation.

--- AGENT OUTPUT ---
{agent_text}
"""


async def _parse_narrative_with_llm(agent_text: str) -> dict | None:
    """Use a fast LLM to extract structured JSON from narrative agent output."""
    try:
        from google import genai

        client = genai.Client()
        response = await client.aio.models.generate_content(
            model=PARSER_MODEL,
            contents=_PARSER_PROMPT.format(agent_text=agent_text),
        )
        if response.text:
            return _extract_json(response.text)
    except Exception as e:
        logger.warning("Parser sub-agent failed: %s", e)
    return None


def _parse_agent_response(raw: dict, license_number: str, state: str) -> VerificationResponse:
    """Convert parsed JSON from agent into a VerificationResponse."""
    verified = raw.get("verified", False)
    raw_results = raw.get("results", [])

    results = []
    for r in raw_results:
        extra = r.get("extra_details", {})
        results.append(LicenseResult(
            license_number=r.get("license_number"),
            legal_name=r.get("legal_name"),
            doing_business_as=r.get("doing_business_as"),
            license_type=r.get("license_type"),
            expiration_date=r.get("expiration_date"),
            jurisdiction=r.get("jurisdiction"),
            location_address=r.get("location_address"),
            city=r.get("city"),
            state=r.get("state"),
            extra_details=extra if isinstance(extra, dict) else {},
        ))

    return VerificationResponse(
        license_number=license_number,
        state=state,
        verified=verified and len(results) > 0,
        defense_line_used=DefenseLine.GEMINI_AGENT,
        results=results,
    )


async def search_license(
    license_number: str,
    state: str = "TX",
    headless: bool = True,
) -> VerificationResponse:
    """
    Use the Gemini Computer Use agent to verify a license.
    """
    cfg = STATE_CONFIGS.get(state)
    if not cfg:
        return VerificationResponse(
            license_number=license_number,
            state=state,
            verified=False,
            defense_line_used=DefenseLine.GEMINI_AGENT,
            error=f"Unsupported state: {state}",
        )

    initial_url = cfg.search_page

    computer = PlaywrightComputer(
        screen_size=COMPUTER_USE_SCREEN_SIZE,
        initial_url=initial_url,
        headless=headless,
    )

    toolset = ComputerUseToolset(computer=computer)

    agent = Agent(
        model=COMPUTER_USE_MODEL,
        name="license_verifier",
        instruction=(
            "You are a browser automation agent that follows instructions exactly. "
            "Do NOT navigate to Google or any site other than the one already open. "
            "Always return your final answer as a JSON object only, with no other text."
        ),
        tools=[toolset],
    )

    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name="license-verify",
        session_service=session_service,
    )
    session = await session_service.create_session(
        app_name="license-verify",
        user_id="user",
    )

    content = types.Content(
        role="user",
        parts=[types.Part.from_text(
            text=_build_agent_instruction(license_number, state),
        )],
    )

    final_text = ""
    try:
        async for event in runner.run_async(
            user_id="user",
            session_id=session.id,
            new_message=content,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final_text = event.content.parts[0].text
    except Exception as e:
        logger.exception("Gemini Computer Use agent failed")
        return VerificationResponse(
            license_number=license_number,
            state=state,
            verified=False,
            defense_line_used=DefenseLine.GEMINI_AGENT,
            error=f"Agent execution error: {e}",
        )

    if not final_text:
        return VerificationResponse(
            license_number=license_number,
            state=state,
            verified=False,
            defense_line_used=DefenseLine.GEMINI_AGENT,
            error="Agent returned no response",
        )

    logger.info("Agent raw response: %s", final_text[:2000])

    parsed = _extract_json(final_text)
    if not parsed:
        # Fallback: use a fast LLM to extract JSON from narrative text
        logger.info("Direct JSON extraction failed, trying parser sub-agent...")
        parsed = await _parse_narrative_with_llm(final_text)
    if not parsed:
        return VerificationResponse(
            license_number=license_number,
            state=state,
            verified=False,
            defense_line_used=DefenseLine.GEMINI_AGENT,
            error=f"Could not parse agent JSON response: {final_text[:200]}",
        )

    return _parse_agent_response(parsed, license_number, state)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
async def _main():
    parser = argparse.ArgumentParser(description="3rd Line: Gemini Computer Use Agent")
    parser.add_argument("--license", required=True, help="License number to search")
    parser.add_argument("--state", default="TX")
    parser.add_argument("--headed", action="store_true", help="Run browser in headed mode (visible)")
    args = parser.parse_args()

    result = await search_license(
        license_number=args.license,
        state=args.state,
        headless=not args.headed,
    )
    print(json.dumps(result.model_dump(), indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
