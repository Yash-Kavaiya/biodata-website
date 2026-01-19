"""
Biodata Management System - FastAPI Application
A full-stack application for biodata OCR processing and match finding.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from backend.config import settings
from backend.routers import upload_router, biodata_router, validation_router, search_router

# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
    Biodata Management System with LLM-powered OCR.

    Features:
    - Upload single or bulk biodata PDF/images
    - LLM-based OCR extraction
    - Validation and approval workflow
    - Similarity-based match finding
    """,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    from backend.services import neo4j_service
    neo4j_service.connect()


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(upload_router)
app.include_router(biodata_router)
app.include_router(validation_router)
app.include_router(search_router)

# Serve static files
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path / "static")), name="static")

# Serve uploaded files
if settings.UPLOAD_DIR.exists():
    app.mount("/files", StaticFiles(directory=str(settings.UPLOAD_DIR)), name="files")


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION
    }


@app.get("/api/info")
async def app_info():
    """Application information."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "features": [
            "Single/Bulk file upload",
            "LLM-powered OCR",
            "OCR validation workflow",
            "Similarity-based matching",
            "JSON local database",
            "Local file storage (cloud-ready)"
        ]
    }


# Serve frontend
@app.get("/")
async def serve_frontend():
    """Serve the main frontend page."""
    index_path = frontend_path / "templates" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Welcome to Biodata Management System. Visit /api/docs for API documentation."}


@app.get("/{path:path}")
async def serve_static_files(path: str):
    """Serve static files or fall back to index."""
    # Try to serve static file
    static_file = frontend_path / "static" / path
    if static_file.exists() and static_file.is_file():
        return FileResponse(str(static_file))

    # Try templates
    template_file = frontend_path / "templates" / path
    if template_file.exists() and template_file.is_file():
        return FileResponse(str(template_file))

    # Fall back to index for SPA routing
    index_path = frontend_path / "templates" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))

    return {"error": "Not found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
