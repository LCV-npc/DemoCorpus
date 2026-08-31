"""
core/text_extraction/utils.py
Utility functions cho text extraction module:
- Born-digital detection
- Font flag parsing
- Extraction statistics
- Color conversion
"""

from __future__ import annotations

from core.text_extraction.models import PageData, DocumentData
from config.constants import MIN_TEXT_CHARS_BORN_DIGITAL


def is_born_digital(pages: list[PageData], threshold: int = MIN_TEXT_CHARS_BORN_DIGITAL) -> bool:
    """
    Kiểm tra PDF có phải born-digital hay scanned.

    Heuristic: tổng số ký tự text trên tất cả pages phải ≥ threshold.
    Nếu ít hơn → đây là scanned PDF (chỉ có hình ảnh).

    Args:
        pages: Danh sách PageData đã extract.
        threshold: Số ký tự tối thiểu để coi là born-digital.

    Returns:
        True nếu born-digital, False nếu scanned.
    """
    total_chars = sum(len(page.text) for page in pages)
    return total_chars >= threshold


def parse_font_flags(flags: int) -> dict[str, bool]:
    """
    Parse font_flags integer từ PyMuPDF thành dict các flag riêng lẻ.

    PyMuPDF font_flags bit layout:
    - Bit 0 (1):  superscript
    - Bit 1 (2):  italic
    - Bit 2 (4):  serif
    - Bit 3 (8):  monospace
    - Bit 4 (16): bold

    Args:
        flags: Integer font_flags từ PyMuPDF span.

    Returns:
        Dict với keys: superscript, italic, serif, monospace, bold.
    """
    return {
        "superscript": bool(flags & 1),
        "italic": bool(flags & 2),
        "serif": bool(flags & 4),
        "monospace": bool(flags & 8),
        "bold": bool(flags & 16),
    }


def compute_extraction_stats(doc: DocumentData) -> dict:
    """
    Tính thống kê tổng hợp cho một DocumentData.

    Args:
        doc: DocumentData đã extract.

    Returns:
        Dict chứa: total_blocks, total_lines, total_spans,
        total_chars, total_images, avg_blocks_per_page.
    """
    total_blocks = 0
    total_lines = 0
    total_spans = 0
    total_chars = 0
    total_images = 0

    for page in doc.pages:
        total_images += page.image_count
        for block in page.blocks:
            total_blocks += 1
            for line in block.lines:
                total_lines += 1
                for span in line.spans:
                    total_spans += 1
                    total_chars += len(span.text)

    avg_blocks_per_page = (
        total_blocks / len(doc.pages) if doc.pages else 0.0
    )

    return {
        "total_blocks": total_blocks,
        "total_lines": total_lines,
        "total_spans": total_spans,
        "total_chars": total_chars,
        "total_images": total_images,
        "avg_blocks_per_page": round(avg_blocks_per_page, 2),
    }


def safe_color_to_hex(color: int) -> str:
    """
    Convert integer color từ PyMuPDF sang hex string #RRGGBB.

    PyMuPDF trả về color dưới dạng integer (24-bit RGB).
    Ví dụ: 0 → #000000, 255 → #0000FF, 16711680 → #FF0000.

    Args:
        color: Integer color value từ PyMuPDF.

    Returns:
        Hex string dạng #RRGGBB.
    """
    # Đảm bảo color nằm trong range hợp lệ
    color = max(0, min(color, 0xFFFFFF))
    return f"#{color:06X}"
