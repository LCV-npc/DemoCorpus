"""Language preference helpers for bilingual article abstracts."""

from __future__ import annotations

import re
from collections.abc import Iterable


_VIETNAMESE_SPECIFIC_CHARS = re.compile(
    r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệ"
    r"íìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]",
    re.IGNORECASE,
)
_VIETNAMESE_COMMON_WORDS = re.compile(
    r"\b(?:và|của|các|nghiên\s+cứu|kết\s+quả|mục\s+tiêu|đối\s+tượng|"
    r"phương\s+pháp|bệnh|điều\s+trị|tỷ\s+lệ|kết\s+luận|tóm\s+tắt)\b",
    re.IGNORECASE,
)
_VIETNAMESE_ABSTRACT_HEADING = re.compile(r"\btóm\s*tắt\b\s*[:.\-]?\s*", re.IGNORECASE)
_FOLLOWING_SECTION = re.compile(
    r"\b(?:từ\s*kh(?:ó|o)[aá]|keywords?|abstract|summary)\b\s*[:.\-]?\s*",
    re.IGNORECASE,
)
_LEADING_ABSTRACT_HEADING = re.compile(
    r"^\s*(?:tóm\s*tắt|abstract|summary)\s*[:.\-]?\s*",
    re.IGNORECASE,
)


def looks_vietnamese(text: str | None) -> bool:
    """Return True when prose contains reliable Vietnamese language cues."""
    if not isinstance(text, str) or not text.strip():
        return False
    specific_chars = len(_VIETNAMESE_SPECIFIC_CHARS.findall(text))
    common_phrases = len(_VIETNAMESE_COMMON_WORDS.findall(text))
    return specific_chars >= 2 or common_phrases >= 2 or (
        specific_chars >= 1 and common_phrases >= 1
    )


def select_preferred_abstract(candidates: Iterable[str | None]) -> str:
    """Prefer the first Vietnamese abstract, otherwise the first non-empty one."""
    values = [value.strip() for value in candidates if isinstance(value, str) and value.strip()]
    for value in values:
        heading = _VIETNAMESE_ABSTRACT_HEADING.search(value)
        if heading is None:
            continue
        remainder = value[heading.end():]
        boundary = _FOLLOWING_SECTION.search(remainder)
        section = remainder[:boundary.start()] if boundary is not None else remainder
        if section.strip():
            return section.strip()

    cleaned = [_LEADING_ABSTRACT_HEADING.sub("", value, count=1).strip() for value in values]
    return next((value for value in cleaned if looks_vietnamese(value)), cleaned[0] if cleaned else "")
