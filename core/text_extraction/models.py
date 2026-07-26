"""
core/text_extraction/models.py
Data models phân cấp cho raw text extraction output từ PyMuPDF.
Hierarchy: Document → Page → Block → Line → Span.

Tách biệt với core/models/document.py (pipeline processing models).
Models này giữ raw granularity ở span-level.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SpanData:
    """Một span text — đơn vị nhỏ nhất, với font metadata."""

    text: str = ""
    font_name: str = ""
    font_size: float = 0.0
    font_flags: int = 0
    color: str = "#000000"
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    def to_dict(self) -> dict:
        """Serialize thành dict cho JSON output."""
        return {
            "text": self.text,
            "font_name": self.font_name,
            "font_size": self.font_size,
            "font_flags": self.font_flags,
            "color": self.color,
            "bbox": list(self.bbox),
        }


@dataclass
class LineData:
    """Một dòng text, chứa danh sách spans."""

    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    spans: list[SpanData] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Ghép text từ tất cả spans."""
        return "".join(span.text for span in self.spans)

    def to_dict(self) -> dict:
        """Serialize thành dict cho JSON output."""
        return {
            "bbox": list(self.bbox),
            "spans": [span.to_dict() for span in self.spans],
        }


@dataclass
class BlockData:
    """Một block (đoạn) text, chứa danh sách lines."""

    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    block_type: int = 0  # 0 = text, 1 = image
    block_number: int = 0
    lines: list[LineData] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Ghép text từ tất cả lines, mỗi line cách nhau bởi newline."""
        return "\n".join(line.text for line in self.lines)

    def to_dict(self) -> dict:
        """Serialize thành dict cho JSON output."""
        return {
            "block_number": self.block_number,
            "block_type": self.block_type,
            "bbox": list(self.bbox),
            "lines": [line.to_dict() for line in self.lines],
        }


@dataclass
class PageData:
    """Một trang PDF, chứa danh sách blocks."""

    page_number: int = 0
    width: float = 0.0
    height: float = 0.0
    blocks: list[BlockData] = field(default_factory=list)
    image_count: int = 0

    @property
    def text(self) -> str:
        """Ghép text từ tất cả text blocks (bỏ qua image blocks)."""
        return "\n".join(
            block.text for block in self.blocks if block.block_type == 0
        )

    def to_dict(self) -> dict:
        """Serialize thành dict cho JSON output."""
        return {
            "page_number": self.page_number,
            "width": self.width,
            "height": self.height,
            "image_count": self.image_count,
            "blocks": [block.to_dict() for block in self.blocks],
        }


@dataclass
class DocumentData:
    """Toàn bộ kết quả extraction từ một PDF."""

    file_path: str = ""
    page_count: int = 0
    pages: list[PageData] = field(default_factory=list)
    is_born_digital: bool = True
    extraction_time_seconds: float = 0.0
    total_blocks: int = 0
    total_spans: int = 0

    def to_dict(self) -> dict:
        """Serialize thành dict cho JSON output."""
        return {
            "file_path": self.file_path,
            "page_count": self.page_count,
            "is_born_digital": self.is_born_digital,
            "extraction_time_seconds": self.extraction_time_seconds,
            "total_blocks": self.total_blocks,
            "total_spans": self.total_spans,
            "pages": [page.to_dict() for page in self.pages],
        }
