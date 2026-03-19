"""
License Verification Server.

Mirrors the product-fidelity-eval server pattern:
- Custom endpoints for single-file verification (cascading Lines 1→2→3)
- Batch processing with SSE progress streaming
- File upload with state selection

Run:
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio
import json
import logging
import os
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message=".*non-text parts in the response.*")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("google.genai").setLevel(logging.ERROR)

# Load .env before any imports that read config
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.config import STATE_CONFIGS, SUPPORTED_STATES
from backend.models import (
    LicenseSearchRequest,
    VerificationResponse,
    DefenseLine,
)
from backend import defense_line_1_http as line1
from backend import defense_line_2_scraper as line2
from backend import defense_line_3_agent as line3
from backend.document_ai import extract_fields, build_search_fields

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Alcohol License Verification API",
    description="3 Lines of Defense for automated alcohol license verification",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Defense line execution
# ---------------------------------------------------------------------------

async def _run_line(
    license_number: str,
    state: str,
    line: DefenseLine,
    trade_name: str | None = None,
) -> VerificationResponse:
    """Execute a specific defense line for the given state."""
    try:
        if line == DefenseLine.HTTP_DIRECT:
            return await line1.search_license(
                license_number=license_number,
                state=state,
                trade_name=trade_name,
            )
        elif line == DefenseLine.PLAYWRIGHT_SCRAPER:
            return await line2.search_license(
                license_number=license_number,
                state=state,
                trade_name=trade_name,
            )
        elif line == DefenseLine.GEMINI_AGENT:
            return await line3.search_license(
                license_number=license_number,
                state=state,
            )
    except Exception as e:
        return VerificationResponse(
            license_number=license_number,
            state=state,
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


@app.get("/api/states")
async def list_states():
    """Return supported states for the dropdown."""
    return [
        {"code": code, "name": cfg.name}
        for code, cfg in STATE_CONFIGS.items()
    ]


# ---------------------------------------------------------------------------
# GCS file listing and preview
# ---------------------------------------------------------------------------

from google.cloud import storage as gcs_storage

_gcs_client = None

def _get_gcs_client():
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = gcs_storage.Client()
    return _gcs_client


def _parse_gcs_path(gcs_path: str):
    """Parse gs://bucket/prefix into (bucket, prefix)."""
    path = gcs_path.replace("gs://", "")
    parts = path.split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    return bucket, prefix


@app.get("/api/gcs/list")
async def gcs_list(path: str):
    """List files in a GCS path."""
    try:
        bucket_name, prefix = _parse_gcs_path(path)
        client = _get_gcs_client()
        bucket = client.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix=prefix))

        files = []
        for blob in blobs:
            if blob.name.endswith("/"):
                continue
            name = blob.name.split("/")[-1]
            lower = name.lower()
            if lower.endswith(".pdf"):
                ftype = "pdf"
            elif any(lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".webp")):
                ftype = "image"
            else:
                continue  # skip non-document files

            size_kb = blob.size / 1024
            size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"

            files.append({
                "name": name,
                "path": f"gs://{bucket_name}/{blob.name}",
                "type": ftype,
                "size": size_str,
            })

        return {"files": files}
    except Exception as e:
        return {"files": [], "error": str(e)}


@app.get("/api/gcs/preview")
async def gcs_preview(path: str):
    """Serve a GCS file for preview (images and PDFs)."""
    from fastapi.responses import Response

    try:
        bucket_name, blob_path = _parse_gcs_path(path)
        client = _get_gcs_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        data = blob.download_as_bytes()

        content_type = blob.content_type or "application/octet-stream"
        lower = blob_path.lower()
        if lower.endswith(".pdf"):
            content_type = "application/pdf"
        elif lower.endswith(".jpg") or lower.endswith(".jpeg"):
            content_type = "image/jpeg"
        elif lower.endswith(".png"):
            content_type = "image/png"
        elif lower.endswith(".tiff"):
            content_type = "image/tiff"
        elif lower.endswith(".webp"):
            content_type = "image/webp"

        return Response(content=data, media_type=content_type)
    except Exception as e:
        return Response(content=str(e), status_code=404)


# ---------------------------------------------------------------------------
# Single File Mode: upload file + cascade with SSE progress
# ---------------------------------------------------------------------------

_single_state: dict | None = None


async def _run_cascade(
    license_number: str,
    state: str,
    queue: asyncio.Queue,
    trade_name: str | None = None,
    address: str | None = None,
    city: str | None = None,
    permit_type: str | None = None,
    defense_line: int | None = None,
):
    """Run methods sequentially, pushing progress events to the queue."""
    all_lines = [
        (DefenseLine.HTTP_DIRECT, "HTTP Direct Request"),
        (DefenseLine.PLAYWRIGHT_SCRAPER, "Playwright Scraper"),
        # Method 3 (Gemini Agent) disabled for now
    ]

    # If a specific method is requested, only run that one
    if defense_line:
        lines = [(dl, label) for dl, label in all_lines if dl.value == defense_line]
        if not lines:
            await queue.put({"status": "complete", "result": None})
            return
    else:
        lines = all_lines

    for line_enum, line_label in lines:
        # Notify: starting this line
        await queue.put({
            "defense_line": line_enum.value,
            "label": line_label,
            "status": "running",
        })

        result = await _run_line(
            license_number, state, line_enum,
            trade_name=trade_name,
        )

        if result.verified:
            await queue.put({
                "defense_line": line_enum.value,
                "label": line_label,
                "status": "success",
                "result": result.model_dump(),
            })
            await queue.put({"status": "complete", "result": result.model_dump()})
            return

        if result.error:
            await queue.put({
                "defense_line": line_enum.value,
                "label": line_label,
                "status": "failed",
                "error": result.error,
            })
        else:
            # No error but not verified (0 results)
            await queue.put({
                "defense_line": line_enum.value,
                "label": line_label,
                "status": "no_results",
            })

    # All lines exhausted
    await queue.put({
        "status": "complete",
        "result": result.model_dump() if result else None,
    })


@app.post("/api/verify/upload")
async def verify_upload(
    file: UploadFile = File(...),
    state: str = Form(...),
):
    """
    Single File Mode: upload a license PDF/image, send to Document AI
    for field extraction, and return extracted fields with confidence scores.

    The frontend displays these in the review form (HITL step) before
    the user triggers the websearch cascade.
    """
    file_bytes = await file.read()
    filename = file.filename or "unknown"

    # Determine MIME type
    lower = filename.lower()
    if lower.endswith(".pdf"):
        mime_type = "application/pdf"
    elif lower.endswith((".jpg", ".jpeg")):
        mime_type = "image/jpeg"
    elif lower.endswith(".png"):
        mime_type = "image/png"
    elif lower.endswith(".tiff"):
        mime_type = "image/tiff"
    elif lower.endswith(".webp"):
        mime_type = "image/webp"
    else:
        mime_type = file.content_type or "application/octet-stream"

    try:
        extraction = extract_fields(file_bytes, mime_type)
        search_fields = build_search_fields(extraction)

        # Override state if jurisdiction was extracted with high confidence
        if search_fields["state"]["value"]:
            resolved_state = search_fields["state"]["value"]
        else:
            resolved_state = state

        return {
            "filename": filename,
            "state": resolved_state,
            "size_bytes": len(file_bytes),
            "fields": search_fields,
        }
    except Exception as e:
        logging.error(f"Document AI extraction failed: {e}")
        return {
            "filename": filename,
            "state": state,
            "size_bytes": len(file_bytes),
            "fields": None,
            "error": f"Extraction failed: {str(e)}",
        }


@app.post("/api/verify/start")
async def verify_start(
    license_number: str = Form(...),
    state: str = Form(...),
    permit_type: str = Form(""),
    trade_name: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    defense_line: str = Form(""),
):
    """Start the cascade for a single license and stream progress via SSE."""
    global _single_state

    if state not in SUPPORTED_STATES:
        return {"error": f"Unsupported state: {state}"}

    dl = int(defense_line) if defense_line else None

    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(
        _run_cascade(
            license_number, state, queue,
            trade_name=trade_name or None,
            address=address or None,
            city=city or None,
            permit_type=permit_type or None,
            defense_line=dl,
        )
    )

    _single_state = {
        "task": task,
        "queue": queue,
        "license_number": license_number,
        "state": state,
    }

    return {"status": "started", "license_number": license_number, "state": state}


@app.get("/api/verify/status")
async def verify_status():
    """SSE endpoint — streams defense line cascade progress to the frontend."""
    if not _single_state:
        return {"error": "No verification running."}

    async def event_stream():
        queue = _single_state["queue"]
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") == "complete":
                    break
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'status': 'keepalive'})}\n\n"
            except Exception:
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Batch with SSE streaming
# ---------------------------------------------------------------------------

from pydantic import BaseModel


class BatchStartRequest(BaseModel):
    licenses: list[LicenseSearchRequest]
    defense_line: int | None = None


_batch_state: dict | None = None


async def _run_batch(
    licenses: list[LicenseSearchRequest],
    defense_line: DefenseLine | None,
    queue: asyncio.Queue,
):
    """Process licenses sequentially and push status events to the queue."""
    for req in licenses:
        await queue.put({
            "license_number": req.license_number,
            "status": "running",
        })

        try:
            # If a specific line is requested, use it; otherwise cascade
            if defense_line:
                result = await _run_line(req.license_number, req.state or "TX", defense_line)
            else:
                # Simple cascade for batch: try each line
                for ln in [DefenseLine.HTTP_DIRECT, DefenseLine.PLAYWRIGHT_SCRAPER]:
                    result = await _run_line(req.license_number, req.state or "TX", ln)
                    if result.verified or result.error is None:
                        break

            await queue.put({
                "license_number": req.license_number,
                "status": "verified" if result.verified else "not_found",
                "defense_line_used": result.defense_line_used,
                "result_count": len(result.results),
                "error": result.error,
            })
        except Exception as e:
            await queue.put({
                "license_number": req.license_number,
                "status": "error",
                "error": str(e),
            })

    await queue.put({"status": "complete"})


@app.post("/api/batch/start")
async def batch_start(body: BatchStartRequest):
    global _batch_state

    if _batch_state and not _batch_state["task"].done():
        return {"error": "A batch is already running."}, 409

    queue: asyncio.Queue = asyncio.Queue()
    defense = DefenseLine(body.defense_line) if body.defense_line else None

    task = asyncio.create_task(
        _run_batch(body.licenses, defense, queue)
    )

    _batch_state = {
        "task": task,
        "queue": queue,
        "status": "running",
        "license_count": len(body.licenses),
    }

    return {"batch_id": "current", "license_count": len(body.licenses)}


@app.get("/api/batch/status")
async def batch_status():
    """SSE endpoint — streams batch progress events to the frontend."""
    if not _batch_state:
        return {"error": "No batch running."}

    async def event_stream():
        queue = _batch_state["queue"]
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") == "complete":
                    break
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'status': 'keepalive'})}\n\n"
            except Exception:
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/batch/cancel")
async def batch_cancel():
    global _batch_state

    if not _batch_state or _batch_state["task"].done():
        return {"error": "No batch running."}

    _batch_state["task"].cancel()
    _batch_state["status"] = "cancelled"
    return {"status": "cancelled"}
