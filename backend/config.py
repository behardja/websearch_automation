"""Configuration constants for license verification across states."""

from dataclasses import dataclass


@dataclass
class StateConfig:
    name: str
    code: str
    base_url: str
    search_page: str
    search_endpoint: str
    business_type_value: str
    field_ids: dict[str, str]
    result_columns: list[str]


# ---------------------------------------------------------------------------
# Texas (TABC)
# ---------------------------------------------------------------------------

TEXAS = StateConfig(
    name="Texas",
    code="TX",
    base_url="https://tabcaims.elicense365.com",
    search_page="https://tabcaims.elicense365.com/Apps/LicenceSimpleSearch/",
    search_endpoint="https://tabcaims.elicense365.com/Apps/LicenceSimpleSearch",
    business_type_value="2",  # "License"
    field_ids={
        "business_type": "ddlBusinessType",
        "license_number": "txtRegOrLicNum",      # max 9 digits
        "trade_name": "txtDBAName",               # max 50 chars
        "address": "txtLicenseAddress",
        "city": "txtCity",
        "search_button": "btnsearch",
        "reset_button": "btnReset",
        "result_grid": "grdLicense",
    },
    result_columns=[
        "StringLicLocId", "LicDBA", "LicAddressLine1",
        "City", "State", "LicExpirationDate",
    ],
)

# ---------------------------------------------------------------------------
# Florida (DBPR) — placeholder, fill in when ready
# ---------------------------------------------------------------------------

FLORIDA = StateConfig(
    name="Florida",
    code="FL",
    base_url="https://www.myfloridalicense.com",
    search_page="https://www.myfloridalicense.com/wl11.asp?mode=0&SID=&bession_id=",
    search_endpoint="",  # TODO: discover the actual endpoint
    business_type_value="",
    field_ids={},         # TODO: map the form fields
    result_columns=[],
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

STATE_CONFIGS: dict[str, StateConfig] = {
    "TX": TEXAS,
    "FL": FLORIDA,
}

SUPPORTED_STATES = list(STATE_CONFIGS.keys())

# ---------------------------------------------------------------------------
# Shared settings
# ---------------------------------------------------------------------------

DEFAULT_DEFENSE_LINE = 1
MAX_RETRIES_PER_LINE = 2
REQUEST_TIMEOUT_SECONDS = 30

# Gemini Computer Use model for 3rd line
COMPUTER_USE_MODEL = "gemini-2.5-computer-use-preview-10-2025"
COMPUTER_USE_SCREEN_SIZE = (1280, 936)
