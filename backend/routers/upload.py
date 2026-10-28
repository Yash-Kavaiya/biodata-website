"""
Upload Router - single and bulk uploads with rate-limited, retried OCR.
A record is only created when OCR succeeds; failed files are deleted.
"""
import asyncio
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile

from backend.config import settings
from backend.models import BiodataInDB, BulkUploadResponse, OCRStatus, UploadResponse
from backend.services import db, ocr_service, queue_service, storage_service
from backend.services.queue_service import BatchJob
from backend.services.storage_service import content_matches_extension

router = APIRouter(prefix="/api/upload", tags=["upload"])
logger = logging.getLogger(__name__)

MAX_SYNC_BULK_FILES = 50


# ==================== Helpers ====================

def validate_upload_content(filename: str, content: bytes) -> str:
    """Check extension, size and file signature; return the extension. Raises ValueError."""
    ext = Path(filename or "").suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise ValueError(f"Invalid file type. Allowed: {', '.join(settings.ALLOWED_EXTENSIONS)}")
    if len(content) > settings.max_file_bytes:
        raise ValueError(f"File too large. Max size: {settings.MAX_FILE_SIZE_MB}MB")
    if not content_matches_extension(content, ext):
        raise ValueError(f"File content does not look like a valid {ext[1:].upper()}")
    return ext


async def read_valid_upload(file: UploadFile) -> Tuple[bytes, str]:
    """Read an upload (bounded by the size limit) and validate it. Raises ValueError."""
    content = await file.read(settings.max_file_bytes + 1)
    return content, validate_upload_content(file.filename or "", content)


def checked_model(model: Optional[str]) -> Optional[str]:
    try:
        return ocr_service.validate_model(model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def failed(filename: str, message: str) -> UploadResponse:
    return UploadResponse(id="", filename=filename, status=OCRStatus.FAILED, message=message)


async def ingest_file(file_path: str, filename: str, model: Optional[str] = None) -> UploadResponse:
    """
    OCR a stored file (rate limited, with retries) and create its record.
    On failure the file is deleted and no record is created.
    """
    try:
        result = await queue_service.process_with_limit(ocr_service.process_file, file_path, model=model)
        biodata = BiodataInDB(
            **result.data,
            file_path=file_path,
            original_filename=filename,
            ocr_status=OCRStatus.COMPLETED,
            ocr_confidence=result.confidence,
            raw_ocr_text=result.raw_text,
        )
        saved = await db.create(biodata)
        return UploadResponse(
            id=saved.id,
            filename=filename,
            status=OCRStatus.COMPLETED,
            message=f"Processed with {result.confidence:.0%} confidence",
        )
    except Exception as e:
        logger.error(f"OCR failed for {filename}: {e}")
        await storage_service.delete_file(file_path)
        return failed(filename, f"OCR failed: {str(e)[:200]}")


async def process_upload(file: UploadFile, model: Optional[str]) -> UploadResponse:
    """Validate, store and OCR one upload."""
    filename = file.filename or "unknown"
    try:
        content, _ = await read_valid_upload(file)
    except ValueError as e:
        return failed(filename, str(e))
    file_path = await storage_service.save_file_content(content, filename)
    return await ingest_file(file_path, filename, model)


async def run_batch(job: BatchJob, items: List[Tuple[str, str]], model: Optional[str]):
    """Background worker: OCR every (file_path, filename); the queue bounds concurrency."""
    async def process_one(file_path: str, filename: str):
        if job.cancelled:
            await storage_service.delete_file(file_path)
            return
        result = await ingest_file(file_path, filename, model)
        ok = result.status != OCRStatus.FAILED
        await queue_service.update_batch_progress(
            job,
            success=ok,
            result=result.model_dump(mode="json") if ok else None,
            error=None if ok else result.message,
            filename=filename,
        )

    await asyncio.gather(*(process_one(path, name) for path, name in items))
    logger.info(f"Batch {job.id} finished: {job.successful}/{job.total} successful")


async def queue_files(files: List[UploadFile], model: Optional[str], background_tasks: BackgroundTasks) -> dict:
    """Validate and store files, then schedule OCR in the background."""
    stored: List[Tuple[str, str]] = []
    errors: List[dict] = []
    for file in files:
        filename = file.filename or "unknown"
        try:
            content, _ = await read_valid_upload(file)
        except ValueError as e:
            errors.append({"filename": filename, "error": str(e)})
            continue
        stored.append((await storage_service.save_file_content(content, filename), filename))

    job = await queue_service.create_batch_job(len(stored) + len(errors))
    for err in errors:
        await queue_service.update_batch_progress(job, success=False, error=err["error"], filename=err["filename"])

    background_tasks.add_task(run_batch, job, stored, model)
    return {
        "job_id": job.id,
        "total": len(files),
        "queued": len(stored),
        "validation_errors": len(errors),
        "errors": errors[:10],
        "message": f"Processing {len(stored)} files in background",
    }


# ==================== Endpoints ====================

@router.get("/models")
async def get_available_models():
    """OCR models the user can choose from."""
    return {
        "models": ocr_service.available_models(),
        "default": ocr_service.default_model(),
        "provider": ocr_service.provider_name,
    }


@router.post("/single", response_model=UploadResponse)
async def upload_single_file(
    file: UploadFile = File(...),
    model: Optional[str] = Query(None, description="Model to use for OCR"),
):
    """Upload and OCR a single biodata PDF/image (waits for the result)."""
    result = await process_upload(file, checked_model(model))
    if result.status == OCRStatus.FAILED:
        raise HTTPException(status_code=400, detail=result.message)
    return result


@router.post("/bulk", response_model=BulkUploadResponse)
async def upload_bulk_files(
    files: List[UploadFile] = File(...),
    model: Optional[str] = Query(None, description="Model to use for OCR"),
):
    """Upload up to 50 files and wait for all results. Use /async/bulk for larger batches."""
    if len(files) > MAX_SYNC_BULK_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_SYNC_BULK_FILES} files for sync upload. Use /api/upload/async/bulk.",
        )
    model = checked_model(model)
    results = await asyncio.gather(*(process_upload(f, model) for f in files))
    successful = sum(1 for r in results if r.status != OCRStatus.FAILED)
    return BulkUploadResponse(
        total=len(results), successful=successful, failed=len(results) - successful, uploads=list(results)
    )


@router.post("/async/bulk")
async def upload_bulk_async(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    model: Optional[str] = Query(None, description="Model to use for OCR"),
):
    """
    Upload a large batch (up to MAX_BULK_FILES) for background processing.
    Track progress with GET /api/upload/batch/{job_id}/status.
    """
    if len(files) > settings.MAX_BULK_FILES:
        raise HTTPException(status_code=400, detail=f"Maximum {settings.MAX_BULK_FILES} files per bulk upload.")
    return await queue_files(files, checked_model(model), background_tasks)


@router.post("/async/single")
async def upload_single_async(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    model: Optional[str] = Query(None, description="Model to use for OCR"),
):
    """Upload one file for background processing; returns a job id immediately."""
    return await queue_files([file], checked_model(model), background_tasks)


async def _get_job(job_id: str) -> BatchJob:
    job = await queue_service.get_batch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")
    return job


@router.get("/batch/{job_id}/status")
async def get_batch_status(job_id: str):
    """Progress, counts, recent errors and overall status of a batch job."""
    return (await _get_job(job_id)).to_dict()


@router.get("/batch/{job_id}/results")
async def get_batch_results(job_id: str):
    """Batch status plus the per-file results of successful items."""
    job = await _get_job(job_id)
    return {**job.to_dict(), "results": job.results}


@router.delete("/batch/{job_id}")
async def cancel_batch_job(job_id: str):
    """Cancel a batch: files not yet sent to OCR are skipped and deleted."""
    job = await _get_job(job_id)
    await queue_service.cancel_batch_job(job)
    return {"message": "Batch job cancelled", "job_id": job_id, "status": job.status.value}


@router.get("/queue/stats")
async def get_queue_stats():
    """Current queue/rate-limiter state, for monitoring."""
    return {
        "circuit_breaker_state": queue_service.circuit_breaker.state,
        "circuit_breaker_failures": queue_service.circuit_breaker.failures,
        "rate_limit_tokens": round(queue_service.rate_limiter.tokens, 2),
        "rate_limit_capacity": queue_service.rate_limiter.capacity,
        "config": {
            "concurrency": settings.QUEUE_CONCURRENCY,
            "requests_per_minute": settings.REQUESTS_PER_MINUTE,
            "max_bulk_files": settings.MAX_BULK_FILES,
        },
    }
