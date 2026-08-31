"""
core/models/document.py
Domain models cho PDF document: TextBlock, Page, Document.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from config.constants import ZoneType


@dataclass
class TextBlock:
    """Một khối văn bản được trích xuất từ PDF, kèm spatial & font metadata."""

    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    text: str = ""
    font_name: str = ""
    font_size: float = 0.0
    font_flags: int = 0
    zone_type: str = ZoneType.UNKNOWN

    # ── Properties ──

    @property
    def is_bold(self) -> bool:
        """Kiểm tra font có bold không (bit 4 trong font_flags, tức giá trị 16)."""
        return bool(self.font_flags & 16)

    @property
    def width(self) -> float:
        """Chiều rộng bounding box."""
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        """Chiều cao bounding box."""
        return self.y1 - self.y0

    @property
    def center_y(self) -> float:
        """Tọa độ Y trung tâm."""
        return (self.y0 + self.y1) / 2

    @property
    def stripped_text(self) -> str:
        """Text đã strip khoảng trắng."""
        return self.text.strip()


@dataclass
class Page:
    """Một trang PDF, chứa danh sách TextBlock."""

    page_index: int = 0
    width: float = 0.0
    height: float = 0.0
    blocks: list[TextBlock] = field(default_factory=list)

    def blocks_in_zone(self, zone_type: str) -> list[TextBlock]:
        """Trả về các blocks thuộc zone_type chỉ định."""
        return [b for b in self.blocks if b.zone_type == zone_type]

    def max_font_size(self) -> float:
        """Font size lớn nhất trong trang, 0.0 nếu không có blocks."""
        if not self.blocks:
            return 0.0
        return max(b.font_size for b in self.blocks)

    def top_fraction_blocks(self, fraction: float = 0.35) -> list[TextBlock]:
        """Trả về các blocks nằm trong phần trên (fraction) của trang."""
        threshold_y = self.height * fraction
        return [b for b in self.blocks if b.y0 < threshold_y]


@dataclass
class Document:
    """Đại diện cho toàn bộ PDF document đã trích xuất."""

    file_path: str = ""
    pages: list[Page] = field(default_factory=list)
    page_count: int = 0
    is_born_digital: bool = True

    # ── Properties ──

    @property
    def first_page(self) -> Optional[Page]:
        """Trang đầu tiên, None nếu document rỗng."""
        return self.pages[0] if self.pages else None

    # ── Methods ──

    def all_blocks(self) -> list[TextBlock]:
        """Tất cả TextBlocks từ mọi trang."""
        result = []
        for page in self.pages:
            result.extend(page.blocks)
        return result

    def blocks_on_page(self, page_num: int) -> list[TextBlock]:
        """Blocks ở trang page_num (0-indexed). Trả về [] nếu ngoài phạm vi."""
        if 0 <= page_num < len(self.pages):
            return self.pages[page_num].blocks
        return []
