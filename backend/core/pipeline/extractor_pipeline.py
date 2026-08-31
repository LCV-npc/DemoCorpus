"""
core/pipeline/extractor_pipeline.py
Pipeline pre-check: validate file trước khi xử lý.
Milestone 1 — chỉ implement _step_precheck và _sha256.
"""

import hashlib
import logging
import os
from pathlib import Path

from config.constants import PDF_MAGIC_BYTES, MAX_FILE_SIZE_BYTES
from core.models.metadata import ExtractedMetadata, ProcessingStep

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Exception cho lỗi trong pipeline processing."""

    def __init__(self, message: str, step: str = ""):
        self.step = step
        super().__init__(message)


class ExtractorPipeline:
    """
    Pipeline xử lý PDF — trích xuất metadata từ file PDF.

    Milestone 1: _step_precheck (file validation + SHA-256).
    Milestones 2-9: delegated to FullPipeline (text extraction → LLM enhancement).
    """

    def __init__(self):
        logger.info("ExtractorPipeline initialized")

    def run(self, file_path: str, source: str = "upload") -> ExtractedMetadata:
        """
        Chạy toàn bộ pipeline trên một file PDF.

        Args:
            file_path: Đường dẫn đến file PDF.
            source: Nguồn file ("upload", "scrape", "local").

        Returns:
            ExtractedMetadata đã xử lý.

        Raises:
            PipelineError: Nếu precheck thất bại.
        """
        metadata = ExtractedMetadata(source=source, file_path=file_path)

        # Step 1: Pre-check (M1)
        self._step_precheck(file_path, metadata)

        # Steps 2-9: Full NLP pipeline
        try:
            from core.pipeline.full_pipeline import FullPipeline
            full = FullPipeline(enable_llm=True)
            result = full.process(file_path)

            if result.success:
                metadata.title = result.title
                metadata.authors = result.authors or []
                metadata.abstract = result.abstract
                metadata.steps_completed.extend(result.stages_completed)
                logger.info(
                    f"Full pipeline completed for {file_path}: "
                    f"title={'✓' if result.title else '✗'}, "
                    f"authors={len(result.authors)}, "
                    f"abstract={'✓' if result.abstract else '✗'}"
                )
            else:
                logger.warning(
                    f"Full pipeline partial failure at {result.failed_stage}: "
                    f"{result.error_message}"
                )
                # Still store whatever was extracted
                metadata.title = result.title
                metadata.authors = result.authors or []
                metadata.abstract = result.abstract
                metadata.steps_completed.extend(result.stages_completed)

        except Exception as e:
            logger.error(f"Full pipeline error: {e}")
            # Pipeline continues — precheck passed, NLP failed

        return metadata

    def _step_precheck(self, file_path: str, metadata: ExtractedMetadata) -> None:
        """
        Pre-check file PDF:
        1. File tồn tại?
        2. File size ≤ giới hạn?
        3. Magic bytes = %PDF?
        4. Tính SHA-256 hash.

        Raises:
            PipelineError nếu file không hợp lệ.
        """
        step = ProcessingStep(step_name="precheck")
        step.start()

        try:
            path = Path(file_path)

            # Check 1: File tồn tại
            if not path.exists():
                raise PipelineError(
                    f"File not found: {file_path}",
                    step="precheck"
                )

            # Check 2: File size
            file_size = path.stat().st_size
            if file_size > MAX_FILE_SIZE_BYTES:
                size_mb = file_size / (1024 * 1024)
                max_mb = MAX_FILE_SIZE_BYTES / (1024 * 1024)
                raise PipelineError(
                    f"File too large: {size_mb:.1f}MB (max {max_mb:.0f}MB)",
                    step="precheck"
                )

            # Check 3: PDF magic bytes
            with open(file_path, "rb") as f:
                magic = f.read(4)
            if magic != PDF_MAGIC_BYTES:
                raise PipelineError(
                    f"Not a valid PDF file (magic bytes: {magic!r})",
                    step="precheck"
                )

            # Check 4: SHA-256 hash
            metadata.file_hash_sha256 = self._sha256(file_path)
            metadata.steps_completed.append("precheck")

            step.complete(success=True)
            logger.info(
                f"Pre-check passed: {path.name} "
                f"({file_size / 1024:.1f}KB, hash={metadata.file_hash_sha256[:12]}...)"
            )

        except PipelineError:
            step.complete(success=False, error=str(step))
            raise
        except Exception as e:
            step.complete(success=False, error=str(e))
            raise PipelineError(f"Unexpected error in precheck: {e}", step="precheck")
        finally:
            metadata.processing_steps.append(step)

    @staticmethod
    def _sha256(file_path: str) -> str:
        """Tính SHA-256 hash cho file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
