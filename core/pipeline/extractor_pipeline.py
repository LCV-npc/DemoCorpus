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

    Milestone 1: chỉ có _step_precheck.
    Các bước khác sẽ thêm ở milestone sau.
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
            PipelineError: Nếu bất kỳ bước nào thất bại.
        """
        metadata = ExtractedMetadata(source=source, file_path=file_path)

        # Step 1: Pre-check
        self._step_precheck(file_path, metadata)

        # Step 2-N: Sẽ thêm ở milestone sau
        # self._step_extract_text(file_path, metadata)
        # self._step_analyze_layout(metadata)
        # self._step_detect_title(metadata)
        # self._step_detect_authors(metadata)
        # self._step_detect_abstract(metadata)
        # self._step_clean_data(metadata)
        # self._step_validate(metadata)

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
