"""
core/layout_analysis/heuristics.py
Spatial + Font heuristic functions cho layout analysis.
Tái sử dụng constants từ config/constants.py, thêm patterns cho KEYWORD/REFERENCE.
"""

from __future__ import annotations

import re

from core.text_extraction.models import BlockData
from config.constants import (
    HEADER_ZONE_FRACTION,
    FOOTER_ZONE_FRACTION,
    TITLE_ZONE_FRACTION,
    ABSTRACT_START_PATTERN,
    HEADER_FOOTER_PATTERNS,
    AFFILIATION_KEYWORDS,
)


# ─────────────────────────────────────────────
# Patterns mới cho Milestone 3 (không sửa constants.py)
# ─────────────────────────────────────────────

KEYWORD_START_PATTERN = re.compile(
    r"^\s*(keywords?|từ\s*khóa|index\s*terms?)\s*[:.\-]?\s*",
    re.IGNORECASE,
)

REFERENCE_START_PATTERN = re.compile(
    r"^\s*("
    r"references?"
    r"|tài\s*liệu\s*tham\s*khảo"
    r"|bibliography"
    r"|danh\s*mục\s*tài\s*liệu"
    r")\s*[:.\-]?\s*",
    re.IGNORECASE,
)

# Block width ratio so với page width để coi là "full-width"
FULL_WIDTH_RATIO = 0.60

# Tolerance cho centered detection (fraction of page width)
CENTER_TOLERANCE_RATIO = 0.15


# ─────────────────────────────────────────────
# Font Analysis
# ─────────────────────────────────────────────

def dominant_font_size(block: BlockData) -> float:
    """
    Font size chiếm nhiều ký tự nhất trong block.

    Duyệt qua tất cả spans, đếm số ký tự theo font_size,
    trả về font_size có nhiều ký tự nhất.
    """
    size_char_count: dict[float, int] = {}
    for line in block.lines:
        for span in line.spans:
            char_count = len(span.text)
            if char_count > 0:
                size_char_count[span.font_size] = (
                    size_char_count.get(span.font_size, 0) + char_count
                )
    if not size_char_count:
        return 0.0
    return max(size_char_count, key=size_char_count.get)


def dominant_font_flags(block: BlockData) -> int:
    """
    Font flags chiếm nhiều ký tự nhất trong block.
    """
    flags_char_count: dict[int, int] = {}
    for line in block.lines:
        for span in line.spans:
            char_count = len(span.text)
            if char_count > 0:
                flags_char_count[span.font_flags] = (
                    flags_char_count.get(span.font_flags, 0) + char_count
                )
    if not flags_char_count:
        return 0
    return max(flags_char_count, key=flags_char_count.get)


def is_bold(flags: int) -> bool:
    """Kiểm tra font có bold (bit 4, value 16)."""
    return bool(flags & 16)


# ─────────────────────────────────────────────
# Spatial Analysis
# ─────────────────────────────────────────────

def block_width(block: BlockData) -> float:
    """Chiều rộng bounding box của block."""
    return block.bbox[2] - block.bbox[0]


def block_height(block: BlockData) -> float:
    """Chiều cao bounding box của block."""
    return block.bbox[3] - block.bbox[1]


def block_center_x(block: BlockData) -> float:
    """Tọa độ X trung tâm của block."""
    return (block.bbox[0] + block.bbox[2]) / 2


def block_center_y(block: BlockData) -> float:
    """Tọa độ Y trung tâm của block."""
    return (block.bbox[1] + block.bbox[3]) / 2


def is_centered(block: BlockData, page_width: float, tolerance: float = 0.0) -> bool:
    """
    Kiểm tra block có căn giữa trang không.

    Args:
        block: BlockData cần kiểm tra.
        page_width: Chiều rộng trang.
        tolerance: Khoảng chấp nhận (pixels). Nếu 0, dùng CENTER_TOLERANCE_RATIO.
    """
    if tolerance <= 0:
        tolerance = page_width * CENTER_TOLERANCE_RATIO
    page_center = page_width / 2
    center = block_center_x(block)
    return abs(center - page_center) <= tolerance


def relative_y(block: BlockData, page_height: float) -> float:
    """Vị trí Y tương đối (0.0 = top, 1.0 = bottom)."""
    if page_height <= 0:
        return 0.0
    return block.bbox[1] / page_height


def is_in_header_zone(block: BlockData, page_height: float) -> bool:
    """Block nằm trong vùng header (top 5%)."""
    return relative_y(block, page_height) < HEADER_ZONE_FRACTION


def is_in_footer_zone(block: BlockData, page_height: float) -> bool:
    """Block nằm trong vùng footer (bottom 10%)."""
    if page_height <= 0:
        return False
    return block.bbox[3] > page_height * (1 - FOOTER_ZONE_FRACTION)


def is_in_title_zone(block: BlockData, page_height: float) -> bool:
    """Block nằm trong vùng title candidate (top 35%)."""
    return relative_y(block, page_height) < TITLE_ZONE_FRACTION


def is_full_width(block: BlockData, page_width: float) -> bool:
    """Block có chiều rộng >= 60% page width."""
    return block_width(block) >= page_width * FULL_WIDTH_RATIO


# ─────────────────────────────────────────────
# Content Pattern Matching
# ─────────────────────────────────────────────

def matches_abstract_start(text: str) -> bool:
    """
    Kiểm tra text có phải keyword bắt đầu abstract.
    Hỗ trợ: "Abstract", "TÓM TẮT", "Tổng quan",
    và cả dạng chữ hoa rời "A BSTRACT" (PyMuPDF small-caps).
    """
    stripped = text.strip()
    # Exact match cho uppercase variants
    if stripped.upper() in ("ABSTRACT", "TÓM TẮT", "TỔNG QUAN"):
        return True
    # Match dạng "A BSTRACT" (small-caps rendering)
    no_space = re.sub(r"\s+", "", stripped).upper()
    if no_space == "ABSTRACT":
        return True
    # Regex pattern từ constants
    return bool(ABSTRACT_START_PATTERN.search(stripped))


def matches_keyword_start(text: str) -> bool:
    """Kiểm tra text có phải keyword section header."""
    return bool(KEYWORD_START_PATTERN.search(text.strip()))


def matches_reference_start(text: str) -> bool:
    """Kiểm tra text có phải reference section header."""
    stripped = text.strip()
    # Exact uppercase match
    if stripped.upper() in ("REFERENCES", "TÀI LIỆU THAM KHẢO", "BIBLIOGRAPHY"):
        return True
    return bool(REFERENCE_START_PATTERN.search(stripped))


def contains_affiliation(text: str) -> bool:
    """Kiểm tra text có chứa affiliation keywords."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in AFFILIATION_KEYWORDS)


def matches_header_footer(text: str) -> bool:
    """Kiểm tra text có match header/footer patterns."""
    stripped = text.strip()
    return any(p.search(stripped) for p in HEADER_FOOTER_PATTERNS)


def max_font_size_in_blocks(blocks: list[BlockData]) -> float:
    """Font size lớn nhất trong danh sách blocks."""
    if not blocks:
        return 0.0
    return max(dominant_font_size(b) for b in blocks)


# ─────────────────────────────────────────────
# Vietnamese Author Name Detection (Option C fix)
# ─────────────────────────────────────────────

# Common Vietnamese surnames (covers ~95% of Vietnamese names)
_VN_SURNAMES = (
    "Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan",
    "Vũ", "Võ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương",
    "Lý", "Đào", "Đinh", "Lương", "Trương", "Tô", "Mai",
    "Chu", "Lưu", "Tạ", "Hà", "Tăng", "Quách", "Thái",
    "Cao", "Lã", "Triệu", "Kiều",
    # Romanized variants (no diacritics - for English papers by VN authors)
    "Nguyen", "Tran", "Le", "Pham", "Hoang", "Huynh", "Phan",
    "Vu", "Vo", "Dang", "Bui", "Do", "Ho", "Ngo", "Duong",
    "Ly", "Dao", "Dinh", "Luong", "Truong", "To", "Mai",
    "Chu", "Luu", "Ta", "Ha", "Tang", "Quach", "Thai",
    "Cao", "La", "Trieu", "Kieu",
)

# Pattern: Vietnamese name with optional superscript number
# "Nguyễn Văn An1" or "Nguyễn Văn An1,2" or "Nguyễn Văn An*"
_VN_NAME_WITH_MARKER = re.compile(
    r"[A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+)+\s*[\d\*,]*"
)

# Pattern for author line: comma-separated names with superscript numbers
# "Nguyễn Văn An1, Trần Thị Bình2, Lê Hoàng Cường3"
_AUTHOR_LINE_PATTERN = re.compile(
    r"[A-ZÀ-Ỹ][a-zà-ỹ]+\s+(?:[A-ZÀ-Ỹ][a-zà-ỹ]+\s*)+[\d\*]*"
    r"(?:\s*,\s*[A-ZÀ-Ỹ][a-zà-ỹ]+\s+(?:[A-ZÀ-Ỹ][a-zà-ỹ]+\s*)+[\d\*]*)+",
)


def looks_like_author_line(text: str) -> bool:
    """
    Kiểm tra text có giống dòng tên tác giả không.

    Nhận diện pattern:
    - Nhiều tên người phân cách bằng dấu phẩy
    - Có thể kèm superscript numbers (1,2,3)
    - Chứa Vietnamese surnames
    - KHÔNG phải reference text, body text, hoặc abstract

    Args:
        text: Text cần kiểm tra.

    Returns:
        True nếu text giống dòng tên tác giả.
    """
    stripped = text.strip()
    if not stripped:
        return False

    # Skip if too short or too long
    # Author lines are typically 20-200 chars
    if len(stripped) < 10 or len(stripped) > 200:
        return False

    # Skip if starts with common non-author patterns
    lower = stripped.lower()
    skip_starts = (
        "doi:", "http", "www.", "email:", "e-mail:",
        "abstract", "tóm tắt", "mục tiêu", "đặt vấn đề",
        "keywords", "từ khóa", "tài liệu",
        "bệnh viện", "trường đại học", "khoa ", "bộ môn",
        "chịu trách nhiệm", "ngày nhận", "ngày chấp nhận",
        "kết quả", "phương pháp", "kết luận", "đối tượng",
        "background", "objective", "method", "result", "conclusion",
        "introduction", "discussion",
        "trên thế giới", "trong nghiên cứu",
        "v.", "i.", "ii.", "iii.", "iv.",
    )
    for prefix in skip_starts:
        if lower.startswith(prefix):
            return False

    # Skip if starts with digit+period (reference entry: "7. Khami MR...")
    if re.match(r"^\d+[\.\)]\s", stripped):
        return False

    # Skip if contains year citation pattern "(2020)" or "(2024)"
    if re.search(r"\(\d{4}\)", stripped):
        return False

    # Skip if contains sentence-like patterns (periods followed by space+lowercase)
    # References and body text have sentences; author lines don't
    if re.search(r"\.\s+[a-zà-ỹ]", stripped):
        return False

    # Skip if it contains too many digits (likely body text with stats)
    digit_count = sum(1 for c in stripped if c.isdigit())
    alpha_count = sum(1 for c in stripped if c.isalpha())
    if alpha_count > 0 and digit_count / alpha_count > 0.25:
        return False

    # Skip if contains common body/reference markers
    body_markers = (
        "et al", "vol.", "pp.", "issn", "isbn", "j.", "rev.",
        "journal", "study", "research", "analysis", "patient",
        "bệnh nhân", "nghiên cứu", "phẫu thuật", "điều trị",
        "phương pháp", "kỹ thuật", "tỷ lệ", "kết quả",
    )
    for marker in body_markers:
        if marker in lower:
            return False

    # Check 1: Contains Vietnamese surnames
    has_vn_surname = False
    for surname in _VN_SURNAMES:
        if surname in stripped:
            has_vn_surname = True
            break

    if not has_vn_surname:
        return False

    # Check 2: Has comma-separated pattern (multiple names)
    name_matches = _VN_NAME_WITH_MARKER.findall(stripped)

    # Calculate what fraction of text is covered by name patterns
    total_name_chars = sum(len(m) for m in name_matches)
    text_ratio = total_name_chars / len(stripped) if stripped else 0

    # Require names to cover at least 50% of the text
    if len(name_matches) >= 2 and text_ratio >= 0.50:
        return True

    # Check 3: Single name with number suffix (may be part of multi-line author)
    # Must cover most of the text
    if len(name_matches) == 1 and text_ratio >= 0.60:
        if any(c.isdigit() or c == '*' for c in stripped):
            return True

    return False

