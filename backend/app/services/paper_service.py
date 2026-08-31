"""
app/services/paper_service.py
Service layer — business logic delegation cho Paper API.

Wraps PersistenceService, PaperRepository, FileStorage.
Router chỉ gọi service, không chứa business logic lớn.
"""

import logging
import uuid
from pathlib import Path
from datetime import datetime, timezone

from config.constants import PDF_MAGIC_BYTES, MAX_FILE_SIZE_BYTES
from config.settings import settings
from infrastructure.storage.file_storage import FileStorage
from infrastructure.database.persistence_service import (
    PersistenceService,
    DuplicatePaperError,
    PersistenceError,
)
from infrastructure.database.repositories.paper_repository import PaperRepository
from infrastructure.database.mongo_client import is_connected
from core.pipeline.extractor_pipeline import PipelineError

logger = logging.getLogger(__name__)


class UploadValidationError(Exception):
    """Lỗi validation upload file."""

    def __init__(self, message: str, status_code: int = 400):
        self.status_code = status_code
        super().__init__(message)


class PaperService:
    """
    Service layer cho tất cả operations liên quan đến Paper.

    Nguyên tắc:
    - REUSE PersistenceService.process_and_save() cho upload pipeline
    - REUSE PaperRepository cho CRUD
    - Không duplicate pipeline/domain logic
    - Không load model mỗi request (model được cache trong FullPipeline)
    """

    def __init__(
        self,
        storage: FileStorage | None = None,
        persistence: PersistenceService | None = None,
        repo: PaperRepository | None = None,
    ):
        self._storage = storage or FileStorage()
        self._repo = repo or PaperRepository()
        self._persistence = persistence or PersistenceService(repo=self._repo)
        logger.info("PaperService initialized")

    # ── Upload + Full Pipeline ──

    def process_upload(self, file_bytes: bytes, filename: str) -> dict:
        """
        Upload PDF và chạy full pipeline M1–M9 → MongoDB.

        Flow:
        1. Validate file (extension, content type, magic bytes, size)
        2. Save to disk via FileStorage
        3. PersistenceService.process_and_save() → M1–M9 + MongoDB
        4. Return result dict

        Args:
            file_bytes: Raw bytes của file PDF.
            filename: Tên file gốc.

        Returns:
            Dict chứa paper_id, title, authors, abstract, confidence, etc.

        Raises:
            UploadValidationError: File không hợp lệ.
            DuplicatePaperError: PDF đã tồn tại (trùng hash).
            PersistenceError: Lỗi MongoDB.
            PipelineError: Pipeline precheck fail.
        """
        # Step 1: Validate
        self._validate_upload(file_bytes, filename)

        # Step 2: Save to disk
        # Use the database paper_id as the storage key too. This keeps
        # FileStorage.get_path(paper_id) valid after persistence.
        paper_id = str(uuid.uuid4())
        file_path = self._storage.save(file_bytes, paper_id)

        try:
            # Step 3: Run full pipeline + save to MongoDB
            # PersistenceService.process_and_save() handles:
            #   - M1 precheck + SHA-256
            #   - Duplicate check
            #   - M2–M9 (text extraction → LLM)
            #   - MongoDB insert
            result, saved_paper_id = self._persistence.process_and_save(
                file_path=file_path,
                source="upload",
                enable_llm=True,
                paper_id=paper_id,
            )

            # Step 4: Build response
            response = {
                "paper_id": saved_paper_id,
                "status": "completed" if result.success else "partial",
                "title": result.title,
                "authors": result.authors,
                "abstract": result.abstract,
                "confidence": result.confidence,
                "validation": result.validation,
                "processing": {
                    "stages_completed": result.stages_completed,
                    "elapsed_seconds": round(result.elapsed_seconds, 3),
                    "failed_stage": result.failed_stage,
                    "error_message": result.error_message,
                },
            }

            logger.info(
                f"Upload processed: paper_id={saved_paper_id}, "
                f"title={'✓' if result.title else '✗'}, "
                f"authors={len(result.authors)}"
            )
            return response

        except DuplicatePaperError:
            # Cleanup: xóa file đã save vì bị trùng
            self._storage.delete(file_path)
            raise

        except (PipelineError, PersistenceError):
            # Cleanup trên lỗi nghiêm trọng
            self._storage.delete(file_path)
            raise

        except Exception as e:
            self._storage.delete(file_path)
            logger.error(f"Unexpected upload error: {e}")
            raise

    def _validate_upload(self, file_bytes: bytes, filename: str) -> None:
        """
        Validate upload file trước khi xử lý.

        Checks:
        - Extension .pdf
        - File size ≤ MAX_FILE_SIZE_BYTES
        - Magic bytes = %PDF
        - File không rỗng

        Raises:
            UploadValidationError nếu không hợp lệ.
        """
        # Check filename
        if not filename:
            raise UploadValidationError("Tên file không hợp lệ")

        # Sanitize: chỉ kiểm tra extension, không dùng filename cho path
        safe_name = Path(filename).name  # Chống path traversal
        if not safe_name.lower().endswith(".pdf"):
            raise UploadValidationError("Chỉ chấp nhận file PDF (.pdf)")

        # Check empty
        if not file_bytes or len(file_bytes) == 0:
            raise UploadValidationError("File rỗng")

        # Check size
        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            size_mb = len(file_bytes) / (1024 * 1024)
            max_mb = MAX_FILE_SIZE_BYTES / (1024 * 1024)
            raise UploadValidationError(
                f"File quá lớn ({size_mb:.1f}MB). Giới hạn: {max_mb:.0f}MB",
                status_code=413,
            )

        # Check magic bytes
        if not file_bytes[:4].startswith(PDF_MAGIC_BYTES):
            raise UploadValidationError("File không phải PDF hợp lệ (magic bytes sai)")

    # ── CRUD Operations ──

    @staticmethod
    def _has_stored_pdf(paper: dict) -> bool:
        """Return whether a record points to its allowed local PDF store.

        The library/search endpoints intentionally list only ``scrape``
        records, but an upload response must remain retrievable by its
        ``paper_id``.  Validate both source-specific roots rather than
        accepting an arbitrary database path.
        """
        source = paper.get("source")
        storage_roots = {
            "scrape": Path(settings.SCRAPE_DIR),
            "upload": Path(settings.UPLOAD_DIR),
        }
        storage_root = storage_roots.get(source)
        if storage_root is None:
            return False

        file_path = paper.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            return False

        try:
            candidate = Path(file_path).resolve()
            candidate.relative_to(storage_root.resolve())
        except (OSError, ValueError):
            return False

        return candidate.is_file() and candidate.suffix.lower() == ".pdf"

    def get_paper(self, paper_id: str) -> dict | None:
        """Fetch a paper only when its source PDF still exists on disk."""
        doc = self._repo.get_paper(paper_id)
        if doc and self._has_stored_pdf(doc):
            doc.pop("file_path", None)
            return doc
        return None

    def list_papers(
        self,
        page: int = 1,
        limit: int = 10,
        min_confidence: float = 0.0,
    ) -> dict:
        """
        Danh sách papers phân trang.

        Returns:
            {"items": [...], "page": int, "limit": int, "total": int}
        """
        query: dict = {"source": "scrape"}
        if min_confidence > 0:
            query["confidence.overall"] = {"$gte": min_confidence}

        items = [
            item
            for item in self._repo.papers.find(query, {"_id": 0}).sort(
                "processing.created_at", -1
            )
            if self._has_stored_pdf(item)
        ]

        # Sanitize: loại bỏ file_path khỏi mỗi item
        for item in items:
            item.pop("file_path", None)

        total = len(items)
        start = (page - 1) * limit
        items = items[start:start + limit]

        return {
            "items": items,
            "page": page,
            "limit": limit,
            "total": total,
        }

    def search_papers(self, query: str, limit: int = 20) -> list[dict]:
        """
        Full-text search trên title và abstract.
        Reuse PaperRepository.search_papers().
        """
        if not query or not query.strip():
            return []

        results = [
            item
            for item in self._repo.search_papers(query=query.strip(), limit=limit)
            if self._has_stored_pdf(item)
        ]

        # Sanitize
        for item in results:
            item.pop("file_path", None)

        return results

    def update_review(
        self,
        paper_id: str,
        is_reviewed: bool,
        reviewer_notes: str = "",
    ) -> bool:
        """
        Cập nhật review status cho paper.
        Reuse PaperRepository.update_paper().
        """
        return self._repo.update_paper(
            paper_id=paper_id,
            fields={
                "review.is_reviewed": is_reviewed,
                "review.reviewer_notes": reviewer_notes,
            },
        )

    # ── Health ──

    def get_health(self) -> dict:
        """Health check: application + MongoDB."""
        db_connected = False
        try:
            db_connected = is_connected()
        except Exception:
            pass

        return {
            "status": "ok" if db_connected else "degraded",
            "database": "connected" if db_connected else "disconnected",
            "version": "0.3.0",
        }
