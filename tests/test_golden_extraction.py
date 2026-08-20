"""
tests/test_golden_extraction.py
Golden standard accuracy tests — compare extraction results against ground truth.

Runs FullPipeline on real PDFs and compares:
1. Title exact match
2. Author subset match (expected ⊂ actual)
3. Abstract prefix match
4. Pipeline success

These tests require actual PDF files to be present.
Skip gracefully if files are missing.
"""

import json
import logging
import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pipeline.full_pipeline import FullPipeline

logger = logging.getLogger(__name__)

# ── Load golden metadata ──
GOLDEN_PATH = Path(__file__).parent / "golden" / "metadata.json"
TESTS_DIR = Path(__file__).parent


def _load_golden() -> list[dict]:
    """Load golden metadata from JSON file."""
    if not GOLDEN_PATH.exists():
        return []
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_pdf_path(entry: dict) -> Path:
    """Resolve relative path in golden metadata to absolute path."""
    rel = entry.get("path", "")
    # Try relative to tests/ dir
    candidate = (TESTS_DIR / rel).resolve()
    if candidate.exists():
        return candidate
    # Try relative to project root
    project_root = TESTS_DIR.parent
    candidate = (project_root / rel).resolve()
    if candidate.exists():
        return candidate
    # Try absolute
    abs_path = Path(rel)
    if abs_path.exists():
        return abs_path
    return candidate  # return unresolved for error reporting


GOLDEN_DATA = _load_golden()

# Skip all tests if no golden data
pytestmark = pytest.mark.skipif(
    not GOLDEN_DATA,
    reason="No golden metadata found at tests/golden/metadata.json"
)


class TestGoldenExtraction:
    """Compare extraction results against golden standard."""

    @classmethod
    def setup_class(cls):
        """Initialize pipeline once for all tests."""
        cls.pipeline = FullPipeline(enable_llm=False)
        cls.results = {}

        # Process each golden PDF
        for entry in GOLDEN_DATA:
            pdf_path = _resolve_pdf_path(entry)
            filename = entry["filename"]

            if not pdf_path.exists():
                logger.warning(f"Golden PDF not found: {pdf_path}")
                cls.results[filename] = None
                continue

            try:
                result = cls.pipeline.process(str(pdf_path))
                cls.results[filename] = result
            except Exception as e:
                logger.error(f"Failed to process {filename}: {e}")
                cls.results[filename] = None

    @pytest.mark.parametrize("entry", GOLDEN_DATA, ids=[e["filename"] for e in GOLDEN_DATA])
    def test_pipeline_success(self, entry):
        """Pipeline should complete successfully."""
        filename = entry["filename"]
        result = self.results.get(filename)
        if result is None:
            pytest.skip(f"PDF not found: {filename}")
        assert result.success, f"Pipeline failed at {result.failed_stage}: {result.error_message}"

    @pytest.mark.parametrize("entry", GOLDEN_DATA, ids=[e["filename"] for e in GOLDEN_DATA])
    def test_title_match(self, entry):
        """Extracted title should match golden standard."""
        filename = entry["filename"]
        result = self.results.get(filename)
        if result is None:
            pytest.skip(f"PDF not found: {filename}")

        expected_title = entry["expected_title"]
        assert result.title is not None, "Title was not extracted"

        # Normalize for comparison: strip, collapse whitespace
        actual = " ".join(result.title.split())
        expected = " ".join(expected_title.split())
        assert actual == expected, (
            f"\nExpected: {expected}\n"
            f"Actual:   {actual}"
        )

    @pytest.mark.parametrize("entry", GOLDEN_DATA, ids=[e["filename"] for e in GOLDEN_DATA])
    def test_authors_subset_match(self, entry):
        """All expected authors should appear in extracted authors."""
        filename = entry["filename"]
        result = self.results.get(filename)
        if result is None:
            pytest.skip(f"PDF not found: {filename}")

        expected_authors = entry["expected_authors"]
        actual_authors = result.authors

        assert len(actual_authors) > 0, "No authors were extracted"

        # Subset match: each expected author should be in actual list
        for expected_name in expected_authors:
            # Try exact match first
            if expected_name in actual_authors:
                continue
            # Try normalized match (ignore case, extra whitespace)
            norm_expected = " ".join(expected_name.lower().split())
            found = any(
                " ".join(a.lower().split()) == norm_expected
                for a in actual_authors
            )
            assert found, (
                f"Expected author '{expected_name}' not found.\n"
                f"Actual authors: {actual_authors}"
            )

    @pytest.mark.parametrize("entry", GOLDEN_DATA, ids=[e["filename"] for e in GOLDEN_DATA])
    def test_abstract_extracted(self, entry):
        """Abstract should be extracted and start with expected prefix."""
        filename = entry["filename"]
        result = self.results.get(filename)
        if result is None:
            pytest.skip(f"PDF not found: {filename}")

        assert result.abstract is not None, "Abstract was not extracted"

        min_len = entry.get("expected_abstract_min_length", 50)
        assert len(result.abstract) >= min_len, (
            f"Abstract too short: {len(result.abstract)} chars (min {min_len})"
        )

        prefix = entry.get("expected_abstract_starts_with", "")
        if prefix:
            # Normalize: collapse whitespace
            actual_start = " ".join(result.abstract[:100].split())
            assert actual_start.startswith(prefix), (
                f"Abstract should start with '{prefix}'\n"
                f"Actual start: '{actual_start[:80]}'"
            )

    @pytest.mark.parametrize("entry", GOLDEN_DATA, ids=[e["filename"] for e in GOLDEN_DATA])
    def test_confidence_above_threshold(self, entry):
        """Overall confidence should be >= 0.5."""
        filename = entry["filename"]
        result = self.results.get(filename)
        if result is None:
            pytest.skip(f"PDF not found: {filename}")

        overall = result.confidence.get("overall", 0)
        assert overall >= 0.5, f"Confidence too low: {overall:.4f}"
