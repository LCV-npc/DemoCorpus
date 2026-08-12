"""
core/data_cleaning/models.py
Data models cho Data Cleaning module (Milestone 7).

CleaningResult — kết quả cuối cùng sau khi cleaning + noise detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ─────────────────────────────────────────────
# Cleaning flag constants
# ─────────────────────────────────────────────

# Character cleaning
CHARS_SUBSTITUTED = "CHARS_SUBSTITUTED"
CONTROL_CHARS_REMOVED = "CONTROL_CHARS_REMOVED"
LIGATURES_EXPANDED = "LIGATURES_EXPANDED"

# Unicode
UNICODE_NORMALIZED = "UNICODE_NORMALIZED"

# Whitespace
WHITESPACE_COLLAPSED = "WHITESPACE_COLLAPSED"

# Hyphenation
HYPHENATION_REPAIRED = "HYPHENATION_REPAIRED"

# Title
TITLE_NEWLINES_REMOVED = "TITLE_NEWLINES_REMOVED"
TITLE_CLEANED = "TITLE_CLEANED"

# Author
AUTHOR_EMAILS_REMOVED = "AUTHOR_EMAILS_REMOVED"
AUTHOR_FOOTNOTES_REMOVED = "AUTHOR_FOOTNOTES_REMOVED"
AUTHOR_DUPLICATES_REMOVED = "AUTHOR_DUPLICATES_REMOVED"
AUTHOR_ORCID_REMOVED = "AUTHOR_ORCID_REMOVED"

# Abstract
ABSTRACT_HEADER_REMOVED = "ABSTRACT_HEADER_REMOVED"
ABSTRACT_FOOTER_REMOVED = "ABSTRACT_FOOTER_REMOVED"
ABSTRACT_CLEANED = "ABSTRACT_CLEANED"

# Noise detection
HIGH_NON_ALPHA_RATIO = "HIGH_NON_ALPHA_RATIO"
HIGH_WHITESPACE_RATIO = "HIGH_WHITESPACE_RATIO"
HIGH_DUPLICATE_LINES = "HIGH_DUPLICATE_LINES"
HIGH_SYMBOL_RATIO = "HIGH_SYMBOL_RATIO"
POSSIBLE_GARBLED_TEXT = "POSSIBLE_GARBLED_TEXT"
TEXT_TOO_SHORT = "TEXT_TOO_SHORT"


@dataclass
class NoiseResult:
    """
    Kết quả noise detection cho một trường metadata.

    Attributes:
        is_noisy: True nếu phát hiện nhiễu.
        noise_score: Noise score [0.0, 1.0]. 0 = clean, 1 = rất noisy.
        flags: Danh sách noise flags.
        metrics: Chi tiết metrics (non_alpha_ratio, whitespace_ratio, ...).
    """

    is_noisy: bool = False
    noise_score: float = 0.0
    flags: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize."""
        return {
            "is_noisy": self.is_noisy,
            "noise_score": round(self.noise_score, 4),
            "flags": self.flags,
            "metrics": {k: round(v, 4) for k, v in self.metrics.items()},
        }


@dataclass
class CleaningResult:
    """
    Kết quả cuối cùng của Data Cleaning pipeline.

    Attributes:
        title: Title đã clean. None nếu input là None.
        authors: Danh sách tên tác giả đã clean.
        abstract: Abstract đã clean. None nếu input là None.
        cleaning_flags: Danh sách flags mô tả các bước cleaning đã thực hiện.
        changes_made: Danh sách mô tả chi tiết các thay đổi.
        title_noise: Noise analysis cho title.
        author_noise: Noise analysis cho authors (tổng hợp).
        abstract_noise: Noise analysis cho abstract.
    """

    title: str | None = None
    authors: list[str] = field(default_factory=list)
    abstract: str | None = None
    cleaning_flags: list[str] = field(default_factory=list)
    changes_made: list[str] = field(default_factory=list)
    title_noise: NoiseResult = field(default_factory=NoiseResult)
    author_noise: NoiseResult = field(default_factory=NoiseResult)
    abstract_noise: NoiseResult = field(default_factory=NoiseResult)

    @property
    def overall_noise_score(self) -> float:
        """Noise score trung bình của 3 trường."""
        scores = [
            self.title_noise.noise_score,
            self.author_noise.noise_score,
            self.abstract_noise.noise_score,
        ]
        return sum(scores) / len(scores)

    @property
    def has_noise(self) -> bool:
        """True nếu bất kỳ trường nào bị noisy."""
        return (
            self.title_noise.is_noisy
            or self.author_noise.is_noisy
            or self.abstract_noise.is_noisy
        )

    def to_dict(self) -> dict:
        """Serialize thành dict cho JSON output."""
        return {
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "cleaning_flags": self.cleaning_flags,
            "changes_made": self.changes_made,
            "noise": {
                "title": self.title_noise.to_dict(),
                "authors": self.author_noise.to_dict(),
                "abstract": self.abstract_noise.to_dict(),
                "overall_score": round(self.overall_noise_score, 4),
                "has_noise": self.has_noise,
            },
        }
