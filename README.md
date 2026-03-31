# Alcohol License Verification — Web Search Automation

Automated verification of alcohol licenses against state government websites, implementing a **3 Lines of Defense** strategy. Supports Texas (TABC), Florida (DBPR), and Georgia (DOR).

## Architecture

Upload a license document → Document AI extracts fields → Human reviews (HITL) → Cascade verification against state website.

![Solution Architecture](imgs/flow.png)

### Defense Lines

| Line | Method | Tech | Description |
|------|--------|------|-------------|
| **1st** | HTTP Direct | `httpx` | POST to the state search endpoint. Fastest, lowest overhead. |
| **2nd** | Browser Automation | `playwright` | Fill form fields and parse DOM. Fallback when HTTP is blocked. |
| **3rd** | AI Agent (Computer Use) | `google-adk` + `gemini-2.5-computer-use` | Gemini visually browses the site like a human. Most resilient but slowest. |

Safety limits on Method 3: max 25 steps and 180s timeout to prevent runaway token usage.

## App Modes

### Single File Mode
- Upload a license PDF/image, select state
- Document AI extracts fields with confidence scores (high/medium/low)
- Quick search by license number only, or full verification on all extracted fields
- Visual cascade showing each defense line: idle → running → success/failed
- Structured JSON output with copy-to-clipboard

### Batch Mode
- Browse files from a GCS path, select state and verification method
- Concurrent Document AI extraction + web verification pipeline
- Configurable cascade: Method 1 & 2 (default), all methods, or individual methods
- Results displayed in 3 columns: low-confidence extractions (yellow), failed (red), verified (green)
- Compiled JSON output

## Project Structure

```
websearch_automation/
├── server.py                      # FastAPI entry point
├── .env                           # GCP project config
├── backend/
│   ├── config.py                  # State configs, constants
│   ├── models.py                  # Pydantic models (LicenseResult, VerificationResponse)
│   ├── document_ai.py             # Document AI extraction
│   ├── defense_line_1_http.py     # HTTP direct
│   ├── defense_line_2_scraper.py  # Playwright browser automation
│   ├── defense_line_3_agent.py    # Gemini Computer Use agent (ADK)
│   └── playwright_computer.py     # Browser interface for ADK ComputerUseToolset
├── app/                           # React + TypeScript frontend
│   └── src/
│       ├── components/
│       │   ├── Header.tsx         # Mode toggle (Single File / Batch)
│       │   ├── SingleFilePanel.tsx # Upload + defense cascade
│       │   └── BatchList.tsx      # GCS file browser + batch processing
│       └── services/
│           └── apiClient.ts       # API client (SSE streaming)
└── imgs/
```

## Setup

### Prerequisites

- Python 3.10+
- Node.js v18+
- Google Cloud authentication (`gcloud auth application-default login`)
- Vertex AI API enabled

### IAM Roles

The service account needs:
- `roles/documentai.apiUser` — Document AI extraction
- `roles/aiplatform.user` — Vertex AI / Gemini
- `roles/storage.objectViewer` — GCS file access

### Environment

```bash
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_GENAI_USE_VERTEXAI=1
```

Or use a `.env` file in the project root.

### Install & Run

```bash
# Python dependencies
pip install -r requirements.txt
playwright install chromium

# Frontend
cd app && npm install

# Start backend (terminal 1)
uvicorn server:app --host 0.0.0.0 --port 8000 --reload

# Start frontend (terminal 2)
cd app && npm run dev # alt. npx vite --host 0.0.0.0
```

App runs at [http://localhost:3000](http://localhost:3000).

### CLI Testing

```bash
python -m backend.defense_line_1_http --license 200034858
python -m backend.defense_line_2_scraper --license 200034858
python -m backend.defense_line_3_agent --license 200034858
```

## Containerization preparation for Deployment

Build and push to Registry using the following:

### Dockerfile

Create a `Dockerfile`:

```dockerfile
# Stage 1 — Build React frontend
FROM node:20-slim AS frontend-build
WORKDIR /build
COPY app/package.json app/package-lock.json ./
RUN npm ci
COPY app/ ./
RUN npm run build

# Stage 2 — Runtime (Playwright base image includes Chromium)
FROM mcr.microsoft.com/playwright/python:v1.52.0-noble
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY server.py ./

COPY --from=frontend-build /build/dist ./app/dist/

RUN playwright install chromium

EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Static File Serving

In the container there is no Vite dev server, so FastAPI needs to serve the built React files itself.

To enable this, `server.py` needs a static file mount added at the end of the file. This mount should:

- Point to the `app/dist/` directory (where the Dockerfile copies the built frontend)
- Use FastAPI's `StaticFiles` with HTML mode enabled, so that non-API route serves `index.html`
- This must be added at the end of `server.py`. FastAPI matches routes top-to-bottom so if the static file handler (which catches all paths) is registered before the `/api` routes, API requests would incorrectly be handled and fail