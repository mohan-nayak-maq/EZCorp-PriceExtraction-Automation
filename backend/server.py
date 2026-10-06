"""FastAPI app for the standalone web-search price tool.

Serves category metadata, single ad-hoc lookups, batch Excel jobs, and (when
``frontend/dist`` has been built) the React UI itself, so one container hosts
the whole tool.

    # from the project root (websearch-tool/)
    uvicorn backend.server:app --reload --port 8100
"""

from __future__ import annotations

import logging
import re
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import storage
from .batch import excel_io, jobs
from .categories import get_category, list_categories
from .config import PROJECT_DIR, get_websearch_settings
from .engine import search, search_multi
from .logging_config import configure_logging
from .models import SearchQuery, SearchResult

configure_logging()
log = logging.getLogger(__name__)

app = FastAPI(title="Web Search Price Tool", version="2.0.0")

# The UI is served from the same origin as the API, so CORS is off unless
# WEBSEARCH_CORS_ORIGINS explicitly lists other origins that need access.
if get_websearch_settings().cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_websearch_settings().cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Client-Id"],
    )

_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'"
)
# FastAPI's interactive docs load their JS/CSS from a CDN, so they skip the CSP.
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if not request.url.path.startswith(_DOCS_PATHS):
        response.headers.setdefault("Content-Security-Policy", _CSP)
    return response


def _require_category(key: str):
    category = get_category(key)
    if category is None:
        raise HTTPException(status_code=404, detail=f"Unknown category: {key}")
    return category


_CLIENT_ID_RE = re.compile(r"[A-Za-z0-9_-]{16,64}")


def _client_id(x_client_id: Annotated[str | None, Header()] = None) -> str:
    """Anonymous per-browser id the frontend generates once and keeps in localStorage.

    Every job/search is tagged with it, and history/view/export only return the
    caller's own runs, so users sharing the same URL don't see each other's data.
    """
    if not x_client_id or not _CLIENT_ID_RE.fullmatch(x_client_id):
        raise HTTPException(status_code=400, detail="Missing or invalid X-Client-Id header")
    return x_client_id


ClientId = Annotated[str, Depends(_client_id)]

MAX_UPLOAD_MB = 10
PREVIEW_ROWS = 10
PREVIEW_MAX_ERRORS = 20
HISTORY_LIMIT = 200


async def _read_upload(file: UploadFile) -> bytes:
    limit = MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"File is larger than the {MAX_UPLOAD_MB} MB upload limit.")
    return data


@app.get("/api/health")
def health() -> dict[str, object]:
    settings = get_websearch_settings()
    return {
        "status": "ok",
        "azure_configured": settings.configured,
        "ai_validation": settings.configured,
        "model": settings.azure_openai_deployment,
    }


@app.get("/api/categories")
def categories() -> list[dict]:
    return [c.to_metadata() for c in list_categories()]


@app.get("/api/categories/{key}/template")
def category_template(key: str) -> Response:
    category = _require_category(key)
    data = excel_io.build_template(category)
    log.info("GET /api/categories/%s/template: downloaded", key)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{key}_template.xlsx"'},
    )


@app.post("/api/search", response_model=SearchResult)
async def quick_search(payload: dict, client_id: ClientId) -> SearchResult:
    key = payload.get("category", "")
    category = _require_category(key)
    country = payload.get("country", "") or (category.allowed_countries[0] if category.allowed_countries else "")
    target_website = payload.get("target_website", "")
    fields = payload.get("fields") or {}
    if not isinstance(fields, dict):
        raise HTTPException(status_code=422, detail="fields must be an object.")
    # Field names only - the values are user-supplied product data.
    log.info("POST /api/search: category=%s, country=%r, site=%r, fields=%s", key, country, target_website, sorted(fields))

    country_error = category.validate_country(country)
    if country_error:
        raise HTTPException(status_code=422, detail=country_error)
    field_errors = category.validate_fields(fields)
    if field_errors:
        raise HTTPException(status_code=422, detail="; ".join(field_errors))

    settings = get_websearch_settings()
    if not settings.configured:
        raise HTTPException(status_code=503, detail="Azure OpenAI is not configured (set AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY)")

    if category.is_multi_site:
        result = await search_multi(country, fields, category)
        storage.save_search(result, client_id)
        return result

    if not target_website:
        raise HTTPException(status_code=422, detail="Target website is required for this category.")
    query = SearchQuery(category=category.key, country=country, target_website=target_website, fields=fields)
    if not query.domain:
        raise HTTPException(status_code=422, detail="Target website is not a valid domain or URL.")

    result = await search(query, category)
    storage.save_search(result, client_id)
    log.info("POST /api/search: %s (%.2fs)", result.status, result.elapsed_seconds or 0)
    if result.status == "error" and result.error:
        # result.error is already user-safe (engine.public_error / UpstreamError).
        raise HTTPException(status_code=502, detail=result.error)
    return result


@app.get("/api/history/searches")
def history_searches(client_id: ClientId, limit: int | None = None) -> dict:
    """The caller's recent ad-hoc (non-batch) lookups, most recent first - persisted across restarts."""
    limit = HISTORY_LIMIT if limit is None else max(1, min(limit, HISTORY_LIMIT))
    return {"searches": [r.model_dump() for r in storage.load_searches(client_id, limit)]}


@app.post("/api/batch/preview")
async def batch_preview(category: str, file: UploadFile) -> dict:
    cat = _require_category(category)
    data = await _read_upload(file)
    log.info("POST /api/batch/preview: category=%s, %d bytes", category, len(data))
    headers, rows, errors = await run_in_threadpool(excel_io.parse_workbook, data, cat)
    row_errors: list[str] = []
    for i, row in enumerate(rows):
        country = row.get("country") or (cat.allowed_countries[0] if cat.allowed_countries else "")
        err = cat.validate_country(country) if country else "Missing country"
        if err:
            row_errors.append(f"Row {i + 1}: {err}")
    log.info(
        "POST /api/batch/preview: %d row(s) parsed, %d parse error(s), %d row error(s)",
        len(rows), len(errors), len(row_errors),
    )
    return {
        "headers": headers,
        "row_count": len(rows),
        "preview_rows": rows[:PREVIEW_ROWS],
        "errors": errors,
        "row_errors": row_errors[:PREVIEW_MAX_ERRORS],
    }


@app.post("/api/batch/jobs")
async def create_batch_job(category: str, file: UploadFile, client_id: ClientId) -> dict:
    cat = _require_category(category)
    data = await _read_upload(file)
    _, rows, errors = await run_in_threadpool(excel_io.parse_workbook, data, cat)
    if errors:
        log.warning("POST /api/batch/jobs: rejected upload for %s - %s", category, errors)
        raise HTTPException(status_code=422, detail="; ".join(errors))
    try:
        job = jobs.create_job(cat, rows, client_id)
    except jobs.JobLimitError as exc:
        log.warning("POST /api/batch/jobs: rejected - %s", exc)
        raise HTTPException(status_code=429, detail=str(exc)) from None
    log.info("POST /api/batch/jobs: created job %s (%s, %d rows)", job.id, category, job.total)
    return {"job_id": job.id, "total": job.total}


@app.get("/api/batch/jobs")
def list_batch_jobs(client_id: ClientId) -> dict:
    items = []
    for job in jobs.list_jobs(client_id):
        matched = sum(1 for r in job.rows if r.result and r.result.status == "found")
        items.append({
            "id": job.id,
            "category": job.category,
            "status": job.status,
            "total": job.total,
            "matched": matched,
            "created_at": job.created_at,
        })
    return {"jobs": items}


@app.get("/api/batch/jobs/{job_id}")
def get_batch_job(job_id: str, client_id: ClientId) -> dict:
    job = jobs.get_job(job_id, client_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return job.model_dump(exclude={"owner"})


@app.get("/api/batch/jobs/{job_id}/export")
def export_batch_job(job_id: str, client_id: ClientId) -> Response:
    job = jobs.get_job(job_id, client_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    category = _require_category(job.category)
    data = excel_io.export_results(category, job.rows)
    log.info("GET /api/batch/jobs/%s/export: exported %d row(s)", job_id, len(job.rows))
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{job.category}_results_{job.id[:8]}.xlsx"'},
    )


# Serve the built React UI from the same origin as the API. Registered last so
# every /api route above takes precedence; unknown /api paths still return 404
# instead of the SPA's index.html.
FRONTEND_DIST = PROJECT_DIR / "frontend" / "dist"

if (FRONTEND_DIST / "index.html").is_file():
    if (FRONTEND_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    log.info("frontend/dist not found - serving the API only (run `npm run build` in frontend/ to bundle the UI)")
