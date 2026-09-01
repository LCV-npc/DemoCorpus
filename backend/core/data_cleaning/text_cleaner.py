"""
core/data_cleaning/text_cleaner.py
TextCleaner -- shared text cleaning utilities.

Pipeline:
1. Control character removal
2. Character substitution (ligatures, smart quotes, etc.)
3. Unicode normalization (NFC)
4. Whitespace normalization
5. Hyphenation repair

KHONG lam mat dau tieng Viet.
KHONG paraphrase, dich, hoac thay doi noi dung.
"""

from __future__ import annotations

import html
import re
import unicodedata

from config.constants import CHAR_SUBSTITUTION_MAP


# ─────────────────────────────────────────────
# Control character pattern
# Giu lai: \n, \r, \t (xu ly rieng o whitespace step)
# Xoa tat ca control chars khac (C0, C1, DEL, etc.)
# ─────────────────────────────────────────────
_CONTROL_CHAR_PATTERN = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"
)

# ─────────────────────────────────────────────
# Hyphenation repair
# Chi repair khi: word-\nword (lowercase tiep sau newline)
# KHONG repair: state-of-the-art, well-known, co-author
# ─────────────────────────────────────────────
_HYPHEN_LINEBREAK_PATTERN = re.compile(
    r"(\w)- *\n *(\w)"
)

# Multi-space pattern
_MULTI_SPACE = re.compile(r"[ \t]+")

# Excessive blank lines (3+ newlines -> 2)
_EXCESSIVE_NEWLINES = re.compile(r"\n{3,}")

# Decode only complete HTML entities. The explicit guard avoids changing
# ordinary medical text containing a literal ampersand, such as "AT&T".
_HTML_ENTITY_PATTERN = re.compile(
    r"&(?:#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});"
)

# Common compound word prefixes/suffixes that should NOT be dehyphenated
_COMPOUND_PREFIXES = frozenset({
    "self", "non", "pre", "post", "anti", "co", "re", "sub",
    "inter", "intra", "multi", "cross", "semi", "over", "under",
    "well", "ill", "full", "half", "high", "low", "long", "short",
    "single", "double", "triple", "state", "real", "large", "small",
    "fine", "broad", "deep", "first", "second", "third",
})

_COMPOUND_SUFFIXES = frozenset({
    "art", "based", "level", "scale", "term", "time", "type",
    "like", "free", "wise", "related", "specific", "driven",
    "aware", "oriented", "focused", "known", "defined",
})


class TextCleaner:
    """
    Shared text cleaning utilities.

    Stateless -- tat ca methods la static hoac stateless.
    An toan cho Vietnamese text (preserve diacritics).
    """

    @staticmethod
    def decode_html_entities(text: str) -> str:
        """Decode single or repeatedly encoded HTML entities safely."""
        if not text:
            return ""

        result = text
        # OJS metadata may contain ``&amp;ecirc;``. BeautifulSoup decodes
        # the outer ``&amp;`` and leaves ``&ecirc;``, so allow a small,
        # bounded number of passes until the value stabilizes.
        for _ in range(3):
            if not _HTML_ENTITY_PATTERN.search(result):
                break
            decoded = html.unescape(result)
            if decoded == result:
                break
            result = decoded
        return result

    @staticmethod
    def remove_control_chars(text: str) -> str:
        """
        Xoa control characters, giu lai newline/tab.

        Args:
            text: Raw text.

        Returns:
            Text da loai bo control chars.
        """
        if not text:
            return ""
        return _CONTROL_CHAR_PATTERN.sub("", text)

    @staticmethod
    def apply_char_substitution(text: str) -> str:
        """
        Ap dung CHAR_SUBSTITUTION_MAP tu constants.py.

        Xu ly: ligatures (fi, fl, ff, ffi, ffl),
        smart quotes, en/em dash, ellipsis, NBSP.

        Args:
            text: Text can thay the.

        Returns:
            Text da substitute.
        """
        if not text:
            return ""
        result = text
        for old_char, new_char in CHAR_SUBSTITUTION_MAP.items():
            result = result.replace(old_char, new_char)
        return result

    @staticmethod
    def normalize_unicode(text: str) -> str:
        """
        Unicode normalization bang NFC.

        NFC (Composed) la chuan cho web va database.
        Dac biet quan trong voi tieng Viet:
        - Composed: a(breve)(acute) = U+1EAF (1 codepoint)
        - Decomposed: a + breve + acute = 3 codepoints
        NFC dam bao 2 chuoi tuong duong duoc chuyen ve cung 1 dang.

        Args:
            text: Text can normalize.

        Returns:
            NFC-normalized text.
        """
        if not text:
            return ""
        return unicodedata.normalize("NFC", text)

    @staticmethod
    def normalize_whitespace(text: str, preserve_paragraphs: bool = False) -> str:
        """
        Normalize whitespace: collapse spaces, tabs, blank lines.

        Args:
            text: Text can normalize.
            preserve_paragraphs: Neu True, giu lai double newlines
                (paragraph breaks). Neu False, replace tat ca newlines
                bang single space.

        Returns:
            Whitespace-normalized text.
        """
        if not text:
            return ""

        if preserve_paragraphs:
            # Collapse 3+ newlines -> 2
            result = _EXCESSIVE_NEWLINES.sub("\n\n", text)
            # Normalize whitespace within each line (spaces, tabs -> single space)
            lines = result.split("\n")
            cleaned_lines = []
            for line in lines:
                cleaned_line = _MULTI_SPACE.sub(" ", line).strip()
                cleaned_lines.append(cleaned_line)
            result = "\n".join(cleaned_lines)
        else:
            # Replace all newlines with space first
            result = text.replace("\n", " ").replace("\r", " ")
            # Collapse multiple spaces/tabs into single space
            result = _MULTI_SPACE.sub(" ", result)

        return result.strip()

    @staticmethod
    def repair_hyphenation(text: str) -> str:
        """
        Sua tu bi ngat bang dau gach noi cuoi dong.

        "transfor-\\nmation" -> "transformation"
        "infor-\\nmation" -> "information"

        KHONG sua compound words hop le:
        "state-of-the-art" (khong co newline)
        "well-\\nknown" -> giu "well-known" (la compound word)

        Logic an toan:
        1. Chi xu ly khi co pattern: word-\\nword
        2. Kiem tra phan truoc dau gach noi co phai compound prefix khong
        3. Kiem tra phan sau co phai compound suffix khong
        4. Neu la compound -> giu dau gach noi, chi xoa newline
        5. Neu khong phai compound -> noi tu, xoa ca gach noi va newline

        Args:
            text: Text co the chua hyphenated words.

        Returns:
            Text da repair hyphenation.
        """
        if not text:
            return ""

        def _replace_hyphen(match: re.Match) -> str:
            before_char = match.group(1)  # last char of word before hyphen
            after_char = match.group(2)   # first char of word after hyphen

            # Lay full word truoc va sau hyphen de check compound
            full_match_str = match.group(0)

            # Tim word truoc hyphen
            start = match.start()
            text_before = text[:start]
            # Tim word boundary
            word_before_match = re.search(r"(\w+)$", text_before + before_char)
            word_before = word_before_match.group(1).lower() if word_before_match else ""

            # Tim word sau hyphen
            end = match.end()
            text_after = after_char + text[end:]
            word_after_match = re.match(r"(\w+)", text_after)
            word_after = word_after_match.group(1).lower() if word_after_match else ""

            # Check compound word
            if word_before in _COMPOUND_PREFIXES or word_after in _COMPOUND_SUFFIXES:
                # Giu hyphen, chi xoa newline
                return f"{before_char}-{after_char}"

            # Khong phai compound -> noi tu
            return f"{before_char}{after_char}"

        return _HYPHEN_LINEBREAK_PATTERN.sub(_replace_hyphen, text)

    @classmethod
    def full_clean(
        cls,
        text: str,
        preserve_paragraphs: bool = False,
    ) -> tuple[str, list[str]]:
        """
        Full cleaning pipeline: HTML entities -> control chars -> substitution
        -> unicode -> hyphenation -> whitespace.

        Args:
            text: Raw text.
            preserve_paragraphs: Giu paragraph breaks (cho abstract).

        Returns:
            (cleaned_text, list_of_changes) -- text da clean va danh sach
            cac thay doi da thuc hien.
        """
        if not text:
            return "", []

        changes: list[str] = []
        result = text

        # Step 1: HTML entities from web/citation metadata
        cleaned = cls.decode_html_entities(result)
        if cleaned != result:
            changes.append("html_entities_decoded")
        result = cleaned

        # Step 2: Control chars
        cleaned = cls.remove_control_chars(result)
        if cleaned != result:
            changes.append("control_chars_removed")
        result = cleaned

        # Step 3: Character substitution
        cleaned = cls.apply_char_substitution(result)
        if cleaned != result:
            changes.append("chars_substituted")
        result = cleaned

        # Step 4: Unicode normalization
        cleaned = cls.normalize_unicode(result)
        if cleaned != result:
            changes.append("unicode_normalized")
        result = cleaned

        # Step 5: Hyphenation repair
        cleaned = cls.repair_hyphenation(result)
        if cleaned != result:
            changes.append("hyphenation_repaired")
        result = cleaned

        # Step 6: Whitespace normalization
        cleaned = cls.normalize_whitespace(result, preserve_paragraphs=preserve_paragraphs)
        if cleaned != result:
            changes.append("whitespace_normalized")
        result = cleaned

        return result, changes
