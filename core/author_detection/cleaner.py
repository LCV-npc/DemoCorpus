"""
core/author_detection/cleaner.py
AuthorCleaner — tách, làm sạch, lọc, và deduplicate tên tác giả.

Pipeline:
1. Remove emails
2. Remove ORCID IDs
3. Remove bracket/parenthesis content (affiliations)
4. Split trên separators (, ; · and &)
5. Clean mỗi tên (footnote markers, superscripts, symbols)
6. Filter (≥2 tokens, ≤80 chars, has alpha, digit_ratio < 0.4)
7. Deduplicate (case-insensitive)
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Regex patterns cho cleaning
# ─────────────────────────────────────────────

# Email pattern
_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)

# ORCID pattern (0000-0001-2345-6789)
_ORCID_PATTERN = re.compile(
    r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]",
)

# Bracket content: (...), [...], {...}
_BRACKET_PATTERN = re.compile(
    r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}",
)

# Footnote markers: superscript digits, *, †, ‡, §, ¶, ‖, #
_FOOTNOTE_PATTERN = re.compile(
    r"[¹²³⁴⁵⁶⁷⁸⁹⁰ᵃᵇᶜᵈᵉ*†‡§¶‖#]+",
)

# Superscript digits as regular digits after name
_SUPERSCRIPT_DIGIT_PATTERN = re.compile(
    r"(?<=\w)\s*[0-9]+(?:\s*[,;]\s*[0-9]+)*\s*$",
)

# Separator patterns cho splitting
_SEPARATOR_PATTERN = re.compile(
    r"""
    \s*;\s*              # semicolons
    |\s*·\s*             # middle dot
    |\s*\band\b\s*       # "and" (word boundary)
    |\s*&\s*             # ampersand
    |\s*,\s*(?!Jr|Sr|II|III|IV)  # comma (nhưng không split "Jr," "Sr,")
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Leading/trailing noise characters
_NOISE_CHARS = re.compile(r"^[\s,;·&*†‡§¶‖#\-]+|[\s,;·&*†‡§¶‖#\-]+$")

# Multiple whitespace
_MULTI_SPACE = re.compile(r"\s+")

# Affiliation keywords — nếu name chứa → không phải tên người
_AFFILIATION_KEYWORDS = [
    "university", "institute", "department", "faculty", "school",
    "college", "laboratory", "hospital", "research center", "centre",
    "đại học", "viện", "khoa", "bộ môn", "trường", "bệnh viện",
    "trung tâm", "phòng thí nghiệm", "corresponding author",
    "email", "e-mail", "abstract", "keywords",
]


class AuthorCleaner:
    """
    Tách, làm sạch, lọc, và deduplicate tên tác giả.

    Stateless — tất cả methods đều có thể gọi độc lập.
    """

    def split_and_clean(self, raw: str) -> list[str]:
        """
        Pipeline đầy đủ: raw text → danh sách tên sạch.

        Args:
            raw: Text thô chứa tên tác giả (có thể lẫn email,
                 affiliations, footnote markers).

        Returns:
            Danh sách tên đã clean, filter, và deduplicate.
        """
        if not raw or not raw.strip():
            return []

        # Step 1-3: Remove noise elements
        text = self._remove_emails(raw)
        text = self._remove_orcid(text)
        text = self._remove_brackets(text)

        # Step 4: Split trên separators
        parts = _SEPARATOR_PATTERN.split(text)

        # Step 5: Clean mỗi tên
        cleaned: list[str] = []
        for part in parts:
            name = self.clean_name(part)
            if name:
                cleaned.append(name)

        # Step 6-7: Filter và deduplicate
        return self.filter_names(cleaned)

    def extract_emails(self, text: str) -> list[str]:
        """
        Trích xuất tất cả email addresses từ text.

        Args:
            text: Text có thể chứa emails.

        Returns:
            Danh sách email addresses.
        """
        return _EMAIL_PATTERN.findall(text)

    def clean_name(self, name: str) -> str:
        """
        Làm sạch một tên tác giả.

        Loại bỏ: footnote markers, superscript digits,
        leading/trailing noise, normalize whitespace.

        Args:
            name: Tên thô.

        Returns:
            Tên đã clean, hoặc empty string nếu không hợp lệ.
        """
        if not name:
            return ""

        result = name

        # Remove footnote markers (¹²³*†‡§)
        result = _FOOTNOTE_PATTERN.sub("", result)

        # Remove trailing superscript digits ("John Doe1,2")
        result = _SUPERSCRIPT_DIGIT_PATTERN.sub("", result)

        # Remove leading/trailing noise chars
        result = _NOISE_CHARS.sub("", result)

        # Normalize whitespace
        result = _MULTI_SPACE.sub(" ", result).strip()

        return result

    def filter_names(self, names: list[str]) -> list[str]:
        """
        Lọc và deduplicate danh sách tên.

        Tiêu chí filter:
        - ≥ 2 tokens (1 từ thường không phải tên đầy đủ)
        - ≤ 80 chars
        - Có ít nhất 1 ký tự alphabetic
        - digit_ratio < 0.4 (không phải mã số)
        - Không chứa affiliation keywords
        - Deduplicate case-insensitive

        Args:
            names: Danh sách tên đã clean.

        Returns:
            Danh sách tên đã filter và deduplicate.
        """
        filtered: list[str] = []
        seen_lower: set[str] = set()

        for name in names:
            if not self._has_valid_structure(name):
                continue

            # Deduplicate (case-insensitive)
            name_lower = name.lower()
            if name_lower in seen_lower:
                continue
            seen_lower.add(name_lower)

            filtered.append(name)

        return filtered

    # ── Private helpers ──

    @staticmethod
    def _remove_emails(text: str) -> str:
        """Loại bỏ email addresses."""
        return _EMAIL_PATTERN.sub("", text)

    @staticmethod
    def _remove_orcid(text: str) -> str:
        """Loại bỏ ORCID IDs."""
        return _ORCID_PATTERN.sub("", text)

    @staticmethod
    def _remove_brackets(text: str) -> str:
        """Loại bỏ nội dung trong ngoặc (affiliations)."""
        return _BRACKET_PATTERN.sub("", text)

    @staticmethod
    def _has_valid_structure(name: str) -> bool:
        """
        Kiểm tra tên có cấu trúc hợp lệ.

        Args:
            name: Tên đã clean.

        Returns:
            True nếu tên hợp lệ.
        """
        # Phải có text
        if not name or not name.strip():
            return False

        # ≤ 80 chars
        if len(name) > 80:
            return False

        # ≥ 2 tokens
        tokens = name.split()
        if len(tokens) < 2:
            return False

        # Phải có ít nhất 1 ký tự alphabetic
        if not any(c.isalpha() for c in name):
            return False

        # digit_ratio < 0.4
        total_chars = len(name.replace(" ", ""))
        if total_chars > 0:
            digit_count = sum(1 for c in name if c.isdigit())
            if digit_count / total_chars >= 0.4:
                return False

        # Không chứa affiliation keywords
        name_lower = name.lower()
        for kw in _AFFILIATION_KEYWORDS:
            if kw in name_lower:
                return False

        return True
