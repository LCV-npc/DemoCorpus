"""
core/title_detection/rules.py
Plausibility rules, noise patterns, và scoring constants cho title detection.

Tách riêng logic quy tắc ra khỏi scorer và detector
để dễ maintain, test, và tái sử dụng.
"""

from __future__ import annotations

import re

from config.constants import HEADER_FOOTER_PATTERNS


# ─────────────────────────────────────────────
# Scoring Weights — trọng số cho từng feature
# ─────────────────────────────────────────────

WEIGHT_FONT_SIZE = 2.0
WEIGHT_BOLD = 1.0
WEIGHT_FONT_FAMILY = 0.5
WEIGHT_POSITION = 1.5
WEIGHT_CENTER_ALIGNMENT = 1.0
WEIGHT_AUTHOR_PROXIMITY = 0.5
WEIGHT_ABSTRACT_PROXIMITY = 0.5
WEIGHT_LINE_COUNT = 0.5
WEIGHT_TITLE_LENGTH = 1.0
WEIGHT_CAPITALIZATION = 0.5

# Tổng trọng số tối đa (dùng để normalize confidence)
MAX_TOTAL_SCORE = (
    WEIGHT_FONT_SIZE
    + WEIGHT_BOLD
    + WEIGHT_FONT_FAMILY
    + WEIGHT_POSITION
    + WEIGHT_CENTER_ALIGNMENT
    + WEIGHT_AUTHOR_PROXIMITY
    + WEIGHT_ABSTRACT_PROXIMITY
    + WEIGHT_LINE_COUNT
    + WEIGHT_TITLE_LENGTH
    + WEIGHT_CAPITALIZATION
)

# ─────────────────────────────────────────────
# Title Plausibility Thresholds
# ─────────────────────────────────────────────

MIN_TITLE_LENGTH = 5
MAX_TITLE_LENGTH = 350
IDEAL_MIN_TITLE_LENGTH = 10
IDEAL_MAX_TITLE_LENGTH = 200

MIN_LINE_COUNT = 1
MAX_IDEAL_LINE_COUNT = 3
MAX_ACCEPTABLE_LINE_COUNT = 5

# ─────────────────────────────────────────────
# Position Thresholds
# ─────────────────────────────────────────────

TITLE_ZONE_MAX_Y = 0.35          # Title phải nằm trong top 35% trang
AUTHOR_PROXIMITY_THRESHOLD = 80.0  # pixels (khoảng cách tối đa đến author)

# ─────────────────────────────────────────────
# Confidence thresholds theo strategy
# ─────────────────────────────────────────────

CONFIDENCE_ZONE_MIN = 0.85
CONFIDENCE_ZONE_MAX = 0.98
CONFIDENCE_FONT_MIN = 0.60
CONFIDENCE_FONT_MAX = 0.85
CONFIDENCE_FIRST_LINE_MIN = 0.30
CONFIDENCE_FIRST_LINE_MAX = 0.55

# ─────────────────────────────────────────────
# Noise Patterns — text không phải title
# ─────────────────────────────────────────────

NOISE_PATTERNS = [
    re.compile(r"doi\s*:\s*10\.\d{4,}", re.IGNORECASE),
    re.compile(r"©\s*\d{4}"),
    re.compile(r"^\s*\d+\s*$"),                          # Page numbers
    re.compile(r"vol\.\s*\d+", re.IGNORECASE),
    re.compile(r"issn\s*[\d\-]+", re.IGNORECASE),
    re.compile(r"received\s*:?\s*\d{1,2}", re.IGNORECASE),
    re.compile(r"accepted\s*:?\s*\d{1,2}", re.IGNORECASE),
    re.compile(r"published\s*:?\s*\d{1,2}", re.IGNORECASE),
    re.compile(r"arxiv:\s*\d+\.\d+", re.IGNORECASE),
    re.compile(r"proceedings\s+of\s+the", re.IGNORECASE),
    re.compile(r"journal\s+of\s+", re.IGNORECASE),
    re.compile(r"^https?://", re.IGNORECASE),
    re.compile(r"^\s*preprint\s*$", re.IGNORECASE),
]

# Font families thường dùng cho title (sans-serif ưu tiên)
TITLE_FONT_FAMILIES = [
    "arial", "helvetica", "calibri", "verdana", "tahoma",
    "opensans", "roboto", "lato", "sourcesans", "noto",
    "nimbus", "freesans", "dejavusans",
]


# ─────────────────────────────────────────────
# Rule Functions
# ─────────────────────────────────────────────

def is_plausible_title(text: str) -> bool:
    """
    Kiểm tra text có thể là title hợp lệ hay không.

    Tiêu chí:
    - Độ dài [5, 350] ký tự
    - Không phải pure digits
    - Không match noise patterns
    - Có ít nhất 1 ký tự alphabetic

    Args:
        text: Text candidate.

    Returns:
        True nếu text có thể là title.
    """
    stripped = text.strip()

    # Kiểm tra độ dài
    if len(stripped) < MIN_TITLE_LENGTH or len(stripped) > MAX_TITLE_LENGTH:
        return False

    # Không phải pure digits
    if stripped.isdigit():
        return False

    # Phải có ít nhất 1 ký tự alphabetic
    if not any(c.isalpha() for c in stripped):
        return False

    # Không match noise patterns
    if is_noise(stripped):
        return False

    return True


def is_noise(text: str) -> bool:
    """
    Kiểm tra text có phải noise (DOI, ©, page numbers, etc.).

    Args:
        text: Text cần kiểm tra.

    Returns:
        True nếu text là noise.
    """
    stripped = text.strip()

    # Kiểm tra NOISE_PATTERNS nội bộ
    for pattern in NOISE_PATTERNS:
        if pattern.search(stripped):
            return True

    # Kiểm tra HEADER_FOOTER_PATTERNS từ constants
    for pattern in HEADER_FOOTER_PATTERNS:
        if pattern.search(stripped):
            return True

    return False


def is_title_case(text: str) -> bool:
    """
    Kiểm tra text có viết dạng Title Case.

    Heuristic: ≥ 60% từ có chữ cái đầu viết hoa
    (bỏ qua stop words ngắn như 'a', 'the', 'of', 'and', ...).

    Args:
        text: Text cần kiểm tra.

    Returns:
        True nếu text ở dạng Title Case.
    """
    stop_words = {"a", "an", "the", "of", "in", "on", "at", "to", "for",
                  "and", "or", "but", "with", "by", "from", "is", "are",
                  "was", "were", "be", "been", "via", "vs"}

    words = text.split()
    if not words:
        return False

    capitalized = 0
    total = 0

    for i, word in enumerate(words):
        # Bỏ qua stop words (trừ từ đầu tiên)
        clean_word = word.strip(".,;:!?()[]\"'-")
        if i > 0 and clean_word.lower() in stop_words:
            continue

        if not clean_word or not clean_word[0].isalpha():
            continue

        total += 1
        if clean_word[0].isupper():
            capitalized += 1

    if total == 0:
        return False

    return (capitalized / total) >= 0.60


def is_all_upper(text: str) -> bool:
    """
    Kiểm tra text có viết HOA TOÀN BỘ.

    Chỉ xét ký tự alphabetic. Yêu cầu ≥ 80% ký tự alpha là uppercase.

    Args:
        text: Text cần kiểm tra.

    Returns:
        True nếu text ở dạng ALL CAPS.
    """
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return False

    upper_count = sum(1 for c in alpha_chars if c.isupper())
    return (upper_count / len(alpha_chars)) >= 0.80
