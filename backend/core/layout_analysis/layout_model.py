"""
core/layout_analysis/layout_model.py
Data models cho layout analysis output.
RegionType, Region, ColumnInfo, LayoutPage, LayoutDocument.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core.text_extraction.models import BlockData


class RegionType(str, Enum):
    """Phân loại vùng bố cục trong trang PDF."""

    TITLE = "TITLE"
    AUTHOR = "AUTHOR"
    AFFILIATION = "AFFILIATION"
    ABSTRACT = "ABSTRACT"
    KEYWORD = "KEYWORD"
    BODY = "BODY"
    REFERENCE = "REFERENCE"
    HEADER = "HEADER"
    FOOTER = "FOOTER"
    UNKNOWN = "UNKNOWN"


@dataclass
class Region:
    """Một vùng bố cục đã xác định, chứa danh sách blocks."""

    region_type: RegionType = RegionType.UNKNOWN
    blocks: list[BlockData] = field(default_factory=list)
    page_number: int = 0
    reading_order_index: int = 0
    confidence: float = 0.0

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """Bounding box bao trùm tất cả blocks trong region."""
        if not self.blocks:
            return (0.0, 0.0, 0.0, 0.0)
        x0 = min(b.bbox[0] for b in self.blocks)
        y0 = min(b.bbox[1] for b in self.blocks)
        x1 = max(b.bbox[2] for b in self.blocks)
        y1 = max(b.bbox[3] for b in self.blocks)
        return (round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2))

    @property
    def text(self) -> str:
        """Ghép text từ tất cả blocks, cách nhau bởi newline."""
        return "\n".join(block.text for block in self.blocks)

    def to_dict(self) -> dict:
        """Serialize thành dict cho JSON output."""
        return {
            "region_type": self.region_type.value,
            "bbox": list(self.bbox),
            "text": self.text,
            "page_number": self.page_number,
            "reading_order_index": self.reading_order_index,
            "confidence": round(self.confidence, 2),
            "block_count": len(self.blocks),
        }


@dataclass
class ColumnInfo:
    """Thông tin về cấu trúc cột của một trang."""

    column_count: int = 1
    left_boundary: float = 0.0
    right_boundary: float = 0.0
    gap_start: float = 0.0
    gap_end: float = 0.0

    @property
    def layout_type(self) -> str:
        """Tên layout dạng string."""
        if self.column_count == 2:
            return "two_column"
        return "single_column"

    def to_dict(self) -> dict:
        return {
            "column_count": self.column_count,
            "layout_type": self.layout_type,
            "gap_start": round(self.gap_start, 2),
            "gap_end": round(self.gap_end, 2),
        }


@dataclass
class LayoutPage:
    """Một trang PDF đã phân tích bố cục."""

    page_number: int = 0
    width: float = 0.0
    height: float = 0.0
    regions: list[Region] = field(default_factory=list)
    column_info: ColumnInfo = field(default_factory=ColumnInfo)

    @property
    def layout_type(self) -> str:
        return self.column_info.layout_type

    def get_regions(self, region_type: RegionType) -> list[Region]:
        """Trả về danh sách regions theo type."""
        return [r for r in self.regions if r.region_type == region_type]

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "width": self.width,
            "height": self.height,
            "layout_type": self.layout_type,
            "column_info": self.column_info.to_dict(),
            "regions": [r.to_dict() for r in self.regions],
        }


@dataclass
class LayoutDocument:
    """Toàn bộ kết quả layout analysis cho một PDF."""

    file_path: str = ""
    page_count: int = 0
    pages: list[LayoutPage] = field(default_factory=list)
    total_regions: int = 0
    analysis_time_seconds: float = 0.0

    def get_regions(
        self, region_type: RegionType, page_number: int | None = None
    ) -> list[Region]:
        """
        Trả về regions theo type, optional filter theo page.

        Args:
            region_type: Loại region cần lấy.
            page_number: Nếu chỉ định, chỉ lấy từ trang đó.

        Returns:
            List các Region matching.
        """
        results: list[Region] = []
        for page in self.pages:
            if page_number is not None and page.page_number != page_number:
                continue
            results.extend(page.get_regions(region_type))
        return results

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "page_count": self.page_count,
            "total_regions": self.total_regions,
            "analysis_time_seconds": round(self.analysis_time_seconds, 3),
            "pages": [p.to_dict() for p in self.pages],
        }
