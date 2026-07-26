"""
core/layout_analysis/layout_analyzer.py
LayoutAnalyzer — orchestrator cho toàn bộ layout analysis pipeline.

Pipeline cho mỗi trang:
1. Column Detection
2. Reading Order Reconstruction
3. Region Detection
4. Build LayoutPage
"""

from __future__ import annotations

import logging
import time

from core.text_extraction.models import DocumentData, PageData
from core.layout_analysis.layout_model import (
    LayoutDocument,
    LayoutPage,
    Region,
    ColumnInfo,
)
from core.layout_analysis.column_detector import ColumnDetector
from core.layout_analysis.reading_order import ReadingOrderReconstructor
from core.layout_analysis.region_detector import RegionDetector

logger = logging.getLogger(__name__)


class LayoutAnalyzer:
    """
    Orchestrator cho layout analysis.

    Nhận DocumentData từ Giai đoạn 2, trả về LayoutDocument
    với regions đã phân loại, reading order, và column info.
    """

    def __init__(
        self,
        column_detector: ColumnDetector | None = None,
        reading_order: ReadingOrderReconstructor | None = None,
        region_detector: RegionDetector | None = None,
    ):
        self._column_detector = column_detector or ColumnDetector()
        self._reading_order = reading_order or ReadingOrderReconstructor()
        self._region_detector = region_detector or RegionDetector()
        logger.info("LayoutAnalyzer initialized")

    def analyze(self, doc: DocumentData) -> LayoutDocument:
        """
        Phân tích bố cục toàn bộ document.

        Args:
            doc: DocumentData từ Giai đoạn 2 (text extraction).

        Returns:
            LayoutDocument với tất cả pages đã annotate.
        """
        start_time = time.time()

        logger.info(
            f"Starting layout analysis: {doc.file_path} "
            f"({doc.page_count} pages)"
        )

        pages: list[LayoutPage] = []
        total_regions = 0

        for page_data in doc.pages:
            layout_page = self._analyze_page(page_data)
            pages.append(layout_page)
            total_regions += len(layout_page.regions)

        elapsed = time.time() - start_time

        result = LayoutDocument(
            file_path=doc.file_path,
            page_count=doc.page_count,
            pages=pages,
            total_regions=total_regions,
            analysis_time_seconds=round(elapsed, 3),
        )

        # Log summary
        self._log_summary(result)

        return result

    def _analyze_page(self, page: PageData) -> LayoutPage:
        """
        Phân tích bố cục một trang.

        Pipeline:
        1. Column detection
        2. Reading order reconstruction
        3. Region detection
        """
        # Step 1: Detect columns
        column_info = self._column_detector.detect(page.blocks, page.width)

        # Step 2: Reconstruct reading order
        ordered_blocks = self._reading_order.reconstruct(
            page.blocks, column_info, page.width
        )

        # Step 3: Detect regions
        regions = self._region_detector.detect(
            page, column_info, ordered_blocks
        )

        return LayoutPage(
            page_number=page.page_number,
            width=page.width,
            height=page.height,
            regions=regions,
            column_info=column_info,
        )

    @staticmethod
    def _log_summary(result: LayoutDocument) -> None:
        """Log thống kê kết quả layout analysis."""
        for page in result.pages:
            region_counts: dict[str, int] = {}
            for region in page.regions:
                rtype = region.region_type.value
                region_counts[rtype] = region_counts.get(rtype, 0) + 1

            logger.info(
                f"Page {page.page_number}: "
                f"layout={page.layout_type}, "
                f"columns={page.column_info.column_count}, "
                f"regions={len(page.regions)} "
                f"({region_counts})"
            )

        logger.info(
            f"Layout analysis complete: "
            f"{result.page_count} pages, "
            f"{result.total_regions} regions, "
            f"time={result.analysis_time_seconds:.3f}s"
        )
