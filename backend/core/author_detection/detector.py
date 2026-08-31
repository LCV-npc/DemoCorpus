"""
core/author_detection/detector.py
AuthorDetector — 3-tier pipeline phát hiện tác giả bài báo.

Tier 1 (Heuristic): Dùng AUTHOR regions từ LayoutDocument → split & clean.
Tier 2 (NER):       Fallback — dùng NER model trích xuất PERSON entities.
Tier 3 (Pattern):   Last resort — tìm text giữa title và abstract/affiliation.

Input:  LayoutDocument (M3) + TitleResult (M4).
Output: AuthorResult.
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
    is_bold as font_is_bold,
    max_font_size_in_blocks,
    contains_affiliation,
)
from core.title_detection.models import TitleResult
from core.author_detection.models import AuthorInfo, AuthorResult
from core.author_detection.cleaner import AuthorCleaner
from core.author_detection.ner_engine import NEREngine, StubNEREngine

logger = logging.getLogger(__name__)

# Confidence ranges theo tier
_CONF_TIER1_MIN = 0.75
_CONF_TIER1_MAX = 0.95
_CONF_TIER2_MIN = 0.65
_CONF_TIER2_MAX = 0.90
_CONF_TIER3_MIN = 0.35
_CONF_TIER3_MAX = 0.70


class AuthorDetector:
    """
    Phát hiện tác giả bài báo khoa học từ LayoutDocument + TitleResult.

    Pipeline 3 tiers theo thứ tự ưu tiên:
    1. Heuristic — AUTHOR zone blocks → split & clean
    2. NER — NER model trích xuất PERSON entities (optional)
    3. Pattern — blocks giữa title_y_end và abstract_y → split & clean

    Sử dụng AuthorCleaner cho tất cả text cleaning.
    """

    def __init__(
        self,
        cleaner: AuthorCleaner | None = None,
        ner_engine: NEREngine | None = None,
    ):
        """
        Khởi tạo detector.

        Args:
            cleaner: AuthorCleaner instance. Nếu None, tạo mới.
            ner_engine: NER engine (optional). Nếu None, dùng StubNEREngine.
        """
        self._cleaner = cleaner or AuthorCleaner()
        self._ner = ner_engine or StubNEREngine()
        logger.info("AuthorDetector initialized")

    def detect(
        self,
        doc: LayoutDocument,
        title_result: TitleResult | None = None,
    ) -> AuthorResult:
        """
        Phát hiện tác giả từ LayoutDocument.

        Chạy TẤT CẢ 4 tiers, gộp kết quả, và deduplicate.
        Confidence = weighted average theo tier priority.

        Args:
            doc: LayoutDocument từ Giai đoạn 3.
            title_result: TitleResult từ Giai đoạn 4 (optional).

        Returns:
            AuthorResult với danh sách authors merged, confidence, strategy.
        """
        if not doc.pages:
            logger.warning(f"Empty document: {doc.file_path}")
            return AuthorResult(strategy="none")

        first_page = doc.pages[0]

        # ── Run all tiers and collect results ──
        tier_results: list[tuple[AuthorResult | None, str, float]] = []
        #                          result, tier_name, weight

        # Tier 1: Heuristic — AUTHOR zones (weight 1.0)
        t1 = self._tier1_heuristic(first_page)
        tier_results.append((t1, "heuristic", 1.0))

        # Tier 1.5: inspect the metadata band directly. PDF producers can
        # split one visual author line across differently classified regions.
        t1_5 = self._tier1_5_metadata_band(first_page, title_result)
        tier_results.append((t1_5, "metadata_band", 0.95))

        # Tier 2: NER — PERSON entities (weight 0.8)
        t2 = self._tier2_ner(first_page)
        tier_results.append((t2, "ner", 0.8))

        # Tier 3: Pattern — gap between title and abstract (weight 0.6)
        t3 = self._tier3_pattern(first_page, title_result)
        tier_results.append((t3, "pattern", 0.6))

        # Tier 3.5: VN Pattern Fallback (weight 0.5)
        t3_5 = self._tier3_5_vn_pattern(first_page, title_result)
        tier_results.append((t3_5, "vn_pattern", 0.5))

        # ── Collect valid tier results ──
        valid_tiers: list[tuple[AuthorResult, str, float]] = []
        for result, tier_name, weight in tier_results:
            if result and result.authors:
                valid_tiers.append((result, tier_name, weight))
                logger.info(
                    f"Tier ({tier_name}): {result.count} authors | "
                    f"{result.author_names[:3]}"
                )

        # ── No results from any tier ──
        if not valid_tiers:
            logger.warning(f"No authors found by any tier: {doc.file_path}")
            return AuthorResult(strategy="none")

        # ── Only one tier found results → return directly (backwards compatible) ──
        if len(valid_tiers) == 1:
            result, tier_name, _ = valid_tiers[0]
            result.strategies_used = [tier_name]
            return result

        # ── Multiple tiers → merge and deduplicate ──
        return self._merge_tier_results(valid_tiers)

    def _merge_tier_results(
        self,
        valid_tiers: list[tuple[AuthorResult, str, float]],
    ) -> AuthorResult:
        """
        Merge authors từ nhiều tiers, deduplicate, tính weighted confidence.

        Priority: authors từ tier có weight cao hơn được giữ nguyên,
        authors mới từ tier thấp hơn chỉ được thêm nếu chưa có.

        Args:
            valid_tiers: List of (AuthorResult, tier_name, weight),
                         sorted by weight descending.

        Returns:
            AuthorResult merged.
        """
        # Sort tiers by weight descending (highest priority first)
        valid_tiers.sort(key=lambda t: t[2], reverse=True)

        merged_authors: list[AuthorInfo] = []
        seen_names_lower: set[str] = set()
        strategies_used: list[str] = []
        raw_texts: list[str] = []

        # Weighted confidence tracking
        total_weight = 0.0
        weighted_conf_sum = 0.0

        for result, tier_name, weight in valid_tiers:
            tier_added = 0
            for author in result.authors:
                name_lower = author.name.lower().strip()
                # Deduplicate: skip if name already seen
                if name_lower in seen_names_lower:
                    continue
                # Fuzzy dedup: skip if name is substring of existing name or vice versa
                is_dup = False
                for existing in seen_names_lower:
                    if name_lower in existing or existing in name_lower:
                        is_dup = True
                        break
                if is_dup:
                    continue

                seen_names_lower.add(name_lower)
                merged_authors.append(author)
                tier_added += 1

            if tier_added > 0:
                strategies_used.append(tier_name)
                weighted_conf_sum += result.confidence * weight
                total_weight += weight

            if result.raw_text:
                raw_texts.append(f"[{tier_name}] {result.raw_text[:100]}")

        # Compute weighted average confidence
        confidence = weighted_conf_sum / total_weight if total_weight > 0 else 0.0

        strategy = "merged" if len(strategies_used) > 1 else strategies_used[0] if strategies_used else "none"

        logger.info(
            f"Merged authors: {len(merged_authors)} total from "
            f"{strategies_used}, confidence={confidence:.3f}"
        )

        return AuthorResult(
            authors=merged_authors,
            confidence=confidence,
            strategy=strategy,
            strategies_used=strategies_used,
            raw_text=" | ".join(raw_texts),
        )

    # ── Tier 1: Heuristic ──

    def _tier1_heuristic(self, page: LayoutPage) -> AuthorResult | None:
        """
        Trích xuất tác giả từ AUTHOR regions.

        Lấy tất cả Region(type=AUTHOR) → gộp text → split & clean.

        Args:
            page: LayoutPage (trang 0).

        Returns:
            AuthorResult hoặc None nếu không có AUTHOR regions.
        """
        author_regions = page.get_regions(RegionType.AUTHOR)
        if not author_regions:
            logger.debug("Tier 1: No AUTHOR regions found")
            return None

        import re
        from core.layout_analysis.heuristics import matches_abstract_start, contains_affiliation

        # Extract text line-by-line and stop if we hit abstract keywords.
        # Fixes case where PyMuPDF grouped author + abstract into one block
        # and M3 classified the whole block as AUTHOR.
        author_lines = []
        found_abstract = False

        # Sắp xếp các blocks trong các regions theo Y coordinate
        all_blocks = []
        for region in author_regions:
            all_blocks.extend(region.blocks)
        all_blocks.sort(key=lambda b: b.bbox[1])

        for block in all_blocks:
            for line in block.lines:
                text = line.text.strip()
                if not text:
                    continue
                if matches_abstract_start(text):
                    found_abstract = True
                    break
                
                # Stop if we hit a line that is clearly body text
                # Authors are names, not sentences. If it's long and doesn't look like authors/affiliation, it's body text.
                from core.layout_analysis.heuristics import looks_like_author_line
                if len(text) > 40 and not looks_like_author_line(text):
                    if not contains_affiliation(text):
                        found_abstract = True
                        break

                author_lines.append(text)
            if found_abstract:
                break

        raw_text = " ".join(author_lines)
        if not raw_text.strip():
            return None

        # Extract emails trước khi clean
        emails = self._cleaner.extract_emails(raw_text)

        # Split & clean
        names = self._cleaner.split_and_clean(raw_text)

        if not names:
            logger.debug(f"Tier 1: No valid names after cleaning: {raw_text[:80]!r}")
            return None

        # Build AuthorInfo list
        authors = self._build_author_infos(names, emails, page)

        # Confidence based on region confidence + number of authors
        region_conf = sum(r.confidence for r in author_regions) / len(author_regions)
        confidence = self._map_confidence(
            region_conf, _CONF_TIER1_MIN, _CONF_TIER1_MAX
        )

        return AuthorResult(
            authors=authors,
            confidence=confidence,
            strategy="heuristic",
            raw_text=raw_text,
        )

    def _tier1_5_metadata_band(
        self,
        page: LayoutPage,
        title_result: TitleResult | None,
    ) -> AuthorResult | None:
        """Recover author lines fragmented by layout-region classification.

        Only inspect the upper metadata band after the title and accept lines
        that already satisfy the strict Vietnamese-author heuristic. This lets
        a missing final author be merged without treating affiliation or
        abstract prose as a person name.
        """
        from core.layout_analysis.heuristics import looks_like_author_line

        title_y_end = self._get_title_y_end(page, title_result)
        if title_y_end is None:
            return None

        line_candidates: list[tuple[float, str]] = []
        seen_lines: set[tuple[float, str]] = set()
        metadata_bottom = page.height * 0.45
        for region in page.regions:
            for block in region.blocks:
                if block.bbox[1] < title_y_end - 5.0 or block.bbox[1] > metadata_bottom:
                    continue
                for line in block.lines:
                    text = line.text.strip()
                    key = (line.bbox[1], text)
                    if key in seen_lines or not looks_like_author_line(text):
                        continue
                    seen_lines.add(key)
                    line_candidates.append((line.bbox[1], text))

        if not line_candidates:
            return None

        line_candidates.sort(key=lambda item: item[0])
        raw_text = " ".join(text for _y, text in line_candidates)
        names = self._cleaner.split_and_clean(raw_text)
        if not names:
            return None

        authors = self._build_author_infos(
            names, self._cleaner.extract_emails(raw_text), page
        )
        return AuthorResult(
            authors=authors,
            confidence=self._map_confidence(0.8, _CONF_TIER1_MIN, _CONF_TIER1_MAX),
            strategy="metadata_band",
            raw_text=raw_text,
        )

    # ── Tier 2: NER ──

    def _tier2_ner(self, page: LayoutPage) -> AuthorResult | None:
        """
        Trích xuất tác giả bằng NER model.

        Chạy NER trên text vùng top 40% trang → filter PERSON entities.

        Args:
            page: LayoutPage (trang 0).

        Returns:
            AuthorResult hoặc None nếu NER không tìm thấy gì.
        """
        # Lấy text từ top 40% trang (vùng có thể chứa author)
        raw_text = self._get_top_region_text(page, fraction=0.40)

        if not raw_text.strip():
            return None

        # Chạy NER
        person_names = self._ner.extract_persons(raw_text)

        if not person_names:
            logger.debug("Tier 2: NER found no PERSON entities")
            return None

        # Clean mỗi tên
        cleaned: list[str] = []
        for name in person_names:
            clean = self._cleaner.clean_name(name)
            if clean:
                cleaned.append(clean)

        # Filter & dedup
        names = self._cleaner.filter_names(cleaned)

        if not names:
            return None

        # Extract emails
        emails = self._cleaner.extract_emails(raw_text)

        authors = self._build_author_infos(names, emails, page)

        return AuthorResult(
            authors=authors,
            confidence=self._map_confidence(0.7, _CONF_TIER2_MIN, _CONF_TIER2_MAX),
            strategy="ner",
            raw_text=raw_text,
        )

    # ── Tier 3: Pattern ──

    def _tier3_pattern(
        self,
        page: LayoutPage,
        title_result: TitleResult | None,
    ) -> AuthorResult | None:
        """
        Fallback: tìm text giữa title và abstract/affiliation.

        Xác định vùng:
        - Top boundary: title_y_end (bottom Y của title bbox)
        - Bottom boundary: abstract_y hoặc affiliation_y (cái nào gần hơn)

        Lấy blocks trong vùng đó → gộp text → split & clean.

        Args:
            page: LayoutPage (trang 0).
            title_result: TitleResult từ M4.

        Returns:
            AuthorResult hoặc None.
        """
        # Xác định boundaries
        title_y_end = self._get_title_y_end(page, title_result)
        abstract_y = self._find_region_y(page, RegionType.ABSTRACT)
        affiliation_y = self._find_region_y(page, RegionType.AFFILIATION)

        if title_y_end is None:
            logger.debug("Tier 3: Cannot determine title bottom boundary")
            return None

        # Bottom boundary = min(abstract_y, affiliation_y) hoặc 40% trang
        bottom_y = page.height * 0.40
        if abstract_y is not None:
            bottom_y = min(bottom_y, abstract_y)
        if affiliation_y is not None:
            bottom_y = min(bottom_y, affiliation_y)

        # Lấy blocks trong vùng
        gap_blocks = self._get_gap_blocks(page, title_y_end, bottom_y)

        if not gap_blocks:
            logger.debug("Tier 3: No blocks in title-abstract gap")
            return None

        # Gộp text
        raw_text = " ".join(b.text.strip() for b in gap_blocks if b.text.strip())

        if not raw_text.strip():
            return None

        # Extract emails
        emails = self._cleaner.extract_emails(raw_text)

        # Split & clean
        names = self._cleaner.split_and_clean(raw_text)

        if not names:
            logger.debug(f"Tier 3: No valid names in gap: {raw_text[:80]!r}")
            return None

        authors = self._build_author_infos(names, emails, page)

        # Lower confidence for pattern-based
        confidence = self._map_confidence(
            0.5, _CONF_TIER3_MIN, _CONF_TIER3_MAX
        )

        return AuthorResult(
            authors=authors,
            confidence=confidence,
            strategy="pattern",
            raw_text=raw_text,
        )

    # ── Tier 3.5: VN Pattern Fallback ──

    def _tier3_5_vn_pattern(
        self,
        page: LayoutPage,
        title_result: TitleResult | None,
    ) -> AuthorResult | None:
        """
        Fallback: Tìm tác giả trong BODY hoặc ABSTRACT region dựa vào VN name pattern.
        Giải quyết lỗi M3 phân loại nhầm author line thành BODY hoặc ABSTRACT.
        """
        from core.layout_analysis.heuristics import looks_like_author_line, matches_abstract_start

        title_y_end = self._get_title_y_end(page, title_result)
        if title_y_end is None:
            return None

        author_lines = []
        found_abstract = False
        
        # Chỉ quét trong các vùng khả nghi nằm dưới title
        target_regions = (
            page.get_regions(RegionType.ABSTRACT) + 
            page.get_regions(RegionType.BODY) +
            page.get_regions(RegionType.AFFILIATION)
        )
        
        # Sort regions theo y
        target_regions.sort(key=lambda r: r.bbox[1])

        for region in target_regions:
            for block in region.blocks:
                # Bỏ qua block nằm trên title
                if block.bbox[1] < title_y_end - 5.0:
                    continue

                for line in block.lines:
                    text = line.text.strip()
                    if not text:
                        continue
                        
                    # Dừng nếu gặp keyword bắt đầu abstract thực sự
                    if matches_abstract_start(text):
                        found_abstract = True
                        break
                        
                    # Check author line pattern
                    if looks_like_author_line(text):
                        author_lines.append(text)

                if found_abstract:
                    break
            if found_abstract:
                break
                
        if not author_lines:
            return None
            
        raw_text = " ".join(author_lines)
        emails = self._cleaner.extract_emails(raw_text)
        names = self._cleaner.split_and_clean(raw_text)

        if not names:
            return None

        authors = self._build_author_infos(names, emails, page)
        confidence = self._map_confidence(0.4, _CONF_TIER3_MIN, _CONF_TIER3_MAX)

        return AuthorResult(
            authors=authors,
            confidence=confidence,
            strategy="vn_pattern",
            raw_text=raw_text,
        )

    # ── Helper Methods ──

    def _build_author_infos(
        self,
        names: list[str],
        emails: list[str],
        page: LayoutPage,
    ) -> list[AuthorInfo]:
        """
        Xây dựng danh sách AuthorInfo từ names và emails.

        Gắn email cho author theo thứ tự (nếu số email ≤ số author).
        Tìm affiliation từ AFFILIATION regions.

        Args:
            names: Danh sách tên đã clean.
            emails: Danh sách emails extracted.
            page: LayoutPage để tìm affiliations.

        Returns:
            Danh sách AuthorInfo.
        """
        # Extract affiliation text (nếu có)
        affiliation_text = self._get_affiliation_text(page)

        authors: list[AuthorInfo] = []
        for i, name in enumerate(names):
            email = emails[i] if i < len(emails) else None
            authors.append(AuthorInfo(
                name=name,
                affiliation=affiliation_text if affiliation_text else None,
                email=email,
            ))

        return authors

    @staticmethod
    def _merge_region_texts(regions: list[Region]) -> str:
        """Gộp text từ nhiều regions, join bằng space."""
        parts: list[str] = []
        for region in regions:
            text = region.text.replace("\n", " ").strip()
            if text:
                parts.append(text)
        return " ".join(parts)

    @staticmethod
    def _get_top_region_text(page: LayoutPage, fraction: float = 0.40) -> str:
        """Lấy text từ top fraction của trang."""
        threshold_y = page.height * fraction
        texts: list[str] = []
        for region in page.regions:
            if region.bbox[1] < threshold_y:
                text = region.text.replace("\n", " ").strip()
                if text:
                    texts.append(text)
        return " ".join(texts)

    @staticmethod
    def _get_title_y_end(
        page: LayoutPage,
        title_result: TitleResult | None,
    ) -> float | None:
        """
        Tìm bottom Y của title.

        Ưu tiên TitleResult.bbox, fallback tới TITLE regions.
        """
        # Từ TitleResult (M4)
        if title_result and title_result.title and len(title_result.bbox) >= 4:
            return title_result.bbox[3]

        # Fallback: TITLE regions
        title_regions = page.get_regions(RegionType.TITLE)
        if title_regions:
            return max(r.bbox[3] for r in title_regions)

        return None

    @staticmethod
    def _find_region_y(page: LayoutPage, region_type: RegionType) -> float | None:
        """Tìm y0 của region đầu tiên thuộc type."""
        regions = page.get_regions(region_type)
        if regions:
            return regions[0].bbox[1]
        return None

    @staticmethod
    def _get_gap_blocks(
        page: LayoutPage,
        top_y: float,
        bottom_y: float,
    ) -> list[BlockData]:
        """
        Lấy blocks nằm giữa top_y và bottom_y.

        Loại bỏ blocks chứa affiliation keywords.

        Args:
            page: LayoutPage.
            top_y: Biên trên (exclusive).
            bottom_y: Biên dưới (exclusive).

        Returns:
            Danh sách blocks đã sort theo y0.
        """
        blocks: list[BlockData] = []
        for region in page.regions:
            for block in region.blocks:
                block_top = block.bbox[1]
                block_bottom = block.bbox[3]
                # Block phải nằm trong vùng gap
                if block_top >= top_y and block_bottom <= bottom_y:
                    # Bỏ qua blocks chứa affiliation keywords
                    text = block.text.strip()
                    if text and not contains_affiliation(text):
                        blocks.append(block)

        # Sort theo y0
        blocks.sort(key=lambda b: b.bbox[1])
        return blocks

    @staticmethod
    def _get_affiliation_text(page: LayoutPage) -> str | None:
        """Lấy affiliation text từ AFFILIATION regions."""
        aff_regions = page.get_regions(RegionType.AFFILIATION)
        if not aff_regions:
            return None
        texts = []
        for r in aff_regions:
            text = r.text.replace("\n", " ").strip()
            if text:
                texts.append(text)
        return "; ".join(texts) if texts else None

    @staticmethod
    def _map_confidence(score: float, conf_min: float, conf_max: float) -> float:
        """Map score → confidence range [conf_min, conf_max]."""
        ratio = min(max(score, 0.0), 1.0)
        return conf_min + ratio * (conf_max - conf_min)
