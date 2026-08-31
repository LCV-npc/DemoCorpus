"""
core/abstract_detection/models.py
Data models cho Abstract Detection module.

AbstractResult — kết quả cuối cùng trả về cho caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Flag constants
ABSTRACT_MAY_BE_LIST = "ABSTRACT_MAY_BE_LIST"
ABSTRACT_TOO_SHORT = "ABSTRACT_TOO_SHORT"
ABSTRACT_TOO_LONG = "ABSTRACT_TOO_LONG"
ABSTRACT_STARTS_WITH_KEYWORD = "ABSTRACT_STARTS_WITH_KEYWORD"


@dataclass
class AbstractResult:
    """
    Kết quả cuối cùng của abstract detection.

    Attributes:
        text: Abstract text đã extract và clean. None nếu không tìm thấy.
        confidence: Confidence score [0.0, 1.0].
        method: Strategy đã dùng ("keyword", "zone", "none").
        start_page: Trang bắt đầu abstract (0-indexed).
        end_page: Trang kết thúc abstract (0-indexed).
        flags: Danh sách flags/warnings.
        alternatives: Danh sách candidates khác (runner-ups).
    """

    text: str | None = None
    confidence: float = 0.0
    method: str = ""              # "keyword", "zone", "none"
    start_page: int = 0
    end_page: int = 0
    flags: list[str] = field(default_factory=list)
    alternatives: list[dict] = field(default_factory=list)

    @property
    def found(self) -> bool:
        """True nếu abstract đã được phát hiện."""
        return self.text is not None and len(self.text) > 0

    @property
    def length(self) -> int:
        """Số ký tự của abstract."""
        return len(self.text) if self.text else 0

    def to_dict(self) -> dict:
        """Serialize thành dict cho JSON/MongoDB output."""
        return {
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "method": self.method,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "flags": self.flags,
            "length": self.length,
            "alternatives": self.alternatives,
        }
