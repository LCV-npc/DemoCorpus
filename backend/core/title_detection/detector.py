"""
core/title_detection/detector.py
TitleDetector — 3-strategy pipeline phát hiện tiêu đề bài báo.

Strategy 1 (Zone-based): Dùng Region(type=TITLE) từ LayoutDocument.
Strategy 2 (Font-based): Fallback — tìm block có font lớn nhất.
Strategy 3 (First-line):  Last resort — dòng đầu không phải noise.

Input: LayoutDocument (từ Giai đoạn 3).
Output: TitleResult.
"""

from __future__ import annotations

import logging
import re

from core.layout_analysis.layout_model import (
    LayoutDocument,
    LayoutPage,
    Region,
    RegionType,
)
from core.text_extraction.models import BlockData
from core.layout_analysis.heuristics import (
    dominant_font_size,
    dominant_font_flags,
    is_bold as font_is_bold,
    is_centered as block_is_centered,
    relative_y as block_relative_y,
    max_font_size_in_blocks,
)
from core.title_detection.models import TitleCandidate, TitleResult
from core.title_detection.scorer import TitleScorer
from core.title_detection.rules import (
    is_plausible_title,
    is_noise,
    MAX_TOTAL_SCORE,
    CONFIDENCE_ZONE_MIN,
    CONFIDENCE_ZONE_MAX,
    CONFIDENCE_FONT_MIN,
    CONFIDENCE_FONT_MAX,
    CONFIDENCE_FIRST_LINE_MIN,
    CONFIDENCE_FIRST_LINE_MAX,
)

logger = logging.getLogger(__name__)


class TitleDetector:
    """
    Phát hiện tiêu đề bài báo khoa học từ LayoutDocument.

    Pipeline 3 strategies theo thứ tự ưu tiên:
    1. Zone-based — sử dụng layout regions đã classify
    2. Font-based — fallback khi không có TITLE zone
    3. First-line — last resort khi không có font info

    Sử dụng TitleScorer để chấm điểm candidates và chọn tốt nhất.
    """

    def __init__(self, scorer: TitleScorer | None = None):
        """
        Khởi tạo detector.

        Args:
            scorer: TitleScorer instance. Nếu None, tạo mới.
        """
        self._scorer = scorer or TitleScorer()
        logger.info("TitleDetector initialized")

    def detect(self, doc: LayoutDocument) -> TitleResult:
        """
        Phát hiện tiêu đề từ LayoutDocument.

        Chạy TẤT CẢ 3 strategies, thu thập candidates,
        chọn candidate có confidence cao nhất.
        Các candidates khác được lưu vào `alternatives`.

        Args:
            doc: LayoutDocument từ Giai đoạn 3.

        Returns:
            TitleResult với title text, confidence, bbox, page.
        """
        if not doc.pages:
            logger.warning(f"Empty document: {doc.file_path}")
            return TitleResult(title=None, strategy="none")

        # ── Run all strategies and collect candidates ──
        candidates: list[TitleResult] = []

        # Strategy 1: Zone-based
        try:
            result = self._strategy_zone(doc)
            if result and result.title:
                candidates.append(result)
                logger.info(
                    f"Strategy 1 (zone): title={result.title[:60]!r} "
                    f"confidence={result.confidence:.2f}"
                )
        except Exception as e:
            logger.warning(f"Strategy 1 (zone) error: {e}")

        # Strategy 2: Font-based fallback
        try:
            result = self._strategy_font(doc)
            if result and result.title:
                candidates.append(result)
                logger.info(
                    f"Strategy 2 (font): title={result.title[:60]!r} "
                    f"confidence={result.confidence:.2f}"
                )
        except Exception as e:
            logger.warning(f"Strategy 2 (font) error: {e}")

        # Strategy 3: First non-noise line
        try:
            result = self._strategy_first_line(doc)
            if result and result.title:
                candidates.append(result)
                logger.info(
                    f"Strategy 3 (first_line): title={result.title[:60]!r} "
                    f"confidence={result.confidence:.2f}"
                )
        except Exception as e:
            logger.warning(f"Strategy 3 (first_line) error: {e}")

        # ── No candidates ──
        if not candidates:
            logger.warning(f"No title found: {doc.file_path}")
            return TitleResult(title=None, strategy="none")

        # ── Pick best candidate by confidence ──
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        best = candidates[0]

        # Store alternatives (other candidates)
        if len(candidates) > 1:
            best.alternatives = [
                {
                    "title": c.title,
                    "confidence": round(c.confidence, 4),
                    "strategy": c.strategy,
                }
                for c in candidates[1:]
            ]
            logger.info(
                f"Title best-of-{len(candidates)}: "
                f"picked {best.strategy} (conf={best.confidence:.2f}), "
                f"alternatives: {[c.strategy for c in candidates[1:]]}"
            )

        return best

    # ── Strategy 1: Zone-based ──

    def _strategy_zone(self, doc: LayoutDocument) -> TitleResult | None:
        """
        Tìm title từ TITLE regions trên trang 0.

        Lấy tất cả Region(type=TITLE) → tạo candidates → score → chọn best.

        Args:
            doc: LayoutDocument.

        Returns:
            TitleResult hoặc None nếu không có TITLE regions.
        """
        first_page = doc.pages[0]
        title_regions = first_page.get_regions(RegionType.TITLE)

        if not title_regions:
            logger.debug("Strategy 1: No TITLE regions found")
            return None

        # Lấy context (author, abstract positions)
        author_y = self._find_region_y(first_page, RegionType.AUTHOR)
        abstract_y = self._find_region_y(first_page, RegionType.ABSTRACT)

        # Nếu có nhiều TITLE regions liên tiếp → merge
        merged_text = self._merge_region_texts(title_regions)
        merged_text = self._clean(merged_text)

        if not is_plausible_title(merged_text):
            logger.debug(
                f"Strategy 1: Merged title not plausible: {merged_text[:50]!r}"
            )
            return None

        # Tính bbox bao trùm tất cả TITLE regions
        merged_bbox = self._merge_bboxes(title_regions)

        # Tìm font info từ blocks trong regions
        all_blocks = []
        for region in title_regions:
            all_blocks.extend(region.blocks)

        font_size = max_font_size_in_blocks(all_blocks) if all_blocks else 0.0
        font_flags_val = self._dominant_font_flags_from_blocks(all_blocks)
        font_name = self._dominant_font_name_from_blocks(all_blocks)

        # Tính max font trên toàn trang 0
        page_all_blocks = []
        for region in first_page.regions:
            page_all_blocks.extend(region.blocks)
        page_max_font = max_font_size_in_blocks(page_all_blocks)

        # Tạo candidate
        candidate = TitleCandidate(
            text=merged_text,
            bbox=merged_bbox,
            page_number=0,
            font_size=font_size,
            font_flags=font_flags_val,
            font_name=font_name,
            is_bold=font_is_bold(font_flags_val),
            is_centered=self._check_centered_regions(title_regions, first_page.width),
            relative_y=merged_bbox[1] / first_page.height if first_page.height > 0 else 0.0,
            page_width=first_page.width,
            page_height=first_page.height,
            line_count=self._count_lines_in_regions(title_regions),
            max_font_size=page_max_font,
            author_region_y=author_y,
            abstract_region_y=abstract_y,
        )

        raw_score = self._scorer.score(candidate)

        # Confidence mapping cho zone strategy
        confidence = self._map_confidence(
            raw_score, CONFIDENCE_ZONE_MIN, CONFIDENCE_ZONE_MAX
        )

        return TitleResult(
            title=merged_text,
            confidence=confidence,
            bbox=list(merged_bbox),
            page=0,
            strategy="zone_based",
            raw_score=raw_score,
        )

    # ── Strategy 2: Font-based ──

    def _strategy_font(self, doc: LayoutDocument) -> TitleResult | None:
        """
        Tìm title dựa trên font size lớn nhất trong top 35% trang 0.

        Lấy blocks có font ≥ 95% max font → filter noise → score → chọn best.

        Args:
            doc: LayoutDocument.

        Returns:
            TitleResult hoặc None.
        """
        first_page = doc.pages[0]

        # Collect tất cả blocks từ regions trên trang 0
        all_blocks: list[BlockData] = []
        for region in first_page.regions:
            all_blocks.extend(region.blocks)

        if not all_blocks:
            logger.debug("Strategy 2: No blocks on first page")
            return None

        page_max_font = max_font_size_in_blocks(all_blocks)
        if page_max_font <= 0:
            logger.debug("Strategy 2: max_font_size = 0")
            return None

        # Filter: blocks có font ≥ 95% max, trong top 35% trang
        font_threshold = page_max_font * 0.95
        title_zone_y = first_page.height * 0.35

        big_font_blocks = [
            b for b in all_blocks
            if dominant_font_size(b) >= font_threshold
            and b.bbox[1] < title_zone_y
            and not is_noise(b.text.strip())
        ]

        if not big_font_blocks:
            logger.debug("Strategy 2: No big-font blocks in title zone")
            return None

        # Sort theo y0 (top → bottom) để merge đúng thứ tự
        big_font_blocks.sort(key=lambda b: b.bbox[1])

        # Merge blocks liên tiếp (y-gap nhỏ)
        groups = self._group_nearby_blocks(big_font_blocks, max_y_gap=30.0)

        # Score từng group, chọn best
        author_y = self._find_region_y(first_page, RegionType.AUTHOR)
        abstract_y = self._find_region_y(first_page, RegionType.ABSTRACT)

        best_result: TitleResult | None = None
        best_score = -1.0

        for group in groups:
            merged_text = self._merge_block_texts(group)
            merged_text = self._clean(merged_text)

            if not is_plausible_title(merged_text):
                continue

            merged_bbox = self._merge_block_bboxes(group)
            font_size = max_font_size_in_blocks(group)
            font_flags_val = self._dominant_font_flags_from_blocks(group)
            font_name = self._dominant_font_name_from_blocks(group)

            candidate = TitleCandidate(
                text=merged_text,
                bbox=merged_bbox,
                page_number=0,
                font_size=font_size,
                font_flags=font_flags_val,
                font_name=font_name,
                is_bold=font_is_bold(font_flags_val),
                is_centered=self._check_centered_blocks(group, first_page.width),
                relative_y=merged_bbox[1] / first_page.height if first_page.height > 0 else 0.0,
                page_width=first_page.width,
                page_height=first_page.height,
                line_count=self._count_lines_in_blocks(group),
                max_font_size=page_max_font,
                author_region_y=author_y,
                abstract_region_y=abstract_y,
            )

            raw_score = self._scorer.score(candidate)
            if raw_score > best_score:
                best_score = raw_score
                best_result = TitleResult(
                    title=merged_text,
                    confidence=self._map_confidence(
                        raw_score, CONFIDENCE_FONT_MIN, CONFIDENCE_FONT_MAX
                    ),
                    bbox=list(merged_bbox),
                    page=0,
                    strategy="font_based",
                    raw_score=raw_score,
                )

        return best_result

    # ── Strategy 3: First non-noise line ──

    def _strategy_first_line(self, doc: LayoutDocument) -> TitleResult | None:
        """
        Last resort: lấy block đầu tiên không phải noise trên trang 0.

        Args:
            doc: LayoutDocument.

        Returns:
            TitleResult hoặc None.
        """
        first_page = doc.pages[0]

        # Collect blocks theo reading order
        all_blocks: list[BlockData] = []
        for region in first_page.regions:
            all_blocks.extend(region.blocks)

        if not all_blocks:
            return None

        # Sort theo y0
        sorted_blocks = sorted(all_blocks, key=lambda b: b.bbox[1])

        for block in sorted_blocks:
            text = block.text.strip()

            if not text:
                continue

            if is_noise(text):
                continue

            cleaned = self._clean(text)
            if not is_plausible_title(cleaned):
                continue

            # Tìm thấy candidate hợp lệ
            page_all_blocks = []
            for region in first_page.regions:
                page_all_blocks.extend(region.blocks)
            page_max_font = max_font_size_in_blocks(page_all_blocks)

            font_size = dominant_font_size(block)
            font_flags_val = dominant_font_flags(block)

            candidate = TitleCandidate(
                text=cleaned,
                bbox=block.bbox,
                page_number=0,
                font_size=font_size,
                font_flags=font_flags_val,
                font_name=self._get_block_font_name(block),
                is_bold=font_is_bold(font_flags_val),
                is_centered=block_is_centered(block, first_page.width),
                relative_y=block_relative_y(block, first_page.height),
                page_width=first_page.width,
                page_height=first_page.height,
                line_count=len(block.lines) if block.lines else 1,
                max_font_size=page_max_font,
                author_region_y=None,
                abstract_region_y=None,
            )

            raw_score = self._scorer.score(candidate)
            confidence = self._map_confidence(
                raw_score, CONFIDENCE_FIRST_LINE_MIN, CONFIDENCE_FIRST_LINE_MAX
            )

            return TitleResult(
                title=cleaned,
                confidence=confidence,
                bbox=list(block.bbox),
                page=0,
                strategy="first_line",
                raw_score=raw_score,
            )

        return None

    # ── Helper Methods ──

    @staticmethod
    def _merge_region_texts(regions: list[Region]) -> str:
        """Gộp text từ nhiều regions, join bằng space."""
        parts = []
        for region in regions:
            text = region.text.strip()
            if text:
                parts.append(text)
        return " ".join(parts)

    @staticmethod
    def _merge_block_texts(blocks: list[BlockData]) -> str:
        """Gộp text từ nhiều blocks, join bằng space."""
        parts = []
        for block in blocks:
            text = block.text.strip()
            if text:
                parts.append(text)
        return " ".join(parts)

    @staticmethod
    def _clean(text: str) -> str:
        """
        Làm sạch title text.

        - Collapse whitespace
        - Strip đầu/cuối
        - Loại bỏ newlines thừa
        """
        # Replace newlines với space
        text = text.replace("\n", " ")
        # Collapse multiple spaces
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _merge_bboxes(regions: list[Region]) -> tuple[float, float, float, float]:
        """Tính bounding box bao trùm tất cả regions."""
        if not regions:
            return (0.0, 0.0, 0.0, 0.0)
        bboxes = [r.bbox for r in regions]
        x0 = min(b[0] for b in bboxes)
        y0 = min(b[1] for b in bboxes)
        x1 = max(b[2] for b in bboxes)
        y1 = max(b[3] for b in bboxes)
        return (x0, y0, x1, y1)

    @staticmethod
    def _merge_block_bboxes(blocks: list[BlockData]) -> tuple[float, float, float, float]:
        """Tính bounding box bao trùm tất cả blocks."""
        if not blocks:
            return (0.0, 0.0, 0.0, 0.0)
        x0 = min(b.bbox[0] for b in blocks)
        y0 = min(b.bbox[1] for b in blocks)
        x1 = max(b.bbox[2] for b in blocks)
        y1 = max(b.bbox[3] for b in blocks)
        return (x0, y0, x1, y1)

    @staticmethod
    def _find_region_y(page: LayoutPage, region_type: RegionType) -> float | None:
        """Tìm y0 của region đầu tiên thuộc type trên trang."""
        regions = page.get_regions(region_type)
        if regions:
            return regions[0].bbox[1]
        return None

    @staticmethod
    def _check_centered_regions(regions: list[Region], page_width: float) -> bool:
        """Kiểm tra tất cả TITLE regions có căn giữa không."""
        if not regions:
            return False
        for region in regions:
            for block in region.blocks:
                if block_is_centered(block, page_width):
                    return True
        return False

    @staticmethod
    def _check_centered_blocks(blocks: list[BlockData], page_width: float) -> bool:
        """Kiểm tra ít nhất 1 block có căn giữa."""
        return any(block_is_centered(b, page_width) for b in blocks)

    @staticmethod
    def _count_lines_in_regions(regions: list[Region]) -> int:
        """Đếm tổng số lines trong tất cả TITLE regions."""
        total = 0
        for region in regions:
            for block in region.blocks:
                total += len(block.lines) if block.lines else 1
        return max(total, 1)

    @staticmethod
    def _count_lines_in_blocks(blocks: list[BlockData]) -> int:
        """Đếm tổng số lines trong blocks."""
        total = 0
        for block in blocks:
            total += len(block.lines) if block.lines else 1
        return max(total, 1)

    @staticmethod
    def _dominant_font_flags_from_blocks(blocks: list[BlockData]) -> int:
        """Tìm font flags chiếm ưu thế trong danh sách blocks."""
        if not blocks:
            return 0
        flags_count: dict[int, int] = {}
        for block in blocks:
            for line in block.lines:
                for span in line.spans:
                    char_count = len(span.text)
                    if char_count > 0:
                        flags_count[span.font_flags] = (
                            flags_count.get(span.font_flags, 0) + char_count
                        )
        if not flags_count:
            return 0
        return max(flags_count, key=flags_count.get)

    @staticmethod
    def _dominant_font_name_from_blocks(blocks: list[BlockData]) -> str:
        """Tìm font name chiếm ưu thế trong danh sách blocks."""
        if not blocks:
            return ""
        name_count: dict[str, int] = {}
        for block in blocks:
            for line in block.lines:
                for span in line.spans:
                    char_count = len(span.text)
                    if char_count > 0:
                        name_count[span.font_name] = (
                            name_count.get(span.font_name, 0) + char_count
                        )
        if not name_count:
            return ""
        return max(name_count, key=name_count.get)

    @staticmethod
    def _get_block_font_name(block: BlockData) -> str:
        """Lấy font name chiếm ưu thế trong block."""
        name_count: dict[str, int] = {}
        for line in block.lines:
            for span in line.spans:
                char_count = len(span.text)
                if char_count > 0:
                    name_count[span.font_name] = (
                        name_count.get(span.font_name, 0) + char_count
                    )
        if not name_count:
            return ""
        return max(name_count, key=name_count.get)

    @staticmethod
    def _group_nearby_blocks(
        blocks: list[BlockData], max_y_gap: float = 30.0
    ) -> list[list[BlockData]]:
        """
        Gom blocks có y-gap nhỏ thành nhóm (merge multi-line title).

        Args:
            blocks: Blocks đã sort theo y0.
            max_y_gap: Khoảng y tối đa giữa 2 blocks liên tiếp
                       để coi là cùng nhóm.

        Returns:
            List các nhóm blocks.
        """
        if not blocks:
            return []

        groups: list[list[BlockData]] = [[blocks[0]]]

        for i in range(1, len(blocks)):
            prev_y1 = blocks[i - 1].bbox[3]  # bottom of previous
            curr_y0 = blocks[i].bbox[1]        # top of current

            if (curr_y0 - prev_y1) <= max_y_gap:
                groups[-1].append(blocks[i])
            else:
                groups.append([blocks[i]])

        return groups

    @staticmethod
    def _map_confidence(
        raw_score: float, conf_min: float, conf_max: float
    ) -> float:
        """
        Map raw score → confidence range [conf_min, conf_max].

        Linear interpolation dựa trên tỉ lệ score / MAX_TOTAL_SCORE.

        Args:
            raw_score: Tổng điểm từ scorer.
            conf_min: Confidence tối thiểu cho strategy.
            conf_max: Confidence tối đa cho strategy.

        Returns:
            Confidence trong [conf_min, conf_max].
        """
        if MAX_TOTAL_SCORE <= 0:
            return conf_min

        ratio = min(raw_score / MAX_TOTAL_SCORE, 1.0)
        return conf_min + ratio * (conf_max - conf_min)
