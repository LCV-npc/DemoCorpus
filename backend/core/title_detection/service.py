"""
core/title_detection/service.py
TitleDetectionService — orchestrator layer cho title detection.
Cung cấp logging, error handling, và integration interface.
"""

from __future__ import annotations

import logging
import time

from core.layout_analysis.layout_model import LayoutDocument
from core.title_detection.detector import TitleDetector
from core.title_detection.models import TitleResult
from core.title_detection.exceptions import TitleDetectionError

logger = logging.getLogger(__name__)


class TitleDetectionService:
    """
    Service layer cho title detection — tích hợp logging, error handling.

    Thin wrapper quanh TitleDetector, cung cấp:
    - Structured logging cho từng bước
    - Error handling thống nhất
    - Timing metrics
    - Dependency injection cho TitleDetector
    """

    def __init__(self, detector: TitleDetector | None = None):
        """
        Khởi tạo service.

        Args:
            detector: TitleDetector instance. Nếu None, tạo mới.
        """
        self._detector = detector or TitleDetector()
        logger.info("TitleDetectionService initialized")

    def detect_title(self, doc: LayoutDocument) -> TitleResult:
        """
        Phát hiện tiêu đề từ LayoutDocument với structured logging.

        Args:
            doc: LayoutDocument từ Giai đoạn 3.

        Returns:
            TitleResult chứa title text, confidence, bbox, page.

        Raises:
            TitleDetectionError: Nếu detection gặp lỗi không xác định.
        """
        start_time = time.time()
        file_name = doc.file_path.split("/")[-1].split("\\")[-1] or "unknown"

        logger.info(
            f"Starting title detection: {file_name} "
            f"({doc.page_count} pages, "
            f"{doc.total_regions} regions)"
        )

        try:
            result = self._detector.detect(doc)
            elapsed = time.time() - start_time

            if result.title:
                logger.info(
                    f"Title detected: {file_name} | "
                    f"strategy={result.strategy}, "
                    f"confidence={result.confidence:.2f}, "
                    f"score={result.raw_score:.2f}, "
                    f"time={elapsed:.3f}s | "
                    f"title={result.title[:80]!r}"
                )
            else:
                logger.warning(
                    f"No title found: {file_name} | "
                    f"time={elapsed:.3f}s"
                )

            return result

        except TitleDetectionError:
            logger.error(
                f"Title detection failed: {file_name}", exc_info=True
            )
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error detecting title in {file_name}: {e}",
                exc_info=True,
            )
            raise TitleDetectionError(
                f"Unexpected error: {e}", file_path=doc.file_path
            ) from e
