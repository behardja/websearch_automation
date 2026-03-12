"""Pydantic models for license verification requests and responses."""

from enum import IntEnum
from typing import Optional

from pydantic import BaseModel, Field


class DefenseLine(IntEnum):
    HTTP_DIRECT = 1
    PLAYWRIGHT_SCRAPER = 2
    GEMINI_AGENT = 3


class LicenseSearchRequest(BaseModel):
    license_number: str = Field(..., max_length=9, pattern=r"^\d+$")
    state: str = Field("TX", max_length=2)
    trade_name: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = None
    city: Optional[str] = None
    defense_line: Optional[DefenseLine] = None  # None = auto-cascade


class BatchSearchRequest(BaseModel):
    licenses: list[LicenseSearchRequest]
    defense_line: Optional[DefenseLine] = None


class LicenseResult(BaseModel):
    license_number: Optional[str] = None
    trade_name: Optional[str] = None
    location_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    expiration_date: Optional[str] = None


class VerificationResponse(BaseModel):
    license_number: str
    state: str = "TX"
    verified: bool
    defense_line_used: DefenseLine
    results: list[LicenseResult] = []
    error: Optional[str] = None


class BatchItemStatus(BaseModel):
    license_number: str
    status: str = "pending"  # pending | running | verified | not_found | error
    defense_line_used: Optional[DefenseLine] = None
    result_count: int = 0
    error: Optional[str] = None


class BatchResponse(BaseModel):
    total: int
    completed: int = 0
    items: list[BatchItemStatus] = []
