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


def _storage_dir(env_name: str, default: Path) -> str:
    """Resolve relative storage settings from the backend project root."""
    configured = Path(os.getenv(env_name, str(default)))
    if not configured.is_absolute():
        configured = _PROJECT_ROOT / configured
    return str(configured.resolve())


class Settings:
    """Application settings — đọc từ biến môi trường, có default values."""

    def __init__(self):
        # MongoDB
        self.MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.MONGODB_DB: str = os.getenv("MONGODB_DB", "medical_corpus")
        self.MONGODB_TEST_DB: str = os.getenv("MONGODB_TEST_DB", "pdf_extractor_test")

        # Storage directories
        self.UPLOAD_DIR: str = _storage_dir(
            "UPLOAD_DIR",
            _PROJECT_ROOT / "data" / "uploads",
        )
        self.SCRAPE_DIR: str = _storage_dir(
            "SCRAPE_DIR",
            _PROJECT_ROOT / "data" / "scraped_pdfs",
        )
        self.MAX_YEAR_RANGE: int = int(os.getenv("MAX_YEAR_RANGE", "20"))
        self.UNKNOWN_YEAR_POLICY: str = os.getenv("UNKNOWN_YEAR_POLICY", "skip").lower()
        if self.UNKNOWN_YEAR_POLICY not in {"skip", "store"}:
            raise ValueError("UNKNOWN_YEAR_POLICY must be 'skip' or 'store'")
        self.CRAWL_DISCOVERY_WORKERS: int = min(
            6, max(1, int(os.getenv("CRAWL_DISCOVERY_WORKERS", "3")))
        )

        # File limits
        self.MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
        self.MAX_FILE_SIZE_BYTES: int = self.MAX_FILE_SIZE_MB * 1024 * 1024

        # Logging
        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

        # Runtime security. Production must explicitly opt in to the API key
        # guard; local development remains simple to bootstrap.
        self.ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").lower()
        self.API_KEY: str = os.getenv("API_KEY", "")
        self.CORS_ORIGINS: list[str] = [
            origin.strip()
            for origin in os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if origin.strip()
        ]

        # NER Model (Milestone 5+)
        self.NER_MODEL_PATH: str = os.getenv("NER_MODEL_PATH", "")

        # LLM (Milestone 9)
        self.LLM_MODEL_PATH: str = os.getenv("LLM_MODEL_PATH", "")
        # Gemini uses Google's OpenAI-compatible endpoint. It is preferred for
        # M9 when configured, while the generic OpenAI-compatible variables
        # remain available for other providers.
        self.GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
        self.GEMINI_API_URL: str = os.getenv(
            "GEMINI_API_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai",
        )
        self.GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.LLM_VALIDATE_ALL_FIELDS: bool = os.getenv(
            "LLM_VALIDATE_ALL_FIELDS", "true"
        ).strip().lower() in {"1", "true", "yes", "on"}
        self.OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
        self.OPENAI_API_URL: str = os.getenv("OPENAI_API_URL", "")
        self.OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")

        # Ensure directories exist
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)
        os.makedirs(self.SCRAPE_DIR, exist_ok=True)

    @property
    def project_root(self) -> Path:
        return _PROJECT_ROOT


# Singleton instance
settings = Settings()

if settings.ENVIRONMENT == "production" and not settings.API_KEY:
    raise RuntimeError("API_KEY must be configured when ENVIRONMENT=production")

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
