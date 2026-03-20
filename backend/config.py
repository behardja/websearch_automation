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
        "LicDBA": "doing_business_as",
        "LicAddressLine1": "location_address",
        "City": "city",
        "State": "state",
        "LicExpirationDate": "expiration_date",
    },
    has_business_type_dropdown=True,
    result_row_selector="tbody tr.k-master-row",
    grid_column_map=[
        "license_number", "doing_business_as", "location_address",
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
    search_page="https://www.myfloridalicense.com/wl11.asp?mode=1&SID=&brd=&typ=&search=LicNbr",
    search_endpoint="https://www.myfloridalicense.com/wl11.asp?mode=2&search=LicNbr&SID=&brd=&typ=",
    business_type_value="400",  # Alcoholic Beverages & Tobacco
    field_ids={
        "license_number": "LicNbr",
        "search_button": "Search1",
        "result_grid": "",  # Florida uses flat HTML tables, not a grid widget
    },
    result_columns=[
        "license_type", "name", "name_type", "license_number_rank", "status_expires",
    ],
    http_payload_fields={
        "license_number": "LicNbr",
    },
    http_response_fields={},  # Florida returns HTML, not JSON — parsed separately
    has_business_type_dropdown=False,
    result_row_selector="table[bgcolor='#f1f1f1'] tr[height='40']",
    grid_column_map=[
        "license_type", "doing_business_as", "name_type", "license_number", "status_expires",
    ],
)

# ---------------------------------------------------------------------------
# Georgia (DOR) — placeholder, fill in when ready
# ---------------------------------------------------------------------------

GEORGIA = StateConfig(
    name="Georgia",
    code="GA",
    base_url="https://gtc.dor.ga.gov",
    search_page="https://gtc.dor.ga.gov/_/#2",
    search_endpoint="",  # JS SPA — no direct HTTP endpoint; Playwright only
    business_type_value="LICALL",  # Alcohol License radio button value
    field_ids={
        "license_type_radio": "Dd-b_0",       # Alcohol License radio
        "license_number": "Dd-f",              # License Number input
        "address": "Dd-g",                     # License Address input
        "business_name": "Dd-h",               # Business / Licensee Name input
        "search_button": "Dd-k",               # Search button
    },
    result_columns=[
        "name", "address", "license_number", "license_type",
        "taxing_jurisdiction", "status", "additional_info",
    ],
    http_payload_fields={},      # No HTTP direct — JS SPA
    http_response_fields={},
    has_business_type_dropdown=False,  # Uses radio buttons, not dropdown
    result_row_selector="table#Dd-51 tbody.DocTableBody tr.TDR",
    grid_column_map=[
        "doing_business_as", "location_address", "license_number",
        "license_type", "taxing_jurisdiction", "status",
    ],
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

STATE_CONFIGS: dict[str, StateConfig] = {
    "TX": TEXAS,
    "FL": FLORIDA,
    "GA": GEORGIA,
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

# Fast model for parser sub-agent (converts narrative agent output to JSON)
PARSER_MODEL = "gemini-3-flash-preview"
