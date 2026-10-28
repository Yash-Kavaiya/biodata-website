#!/usr/bin/env python3
"""
Biodata Management System - Run Script
"""
import os

import uvicorn

from backend.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
