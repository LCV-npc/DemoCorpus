"""
core/data_cleaning/service.py
DataCleaningService -- orchestrator cho Data Cleaning pipeline (Milestone 7).

Pipeline:
1. Clean title -> TitleCleaner
2. Clean authors -> MetadataAuthorCleaner
3. Clean abstract -> AbstractCleaner
4. Detect noise -> NoiseDetector
5. Return CleaningResult

Input: raw title, authors, abstract tu M4/M5/M6.
Output: CleaningResult voi cleaned fields + noise analysis.
"""

from __future__ import annotations

import logging
import time

from core.data_cleaning.models import CleaningResult
from core.data_cleaning.text_cleaner import TextCleaner
from core.data_cleaning.title_cleaner import TitleCleaner
from core.data_cleaning.author_cleaner import MetadataAuthorCleaner
from core.data_cleaning.abstract_cleaner import AbstractCleaner
from core.data_cleaning.noise_detector import NoiseDetector

logger = logging.getLogger(__name__)


class DataCleaningService:
    """
    Orchestrator cho Data Cleaning pipeline.

    Nhan raw metadata tu M4/M5/M6,
    ap dung cleaning + noise detection,
    tra ve CleaningResult.
    """

    def __init__(self):
        logger.info("DataCleaningService initialized")

    def clean(
        self,
        title: str | None = None,
        authors: list[str] | None = None,
        abstract: str | None = None,
    ) -> CleaningResult:
        """
        Full cleaning pipeline.

        Args:
            title: Raw title tu TitleResult.title (M4).
            authors: Raw author names tu AuthorResult.author_names (M5).
            abstract: Raw abstract tu AbstractResult.text (M6).

        Returns:
            CleaningResult voi cleaned data + noise scores.
        """
        start_time = time.time()
        all_changes: list[str] = []
        all_flags: list[str] = []

        if authors is None:
            authors = []

        # ── Step 1: Clean Title ──
        cleaned_title, title_changes = TitleCleaner.clean(title)
        all_changes.extend([f"title: {c}" for c in title_changes])

        # ── Step 2: Clean Authors ──
        cleaned_authors, author_changes = MetadataAuthorCleaner.clean_all(authors)
        all_changes.extend([f"author: {c}" for c in author_changes])

        # ── Step 3: Clean Abstract ──
        cleaned_abstract, abstract_changes = AbstractCleaner.clean(abstract)
        all_changes.extend([f"abstract: {c}" for c in abstract_changes])

        # ── Step 4: Noise Detection ──
        title_noise = NoiseDetector.analyze(cleaned_title)
        author_noise = NoiseDetector.analyze_authors(cleaned_authors)
        abstract_noise = NoiseDetector.analyze(cleaned_abstract)

        # Collect all flags
        all_flags.extend([f"title_noise: {f}" for f in title_noise.flags])
        all_flags.extend([f"author_noise: {f}" for f in author_noise.flags])
        all_flags.extend([f"abstract_noise: {f}" for f in abstract_noise.flags])

        elapsed = time.time() - start_time

        result = CleaningResult(
            title=cleaned_title,
            authors=cleaned_authors,
            abstract=cleaned_abstract,
            cleaning_flags=all_flags,
            changes_made=all_changes,
            title_noise=title_noise,
            author_noise=author_noise,
            abstract_noise=abstract_noise,
        )

        # Log summary
        logger.info(
            f"Cleaning complete: "
            f"title={'OK' if cleaned_title else 'None'}, "
            f"authors={len(cleaned_authors)}, "
            f"abstract={'OK' if cleaned_abstract else 'None'}, "
            f"changes={len(all_changes)}, "
            f"noise_score={result.overall_noise_score:.4f}, "
            f"time={elapsed:.3f}s"
        )

        return result
