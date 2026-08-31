"""
core/pipeline/full_pipeline.py
End-to-end PDF processing pipeline — Orchestrates M1 through M9.

Input: PDF file path (local or scraped).
Output: dict with all extracted metadata, validation, and scores.

This module solves the critical gap identified in the system audit:
Previously, M2–M9 only existed in demo scripts. This orchestrator
connects them into a single callable pipeline.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.text_extraction.extractor import PDFTextExtractor
from core.layout_analysis.layout_analyzer import LayoutAnalyzer
from core.title_detection.service import TitleDetectionService
from core.author_detection.service import AuthorDetectionService
from core.abstract_detection.service import AbstractDetectionService
from core.data_cleaning.service import DataCleaningService
from core.validators.validation_engine import ValidationEngine
from core.validators.llm_validator import LLMValidator
from infrastructure.nlp.llm_loader import load_llm
from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """
    Result of the full extraction pipeline.

    Contains all extracted metadata, validation scores,
    and per-stage status for error analysis.
    """

    # Source info
    file_path: str = ""
    source_url: str = ""
    pdf_url: str = ""

    # Extracted fields
    title: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    abstract: Optional[str] = None

    # Validation
    validation: dict = field(default_factory=dict)
    confidence: dict = field(default_factory=dict)

    # Pipeline tracking
    success: bool = False
    failed_stage: str = ""
    error_message: str = ""
    stages_completed: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict:
        """Serialize for JSON output / MongoDB storage."""
        return {
            "file_path": self.file_path,
            "source_url": self.source_url,
            "pdf_url": self.pdf_url,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "validation": self.validation,
            "confidence": self.confidence,
            "success": self.success,
            "failed_stage": self.failed_stage,
            "error_message": self.error_message,
            "stages_completed": self.stages_completed,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }


class FullPipeline:
    """
    End-to-end PDF processing: M2 → M3 → M4 → M5 → M6 → M7 → M8 → M9.

    Usage:
        pipeline = FullPipeline()
        result = pipeline.process("path/to/paper.pdf")
        print(result.title, result.authors, result.abstract)

    Error handling:
        - Each stage is wrapped in try/except.
        - On failure: logs error, records failed_stage, returns partial result.
        - Pipeline does NOT crash on any single stage failure.
    """

    def __init__(self, enable_llm: bool = True):
        """
        Initialize pipeline with all services.

        Args:
            enable_llm: If True, attempt to load LLM for M9 enhancement.
                        If False or LLM unavailable, M9 is skipped gracefully.
        """
        self._extractor = PDFTextExtractor()
        self._layout_analyzer = LayoutAnalyzer()
        self._title_service = TitleDetectionService()
        self._author_service = AuthorDetectionService()
        self._abstract_service = AbstractDetectionService()
        self._cleaning_service = DataCleaningService()
        self._validation_engine = ValidationEngine()

        # LLM (optional)
        self._llm_validator = None
        if enable_llm:
            try:
                llm = load_llm()
                if llm is not None:
                    self._llm_validator = LLMValidator(
                        llm_model=llm,
                        validate_all_fields=settings.LLM_VALIDATE_ALL_FIELDS,
                    )
                    logger.info("FullPipeline: LLM enhancement enabled")
                else:
                    logger.info("FullPipeline: No LLM available, M9 skipped")
            except Exception as e:
                logger.warning(f"FullPipeline: LLM init failed: {e}")

        logger.info("FullPipeline initialized")

    def process(
        self,
        file_path: str,
        source_url: str = "",
        pdf_url: str = "",
    ) -> PipelineResult:
        """
        Run full extraction pipeline on a PDF file.

        Args:
            file_path: Absolute path to PDF file.
            source_url: Original website URL (for provenance).
            pdf_url: Direct PDF URL (for provenance).

        Returns:
            PipelineResult with all extracted data and stage tracking.
        """
        start_time = time.time()
        result = PipelineResult(
            file_path=file_path,
            source_url=source_url,
            pdf_url=pdf_url,
        )

        file_name = Path(file_path).name
        logger.info(f"Pipeline START: {file_name}")

        # ── Stage M2: Text Extraction ──
        try:
            doc_data = self._extractor.extract(file_path)
            result.stages_completed.append("text_extraction")
            logger.info(f"  M2 ✓ Text extraction: {len(doc_data.pages)} pages")
        except Exception as e:
            result.failed_stage = "text_extraction"
            result.error_message = f"M2 Text extraction failed: {e}"
            logger.error(result.error_message)
            result.elapsed_seconds = time.time() - start_time
            return result

        # ── Stage M3: Layout Analysis ──
        try:
            layout_doc = self._layout_analyzer.analyze(doc_data)
            result.stages_completed.append("layout_analysis")
            logger.info(f"  M3 ✓ Layout analysis: {len(layout_doc.pages)} pages")
        except Exception as e:
            result.failed_stage = "layout_analysis"
            result.error_message = f"M3 Layout analysis failed: {e}"
            logger.error(result.error_message)
            result.elapsed_seconds = time.time() - start_time
            return result

        # ── Stage M4: Title Detection ──
        title_result = None
        try:
            title_result = self._title_service.detect_title(layout_doc)
            result.stages_completed.append("title_detection")
            logger.info(f"  M4 ✓ Title: {repr(title_result.title)[:60] if title_result.title else 'None'}")
        except Exception as e:
            logger.warning(f"  M4 ✗ Title detection failed: {e}")
            result.stages_completed.append("title_detection_failed")

        # ── Stage M5: Author Detection ──
        author_result = None
        try:
            author_result = self._author_service.detect_authors(layout_doc, title_result)
            result.stages_completed.append("author_detection")
            logger.info(f"  M5 ✓ Authors: {author_result.count} found")
        except Exception as e:
            logger.warning(f"  M5 ✗ Author detection failed: {e}")
            result.stages_completed.append("author_detection_failed")

        # ── Stage M6: Abstract Detection ──
        abstract_result = None
        try:
            abstract_result = self._abstract_service.detect_abstract(doc_data, layout_doc)
            result.stages_completed.append("abstract_detection")
            abs_preview = repr(abstract_result.text[:50]) if abstract_result.text else "None"
            logger.info(f"  M6 ✓ Abstract: {abs_preview}...")
        except Exception as e:
            logger.warning(f"  M6 ✗ Abstract detection failed: {e}")
            result.stages_completed.append("abstract_detection_failed")

        # ── Cross-Validation: detect contamination between fields ──
        cross_flags = self._cross_validate(title_result, author_result, abstract_result)
        if cross_flags:
            logger.warning(f"  Cross-validation flags: {cross_flags}")

        # Gather raw extracted fields
        raw_title = title_result.title if title_result else None
        # The first-line fallback has no title zone or typography evidence. A
        # low score commonly means the PDF begins mid-article, so retaining it
        # would publish body prose as a title. Prefer an empty field until a
        # structured source candidate can supply the correct value.
        title_words = raw_title.split() if raw_title else []
        title_case_ratio = (
            sum(word[0].isupper() for word in title_words if word) / len(title_words)
            if title_words else 0.0
        )
        if (
            title_result
            and title_result.strategy == "first_line"
            and title_result.confidence < 0.60
            and len(title_words) > 8
            and title_case_ratio < 0.45
            and raw_title.rstrip().endswith((".", ";"))
        ):
            logger.warning(
                "Discarding low-evidence first-line title candidate: %r",
                title_result.title[:80] if title_result.title else "",
            )
            raw_title = None
        raw_authors = author_result.author_names if author_result else []
        raw_abstract = abstract_result.text if abstract_result else None

        # ── Stage M7: Data Cleaning ──
        cleaning_result = None
        try:
            cleaning_result = self._cleaning_service.clean(
                title=raw_title,
                authors=raw_authors,
                abstract=raw_abstract,
            )
            result.title = cleaning_result.title
            result.authors = cleaning_result.authors
            result.abstract = cleaning_result.abstract
            result.stages_completed.append("data_cleaning")
            logger.info(f"  M7 ✓ Cleaning: {len(cleaning_result.changes_made)} changes")
        except Exception as e:
            # Fallback: use raw values
            result.title = raw_title
            result.authors = raw_authors
            result.abstract = raw_abstract
            logger.warning(f"  M7 ✗ Cleaning failed: {e}, using raw values")
            result.stages_completed.append("data_cleaning_failed")

        # ── Stage M8: Validation & Scoring ──
        validation_report = None
        try:
            if cleaning_result:
                validation_report = self._validation_engine.validate(
                    cleaning_result=cleaning_result
                )
            else:
                validation_report = self._validation_engine.validate(
                    title=result.title,
                    authors=result.authors,
                    abstract=result.abstract,
                )
            result.stages_completed.append("validation")
            logger.info(
                f"  M8 ✓ Validation: overall={validation_report.overall_score:.4f} "
                f"{'PASS' if validation_report.passed else 'FAIL'}"
            )
        except Exception as e:
            logger.warning(f"  M8 ✗ Validation failed: {e}")
            result.stages_completed.append("validation_failed")

        # ── Stage M9: LLM Enhancement ──
        enhanced_report = validation_report
        if self._llm_validator and validation_report:
            try:
                # Build context from first page
                context = ""
                if doc_data.pages:
                    page_texts = [b.text for b in doc_data.pages[0].blocks]
                    context = " ".join(page_texts)[:500]

                enhanced_report = self._llm_validator.enhance(
                    validation_report,
                    title=result.title,
                    authors=result.authors,
                    abstract=result.abstract,
                    context=context,
                )
                result.stages_completed.append("llm_enhancement")
                logger.info(
                    f"  M9 ✓ LLM: overall={enhanced_report.overall_score:.4f} "
                    f"enhanced={enhanced_report.llm_enhanced}"
                )
            except Exception as e:
                logger.warning(f"  M9 ✗ LLM enhancement failed: {e}")
                result.stages_completed.append("llm_enhancement_failed")
        else:
            result.stages_completed.append("llm_enhancement_skipped")

        # ── Build output ──
        if enhanced_report:
            result.validation = enhanced_report.to_dict()
            result.confidence = {
                "title": enhanced_report.title.score,
                "authors": enhanced_report.authors.score,
                "abstract": enhanced_report.abstract.score,
                "overall": enhanced_report.overall_score,
            }

        failed_stages = [
            stage for stage in result.stages_completed
            if stage.endswith("_failed")
        ]
        # A request is fully completed only when every required stage produced
        # a result. Earlier code reported M4-M9 failures as completed work.
        result.success = validation_report is not None and not failed_stages
        if not result.success:
            result.failed_stage = failed_stages[0].removesuffix("_failed") if failed_stages else "validation"
            result.error_message = (
                "Pipeline completed partially; failed stages: "
                + ", ".join(failed_stages or ["validation"])
            )
        result.elapsed_seconds = time.time() - start_time

        logger.info(
            f"Pipeline DONE: {file_name} | "
            f"title={'✓' if result.title else '✗'} "
            f"authors={len(result.authors)} "
            f"abstract={'✓' if result.abstract else '✗'} "
            f"overall={result.confidence.get('overall', 0):.4f} "
            f"time={result.elapsed_seconds:.3f}s"
        )

        return result

    def process_batch(
        self,
        file_paths: list[str],
        source_url: str = "",
    ) -> list[PipelineResult]:
        """
        Process multiple PDFs.

        Args:
            file_paths: List of PDF file paths.
            source_url: Common source URL.

        Returns:
            List of PipelineResult for each file.
        """
        results = []
        total = len(file_paths)
        for i, fp in enumerate(file_paths, 1):
            logger.info(f"Batch [{i}/{total}]: {Path(fp).name}")
            result = self.process(fp, source_url=source_url)
            results.append(result)
        return results

    @staticmethod
    def _cross_validate(title_result, author_result, abstract_result) -> list[str]:
        """
        Cross-validate M4/M5/M6 results to detect contamination.

        Checks:
        1. Title ∩ Authors: title contains an author name
        2. Title ∩ Abstract: title appears as first line of abstract
        3. Authors ∩ Abstract: author names appear in abstract preamble

        Returns:
            List of warning flags. Empty if no contamination detected.
        """
        flags: list[str] = []

        title_text = (title_result.title or "") if title_result else ""
        author_names = (author_result.author_names if author_result else [])
        abstract_text = (abstract_result.text or "") if abstract_result else ""

        if not title_text:
            return flags

        title_lower = title_text.lower().strip()

        # 1. Title ∩ Authors: check if title contains an author name
        for name in author_names:
            if len(name) >= 4 and name.lower() in title_lower:
                flags.append(f"TITLE_CONTAINS_AUTHOR:{name}")
                logger.debug(f"Cross-validation: title contains author name '{name}'")

        # 2. Title ∩ Abstract: check if title appears as first line of abstract
        if abstract_text:
            abstract_lower = abstract_text.lower().strip()
            # Check first 200 chars of abstract for title text
            abstract_start = abstract_lower[:200]
            if title_lower in abstract_start:
                flags.append("TITLE_IN_ABSTRACT_START")
                logger.debug("Cross-validation: title appears at start of abstract")

        # 3. Authors ∩ Abstract: check if author names in abstract preamble
        if abstract_text and author_names:
            # Only check first 150 chars (preamble area)
            abstract_preamble = abstract_text[:150].lower()
            for name in author_names:
                if len(name) >= 4 and name.lower() in abstract_preamble:
                    flags.append(f"AUTHOR_IN_ABSTRACT_PREAMBLE:{name}")
                    logger.debug(
                        f"Cross-validation: author '{name}' in abstract preamble"
                    )

        return flags
