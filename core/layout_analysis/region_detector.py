"""
core/layout_analysis/region_detector.py
RegionDetector — phân loại blocks thành các vùng bố cục.

Phase 1: Tìm structural markers (abstract_y, keyword_y, reference_y)
Phase 2: Classify từng block theo thứ tự ưu tiên
Phase 3: Gom blocks liên tiếp cùng type thành Region
"""

from __future__ import annotations

import logging

from core.text_extraction.models import BlockData, PageData
from core.layout_analysis.layout_model import Region, RegionType, ColumnInfo
from core.layout_analysis import heuristics as h

logger = logging.getLogger(__name__)

# Confidence scores mặc định cho từng loại detection
_CONFIDENCE = {
    RegionType.HEADER: 0.90,
    RegionType.FOOTER: 0.85,
    RegionType.TITLE: 0.80,
    RegionType.AUTHOR: 0.70,
    RegionType.AFFILIATION: 0.75,
    RegionType.ABSTRACT: 0.85,
    RegionType.KEYWORD: 0.85,
    RegionType.REFERENCE: 0.90,
    RegionType.BODY: 0.65,
    RegionType.UNKNOWN: 0.30,
}


class RegionDetector:
    """Phát hiện và phân loại các vùng bố cục trên trang PDF."""

    def detect(
        self,
        page: PageData,
        column_info: ColumnInfo,
        ordered_blocks: list[BlockData],
    ) -> list[Region]:
        """
        Detect regions cho một trang.

        Args:
            page: PageData gốc.
            column_info: ColumnInfo từ ColumnDetector.
            ordered_blocks: Blocks đã sort theo reading order.

        Returns:
            List các Region đã classify và gom nhóm.
        """
        if page.page_number == 0:
            return self._detect_first_page(
                page, column_info, ordered_blocks
            )
        else:
            return self._detect_subsequent_page(
                page, ordered_blocks
            )

    def _detect_first_page(
        self,
        page: PageData,
        column_info: ColumnInfo,
        ordered_blocks: list[BlockData],
    ) -> list[Region]:
        """
        Classify blocks trên trang 1 — logic phức tạp.

        Thứ tự ưu tiên:
        HEADER → FOOTER → REFERENCE → KEYWORD → ABSTRACT
        → TITLE → AFFILIATION → AUTHOR → BODY
        """
        if not ordered_blocks:
            return []

        pw = page.width
        ph = page.height

        # Tìm max font size cho title detection
        max_font = h.max_font_size_in_blocks(ordered_blocks)

        # Phase 1: Tìm structural markers
        markers = self._find_structural_markers(ordered_blocks, max_font, pw, ph)
        abstract_y = markers.get("abstract_y")
        keyword_y = markers.get("keyword_y")
        reference_y = markers.get("reference_y")
        title_y_start = markers.get("title_y_start")

        # Phase 2: Classify từng block
        labels: list[RegionType] = []
        title_y_end: float | None = None

        for block in ordered_blocks:
            label = self._classify_block(
                block, pw, ph, max_font,
                abstract_y, keyword_y, reference_y,
                title_y_start, title_y_end,
            )
            labels.append(label)

            # Track title end position cho author/affiliation detection
            if label == RegionType.TITLE:
                if title_y_end is None or block.bbox[3] > title_y_end:
                    title_y_end = block.bbox[3]

        # Phase 3: Gom blocks liên tiếp cùng type thành Region
        return self._group_into_regions(
            ordered_blocks, labels, page.page_number
        )

    def _detect_subsequent_page(
        self,
        page: PageData,
        ordered_blocks: list[BlockData],
    ) -> list[Region]:
        """
        Classify blocks trên trang 2+ — logic đơn giản hơn.
        Mặc định BODY, ngoại trừ HEADER, FOOTER, REFERENCE.
        """
        if not ordered_blocks:
            return []

        ph = page.height
        labels: list[RegionType] = []

        # Tìm reference marker trên trang này
        reference_y: float | None = None
        for block in ordered_blocks:
            text = block.text.strip()
            if h.matches_reference_start(text):
                reference_y = block.bbox[1]
                break

        for block in ordered_blocks:
            text = block.text.strip()

            if h.is_in_header_zone(block, ph) and h.matches_header_footer(text):
                labels.append(RegionType.HEADER)
            elif h.is_in_footer_zone(block, ph) and (
                h.matches_header_footer(text) or self._is_page_number(text)
            ):
                labels.append(RegionType.FOOTER)
            elif reference_y is not None and block.bbox[1] >= reference_y:
                labels.append(RegionType.REFERENCE)
            else:
                labels.append(RegionType.BODY)

        return self._group_into_regions(
            ordered_blocks, labels, page.page_number
        )

    def _find_structural_markers(
        self, blocks: list[BlockData], max_font: float, page_width: float, page_height: float
    ) -> dict[str, float | None]:
        """
        Scan blocks để tìm vị trí y0 của abstract, keyword, reference, title markers.
        """
        abstract_y: float | None = None
        keyword_y: float | None = None
        reference_y: float | None = None
        title_y_start: float | None = None

        for block in blocks:
            text = block.text.strip()
            if not text:
                continue

            y0 = block.bbox[1]
            # Title detection
            if title_y_start is None:
                font_size = h.dominant_font_size(block)
                font_flags = h.dominant_font_flags(block)
                bold = h.is_bold(font_flags)
                is_title_font = max_font > 0 and font_size >= max_font * 0.95
                if is_title_font and (bold or h.is_centered(block, page_width)):
                    if h.is_in_title_zone(block, page_height) or is_title_font:
                        title_y_start = y0

            # Chỉ lấy marker đầu tiên
            if abstract_y is None and h.matches_abstract_start(text):
                abstract_y = y0
            if keyword_y is None and h.matches_keyword_start(text):
                keyword_y = y0
            if reference_y is None and h.matches_reference_start(text):
                reference_y = y0

        return {
            "abstract_y": abstract_y,
            "keyword_y": keyword_y,
            "reference_y": reference_y,
            "title_y_start": title_y_start,
        }

    def _classify_block(
        self,
        block: BlockData,
        page_width: float,
        page_height: float,
        max_font: float,
        abstract_y: float | None,
        keyword_y: float | None,
        reference_y: float | None,
        title_y_start: float | None,
        title_y_end: float | None,
    ) -> RegionType:
        """
        Classify một block dựa trên spatial, font, và context.
        """
        text = block.text.strip()
        if not text:
            return RegionType.UNKNOWN

        y0 = block.bbox[1]
        font_size = h.dominant_font_size(block)
        font_flags = h.dominant_font_flags(block)
        bold = h.is_bold(font_flags)

        # 1. HEADER
        if h.is_in_header_zone(block, page_height) and h.matches_header_footer(text):
            return RegionType.HEADER

        # 2. FOOTER
        if h.is_in_footer_zone(block, page_height):
            if h.matches_header_footer(text) or self._is_page_number(text):
                return RegionType.FOOTER
                
        # 3. TITLE — ưu tiên cao hơn Reference nếu có 2 paper trên cùng trang
        is_title_font = max_font > 0 and font_size >= max_font * 0.95
        if is_title_font and (bold or h.is_centered(block, page_width)):
            if h.is_in_title_zone(block, page_height) or is_title_font:
                return RegionType.TITLE

        # 4. REFERENCE section
        if reference_y is not None and y0 >= reference_y:
            # Ngăn không cho reference nuốt title/abstract của bài báo tiếp theo
            if title_y_start is not None and title_y_start > reference_y and y0 >= title_y_start:
                pass # Qua phần reference rồi
            else:
                return RegionType.REFERENCE

        # 5. KEYWORD section
        if keyword_y is not None:
            upper_bound = reference_y if reference_y is not None else float("inf")
            if title_y_start is not None and title_y_start > keyword_y:
                upper_bound = min(upper_bound, title_y_start)
                
            if keyword_y <= y0 < upper_bound:
                return RegionType.KEYWORD

        # 6. ABSTRACT marker or content
        if h.matches_abstract_start(text):
            return RegionType.ABSTRACT

        if abstract_y is not None:
            lower_bound = keyword_y or reference_y or float("inf")
            if title_y_start is not None and title_y_start > abstract_y:
                lower_bound = min(lower_bound, title_y_start)
                
            if abstract_y - 5.0 <= y0 < lower_bound:
                return RegionType.ABSTRACT

        # 7. AFFILIATION
        if h.contains_affiliation(text):
            if title_y_end is not None:
                if abstract_y is not None and abstract_y > title_y_end:
                    if title_y_end <= y0 < abstract_y:
                        return RegionType.AFFILIATION
                else:
                    if y0 >= title_y_end:
                        return RegionType.AFFILIATION

        # 8. AUTHOR — giữa title và abstract/affiliation
        if title_y_end is not None:
            upper_bound_author = abstract_y or float("inf")
            # Author chỉ ở ngay dưới title
            if title_y_end <= y0 < upper_bound_author:
                if font_size < max_font * 0.95:
                    return RegionType.AUTHOR

        # 9. BODY (mặc định)
        return RegionType.BODY

    @staticmethod
    def _is_page_number(text: str) -> bool:
        """Kiểm tra text có phải page number (chỉ chứa số)."""
        return text.strip().isdigit()

    @staticmethod
    def _group_into_regions(
        blocks: list[BlockData],
        labels: list[RegionType],
        page_number: int,
    ) -> list[Region]:
        """
        Gom blocks liên tiếp cùng RegionType thành một Region.

        Args:
            blocks: Danh sách blocks (theo reading order).
            labels: Label tương ứng cho mỗi block.
            page_number: Số trang.

        Returns:
            List các Region đã gom nhóm.
        """
        if not blocks:
            return []

        regions: list[Region] = []
        current_type = labels[0]
        current_blocks: list[BlockData] = [blocks[0]]

        for i in range(1, len(blocks)):
            if labels[i] == current_type:
                current_blocks.append(blocks[i])
            else:
                # Emit region hiện tại
                regions.append(Region(
                    region_type=current_type,
                    blocks=current_blocks,
                    page_number=page_number,
                    reading_order_index=len(regions),
                    confidence=_CONFIDENCE.get(current_type, 0.5),
                ))
                current_type = labels[i]
                current_blocks = [blocks[i]]

        # Emit region cuối cùng
        regions.append(Region(
            region_type=current_type,
            blocks=current_blocks,
            page_number=page_number,
            reading_order_index=len(regions),
            confidence=_CONFIDENCE.get(current_type, 0.5),
        ))

        return regions
