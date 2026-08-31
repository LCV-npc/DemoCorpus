"""
core/title_detection/models.py
Data models cho Title Detection module.

TitleCandidate — đối tượng trung gian chứa features để scoring.
TitleResult — kết quả cuối cùng trả về cho caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TitleCandidate:
    """
    Candidate title — chứa text và tất cả features cần thiết cho scoring.

    Được tạo từ Region hoặc BlockData, enriched với context
    từ trang (max font, page dimensions, author/abstract positions).
    """

    # ── Core data ──
    text: str = ""
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    page_number: int = 0

    # ── Font features ──
    font_size: float = 0.0
    font_flags: int = 0
    font_name: str = ""
    is_bold: bool = False

    # ── Spatial features ──
    is_centered: bool = False
    relative_y: float = 0.0       # 0.0 = top, 1.0 = bottom
    page_width: float = 0.0
    page_height: float = 0.0

    # ── Content features ──
    line_count: int = 1

    # ── Context features (từ trang) ──
    max_font_size: float = 0.0    # Font lớn nhất trên trang
    author_region_y: float | None = None   # y0 của author region
    abstract_region_y: float | None = None  # y0 của abstract region

    # ── Score (set bởi TitleScorer) ──
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class TitleResult:
    """
    Kết quả cuối cùng của title detection.

    Chứa title text, confidence score, bounding box,
    page number, và metadata về strategy đã dùng.
    """

    title: str | None = None
    confidence: float = 0.0
    bbox: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    page: int = 0
    strategy: str = ""            # "zone_based", "font_based", "first_line"
    raw_score: float = 0.0
    alternatives: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize thành dict cho JSON/MongoDB output."""
        return {
            "title": self.title,
            "confidence": round(self.confidence, 4),
            "bbox": [round(v, 2) for v in self.bbox],
            "page": self.page,
            "strategy": self.strategy,
            "raw_score": round(self.raw_score, 4),
            "alternatives": self.alternatives,
        }
