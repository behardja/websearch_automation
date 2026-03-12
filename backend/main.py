"""
FastAPI server for TABC License Verification.

Provides REST endpoints for the frontend app (Agent mode & Batch mode).
Implements the defense line cascade: tries Line 1 first, falls back to
Line 2, then Line 3 if earlier lines fail.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import (
    LicenseSearchRequest,
    BatchSearchRequest,
    VerificationResponse,
    BatchResponse,
    BatchItemStatus,
    DefenseLine,
)
from . import defense_line_1_http as line1
from . import defense_line_2_scraper as line2
from . import defense_line_3_agent as line3


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: install playwright browsers if needed
    yield
    # Shutdown: cleanup


app = FastAPI(
    title="TABC License Verification API",
    description="3 Lines of Defense for automated alcohol license verification",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _cascade_search(req: LicenseSearchRequest) -> VerificationResponse:
    """
    Try each defense line in order. If a specific line is requested, use only that one.
    Otherwise, cascade: 1 -> 2 -> 3.
    """
    if req.defense_line:
        return await _run_line(req, req.defense_line)

    # Auto-cascade
    for line_num in [DefenseLine.HTTP_DIRECT, DefenseLine.PLAYWRIGHT_SCRAPER, DefenseLine.GEMINI_AGENT]:
        result = await _run_line(req, line_num)
        if result.verified or result.error is None:
            return result
    return result  # Return last attempt's result


async def _run_line(req: LicenseSearchRequest, line: DefenseLine) -> VerificationResponse:
    """Execute a specific defense line."""
    try:
        if line == DefenseLine.HTTP_DIRECT:
            return await line1.search_license(
                license_number=req.license_number,
                trade_name=req.trade_name,
                address=req.address,
                city=req.city,
            )
        elif line == DefenseLine.PLAYWRIGHT_SCRAPER:
            return await line2.search_license(
                license_number=req.license_number,
                trade_name=req.trade_name,
                address=req.address,
                city=req.city,
            )
        elif line == DefenseLine.GEMINI_AGENT:
            return await line3.search_license(
                license_number=req.license_number,
            )
    except Exception as e:
        return VerificationResponse(
            license_number=req.license_number,
            verified=False,
            defense_line_used=line,
            error=str(e),
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/verify", response_model=VerificationResponse)
async def verify_license(req: LicenseSearchRequest):
    """Verify a single license (Agent mode)."""
    return await _cascade_search(req)


@app.post("/api/batch", response_model=BatchResponse)
async def batch_verify(req: BatchSearchRequest):
    """
    Verify multiple licenses (Batch mode).
    Processes sequentially to avoid overwhelming the TABC site.
    """
    items: list[BatchItemStatus] = []

    for license_req in req.licenses:
        if req.defense_line:
            license_req.defense_line = req.defense_line

        try:
            result = await _cascade_search(license_req)
            items.append(
                BatchItemStatus(
                    license_number=license_req.license_number,
                    status="verified" if result.verified else "not_found",
                    defense_line_used=result.defense_line_used,
                    result_count=len(result.results),
                    error=result.error,
                )
            )
        except Exception as e:
            items.append(
                BatchItemStatus(
                    license_number=license_req.license_number,
                    status="error",
                    error=str(e),
                )
            )

    return BatchResponse(
        total=len(req.licenses),
        completed=len(items),
        items=items,
    )
