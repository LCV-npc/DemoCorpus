"""
app/dependencies.py
FastAPI Dependency Injection providers.

Singleton instances cho PaperService, PaperRepository, FileStorage.
Không load NER/LLM model mỗi request — model được cache trong FullPipeline
(tạo bởi PersistenceService.process_and_save khi cần).
"""

import logging

from fastapi import Header, HTTPException, status

from app.services.paper_service import PaperService

logger = logging.getLogger(__name__)

# Module-level singleton
_paper_service: PaperService | None = None


def get_paper_service() -> PaperService:
    """
    FastAPI dependency — trả về singleton PaperService.

    Usage trong router:
        @router.get("/results")
        def list_results(service: PaperService = Depends(get_paper_service)):
            ...

    PaperService sẽ tạo PaperRepository, PersistenceService, FileStorage
    một lần duy nhất và reuse cho tất cả requests.
    """
    global _paper_service
    if _paper_service is None:
        try:
            _paper_service = PaperService()
            logger.info("PaperService singleton created")
        except Exception as e:
            logger.error(f"Failed to create PaperService: {e}")
            raise
    return _paper_service


def require_write_access(x_api_key: str | None = Header(default=None)) -> None:
    """Protect state-changing endpoints outside local development."""
    from config.settings import settings

    if settings.ENVIRONMENT == "production" and x_api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid X-API-Key header is required",
        )
