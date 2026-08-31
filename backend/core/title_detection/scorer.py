"""
core/title_detection/scorer.py
TitleScorer — hệ thống chấm điểm 10 features cho title candidates.

Mỗi feature trả về điểm trong khoảng [0.0, weight].
Tổng điểm tối đa = MAX_TOTAL_SCORE (~9.0).
Confidence = raw_score / MAX_TOTAL_SCORE.

Thiết kế: Pure computation, không có I/O hay side effects.
"""

from __future__ import annotations

import logging

from core.title_detection.models import TitleCandidate
from core.title_detection.rules import (
    WEIGHT_FONT_SIZE,
    WEIGHT_BOLD,
    WEIGHT_FONT_FAMILY,
    WEIGHT_POSITION,
    WEIGHT_CENTER_ALIGNMENT,
    WEIGHT_AUTHOR_PROXIMITY,
    WEIGHT_ABSTRACT_PROXIMITY,
    WEIGHT_LINE_COUNT,
    WEIGHT_TITLE_LENGTH,
    WEIGHT_CAPITALIZATION,
    MAX_TOTAL_SCORE,
    TITLE_ZONE_MAX_Y,
    AUTHOR_PROXIMITY_THRESHOLD,
    IDEAL_MIN_TITLE_LENGTH,
    IDEAL_MAX_TITLE_LENGTH,
    MAX_IDEAL_LINE_COUNT,
    MAX_ACCEPTABLE_LINE_COUNT,
    TITLE_FONT_FAMILIES,
    is_title_case,
    is_all_upper,
)

logger = logging.getLogger(__name__)


class TitleScorer:
    """
    Chấm điểm title candidates dựa trên 10 features.

    Mỗi feature method trả về float trong [0.0, weight].
    Method `score()` tính tổng và gắn kết quả vào candidate.
    """

    def score(self, candidate: TitleCandidate) -> float:
        """
        Tính tổng điểm cho một candidate.

        Gắn score và score_breakdown vào candidate object.

        Args:
            candidate: TitleCandidate cần chấm điểm.

        Returns:
            Tổng điểm (raw score).
        """
        breakdown: dict[str, float] = {
            "font_size": self._score_font_size(candidate),
            "bold": self._score_bold(candidate),
            "font_family": self._score_font_family(candidate),
            "position": self._score_position(candidate),
            "center_alignment": self._score_alignment(candidate),
            "author_proximity": self._score_author_proximity(candidate),
            "abstract_proximity": self._score_abstract_proximity(candidate),
            "line_count": self._score_line_count(candidate),
            "title_length": self._score_title_length(candidate),
            "capitalization": self._score_capitalization(candidate),
        }

        total = sum(breakdown.values())
        candidate.score = total
        candidate.score_breakdown = breakdown

        logger.debug(
            f"Scored candidate: total={total:.2f}/{MAX_TOTAL_SCORE:.1f} "
            f"text={candidate.text[:50]!r}"
        )

        return total

    # ── Individual Feature Scorers ──

    def _score_font_size(self, c: TitleCandidate) -> float:
        """
        Font size ratio so với max font trên trang.

        Score = (font_size / max_font) * WEIGHT.
        Font bằng hoặc gần max → điểm cao nhất.

        Args:
            c: TitleCandidate.

        Returns:
            Score trong [0.0, WEIGHT_FONT_SIZE].
        """
        if c.max_font_size <= 0 or c.font_size <= 0:
            return 0.0

        ratio = c.font_size / c.max_font_size
        # Clamp ratio to [0, 1]
        ratio = min(ratio, 1.0)
        return ratio * WEIGHT_FONT_SIZE

    def _score_bold(self, c: TitleCandidate) -> float:
        """
        Binary: font có bold flag.

        Args:
            c: TitleCandidate.

        Returns:
            WEIGHT_BOLD nếu bold, 0.0 nếu không.
        """
        return WEIGHT_BOLD if c.is_bold else 0.0

    def _score_font_family(self, c: TitleCandidate) -> float:
        """
        Font family phù hợp title.

        Sans-serif → điểm cao hơn (thường dùng cho title).
        Serif → điểm trung bình (vẫn có thể là title).
        Không nhận diện → điểm thấp.

        Args:
            c: TitleCandidate.

        Returns:
            Score trong [0.0, WEIGHT_FONT_FAMILY].
        """
        if not c.font_name:
            return 0.0

        font_lower = c.font_name.lower().replace("-", "").replace(" ", "")

        # Sans-serif families → bonus cao
        for family in TITLE_FONT_FAMILIES:
            if family in font_lower:
                return WEIGHT_FONT_FAMILY

        # Serif fonts → điểm trung bình (vẫn phổ biến trong academic papers)
        if "serif" in font_lower or "times" in font_lower or "roman" in font_lower:
            return WEIGHT_FONT_FAMILY * 0.6

        # Bold variant hoặc font lạ → điểm cơ bản
        if "bold" in font_lower:
            return WEIGHT_FONT_FAMILY * 0.4

        return WEIGHT_FONT_FAMILY * 0.2

    def _score_position(self, c: TitleCandidate) -> float:
        """
        Vị trí Y trên trang — title ở top → điểm cao.

        Linear decay: y=0% → full score, y=35% → 0.
        y > 35% → penalty (trả 0).

        Args:
            c: TitleCandidate.

        Returns:
            Score trong [0.0, WEIGHT_POSITION].
        """
        if c.relative_y >= TITLE_ZONE_MAX_Y:
            return 0.0

        # Linear interpolation: top = 1.0, threshold = 0.0
        position_factor = 1.0 - (c.relative_y / TITLE_ZONE_MAX_Y)
        return position_factor * WEIGHT_POSITION

    def _score_alignment(self, c: TitleCandidate) -> float:
        """
        Binary: block có căn giữa trang.

        Args:
            c: TitleCandidate.

        Returns:
            WEIGHT_CENTER_ALIGNMENT nếu centered, 0.0 nếu không.
        """
        return WEIGHT_CENTER_ALIGNMENT if c.is_centered else 0.0

    def _score_author_proximity(self, c: TitleCandidate) -> float:
        """
        Khoảng cách đến author region — title nằm ngay trên author → bonus.

        Args:
            c: TitleCandidate.

        Returns:
            Score trong [0.0, WEIGHT_AUTHOR_PROXIMITY].
        """
        if c.author_region_y is None:
            # Không có author info → cho nửa điểm (neutral)
            return WEIGHT_AUTHOR_PROXIMITY * 0.3

        # Title phải nằm TRÊN author
        title_bottom = c.bbox[3]
        if title_bottom > c.author_region_y:
            return 0.0

        distance = c.author_region_y - title_bottom
        if distance <= AUTHOR_PROXIMITY_THRESHOLD:
            # Càng gần author → điểm càng cao
            proximity_factor = 1.0 - (distance / AUTHOR_PROXIMITY_THRESHOLD)
            return proximity_factor * WEIGHT_AUTHOR_PROXIMITY

        return 0.0

    def _score_abstract_proximity(self, c: TitleCandidate) -> float:
        """
        Title phải nằm TRƯỚC abstract → bonus.

        Args:
            c: TitleCandidate.

        Returns:
            Score trong [0.0, WEIGHT_ABSTRACT_PROXIMITY].
        """
        if c.abstract_region_y is None:
            # Không có abstract info → cho nửa điểm
            return WEIGHT_ABSTRACT_PROXIMITY * 0.3

        # Title phải nằm trước abstract
        title_bottom = c.bbox[3]
        if title_bottom < c.abstract_region_y:
            return WEIGHT_ABSTRACT_PROXIMITY

        return 0.0

    def _score_line_count(self, c: TitleCandidate) -> float:
        """
        Số dòng — 1-3 dòng là lý tưởng cho title.

        Args:
            c: TitleCandidate.

        Returns:
            Score trong [0.0, WEIGHT_LINE_COUNT].
        """
        if c.line_count < 1:
            return 0.0

        if c.line_count <= MAX_IDEAL_LINE_COUNT:
            return WEIGHT_LINE_COUNT

        if c.line_count <= MAX_ACCEPTABLE_LINE_COUNT:
            return WEIGHT_LINE_COUNT * 0.5

        return 0.0

    def _score_title_length(self, c: TitleCandidate) -> float:
        """
        Độ dài text — 10-200 ký tự là lý tưởng.

        Args:
            c: TitleCandidate.

        Returns:
            Score trong [0.0, WEIGHT_TITLE_LENGTH].
        """
        text_len = len(c.text.strip())

        if text_len < 5:
            return 0.0

        if IDEAL_MIN_TITLE_LENGTH <= text_len <= IDEAL_MAX_TITLE_LENGTH:
            return WEIGHT_TITLE_LENGTH

        if text_len <= 300:
            return WEIGHT_TITLE_LENGTH * 0.5

        return 0.0

    def _score_capitalization(self, c: TitleCandidate) -> float:
        """
        Kiểu viết hoa — Title Case hoặc ALL CAPS → bonus.

        Args:
            c: TitleCandidate.

        Returns:
            Score trong [0.0, WEIGHT_CAPITALIZATION].
        """
        text = c.text.strip()

        if is_all_upper(text):
            return WEIGHT_CAPITALIZATION

        if is_title_case(text):
            return WEIGHT_CAPITALIZATION

        # Mixed case / lowercase → partial score
        return WEIGHT_CAPITALIZATION * 0.3
