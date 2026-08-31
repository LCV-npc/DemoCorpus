"""
infrastructure/database/persistence_service.py
Bridge between pipeline output and MongoDB storage.

Milestone 10 — MongoDB Persistence.

This service is the integration layer:
- Pipeline produces PipelineResult / ExtractedMetadata
- PersistenceService serializes and stores via PaperRepository
- Handles duplicates, errors, and logging

Does NOT import or modify any NLP/PDF extraction code.
"""

import logging
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from pymongo.errors import DuplicateKeyError

from core.models.metadata import ExtractedMetadata
from core.abstract_detection.language import looks_vietnamese
from core.pipeline.full_pipeline import PipelineResult
from core.validators.validation_engine import ValidationEngine
from config.constants import OVERALL_FIELD_WEIGHTS
from infrastructure.database.repositories.paper_repository import PaperRepository

logger = logging.getLogger(__name__)

# Bump this when an extraction rule changes so stored papers can be upgraded.
# Bump when deterministic extraction/normalization logic changes so existing
# PDFs can be extracted again from the Library without re-crawling.
METADATA_EXTRACTION_VERSION = 7


class PersistenceError(Exception):
    """Exception cho lỗi persistence (MongoDB insert/update/query)."""

    def __init__(self, message: str, paper_id: str = "", cause: Exception | None = None):
        self.paper_id = paper_id
        self.cause = cause
        super().__init__(message)


class DuplicatePaperError(PersistenceError):
    """Raised khi cố insert paper với SHA-256 hash đã tồn tại."""

    def __init__(self, file_hash: str, existing_paper_id: str = ""):
        self.file_hash = file_hash
        self.existing_paper_id = existing_paper_id
        super().__init__(
            f"Duplicate paper: hash={file_hash[:16]}... "
            f"already exists as paper_id={existing_paper_id}"
        )


class PersistenceService:
    """
    Bridge between pipeline output and MongoDB storage.

    Usage:
        service = PersistenceService()

        # Option 1: Save ExtractedMetadata directly
        paper_id = service.save_extracted_metadata(metadata)

        # Option 2: Save PipelineResult with hash
        paper_id = service.save_pipeline_result(result, file_hash="abc...")

        # Option 3: Run pipeline + save in one call
        result, paper_id = service.process_and_save("path/to/paper.pdf")
    """

    def __init__(self, repo: PaperRepository | None = None):
        """
        Initialize PersistenceService.

        Args:
            repo: PaperRepository instance. If None, creates default.
        """
        self._repo = repo or PaperRepository()
        logger.info("PersistenceService initialized")

    @property
    def repo(self) -> PaperRepository:
        """Access underlying PaperRepository for direct queries."""
        return self._repo

    @staticmethod
    def _apply_source_metadata(
        result: PipelineResult, source_metadata: dict | None
    ) -> tuple[dict, dict]:
        """Resolve metadata using article citation tags before PDF fallbacks.

        Citation tags belong to the article's landing page and are therefore a
        strong source for its title, author list and abstract.  The PDF pipeline
        still runs for all documents; it fills fields missing from the source
        and provides diagnostics.  Re-validating the resolved values prevents
        the old PDF-only score from claiming 100% for a masthead or body text.
        """
        source_metadata = source_metadata or {}
        resolved = {
            "title": result.title,
            "authors": result.authors,
            "abstract": result.abstract,
        }
        provenance = {
            "title": "pdf_pipeline",
            "authors": "pdf_pipeline",
            "abstract": "pdf_pipeline",
        }
        for field in ("title", "authors", "abstract"):
            value = source_metadata.get(field)
            if field == "authors":
                valid = isinstance(value, list) and bool(value)
            else:
                valid = isinstance(value, str) and bool(value.strip())
            if valid:
                if (
                    field == "abstract"
                    and looks_vietnamese(resolved["abstract"])
                    and not looks_vietnamese(value)
                ):
                    continue
                resolved[field] = value
                provenance[field] = "article_citation_metadata"

        result.title = resolved["title"]
        result.authors = resolved["authors"]
        result.abstract = resolved["abstract"]

        report = ValidationEngine().validate(
            title=result.title,
            authors=result.authors,
            abstract=result.abstract,
        )
        result.validation = report.to_dict()
        scores = {
            "title": report.title.score,
            "authors": report.authors.score,
            "abstract": report.abstract.score,
        }
        # Citation metadata is strong evidence but not an absolute guarantee;
        # reserve 100% for a future human-reviewed state, not automated output.
        for field, source in provenance.items():
            if source == "article_citation_metadata":
                scores[field] = min(scores[field], 0.95)
        result.confidence = {
            **scores,
            "overall": sum(
                scores[field] * OVERALL_FIELD_WEIGHTS[field]
                for field in ("title", "authors", "abstract")
            ),
        }
        return source_metadata, provenance

    def save_extracted_metadata(self, metadata: ExtractedMetadata) -> str:
        """
        Lưu ExtractedMetadata vào MongoDB.

        Args:
            metadata: ExtractedMetadata domain object (output of ExtractorPipeline).

        Returns:
            paper_id đã lưu.

        Raises:
            DuplicatePaperError: nếu SHA-256 hash đã tồn tại.
            PersistenceError: cho các lỗi MongoDB khác.
        """
        try:
            doc = metadata.to_dict()
            paper_id = self._repo.insert_paper(doc)
            logger.info(f"Saved ExtractedMetadata: paper_id={paper_id}")
            return paper_id

        except DuplicateKeyError:
            # Tìm paper đã tồn tại
            existing = self._repo.get_by_hash(metadata.file_hash_sha256)
            existing_id = existing.get("paper_id", "") if existing else ""
            raise DuplicatePaperError(
                file_hash=metadata.file_hash_sha256,
                existing_paper_id=existing_id,
            )

        except Exception as e:
            if isinstance(e, (DuplicatePaperError, PersistenceError)):
                raise
            logger.error(f"Failed to save metadata: {e}")
            raise PersistenceError(
                f"Failed to save paper: {e}",
                paper_id=metadata.paper_id,
                cause=e,
            )

    def save_pipeline_result(
        self,
        result: PipelineResult,
        file_hash: str,
        source: str = "local",
        paper_id: str = "",
    ) -> str:
        """
        Lưu PipelineResult vào MongoDB.

        Converts PipelineResult (from FullPipeline) to MongoDB document
        format and inserts via PaperRepository.

        Args:
            result: PipelineResult from FullPipeline.process()
            file_hash: SHA-256 hash của file PDF
            source: Nguồn ("upload", "scrape", "local")
            paper_id: ID tùy chọn. Nếu rỗng, tự sinh UUID.

        Returns:
            paper_id đã lưu.

        Raises:
            DuplicatePaperError: nếu SHA-256 hash đã tồn tại.
            PersistenceError: cho các lỗi MongoDB khác.
        """
        if not paper_id:
            paper_id = str(uuid.uuid4())

        now = datetime.now(timezone.utc).isoformat()

        file = Path(result.file_path)
        doc = {
            "paper_id": paper_id,
            "file_hash_sha256": file_hash,
            "filename": file.name,
            "file_size_bytes": file.stat().st_size if file.exists() else 0,
            "source": source,
            "source_url": result.source_url,
            "pdf_url": result.pdf_url,
            "file_path": result.file_path,
            "extracted": {
                "title": result.title,
                "authors": result.authors,
                "abstract": result.abstract,
            },
            "validation": result.validation,
            "confidence": result.confidence,
            "processing": {
                "steps_completed": result.stages_completed,
                "processing_steps": [],
                "elapsed_seconds": round(result.elapsed_seconds, 3),
                "metadata_extraction_version": METADATA_EXTRACTION_VERSION,
                "created_at": now,
            },
            "filter_result": None,
            "review": {
                "is_reviewed": False,
                "reviewer_notes": "",
            },
            "updated_at": now,
        }

        try:
            saved_id = self._repo.insert_paper(doc)
            logger.info(
                f"Saved PipelineResult: paper_id={saved_id}, "
                f"title={repr(result.title)[:40] if result.title else 'None'}"
            )
            return saved_id

        except DuplicateKeyError:
            existing = self._repo.get_by_hash(file_hash)
            existing_id = existing.get("paper_id", "") if existing else ""
            raise DuplicatePaperError(
                file_hash=file_hash,
                existing_paper_id=existing_id,
            )

        except Exception as e:
            if isinstance(e, (DuplicatePaperError, PersistenceError)):
                raise
            logger.error(f"Failed to save pipeline result: {e}")
            raise PersistenceError(
                f"Failed to save pipeline result: {e}",
                paper_id=paper_id,
                cause=e,
            )

    def process_and_save(
        self,
        file_path: str,
        source: str = "local",
        source_url: str = "",
        enable_llm: bool = True,
        paper_id: str = "",
    ) -> tuple[PipelineResult, str]:
        """
        Chạy full pipeline (M1-M9) rồi lưu kết quả vào MongoDB.

        Convenience method kết hợp pipeline + persistence.

        Args:
            file_path: Đường dẫn đến file PDF.
            source: Nguồn file.
            source_url: URL nguồn.
            enable_llm: Bật/tắt LLM enhancement (M9).

        Returns:
            Tuple of (PipelineResult, paper_id).

        Raises:
            DuplicatePaperError: nếu PDF đã tồn tại (by hash).
            PersistenceError: cho lỗi persistence khác.
        """
        from core.pipeline.extractor_pipeline import ExtractorPipeline

        # Step 1: Run M1 (precheck + SHA-256)
        extractor = ExtractorPipeline()
        metadata = ExtractedMetadata(source=source, file_path=file_path)
        extractor._step_precheck(file_path, metadata)
        file_hash = metadata.file_hash_sha256

        # Step 2: Check duplicate before running heavy pipeline
        existing = self._repo.get_by_hash(file_hash)
        if existing:
            raise DuplicatePaperError(
                file_hash=file_hash,
                existing_paper_id=existing.get("paper_id", ""),
            )

        # Step 3: Run M2-M9
        from core.pipeline.full_pipeline import FullPipeline
        pipeline = FullPipeline(enable_llm=enable_llm)
        result = pipeline.process(
            file_path,
            source_url=source_url,
        )

        # Step 4: Save to MongoDB
        paper_id = self.save_pipeline_result(
            result=result,
            file_hash=file_hash,
            source=source,
            paper_id=paper_id,
        )

        return result, paper_id

    def process_and_update_existing(
        self,
        file_path: str,
        source: str = "scrape",
        source_url: str = "",
        paper_id: str = "",
        enable_llm: bool = False,
        source_metadata: dict | None = None,
    ) -> tuple[PipelineResult, str]:
        """Run the pipeline for a stored PDF and update a matching crawl record.

        Crawl jobs save lightweight records first so the library can list files
        immediately. This method upgrades that record after extraction instead
        of rejecting the PDF's own SHA-256 hash as a duplicate.
        """
        from core.pipeline.extractor_pipeline import ExtractorPipeline
        from core.pipeline.full_pipeline import FullPipeline

        extractor = ExtractorPipeline()
        metadata = ExtractedMetadata(source=source, file_path=file_path)
        extractor._step_precheck(file_path, metadata)
        file_hash = metadata.file_hash_sha256
        existing = self._repo.get_by_hash(file_hash)

        pipeline = FullPipeline(enable_llm=enable_llm)
        result = pipeline.process(file_path, source_url=source_url)
        source_metadata, provenance = self._apply_source_metadata(
            result, source_metadata
        )

        if existing:
            saved_id = existing.get("paper_id", "")
            if not saved_id:
                raise PersistenceError("Existing paper is missing paper_id")
            fields = {
                "file_hash_sha256": file_hash,
                "filename": Path(result.file_path).name,
                "file_size_bytes": Path(result.file_path).stat().st_size,
                "source": source,
                "source_url": existing.get("source_url") or result.source_url,
                "pdf_url": existing.get("pdf_url") or result.pdf_url,
                "file_path": result.file_path,
                "extracted": {
                    "title": result.title,
                    "authors": result.authors,
                    "abstract": result.abstract,
                },
                "validation": result.validation,
                "confidence": result.confidence,
                "metadata_provenance": provenance,
                "processing": {
                    "steps_completed": result.stages_completed,
                    "processing_steps": [],
                    "elapsed_seconds": round(result.elapsed_seconds, 3),
                    "metadata_extraction_version": METADATA_EXTRACTION_VERSION,
                    "created_at": existing.get("processing", {}).get(
                        "created_at", datetime.now(timezone.utc).isoformat()
                    ),
                },
            }
            if source_metadata:
                fields["source_metadata"] = source_metadata
            if not self._repo.update_paper(saved_id, fields):
                raise PersistenceError("Failed to update existing paper", paper_id=saved_id)
            return result, saved_id

        saved_id = self.save_pipeline_result(
            result=result,
            file_hash=file_hash,
            source=source,
            paper_id=paper_id,
        )
        return result, saved_id

    def get_paper(self, paper_id: str) -> Optional[dict]:
        """Lấy paper từ MongoDB theo paper_id."""
        return self._repo.get_paper(paper_id)

    def get_paper_as_metadata(self, paper_id: str) -> Optional[ExtractedMetadata]:
        """
        Lấy paper từ MongoDB và reconstruct thành ExtractedMetadata domain object.

        Returns:
            ExtractedMetadata hoặc None nếu không tìm thấy.
        """
        doc = self._repo.get_paper(paper_id)
        if doc is None:
            return None
        return ExtractedMetadata.from_dict(doc)
