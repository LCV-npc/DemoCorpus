"""
app/main.py
FastAPI application — Web server cho PDF Medical Corpus Builder.
"""

import sys
from pathlib import Path

# Add project root to path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from infrastructure.database.mongo_client import close_client
from app.routers import scraper_router


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
        description="Hệ thống thu thập và xây dựng kho ngữ liệu y tế tiếng Việt",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(scraper_router.router, prefix="/api")

    # Static files
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()
