# Biodata Management System

Upload matrimonial biodata PDFs/photos, extract every field with an LLM (NVIDIA Nemotron, Gemini on Vertex AI, or Claude), review and correct the results, then find compatible matches.

## Features

- **Upload**: single files, multi-file, or whole folders (up to 200 files) with background processing and live progress
- **LLM OCR**: NVIDIA Nemotron (vision model reads the page, Nemotron Ultra extracts fields), Gemini (Vertex AI) or Claude. Output is normalized (gender/marital status/age) before saving
- **Resilient queue**: rate limiting, retries with backoff on 429/5xx/timeouts, circuit breaker, cancellable batches
- **Validation workflow**: compare with the original document, then approve, edit (all 34 fields), re-run OCR, or reject
- **Matching**: search by preferences, by an existing profile, or by uploading a biodata (not stored)
- **Telegram bot** (optional): send a PDF/photo to your bot; it is OCR'd and added, with Approve / Reject buttons in the chat
- **Graph view** (optional): Neo4j relationship graph of approved profiles
- **Security**: optional HTTP Basic auth, uploads served only through the API, file type checked by content

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env        # set AUTH_PASSWORD and your OCR provider
python run.py               # http://localhost:8000
```

For NVIDIA, set `LLM_PROVIDER=nvidia` and `NVIDIA_API_KEY`. For Vertex AI, authenticate once with `gcloud auth application-default login` and set `GCP_PROJECT_ID`.
Set `LLM_PROVIDER=local` to run without any LLM: files are stored, but no fields are extracted.

API docs: http://localhost:8000/api/docs

### Telegram bot

1. Create a bot with [@BotFather](https://t.me/BotFather) and set `TELEGRAM_BOT_TOKEN`.
2. Start the app and send any message to your bot. It replies with your chat ID.
3. Add that ID to `TELEGRAM_ALLOWED_CHAT_IDS` and restart.

Then send biodata PDFs or photos (as a *file* for best quality). Commands: `/stats`, `/help`.
The bot uses long polling, so it works without a public URL. Run a single app process, since two pollers on one token conflict.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite runs the full workflow against the real API (upload → review → approve → match → delete) with a scripted OCR provider, in a temporary directory. It never touches your data, LLM, or Neo4j.

## Docker

```bash
docker build -t biodata .
docker run -p 8080:8080 --env-file .env -v biodata-data:/app/data biodata
```

Uploads and the JSON database live in the `/app/data` volume.

## Project structure

```
backend/
  main.py                 App setup, auth middleware, startup recovery
  config.py               Settings (env / .env)
  models/biodata.py       Pydantic schemas
  routers/                upload, biodata, validation, search, graph
  services/
    ocr_service.py        Providers + parsing/normalization/confidence
    queue_service.py      Rate limiter, retries, circuit breaker, batch jobs
    database_service.py   Thread-safe JSON database (atomic writes)
    storage_service.py    Local file storage, confined to UPLOAD_DIR
    similarity_service.py Weighted match scoring
    graph_service.py      Optional Neo4j sync and queries
frontend/                 AngularJS single page app
tests/                    End-to-end and unit tests
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/upload/models` | Selectable OCR models |
| POST | `/api/upload/single` | Upload and OCR one file (waits) |
| POST | `/api/upload/bulk` | Up to 50 files (waits) |
| POST | `/api/upload/async/bulk` | Large batch in background → `job_id` |
| POST | `/api/upload/async/single` | One file in background → `job_id` |
| GET | `/api/upload/batch/{id}/status` · `/results` | Batch progress / per-file results |
| DELETE | `/api/upload/batch/{id}` | Cancel remaining files in a batch |
| GET | `/api/biodata?page=&page_size=&status=&q=` | List with filters |
| GET | `/api/biodata/stats` · `/pending` · `/approved` | Counts / review queue / approved |
| GET/PUT/DELETE | `/api/biodata/{id}` | Read / update / delete |
| GET | `/api/biodata/{id}/file` | Original document (`?download=true` to save) |
| POST | `/api/biodata` | Create manually (pre-approved) |
| POST | `/api/validation/approve/{id}` · `reject/{id}` · `edit/{id}` · `re-ocr/{id}` | Review actions |
| POST | `/api/validation/auto-approve-all?min_confidence=` | Bulk approve |
| POST | `/api/search/preferences` · `by-biodata/{id}` · `by-upload` | Matching |
| GET | `/api/search/stats` | Approved profile summary |
| GET | `/api/graph/data` · `stats` · `similar/{id}` | Graph (Neo4j) |
| POST | `/api/graph/sync` | Rebuild graph from the database |
| GET | `/api/health` | Health check (no auth) |

## Data and privacy

Biodatas contain personal data. `backend/db/*.json` and `uploads/` are git-ignored; keep them out of version control, set `AUTH_USERNAME`/`AUTH_PASSWORD` before exposing the app beyond your machine, and serve it over HTTPS.
