"""
app/main.py
FastAPI application — Backend API server cho PDF Medical Corpus Builder.

Backend chỉ serve API. Frontend chạy riêng trên Vite dev server.
"""

import sys
from pathlib import Path

# Add project root to path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from infrastructure.database.mongo_client import close_client
from app.routers import scraper_router
from app.routers import paper_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup & shutdown events."""
    yield
    # Cleanup
    close_client()


def create_app() -> FastAPI:
    """Tạo và configure FastAPI app."""
    app = FastAPI(
        title="Medical PDF Corpus Builder",
        description=(
            "Backend API — Hệ thống thu thập và xây dựng kho ngữ liệu y tế tiếng Việt. "
            "Upload PDF → Pipeline M1–M9 → MongoDB → REST API."
        ),
        version="0.3.0",
        lifespan=lifespan,
    )

    # CORS — cho phép frontend dev server (Vite port 5173)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers — API only, không serve static files
    app.include_router(paper_router.router, prefix="/api", tags=["Papers"])
    app.include_router(scraper_router.router, prefix="/api", tags=["Scraper"])

    return app


app = create_app()
