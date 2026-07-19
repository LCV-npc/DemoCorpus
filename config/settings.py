"""
config/settings.py
Env-based settings, loaded from .env file via python-dotenv.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


class Settings:
    """Application settings — đọc từ biến môi trường, có default values."""

    def __init__(self):
        # MongoDB
        self.MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.MONGODB_DB: str = os.getenv("MONGODB_DB", "medical_corpus")

        # Storage directories
        self.UPLOAD_DIR: str = os.getenv(
            "UPLOAD_DIR",
            str(_PROJECT_ROOT / "data" / "uploads")
        )
        self.SCRAPE_DIR: str = os.getenv(
            "SCRAPE_DIR",
            str(_PROJECT_ROOT / "data" / "scraped_pdfs")
        )

        # File limits
        self.MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
        self.MAX_FILE_SIZE_BYTES: int = self.MAX_FILE_SIZE_MB * 1024 * 1024

        # Logging
        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

        # NER Model (Milestone 5+)
        self.NER_MODEL_PATH: str = os.getenv("NER_MODEL_PATH", "")

        # LLM (Milestone 8+)
        self.LLM_MODEL_PATH: str = os.getenv("LLM_MODEL_PATH", "")
        self.OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
        self.OPENAI_API_URL: str = os.getenv("OPENAI_API_URL", "")

        # Ensure directories exist
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)
        os.makedirs(self.SCRAPE_DIR, exist_ok=True)

    @property
    def project_root(self) -> Path:
        return _PROJECT_ROOT


# Singleton instance
settings = Settings()

# ─────────────────────────────────────────────
# Logging setup
# ─────────────────────────────────────────────
def setup_logging():
    """Configure structured logging for the application."""
    log_format = (
        "%(asctime)s │ %(levelname)-8s │ %(name)-25s │ %(message)s"
    )
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Suppress noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)


setup_logging()
