"""
core/abstract_detection/detector.py
AbstractDetector — core detection engine cho abstract extraction.

Pipeline:
1. Keyword Anchoring — tìm abstract bằng regex pattern trên text đã ordered
2. Layout Zone Fallback — dùng RegionType.ABSTRACT từ Milestone 3
3. Clean & Validate — minimal cleaning + validation

Input: DocumentData (M2) + LayoutDocument (M3)
Output: AbstractResult
"""

from __future__ import annotations

import logging
import re

from core.text_extraction.models import DocumentData
from core.layout_analysis.layout_model import LayoutDocument, RegionType
from core.abstract_detection.models import (
    AbstractResult,
    ABSTRACT_MAY_BE_LIST,
    ABSTRACT_TOO_SHORT,
    ABSTRACT_TOO_LONG,
    ABSTRACT_STARTS_WITH_KEYWORD,
)
from config.constants import (
    ABSTRACT_START_PATTERN,
    ABSTRACT_END_PATTERN,
    ABSTRACT_MIN_LENGTH,
    ABSTRACT_MAX_LENGTH,
    NEWLINE_RATIO_THRESHOLD,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Soft hyphen pattern cho cleaning
# ─────────────────────────────────────────────
_SOFT_HYPHEN_PATTERN = re.compile(r"-\s*\n\s*")

# Pattern cho excessive blank lines (3+ consecutive newlines → 2)
_EXCESSIVE_BLANK_LINES = re.compile(r"\n{3,}")

# Số trang tối đa để scan abstract (abstract hiếm khi nằm sau trang 2)
_MAX_PAGES_TO_SCAN = 3


class AbstractDetector:
    """
    Core detector cho abstract extraction.

    Sử dụng 2 chiến lược:
    1. Keyword Anchoring — regex-based, confidence cao
    2. Layout Zone Fallback — dùng M3 regions, nếu keyword fail

    Không sử dụng LLM. Không paraphrase. Chỉ detect + extract + clean.
    """

    def detect(
        self,
        doc_data: DocumentData,
        layout_doc: LayoutDocument,
    ) -> AbstractResult:
        """
        Phát hiện và trích xuất abstract từ document.

        Args:
            doc_data: DocumentData từ M2 (text extraction).
            layout_doc: LayoutDocument từ M3 (layout analysis).

        Returns:
            AbstractResult chứa abstract text, confidence, method.
        """
        if not doc_data.pages:
            logger.warning("Empty document — no pages to scan")
            return AbstractResult(method="none")

        # Strategy 1: Keyword Anchoring
        keyword_result = self._extract_by_keyword(doc_data, layout_doc)
        if keyword_result is not None and keyword_result.found:
            logger.info(
                f"Abstract found by keyword anchoring: "
                f"{keyword_result.length} chars, "
                f"confidence={keyword_result.confidence:.2f}"
            )
            return keyword_result

        # Strategy 2: Layout Zone Fallback
        zone_result = self._extract_by_zone(layout_doc)
        if zone_result is not None and zone_result.found:
            logger.info(
                f"Abstract found by zone fallback: "
                f"{zone_result.length} chars, "
                f"confidence={zone_result.confidence:.2f}"
            )
            return zone_result

        # Both strategies failed
        logger.warning("No abstract found by any strategy")
        return AbstractResult(method="none")

    def _extract_by_keyword(
        self,
        doc_data: DocumentData,
        layout_doc: LayoutDocument,
    ) -> AbstractResult | None:
        """
        Strategy 1: Keyword Anchoring.

        Xây dựng text theo reading order (từ M3), sau đó
        scan ABSTRACT_START_PATTERN và ABSTRACT_END_PATTERN.

        Args:
            doc_data: DocumentData từ M2.
            layout_doc: LayoutDocument từ M3 (cho reading order).

        Returns:
            AbstractResult nếu tìm thấy, None nếu không.
        """
        # Build ordered text cho các trang đầu
        page_texts = self._build_ordered_text(doc_data, layout_doc)
        if not page_texts:
            return None

        # Ghép text từ các trang đầu, giữ track page boundaries
        combined_text = ""
        page_boundaries: list[tuple[int, int, int]] = []  # (start_idx, end_idx, page_num)

        for page_num, text in page_texts:
            start_idx = len(combined_text)
            combined_text += text + "\n"
            end_idx = len(combined_text)
            page_boundaries.append((start_idx, end_idx, page_num))

        # Tìm abstract start
        start_match = ABSTRACT_START_PATTERN.search(combined_text)
        if start_match is None:
            logger.debug("Keyword anchoring: no abstract start pattern found")
            return None

        # Abstract content bắt đầu SAU keyword (không lấy chữ "ABSTRACT")
        content_start = start_match.end()

        # Tìm abstract end — chỉ search SAU content_start
        end_match = ABSTRACT_END_PATTERN.search(combined_text, content_start)

        if end_match is not None:
            content_end = end_match.start()
        else:
            # Không tìm thấy end marker — lấy đến hết trang chứa abstract start
            # Tìm trang chứa abstract start
            start_page_num = 0
            for start_idx, end_idx, page_num in page_boundaries:
                if start_idx <= start_match.start() < end_idx:
                    start_page_num = page_num
                    content_end = end_idx
                    break
            else:
                content_end = len(combined_text)

        # Extract raw text
        raw_abstract = combined_text[content_start:content_end]

        # Clean & Validate
        cleaned = self._clean_abstract(raw_abstract)
        is_valid, flags = self._validate(cleaned)

        if not is_valid:
            logger.debug(
                f"Keyword anchoring: abstract found but invalid "
                f"(length={len(cleaned)}, flags={flags})"
            )
            return None

        # Determine pages
        start_page = 0
        end_page = 0
        for start_idx, end_idx, page_num in page_boundaries:
            if start_idx <= start_match.start() < end_idx:
                start_page = page_num
            if start_idx < content_end <= end_idx:
                end_page = page_num

        # Confidence: cao hơn nếu có cả start + end markers
        confidence = 0.95 if end_match is not None else 0.85

        # Check newline ratio
        self._check_newline_ratio(cleaned, flags)

        return AbstractResult(
            text=cleaned,
            confidence=confidence,
            method="keyword",
            start_page=start_page,
            end_page=end_page,
            flags=flags,
        )

    def _extract_by_zone(
        self,
        layout_doc: LayoutDocument,
    ) -> AbstractResult | None:
        """
        Strategy 2: Layout Zone Fallback.

        Lấy regions có RegionType.ABSTRACT từ M3,
        sắp xếp theo reading order, nối text.

        Args:
            layout_doc: LayoutDocument từ M3.

        Returns:
            AbstractResult nếu tìm thấy abstract zones, None nếu không.
        """
        abstract_regions = layout_doc.get_regions(RegionType.ABSTRACT)

        if not abstract_regions:
            logger.debug("Zone fallback: no ABSTRACT regions found")
            return None

        # Sort by page_number, then reading_order_index
        abstract_regions.sort(
            key=lambda r: (r.page_number, r.reading_order_index)
        )

        # Nối text từ các regions (reading order đúng)
        region_texts: list[str] = []
        for region in abstract_regions:
            text = region.text.strip()
            if text:
                region_texts.append(text)

        if not region_texts:
            return None

        raw_abstract = "\n".join(region_texts)

        # Loại bỏ dòng "Abstract" / "TÓM TẮT" ở đầu nếu có
        raw_abstract = ABSTRACT_START_PATTERN.sub("", raw_abstract, count=1).strip()

        # Clean & Validate
        cleaned = self._clean_abstract(raw_abstract)
        is_valid, flags = self._validate(cleaned)

        if not is_valid:
            logger.debug(
                f"Zone fallback: abstract found but invalid "
                f"(length={len(cleaned)}, flags={flags})"
            )
            return None

        # Pages
        start_page = abstract_regions[0].page_number
        end_page = abstract_regions[-1].page_number

        # Confidence dựa trên region confidence trung bình
        avg_confidence = sum(r.confidence for r in abstract_regions) / len(abstract_regions)
        confidence = min(avg_confidence, 0.85)

        # Check newline ratio
        self._check_newline_ratio(cleaned, flags)

        return AbstractResult(
            text=cleaned,
            confidence=round(confidence, 4),
            method="zone",
            start_page=start_page,
            end_page=end_page,
            flags=flags,
        )

    def _build_ordered_text(
        self,
        doc_data: DocumentData,
        layout_doc: LayoutDocument,
    ) -> list[tuple[int, str]]:
        """
        Xây dựng text theo reading order cho các trang đầu.

        Sử dụng regions từ M3 (đã có reading order)
        thay vì raw blocks từ M2 (có thể sai thứ tự ở PDF 2 cột).

        Args:
            doc_data: DocumentData từ M2.
            layout_doc: LayoutDocument từ M3.

        Returns:
            List (page_number, ordered_text) cho mỗi trang.
        """
        result: list[tuple[int, str]] = []
        max_pages = min(len(layout_doc.pages), _MAX_PAGES_TO_SCAN)

        for i in range(max_pages):
            layout_page = layout_doc.pages[i]

            # Lấy tất cả regions đã sorted theo reading_order_index
            sorted_regions = sorted(
                layout_page.regions,
                key=lambda r: r.reading_order_index,
            )

            # Nối text từ regions theo reading order
            page_text_parts: list[str] = []
            for region in sorted_regions:
                text = region.text.strip()
                if text:
                    page_text_parts.append(text)

            if page_text_parts:
                page_text = "\n".join(page_text_parts)
                result.append((layout_page.page_number, page_text))

        return result

    @staticmethod
    def _clean_abstract(raw: str) -> str:
        """
        Minimal cleaning cho abstract text.

        Chỉ thực hiện:
        1. Remove soft hyphens (word-\n → word)
        2. Normalize whitespace
        3. Collapse excessive blank lines
        4. Strip leading/trailing whitespace

        KHÔNG thực hiện deep cleaning (đó là Milestone 7).

        Args:
            raw: Raw abstract text.

        Returns:
            Cleaned abstract text.
        """
        if not raw:
            return ""

        text = raw

        # 1. Remove soft hyphens: "infor-\nmation" → "information"
        text = _SOFT_HYPHEN_PATTERN.sub("", text)

        # 2. Collapse excessive blank lines (3+ → 2)
        text = _EXCESSIVE_BLANK_LINES.sub("\n\n", text)

        # 3. Normalize whitespace within lines (multiple spaces → single)
        lines = text.split("\n")
        cleaned_lines: list[str] = []
        for line in lines:
            cleaned_line = " ".join(line.split())
            cleaned_lines.append(cleaned_line)
        text = "\n".join(cleaned_lines)

        # 4. Strip leading/trailing whitespace
        text = text.strip()

        return text

    @staticmethod
    def _validate(text: str) -> tuple[bool, list[str]]:
        """
        Validate abstract text.

        Kiểm tra:
        - Không None/rỗng
        - Đủ dài (≥ ABSTRACT_MIN_LENGTH)
        - Không quá dài (≤ ABSTRACT_MAX_LENGTH, truncate nếu vượt)
        - Không chỉ chứa symbols
        - Không bắt đầu bằng "Keywords"
        - Không phải pure list

        Args:
            text: Abstract text đã clean.

        Returns:
            (is_valid, flags) — True nếu hợp lệ, kèm danh sách flags.
        """
        flags: list[str] = []

        # Check rỗng
        if not text or not text.strip():
            return False, flags

        # Check quá ngắn
        if len(text) < ABSTRACT_MIN_LENGTH:
            flags.append(ABSTRACT_TOO_SHORT)
            return False, flags

        # Check bắt đầu bằng "Keywords" (nhầm section)
        stripped_lower = text.strip().lower()
        if stripped_lower.startswith("keyword") or stripped_lower.startswith("từ khóa"):
            flags.append(ABSTRACT_STARTS_WITH_KEYWORD)
            return False, flags

        # Check chỉ chứa symbols (không có alphabetic chars)
        alpha_count = sum(1 for c in text if c.isalpha())
        if alpha_count < 10:
            return False, flags

        # Check pure list (mỗi dòng bắt đầu bằng bullet/number)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) >= 3:
            list_pattern = re.compile(r"^(\d+[\.\)]\s|[-•●▪]\s)")
            list_lines = sum(1 for l in lines if list_pattern.match(l))
            if list_lines == len(lines):
                return False, flags

        # Check quá dài — truncate nhưng vẫn valid
        if len(text) > ABSTRACT_MAX_LENGTH:
            flags.append(ABSTRACT_TOO_LONG)
            # Không return False — abstract vẫn valid, chỉ thêm flag

        return True, flags

    @staticmethod
    def _check_newline_ratio(text: str, flags: list[str]) -> None:
        """
        Tính newline ratio và thêm flag nếu vượt threshold.

        KHÔNG xóa abstract — chỉ thêm warning flag.

        Args:
            text: Abstract text.
            flags: Danh sách flags (sẽ mutate in-place).
        """
        if not text:
            return

        newline_count = text.count("\n")
        text_length = len(text)

        if text_length > 0:
            ratio = newline_count / text_length
            if ratio > NEWLINE_RATIO_THRESHOLD:
                if ABSTRACT_MAY_BE_LIST not in flags:
                    flags.append(ABSTRACT_MAY_BE_LIST)
                logger.debug(
                    f"High newline ratio: {ratio:.3f} "
                    f"(threshold={NEWLINE_RATIO_THRESHOLD})"
                )
