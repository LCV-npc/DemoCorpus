"""
core/author_detection/service.py
AuthorDetectionService — orchestrator layer cho author detection.
Cung cấp logging, error handling, và integration interface.
"""

from __future__ import annotations

import logging
import time

from core.layout_analysis.layout_model import LayoutDocument
from core.title_detection.models import TitleResult
from core.author_detection.detector import AuthorDetector
from core.author_detection.models import AuthorResult

logger = logging.getLogger(__name__)


class AuthorDetectionError(Exception):
    """Exception cho author detection errors."""

    def __init__(self, message: str, file_path: str = ""):
        self.file_path = file_path
        super().__init__(message)


class AuthorDetectionService:
    """
    Service layer cho author detection — tích hợp logging, error handling.

    Thin wrapper quanh AuthorDetector, cung cấp:
    - Structured logging
    - Error handling thống nhất
    - Timing metrics
    - Dependency injection
    """

    def __init__(self, detector: AuthorDetector | None = None):
        """
        Khởi tạo service.

        Args:
            detector: AuthorDetector instance. Nếu None, tạo mới.
        """
        self._detector = detector or AuthorDetector()
        logger.info("AuthorDetectionService initialized")

    def detect_authors(
        self,
        doc: LayoutDocument,
        title_result: TitleResult | None = None,
    ) -> AuthorResult:
        """
        Phát hiện tác giả từ LayoutDocument với structured logging.

        Args:
            doc: LayoutDocument từ Giai đoạn 3.
            title_result: TitleResult từ Giai đoạn 4 (optional).

        Returns:
            AuthorResult chứa danh sách tác giả.

        Raises:
            AuthorDetectionError: Nếu detection gặp lỗi không xác định.
        """
        start_time = time.time()
        file_name = doc.file_path.split("/")[-1].split("\\")[-1] or "unknown"

        logger.info(
            f"Starting author detection: {file_name} "
            f"({doc.page_count} pages)"
        )

        try:
            result = self._detector.detect(doc, title_result)
            elapsed = time.time() - start_time

            if result.authors:
                names_preview = ", ".join(result.author_names[:5])
                if result.count > 5:
                    names_preview += f" (+{result.count - 5} more)"

                logger.info(
                    f"Authors detected: {file_name} | "
                    f"strategy={result.strategy}, "
                    f"count={result.count}, "
                    f"confidence={result.confidence:.2f}, "
                    f"time={elapsed:.3f}s | "
                    f"authors=[{names_preview}]"
                )
            else:
                logger.warning(
                    f"No authors found: {file_name} | "
                    f"time={elapsed:.3f}s"
                )

            return result

        except AuthorDetectionError:
            logger.error(
                f"Author detection failed: {file_name}", exc_info=True
            )
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error detecting authors in {file_name}: {e}",
                exc_info=True,
            )
            raise AuthorDetectionError(
                f"Unexpected error: {e}", file_path=doc.file_path
            ) from e
