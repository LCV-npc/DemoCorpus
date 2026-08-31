"""
core/text_extraction/service.py
TextExtractionService — orchestrator layer cho text extraction.
Cung cấp logging, error handling, batch processing.
"""

from __future__ import annotations

import logging
from pathlib import Path

from core.text_extraction.extractor import PDFTextExtractor
from core.text_extraction.models import DocumentData
from core.text_extraction.exceptions import PDFExtractionError

logger = logging.getLogger(__name__)


class TextExtractionService:
    """
    Service layer cho text extraction — tích hợp logging, error handling.

    Hỗ trợ:
    - Single document extraction
    - Batch processing (nhiều files)
    - Dependency injection cho PDFTextExtractor
    """

    def __init__(self, extractor: PDFTextExtractor | None = None):
        """
        Khởi tạo service.

        Args:
            extractor: PDFTextExtractor instance. Nếu None, tạo mới.
        """
        self._extractor = extractor or PDFTextExtractor()
        logger.info("TextExtractionService initialized")

    def extract_document(self, file_path: str) -> DocumentData:
        """
        Trích xuất text từ một file PDF với structured logging.

        Args:
            file_path: Đường dẫn đến file PDF.

        Returns:
            DocumentData chứa toàn bộ kết quả extraction.

        Raises:
            PDFExtractionError: Nếu extraction thất bại.
        """
        file_name = Path(file_path).name
        logger.info(f"Starting extraction: {file_name}")

        try:
            result = self._extractor.extract(file_path)

            logger.info(
                f"Extraction complete: {file_name} | "
                f"pages={result.page_count}, "
                f"blocks={result.total_blocks}, "
                f"spans={result.total_spans}, "
                f"born_digital={result.is_born_digital}, "
                f"time={result.extraction_time_seconds:.3f}s"
            )

            return result

        except PDFExtractionError:
            logger.error(f"Extraction failed: {file_name}", exc_info=True)
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error extracting {file_name}: {e}",
                exc_info=True,
            )
            raise PDFExtractionError(
                f"Unexpected error: {e}", file_path=file_path
            ) from e

    def extract_batch(self, file_paths: list[str]) -> list[DocumentData | None]:
        """
        Batch extraction cho nhiều file PDF.

        Mỗi file được xử lý độc lập — lỗi ở file này không ảnh hưởng
        đến file khác. File lỗi trả về None tại vị trí tương ứng.

        Args:
            file_paths: Danh sách đường dẫn file PDF.

        Returns:
            List kết quả. DocumentData nếu thành công, None nếu lỗi.
        """
        total = len(file_paths)
        logger.info(f"Starting batch extraction: {total} files")

        results: list[DocumentData | None] = []
        success_count = 0
        error_count = 0

        for i, file_path in enumerate(file_paths, start=1):
            file_name = Path(file_path).name
            logger.info(f"Batch [{i}/{total}]: {file_name}")

            try:
                result = self.extract_document(file_path)
                results.append(result)
                success_count += 1
            except Exception as e:
                logger.error(f"Batch [{i}/{total}] failed: {file_name} — {e}")
                results.append(None)
                error_count += 1

        logger.info(
            f"Batch extraction complete: "
            f"{success_count} succeeded, {error_count} failed, "
            f"{total} total"
        )

        return results
