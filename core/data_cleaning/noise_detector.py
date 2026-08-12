"""
core/data_cleaning/noise_detector.py
NoiseDetector -- phat hien du lieu nghi ngo/nhieu.

Tinh cac chi so:
- non_alpha_ratio: ty le ky tu khong phai alpha
- whitespace_ratio: ty le khoang trang
- newline_ratio: ty le newline
- duplicate_line_ratio: ty le dong trung lap
- symbol_ratio: ty le ky tu dac biet bat thuong

KHONG xoa du lieu. Chi flag va tra ve noise score.
"""

from __future__ import annotations

import logging
from collections import Counter

from core.data_cleaning.models import (
    NoiseResult,
    HIGH_NON_ALPHA_RATIO,
    HIGH_WHITESPACE_RATIO,
    HIGH_DUPLICATE_LINES,
    HIGH_SYMBOL_RATIO,
    POSSIBLE_GARBLED_TEXT,
    TEXT_TOO_SHORT,
)
from config.constants import (
    NOISE_NON_ALPHA_THRESHOLD,
    NOISE_WHITESPACE_THRESHOLD,
    NOISE_DUPLICATE_LINE_THRESHOLD,
    NOISE_SYMBOL_THRESHOLD,
)

logger = logging.getLogger(__name__)

# Suspicious symbols (khong phai punctuation thong thuong)
_SUSPICIOUS_CHARS = frozenset(
    "§¶†‡‖¤¦©®™°±µ¿¡"
    "□■▪▫◊●○◦★☆♦♠♣♥"
    "←→↑↓↔⇒⇔∀∃∅∈∉∩∪⊂⊃"
    "≈≠≤≥≡∞∝∑∏√∫∂∇"
)


class NoiseDetector:
    """
    Phat hien text nhieu/nghi ngo.

    Khong xoa data. Chi tra ve NoiseResult voi:
    - is_noisy: True/False
    - noise_score: [0.0, 1.0]
    - flags: danh sach van de
    - metrics: chi tiet metrics
    """

    @staticmethod
    def analyze(text: str | None) -> NoiseResult:
        """
        Phan tich mot text field de phat hien noise.

        Args:
            text: Text can phan tich. None/empty -> noise_score=0.

        Returns:
            NoiseResult voi metrics va flags.
        """
        if not text or not text.strip():
            return NoiseResult(
                is_noisy=False,
                noise_score=0.0,
                flags=[TEXT_TOO_SHORT] if text == "" else [],
                metrics={},
            )

        text_len = len(text)
        flags: list[str] = []

        # ── Metric 1: Non-alpha ratio ──
        alpha_count = sum(1 for c in text if c.isalpha())
        non_alpha_ratio = 1.0 - (alpha_count / text_len) if text_len > 0 else 0.0

        if non_alpha_ratio > NOISE_NON_ALPHA_THRESHOLD:
            flags.append(HIGH_NON_ALPHA_RATIO)

        # ── Metric 2: Whitespace ratio ──
        ws_count = sum(1 for c in text if c.isspace())
        whitespace_ratio = ws_count / text_len if text_len > 0 else 0.0

        if whitespace_ratio > NOISE_WHITESPACE_THRESHOLD:
            flags.append(HIGH_WHITESPACE_RATIO)

        # ── Metric 3: Newline ratio ──
        newline_count = text.count("\n")
        newline_ratio = newline_count / text_len if text_len > 0 else 0.0

        # ── Metric 4: Duplicate line ratio ──
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        total_lines = len(lines)
        if total_lines > 1:
            line_counts = Counter(lines)
            duplicate_lines = sum(count - 1 for count in line_counts.values() if count > 1)
            duplicate_line_ratio = duplicate_lines / total_lines
        else:
            duplicate_line_ratio = 0.0

        if duplicate_line_ratio > NOISE_DUPLICATE_LINE_THRESHOLD:
            flags.append(HIGH_DUPLICATE_LINES)

        # ── Metric 5: Suspicious symbol ratio ──
        symbol_count = sum(1 for c in text if c in _SUSPICIOUS_CHARS)
        symbol_ratio = symbol_count / text_len if text_len > 0 else 0.0

        if symbol_ratio > NOISE_SYMBOL_THRESHOLD:
            flags.append(HIGH_SYMBOL_RATIO)

        # ── Garbled text detection ──
        # Text co nhieu ky tu khong thuoc bat ky script nao
        # hoac ti le alphabetic qua thap (< 30%)
        alpha_ratio = alpha_count / text_len if text_len > 0 else 0.0
        if alpha_ratio < 0.30 and text_len > 20:
            if POSSIBLE_GARBLED_TEXT not in flags:
                flags.append(POSSIBLE_GARBLED_TEXT)

        # ── Too short ──
        if text_len < 10:
            if TEXT_TOO_SHORT not in flags:
                flags.append(TEXT_TOO_SHORT)

        # ── Compute composite noise score ──
        # Weighted average cua cac metrics
        noise_score = (
            non_alpha_ratio * 0.30
            + whitespace_ratio * 0.15
            + newline_ratio * 0.10
            + duplicate_line_ratio * 0.20
            + symbol_ratio * 0.25
        )

        is_noisy = len(flags) > 0

        metrics = {
            "non_alpha_ratio": non_alpha_ratio,
            "whitespace_ratio": whitespace_ratio,
            "newline_ratio": newline_ratio,
            "duplicate_line_ratio": duplicate_line_ratio,
            "symbol_ratio": symbol_ratio,
            "alpha_ratio": alpha_ratio,
            "text_length": float(text_len),
        }

        return NoiseResult(
            is_noisy=is_noisy,
            noise_score=min(noise_score, 1.0),
            flags=flags,
            metrics=metrics,
        )

    @staticmethod
    def analyze_authors(authors: list[str]) -> NoiseResult:
        """
        Phan tich noise cho danh sach author names.

        Gop tat ca names thanh 1 string roi analyze.
        Them check: empty list, single-char names.

        Args:
            authors: Danh sach ten tac gia.

        Returns:
            NoiseResult cho toan bo danh sach.
        """
        if not authors:
            return NoiseResult(
                is_noisy=False,
                noise_score=0.0,
                flags=[TEXT_TOO_SHORT],
                metrics={},
            )

        # Combine all names
        combined = " ; ".join(authors)
        result = NoiseDetector.analyze(combined)

        # Additional check: too many single-char names
        short_names = sum(1 for name in authors if len(name.strip()) <= 2)
        if short_names > len(authors) * 0.5 and len(authors) >= 2:
            if POSSIBLE_GARBLED_TEXT not in result.flags:
                result.flags.append(POSSIBLE_GARBLED_TEXT)
                result.is_noisy = True

        return result
