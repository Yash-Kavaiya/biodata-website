"""
Biodata Management System - FastAPI Application
A full-stack application for biodata OCR processing and match finding.
"""
import asyncio
import base64
import binascii
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.routers import biodata_router, graph_router, search_router, upload_router, validation_router
from backend.services import db, graph_service, ocr_service
from backend.services.telegram_bot import create_bot

logging.basicConfig(
    level=settings.LOG_LEVEL.upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("biodata")
# httpx logs full request URLs at INFO, and Telegram URLs contain the bot token
logging.getLogger("httpx").setLevel(logging.WARNING)
# Neo4j reports "index already exists" for every idempotent schema statement at startup
logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
INDEX_HTML = FRONTEND_DIR / "templates" / "index.html"

# Paths reachable without credentials (for load balancer / container health checks)
PUBLIC_PATHS = {"/api/health"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    recovered = await db.recover_interrupted()
    if recovered:
        logger.warning(f"Marked {recovered} interrupted OCR job(s) as failed")
    if graph_service.configured:
        await graph_service.initialize_schema()
    if not settings.auth_enabled:
        logger.warning("AUTH_USERNAME/AUTH_PASSWORD not set: the app and its personal data are unprotected")
    logger.info(f"OCR provider: {ocr_service.provider_name}")

    bot = create_bot()
    bot_task = asyncio.create_task(bot.run()) if bot else None
    yield
    if bot_task:
        bot_task.cancel()
        await asyncio.gather(bot_task, return_exceptions=True)
        await bot.close()
    graph_service.close()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Upload biodata PDFs/images, extract fields with an LLM, review them, and find compatible matches.",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


def _credentials_valid(header: str) -> bool:
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        username, _, password = base64.b64decode(encoded).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return False
    user_ok = secrets.compare_digest(username.encode(), settings.AUTH_USERNAME.encode())
    pass_ok = secrets.compare_digest(password.encode(), settings.AUTH_PASSWORD.encode())
    return user_ok and pass_ok


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """Require HTTP Basic credentials on every route when AUTH_USERNAME/AUTH_PASSWORD are set."""
    if (
        settings.auth_enabled
        and request.method != "OPTIONS"
        and request.url.path not in PUBLIC_PATHS
        and not _credentials_valid(request.headers.get("authorization", ""))
    ):
        return JSONResponse(
            {"detail": "Authentication required"},
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Biodata Manager"'},
        )
    return await call_next(request)


if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(upload_router)
app.include_router(biodata_router)
app.include_router(validation_router)
app.include_router(search_router)
app.include_router(graph_router)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")


@app.get("/api/health")
async def health_check():
    """Liveness check (never requires auth)."""
    return {"status": "healthy", "app": settings.APP_NAME, "version": settings.APP_VERSION}


@app.get("/api/info")
async def app_info():
    """Runtime configuration summary."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "ocr_provider": ocr_service.provider_name,
        "graph_enabled": graph_service.configured,
        "auth_enabled": settings.auth_enabled,
        "telegram_enabled": bool(settings.TELEGRAM_BOT_TOKEN),
        "max_file_size_mb": settings.MAX_FILE_SIZE_MB,
        "max_bulk_files": settings.MAX_BULK_FILES,
    }


@app.get("/", include_in_schema=False)
async def serve_frontend():
    return FileResponse(INDEX_HTML)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)
