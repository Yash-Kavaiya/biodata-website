"""
Queue Service - Advanced rate limiting, retry logic, and batch processing.
Handles 100+ concurrent uploads with proper backpressure.
"""
import asyncio
import logging
import random
import time
from typing import TypeVar, Callable, Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
import uuid


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

T = TypeVar("T")
logger = logging.getLogger(__name__)


class BatchStatus(str, Enum):
    """Status of a batch job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL = "partial"  # Some succeeded, some failed
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BatchJob:
    """Tracks a batch processing job."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    total: int = 0
    processed: int = 0
    successful: int = 0
    failed: int = 0
    status: BatchStatus = BatchStatus.PENDING
    created_at: datetime = field(default_factory=_utcnow)
    completed_at: Optional[datetime] = None
    cancelled: bool = False
    errors: List[Dict[str, str]] = field(default_factory=list)
    results: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def progress_percent(self) -> float:
        return (self.processed / self.total * 100) if self.total > 0 else 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "total": self.total,
            "processed": self.processed,
            "successful": self.successful,
            "failed": self.failed,
            "progress_percent": round(self.progress_percent, 1),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "errors": self.errors[-10:],  # Last 10 errors only
        }


class CircuitOpenError(Exception):
    """Raised when the circuit breaker rejects a call."""


class TokenBucket:
    """
    Token bucket rate limiter.
    Allows burst capacity while maintaining average rate.
    """
    def __init__(self, rate: float, capacity: int):
        """
        Args:
            rate: Tokens added per second
            capacity: Maximum tokens (burst capacity)
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> float:
        """
        Reserve tokens and return how long the caller must wait before using them.
        Tokens may go negative: each caller reserves its own slot, so concurrent
        waiters are spread out instead of all firing when the bucket refills.
        """
        async with self._lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.last_update) * self.rate)
            self.last_update = now
            self.tokens -= tokens
            return max(0.0, -self.tokens / self.rate)


class CircuitBreaker:
    """
    Circuit breaker pattern to prevent cascading failures.
    Opens circuit after consecutive failures, allowing recovery.
    """
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max: int = 3
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max

        self.failures = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed, open, half-open
        self.half_open_successes = 0
        self._lock = asyncio.Lock()

    async def can_execute(self) -> bool:
        """Check if execution is allowed."""
        async with self._lock:
            if self.state == "closed":
                return True

            if self.state == "open":
                # Check if recovery timeout passed
                if self.last_failure_time and \
                   time.monotonic() - self.last_failure_time >= self.recovery_timeout:
                    self.state = "half-open"
                    self.half_open_successes = 0
                    logger.info("Circuit breaker entering half-open state")
                    return True
                return False

            # half-open: allow limited requests
            return self.half_open_successes < self.half_open_max

    async def record_success(self):
        """Record a successful execution."""
        async with self._lock:
            if self.state == "half-open":
                self.half_open_successes += 1
                if self.half_open_successes >= self.half_open_max:
                    self.state = "closed"
                    self.failures = 0
                    logger.info("Circuit breaker closed after recovery")
            else:
                self.failures = 0

    async def record_failure(self):
        """Record a failed execution."""
        async with self._lock:
            self.failures += 1
            self.last_failure_time = time.monotonic()

            if self.state == "half-open":
                self.state = "open"
                logger.warning("Circuit breaker re-opened after half-open failure")
            elif self.failures >= self.failure_threshold:
                self.state = "open"
                logger.warning(f"Circuit breaker opened after {self.failures} failures")


class QueueService:
    """
    Advanced queue service with rate limiting, retry, and batch processing.
    Optimized for handling 100+ concurrent file uploads.
    """

    def __init__(
        self,
        concurrency: int = 5,
        requests_per_minute: int = 60,
        burst_capacity: int = 10,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ):
        """
        Initialize the queue service.

        Args:
            concurrency: Maximum concurrent tasks
            requests_per_minute: Rate limit (RPM)
            burst_capacity: Max burst requests
            max_retries: Maximum retry attempts
            base_delay: Base delay for exponential backoff (seconds)
            max_delay: Maximum delay between retries (seconds)
        """
        self.semaphore = asyncio.Semaphore(concurrency)
        self.rate_limiter = TokenBucket(
            rate=requests_per_minute / 60.0,  # Convert to per-second
            capacity=burst_capacity
        )
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=10,
            recovery_timeout=60.0
        )
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

        # Batch job tracking
        self._batch_jobs: Dict[str, BatchJob] = {}
        self._jobs_lock = asyncio.Lock()

    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if an error is retryable (rate limit, temporary failure)."""
        if isinstance(error, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
            return True
        status = getattr(getattr(error, "response", None), "status_code", None) or getattr(error, "code", None)
        if isinstance(status, int):
            return status in (408, 429, 500, 502, 503, 504, 529)
        error_str = str(error).lower()
        retryable_patterns = [
            "429",  # Rate limit
            "503",  # Service unavailable
            "502",  # Bad gateway
            "529",  # Overloaded
            "overloaded",
            "unavailable",
            "resource_exhausted",
            "quota",
            "rate limit",
            "too many requests",
            "temporarily unavailable",
            "timeout",
        ]
        return any(pattern in error_str for pattern in retryable_patterns)

    async def _execute_with_retry(
        self,
        func: Callable[..., Any],
        *args,
        **kwargs
    ) -> Any:
        """Execute function with exponential backoff retry."""
        last_error = None

        for attempt in range(self.max_retries + 1):
            if not await self.circuit_breaker.can_execute():
                raise CircuitOpenError("OCR service temporarily unavailable (circuit breaker open)")
            try:
                result = await func(*args, **kwargs)
                await self.circuit_breaker.record_success()
                return result

            except Exception as e:
                last_error = e

                # Bad input (corrupt file, invalid model) is not a provider outage:
                # don't count it toward the circuit breaker and don't retry it.
                if not self._is_retryable_error(e):
                    logger.error(f"Non-retryable error: {e}")
                    raise

                await self.circuit_breaker.record_failure()

                # Don't retry on last attempt
                if attempt >= self.max_retries:
                    logger.error(f"Max retries ({self.max_retries}) exceeded: {e}")
                    raise

                # Exponential backoff with jitter
                delay = min(self.base_delay * (2 ** attempt) * random.uniform(1.0, 1.5), self.max_delay)
                logger.warning(f"Retry {attempt + 1}/{self.max_retries} after {delay:.1f}s: {e}")
                await asyncio.sleep(delay)

        raise last_error

    async def process_with_limit(
        self,
        func: Callable[..., Any],
        *args,
        **kwargs
    ) -> Any:
        """
        Execute a function with rate limiting and retry logic.

        Args:
            func: The async function to execute.
            *args: Arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            The result of the function call.
        """
        # Wait for rate limit token
        wait_time = await self.rate_limiter.acquire()
        if wait_time > 0:
            logger.debug(f"Rate limited, waiting {wait_time:.2f}s")
            await asyncio.sleep(wait_time)

        # Acquire semaphore slot
        async with self.semaphore:
            return await self._execute_with_retry(func, *args, **kwargs)

    # ==================== Batch Processing ====================

    async def create_batch_job(self, total: int) -> BatchJob:
        """Create a new batch job for tracking."""
        await self.cleanup_old_jobs()
        job = BatchJob(total=total, status=BatchStatus.PROCESSING)
        async with self._jobs_lock:
            self._batch_jobs[job.id] = job
        return job

    async def get_batch_job(self, job_id: str) -> Optional[BatchJob]:
        """Get batch job by ID."""
        async with self._jobs_lock:
            return self._batch_jobs.get(job_id)

    async def update_batch_progress(
        self,
        job: BatchJob,
        success: bool,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        filename: Optional[str] = None
    ):
        """Update batch job progress."""
        async with self._jobs_lock:
            job.processed += 1
            if success:
                job.successful += 1
                if result:
                    job.results.append(result)
            else:
                job.failed += 1
                if error:
                    job.errors.append({
                        "filename": filename or "unknown",
                        "error": error[:200]  # Truncate long errors
                    })

            # Update status on completion
            if job.processed >= job.total and not job.cancelled:
                job.completed_at = _utcnow()
                if job.failed == 0:
                    job.status = BatchStatus.COMPLETED
                elif job.successful == 0:
                    job.status = BatchStatus.FAILED
                else:
                    job.status = BatchStatus.PARTIAL

    async def cancel_batch_job(self, job: BatchJob):
        """Stop scheduling further files for a job. In-flight OCR calls still finish."""
        async with self._jobs_lock:
            if job.status == BatchStatus.PROCESSING:
                job.cancelled = True
                job.status = BatchStatus.CANCELLED
                job.completed_at = _utcnow()

    async def cleanup_old_jobs(self, max_age_hours: int = 24):
        """Remove old completed jobs to prevent memory leaks."""
        async with self._jobs_lock:
            now = _utcnow()
            to_remove = []
            for job_id, job in self._batch_jobs.items():
                if job.completed_at:
                    age = (now - job.completed_at).total_seconds() / 3600
                    if age > max_age_hours:
                        to_remove.append(job_id)

            for job_id in to_remove:
                del self._batch_jobs[job_id]

            if to_remove:
                logger.info(f"Cleaned up {len(to_remove)} old batch jobs")


# Create instance using config values
def create_queue_service() -> QueueService:
    """Create queue service with settings from config."""
    from backend.config import settings
    return QueueService(
        concurrency=settings.QUEUE_CONCURRENCY,
        requests_per_minute=settings.REQUESTS_PER_MINUTE,
        burst_capacity=settings.BURST_CAPACITY,
        max_retries=settings.MAX_RETRIES,
        base_delay=settings.RETRY_BASE_DELAY,
        max_delay=settings.RETRY_MAX_DELAY,
    )


# Default singleton instance
queue_service = create_queue_service()
