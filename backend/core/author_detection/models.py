"""
core/author_detection/models.py
Data models cho Author Detection module.

AuthorInfo — thông tin một tác giả (name, affiliation, email).
AuthorResult — kết quả cuối cùng trả về cho caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AuthorInfo:
    """
    Thông tin một tác giả đã trích xuất.

    Attributes:
        name: Tên tác giả đã normalize.
        affiliation: Tên cơ quan/trường (nếu phát hiện được).
        email: Địa chỉ email (nếu phát hiện được).
    """

    name: str = ""
    affiliation: str | None = None
    email: str | None = None

    def to_dict(self) -> dict:
        """Serialize thành dict cho JSON/MongoDB output."""
        result: dict = {"name": self.name}
        if self.affiliation is not None:
            result["affiliation"] = self.affiliation
        if self.email is not None:
            result["email"] = self.email
        return result


@dataclass
class AuthorResult:
    """
    Kết quả cuối cùng của author detection.

    Attributes:
        authors: Danh sách tác giả đã phát hiện.
        confidence: Confidence score [0.0, 1.0].
        strategy: Tier đã dùng ("heuristic", "ner", "pattern", "merged", "none").
        strategies_used: Danh sách tiers đã đóng góp authors (khi strategy="merged").
        raw_text: Text gốc trước khi clean (để debug).
    """

    authors: list[AuthorInfo] = field(default_factory=list)
    confidence: float = 0.0
    strategy: str = ""
    strategies_used: list[str] = field(default_factory=list)
    raw_text: str = ""

    @property
    def author_names(self) -> list[str]:
        """Danh sách tên tác giả (tiện lợi)."""
        return [a.name for a in self.authors]

    @property
    def count(self) -> int:
        """Số lượng tác giả."""
        return len(self.authors)

    def to_dict(self) -> dict:
        """Serialize thành dict cho JSON/MongoDB output."""
        return {
            "authors": [a.to_dict() for a in self.authors],
            "confidence": round(self.confidence, 4),
            "strategy": self.strategy,
            "strategies_used": self.strategies_used,
            "count": self.count,
        }
