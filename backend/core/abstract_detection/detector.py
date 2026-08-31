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

from core.text_extraction.models import BlockData, DocumentData
from core.layout_analysis.heuristics import (
    block_center_x,
    is_full_width,
    looks_like_author_line,
)
from core.layout_analysis.layout_model import LayoutDocument, LayoutPage, RegionType
from core.abstract_detection.models import (
    AbstractResult,
    ABSTRACT_MAY_BE_LIST,
    ABSTRACT_TOO_SHORT,
    ABSTRACT_TOO_LONG,
    ABSTRACT_STARTS_WITH_KEYWORD,
)
from core.abstract_detection.language import looks_vietnamese
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

# Some Vietnamese journals place an unlabeled, italic abstract between the
# affiliation block and "Từ khóa". It is not classified as RegionType.ABSTRACT
# by layout analysis, so retain a narrowly-scoped visual fallback for page 1.
_KEYWORD_LABEL_PATTERN = re.compile(
    r"^\s*(?:keywords?|từ\s*khóa)\s*[:.]",
    re.IGNORECASE,
)
_KEYWORD_LEAK_PATTERN = re.compile(
    r"\b(?:keywords?|index\s*terms?|từ\s*kh(?:o|ó)[aá])\s*[:.]",
    re.IGNORECASE,
)
_MAX_UNLABELED_BLOCK_GAP = 32.0
_MIN_UNLABELED_LINE_WORDS = 4
_MAX_UPPERCASE_HEADING_RATIO = 0.82
_AFFILIATION_LINE_PATTERN = re.compile(
    r"^\s*(?:\d+[\s,;]*)?(?:trường|đại\s+học|bệnh\s+viện|học\s+viện|viện|"
    r"khoa|bộ\s+môn|university|hospital|institute|department|faculty)\b",
    re.IGNORECASE,
)


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

        Chạy TẤT CẢ strategies, thu thập candidates,
        chọn candidate tốt nhất theo confidence.
        Nếu confidence chênh lệch < 0.1, ưu tiên abstract dài hơn.

        Args:
            doc_data: DocumentData từ M2 (text extraction).
            layout_doc: LayoutDocument từ M3 (layout analysis).

        Returns:
            AbstractResult chứa abstract text, confidence, method.
        """
        if not doc_data.pages:
            logger.warning("Empty document — no pages to scan")
            return AbstractResult(method="none")

        # ── Run all strategies ──
        candidates: list[AbstractResult] = []

        # Strategy 1: Keyword Anchoring
        try:
            keyword_result = self._extract_by_keyword(doc_data, layout_doc)
            if keyword_result is not None and keyword_result.found:
                candidates.append(keyword_result)
                logger.info(
                    f"Abstract found by keyword anchoring: "
                    f"{keyword_result.length} chars, "
                    f"confidence={keyword_result.confidence:.2f}"
                )
        except Exception as e:
            logger.warning(f"Keyword anchoring error: {e}")

        # Strategy 2: Layout Zone Fallback
        try:
            zone_result = self._extract_by_zone(layout_doc)
            if zone_result is not None and zone_result.found:
                candidates.append(zone_result)
                logger.info(
                    f"Abstract found by zone fallback: "
                    f"{zone_result.length} chars, "
                    f"confidence={zone_result.confidence:.2f}"
                )
        except Exception as e:
            logger.warning(f"Zone fallback error: {e}")

        # Strategy 3: Unlabeled visual abstract before the keyword line.
        # This is common in the Vietnamese medical-journal template where the
        # abstract has smaller italic text but no "Tóm tắt" heading.
        try:
            unlabeled_result = self._extract_unlabeled_before_keywords(doc_data)
            if unlabeled_result is not None and unlabeled_result.found:
                candidates.append(unlabeled_result)
                logger.info(
                    f"Abstract found by unlabeled-before-keywords fallback: "
                    f"{unlabeled_result.length} chars, "
                    f"confidence={unlabeled_result.confidence:.2f}"
                )
        except Exception as e:
            logger.warning(f"Unlabeled abstract fallback error: {e}")

        # ── No candidates ──
        if not candidates:
            logger.warning("No abstract found by any strategy")
            return AbstractResult(method="none")

        # ── Pick best candidate ──
        if len(candidates) == 1:
            return candidates[0]

        # A Vietnamese medical corpus should retain the Vietnamese abstract
        # whenever both language versions are present. Confidence and length
        # are tie-breakers within the same language preference.
        candidates.sort(
            key=lambda c: (
                looks_vietnamese(c.text),
                not bool(ABSTRACT_START_PATTERN.search(c.text or "")),
                c.confidence,
                c.length,
            ),
            reverse=True,
        )

        best = candidates[0]
        runner_up = candidates[1]

        # A keyword match that starts again in a body heading (for example
        # "Tổng quan") can be much longer than the true unlabeled abstract.
        # The visual candidate ends directly at "Từ khóa", so it is safer
        # when the keyword candidate is implausibly larger.
        if (
            not (looks_vietnamese(best.text) and not looks_vietnamese(runner_up.text))
            and
            runner_up.method == "unlabeled_before_keywords"
            and runner_up.confidence >= 0.75
            and best.length > runner_up.length * 1.8
        ):
            best, runner_up = runner_up, best
            logger.info(
                f"Abstract swapped: bounded visual candidate {best.method} "
                f"({best.length} chars) avoids oversized {runner_up.method} "
                f"candidate ({runner_up.length} chars)"
            )

        # If confidence difference < 0.1, prefer a longer result only when it
        # cannot override the visual fallback that is explicitly bounded by
        # the keyword line.  An oversized keyword candidate may include body
        # text when a PDF has no explicit abstract heading.
        if (
            not (looks_vietnamese(best.text) and not looks_vietnamese(runner_up.text))
            and
            best.method != "unlabeled_before_keywords"
            and (best.confidence - runner_up.confidence) < 0.1
            and runner_up.length > best.length
        ):
            best, runner_up = runner_up, best
            logger.info(
                f"Abstract swapped: prefer longer {best.method} "
                f"({best.length} chars) over {runner_up.method} "
                f"({runner_up.length} chars), confidence diff < 0.1"
            )

        # Store alternatives
        best.alternatives = [
            {
                "method": c.method,
                "confidence": round(c.confidence, 4),
                "length": c.length,
                "text_preview": (c.text or "")[:100],
            }
            for c in candidates if c is not best
        ]

        logger.info(
            f"Abstract best-of-{len(candidates)}: "
            f"picked {best.method} (conf={best.confidence:.2f}, "
            f"len={best.length})"
        )

        return best

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

        # Evaluate every language section. Vietnamese headings are tried
        # first; English Abstract/Summary remains the fallback when the
        # Vietnamese section is missing or invalid.
        start_matches = list(ABSTRACT_START_PATTERN.finditer(combined_text))
        if not start_matches:
            logger.debug("Keyword anchoring: no abstract start pattern found")
            return None
        ordered_matches = sorted(
            start_matches,
            key=lambda match: (
                not match.group(1).casefold().startswith("tóm"),
                match.start(),
            ),
        )

        for start_match in ordered_matches:
            content_start = start_match.end()
            end_match = ABSTRACT_END_PATTERN.search(combined_text, content_start)
            next_start = next(
                (
                    match.start()
                    for match in start_matches
                    if match.start() > start_match.start()
                ),
                None,
            )
            explicit_boundaries = [
                boundary
                for boundary in (
                    end_match.start() if end_match is not None else None,
                    next_start,
                )
                if boundary is not None
            ]
            if explicit_boundaries:
                content_end = min(explicit_boundaries)
            else:
                content_end = next(
                    (
                        end_idx
                        for start_idx, end_idx, _page_num in page_boundaries
                        if start_idx <= start_match.start() < end_idx
                    ),
                    len(combined_text),
                )

            cleaned = self._clean_abstract(combined_text[content_start:content_end])
            is_valid, flags = self._validate(cleaned)
            if not is_valid:
                logger.debug(
                    "Keyword anchoring candidate invalid: label=%s, length=%s, flags=%s",
                    start_match.group(1),
                    len(cleaned),
                    flags,
                )
                continue

            start_page = 0
            end_page = 0
            for start_idx, end_idx, page_num in page_boundaries:
                if start_idx <= start_match.start() < end_idx:
                    start_page = page_num
                if start_idx < content_end <= end_idx:
                    end_page = page_num

            self._check_newline_ratio(cleaned, flags)
            return AbstractResult(
                text=cleaned,
                confidence=0.95 if explicit_boundaries else 0.85,
                method="keyword",
                start_page=start_page,
                end_page=end_page,
                flags=flags,
            )

        return None

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
        # A PDF producer may emit a short right-column ending before the main
        # left-column paragraph.  Reconstruct the order inside the bounded
        # ABSTRACT zone from its geometry rather than trusting that stream.
        pages_by_number = {page.page_number: page for page in layout_doc.pages}
        blocks_by_page: dict[int, list[BlockData]] = {}
        for region in abstract_regions:
            blocks_by_page.setdefault(region.page_number, []).extend(region.blocks)

        region_texts: list[str] = []
        used_column_order = False
        for page_number in sorted(blocks_by_page):
            ordered_blocks, page_used_column_order = self._order_abstract_blocks(
                blocks_by_page[page_number], pages_by_number.get(page_number)
            )
            used_column_order = used_column_order or page_used_column_order
            text = "\n".join(block.text for block in ordered_blocks).strip()
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
        method = "zone"
        if used_column_order:
            # The blocks are explicitly labelled ABSTRACT and their page
            # coordinates provide the reading order, so this must outrank a
            # raw keyword stream that interleaves columns.
            confidence = max(confidence, 0.96)
            method = "zone_column_order"

        # Check newline ratio
        self._check_newline_ratio(cleaned, flags)

        return AbstractResult(
            text=cleaned,
            confidence=round(confidence, 4),
            method=method,
            start_page=start_page,
            end_page=end_page,
            flags=flags,
        )

    @staticmethod
    def _order_abstract_blocks(
        blocks: list[BlockData],
        page: LayoutPage | None,
    ) -> tuple[list[BlockData], bool]:
        """Order a bounded abstract zone without interleaving two columns.

        A small number of journal PDFs expose the final paragraph of the
        right column before the left-column body.  The method preserves every
        block verbatim and only uses its physical position to restore the
        conventional order: full-width heading, left column, right column.
        """
        if len(blocks) < 2 or page is None or page.width <= 0:
            return list(blocks), False

        unique_blocks: list[BlockData] = []
        seen_ids: set[int] = set()
        for block in blocks:
            if id(block) not in seen_ids:
                unique_blocks.append(block)
                seen_ids.add(id(block))

        page_center = page.width / 2
        full_width_blocks = [
            block for block in unique_blocks if is_full_width(block, page.width)
        ]
        column_blocks = [
            block for block in unique_blocks if block not in full_width_blocks
        ]
        left_blocks = [
            block for block in column_blocks if block_center_x(block) < page_center
        ]
        right_blocks = [
            block for block in column_blocks if block_center_x(block) >= page_center
        ]

        # Use M3's page result when available.  The zone itself is enough to
        # infer columns on hybrid first pages whose title/author area caused
        # a conservative whole-page single-column classification.
        if not (page.column_info.column_count == 2 or (left_blocks and right_blocks)):
            return list(unique_blocks), False

        full_width_blocks.sort(key=lambda block: (block.bbox[1], block.bbox[0]))
        left_blocks.sort(key=lambda block: (block.bbox[1], block.bbox[0]))
        right_blocks.sort(key=lambda block: (block.bbox[1], block.bbox[0]))
        first_column_y = min(
            (block.bbox[1] for block in left_blocks + right_blocks),
            default=float("inf"),
        )
        leading_full = [
            block for block in full_width_blocks if block.bbox[1] <= first_column_y
        ]
        trailing_full = [
            block for block in full_width_blocks if block.bbox[1] > first_column_y
        ]
        ordered = leading_full + left_blocks + right_blocks + trailing_full
        changed = [id(block) for block in ordered] != [id(block) for block in unique_blocks]
        return ordered, changed

    def _extract_unlabeled_before_keywords(
        self,
        doc_data: DocumentData,
    ) -> AbstractResult | None:
        """Extract the final contiguous full-width paragraph before keywords.

        This fallback only examines the first page. It requires a real keyword
        label and takes the closest vertically-contiguous group of wide text
        blocks immediately above it, which avoids treating title, author and
        affiliation blocks as an abstract.
        """
        first_page = doc_data.pages[0]
        if first_page.width <= 0:
            return None

        # Work at line level. Some publishers keep every visual line in a
        # separate block, while others combine the full preamble into one
        # block. A block-only rule cannot distinguish them reliably.
        lines = [
            (line.text.strip(), line.bbox, line.spans)
            for block in first_page.blocks
            if block.block_type == 0
            for line in block.lines
            if line.text.strip()
        ]
        lines.sort(key=lambda item: (item[1][1], item[1][0]))
        keyword_index = next(
            (
                index
                for index, (text, _bbox, _spans) in enumerate(lines)
                if _KEYWORD_LABEL_PATTERN.match(text)
            ),
            None,
        )
        if keyword_index is None:
            return None

        keyword_top = lines[keyword_index][1][1]
        group: list[tuple[str, tuple[float, float, float, float], list]] = []
        previous_top = keyword_top

        for text, bbox, spans in reversed(lines[:keyword_index]):
            _x0, y0, _x1, y1 = bbox
            if y1 > keyword_top:
                continue
            if previous_top - y1 > _MAX_UNLABELED_BLOCK_GAP:
                break
            if not self._looks_like_unlabeled_abstract_line(text):
                # A title, author, affiliation, or section heading marks the
                # start of the abstract area. Do not continue into metadata.
                break
            group.append((text, bbox, spans))
            previous_top = y0

        if not group:
            return None

        group.reverse()
        raw_abstract = "\n".join(text for text, _bbox, _spans in group)
        cleaned = self._clean_abstract(raw_abstract)
        is_valid, flags = self._validate(cleaned)
        if not is_valid:
            return None

        spans = [
            span
            for _text, _bbox, line_spans in group
            for span in line_spans
            if span.text.strip()
        ]
        italic_ratio = (
            sum(1 for span in spans if span.font_flags & 2) / len(spans)
            if spans else 0.0
        )
        confidence = 0.78
        if len(group) >= 2:
            confidence += 0.05
        if italic_ratio >= 0.6:
            confidence += 0.05

        self._check_newline_ratio(cleaned, flags)
        return AbstractResult(
            text=cleaned,
            confidence=round(min(confidence, 0.9), 4),
            method="unlabeled_before_keywords",
            start_page=first_page.page_number,
            end_page=first_page.page_number,
            flags=flags,
        )

    @staticmethod
    def _looks_like_unlabeled_abstract_line(text: str) -> bool:
        """Return whether a line can belong to an unlabeled abstract.

        Accept normal prose, including a short final line, but use author and
        affiliation metadata as hard boundaries.
        """
        normalized = " ".join(text.split())
        if not normalized:
            return False
        if _AFFILIATION_LINE_PATTERN.match(normalized) or looks_like_author_line(normalized):
            return False
        if _KEYWORD_LABEL_PATTERN.match(normalized):
            return False
        if len(normalized.split()) < _MIN_UNLABELED_LINE_WORDS:
            return False

        alpha_chars = [char for char in normalized if char.isalpha()]
        if not alpha_chars:
            return False
        uppercase_ratio = sum(char.isupper() for char in alpha_chars) / len(alpha_chars)
        return uppercase_ratio < _MAX_UPPERCASE_HEADING_RATIO

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

        # Check a keyword block at the beginning of the candidate.  Besides a
        # direct start, tolerate both Vietnamese spellings "từ khóa" and
        # "từ khoá" because PDFs frequently preserve the latter.
        stripped_lower = text.strip().lower()
        if _KEYWORD_LEAK_PATTERN.search(stripped_lower[:350]):
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
