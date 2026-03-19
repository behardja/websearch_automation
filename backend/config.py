"""Configuration constants for license verification across states."""

from dataclasses import dataclass, field


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

    # -- Method 1 (HTTP Direct) mappings --
    # Maps our standard field names to the state's POST parameter names
    http_payload_fields: dict[str, str] = field(default_factory=dict)
    # Maps the state's JSON response field names to our LicenseResult fields
    http_response_fields: dict[str, str] = field(default_factory=dict)

    # -- Method 2 (Playwright) behavior --
    # Does the form have a business-type dropdown that must be selected first?
    has_business_type_dropdown: bool = True
    # CSS selector for result rows (default: Kendo grid rows)
    result_row_selector: str = "tbody tr.k-master-row"
    # Ordered list of visible column names mapping to LicenseResult fields
    # (after skipping hidden columns)
    grid_column_map: list[str] = field(default_factory=list)


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
    http_payload_fields={
        "license_number": "LicNumber",
        "trade_name": "DBAName",
        "address": "Address",
        "city": "City",
    },
    http_response_fields={
        "StringLicLocId": "license_number",
        "LicDBA": "trade_name",
        "LicAddressLine1": "location_address",
        "City": "city",
        "State": "state",
        "LicExpirationDate": "expiration_date",
    },
    has_business_type_dropdown=True,
    result_row_selector="tbody tr.k-master-row",
    grid_column_map=[
        "license_number", "trade_name", "location_address",
        "city", "state", "expiration_date",
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
    http_payload_fields={},
    http_response_fields={},
    has_business_type_dropdown=False,  # Florida's form works differently
    result_row_selector="",           # TODO: discover the grid structure
    grid_column_map=[],
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
