"""
core/abstract_detection/service.py
AbstractDetectionService — orchestrator layer cho abstract detection.
Cung cấp logging, error handling, và integration interface.
"""

from __future__ import annotations

import logging
import time

from core.text_extraction.models import DocumentData
from core.layout_analysis.layout_model import LayoutDocument
from core.abstract_detection.detector import AbstractDetector
from core.abstract_detection.models import AbstractResult
from core.abstract_detection.exceptions import AbstractDetectionError

logger = logging.getLogger(__name__)


class AbstractDetectionService:
    """
    Service layer cho abstract detection — tích hợp logging, error handling.

    Thin wrapper quanh AbstractDetector, cung cấp:
    - Structured logging cho từng bước
    - Error handling thống nhất
    - Timing metrics
    - Dependency injection cho AbstractDetector
    """

    def __init__(self, detector: AbstractDetector | None = None):
        """
        Khởi tạo service.

        Args:
            detector: AbstractDetector instance. Nếu None, tạo mới.
        """
        self._detector = detector or AbstractDetector()
        logger.info("AbstractDetectionService initialized")

    def detect_abstract(
        self,
        doc_data: DocumentData,
        layout_doc: LayoutDocument,
    ) -> AbstractResult:
        """
        Phát hiện abstract từ DocumentData + LayoutDocument.

        Args:
            doc_data: DocumentData từ M2 (text extraction).
            layout_doc: LayoutDocument từ M3 (layout analysis).

        Returns:
            AbstractResult chứa abstract text, confidence, method.

        Raises:
            AbstractDetectionError: Nếu detection gặp lỗi không xác định.
        """
        start_time = time.time()
        file_name = (
            layout_doc.file_path.split("/")[-1].split("\\")[-1]
            or "unknown"
        )

        logger.info(
            f"Starting abstract detection: {file_name} "
            f"({layout_doc.page_count} pages, "
            f"{layout_doc.total_regions} regions)"
        )

        try:
            result = self._detector.detect(doc_data, layout_doc)
            elapsed = time.time() - start_time

            if result.found:
                logger.info(
                    f"Abstract detected: {file_name} | "
                    f"method={result.method}, "
                    f"confidence={result.confidence:.2f}, "
                    f"length={result.length}, "
                    f"pages=[{result.start_page}-{result.end_page}], "
                    f"flags={result.flags}, "
                    f"time={elapsed:.3f}s | "
                    f"preview={result.text[:80]!r}"
                )
            else:
                logger.warning(
                    f"No abstract found: {file_name} | "
                    f"time={elapsed:.3f}s"
                )

            return result

        except AbstractDetectionError:
            logger.error(
                f"Abstract detection failed: {file_name}", exc_info=True
            )
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error detecting abstract in {file_name}: {e}",
                exc_info=True,
            )
            raise AbstractDetectionError(
                f"Unexpected error: {e}", file_path=layout_doc.file_path
            ) from e
