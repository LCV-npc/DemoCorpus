"""
core/validators/llm_validator.py
LLMValidator — Semantic validation enhancement using LLM (Milestone 9).

Pipeline:
1. Nhận ValidationReport từ M8 + raw metadata/context.
2. Kiểm tra từng field: nếu rule_score < LLM_ENHANCEMENT_THRESHOLD → gọi LLM.
3. Parse LLM JSON response → extract confidence.
4. Combine scores: final = (rule_score + llm_score) / 2.
5. Trả về enhanced ValidationReport.

QUAN TRỌNG:
- LLM là "Semantic Validator", KHÔNG phải "Extractor".
- LLM KHÔNG được viết lại title/authors/abstract.
- LLM chỉ đánh giá: "candidate này có hợp lệ không?"
- Nếu LLM lỗi → giữ rule-based result, đánh dấu warning.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import time
from dataclasses import replace

from core.validators.models import FieldValidation, ValidationReport
from core.validators.scoring import ValidationScorer
from config.constants import (
    LLM_ENHANCEMENT_THRESHOLD,
    LLM_SCORE_WEIGHT_RULE,
    LLM_SCORE_WEIGHT_LLM,
    LLM_INVALID_CONFIDENCE_CAP,
    LLM_MAX_CONFIDENCE,
    LLM_MIN_CONFIDENCE,
    LLM_MAX_CONTEXT_CHARS,
    LLM_MAX_ABSTRACT_CHARS,
    LLM_TITLE_PROMPT,
    LLM_AUTHOR_PROMPT,
    LLM_ABSTRACT_PROMPT,
    VALIDATION_PASS_THRESHOLD,
)

logger = logging.getLogger(__name__)

# Regex to extract JSON from markdown code fences
_CODE_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n?(.*?)\n?\s*```",
    re.DOTALL,
)


class LLMValidator:
    """
    Semantic validation enhancement using LLM.

    Wraps M8's ValidationReport and enhances low-confidence fields
    by querying an LLM for semantic assessment.

    Usage:
        llm = StubLLM()  # or load_llm()
        validator = LLMValidator(llm_model=llm)
        enhanced = validator.enhance(report, title="...", authors=[...], ...)
    """

    def __init__(self, llm_model=None, validate_all_fields: bool = False):
        """
        Initialize LLM Validator.

        Args:
            llm_model: LLM instance with generate(prompt) -> str method.
                       None → LLM enhancement disabled (all fields keep rule scores).
        """
        self._llm = llm_model
        self._validate_all_fields = validate_all_fields
        self._provider = type(llm_model).__name__ if llm_model else "none"
        logger.info(f"LLMValidator initialized: provider={self._provider}")

    def enhance(
        self,
        report: ValidationReport,
        *,
        title: str | None = None,
        authors: list[str] | None = None,
        abstract: str | None = None,
        context: str = "",
    ) -> ValidationReport:
        """
        Enhance validation report with LLM semantic assessment.

        Checks each field: if rule_score < threshold → call LLM.
        Creates a NEW report (does not mutate original).

        Args:
            report: M8 ValidationReport (rule-based).
            title: Extracted title (for prompt context).
            authors: Extracted authors (for prompt context).
            abstract: Extracted abstract (for prompt context).
            context: First ~500 chars of document text (for LLM context).

        Returns:
            Enhanced ValidationReport. If no LLM available, returns copy of original.
        """
        start_time = time.time()

        # Deep copy to avoid mutating original M8 report
        enhanced = ValidationReport(
            title=replace(report.title, checked_rules=list(report.title.checked_rules),
                          issues=list(report.title.issues), warnings=list(report.title.warnings)),
            authors=replace(report.authors, checked_rules=list(report.authors.checked_rules),
                            issues=list(report.authors.issues), warnings=list(report.authors.warnings)),
            abstract=replace(report.abstract, checked_rules=list(report.abstract.checked_rules),
                             issues=list(report.abstract.issues), warnings=list(report.abstract.warnings)),
            overall_score=report.overall_score,
            passed=report.passed,
        )

        if self._llm is None:
            logger.info("LLM not available — returning rule-based report unchanged")
            return enhanced

        llm_called_any = False
        ctx = (context[:LLM_MAX_CONTEXT_CHARS] if context else "")

        # ── Title Enhancement ──
        if self._should_enhance(enhanced.title.score):
            logger.info(
                f"Title score {enhanced.title.score:.4f} < {LLM_ENHANCEMENT_THRESHOLD} "
                f"→ calling LLM"
            )
            enhanced.title = self._enhance_field(
                field_validation=enhanced.title,
                prompt=self._build_title_prompt(title, ctx, enhanced.title.issues),
                field_name="title",
            )
            llm_called_any = True
        else:
            logger.info(
                f"Title score {enhanced.title.score:.4f} >= {LLM_ENHANCEMENT_THRESHOLD} "
                f"→ LLM skipped"
            )

        # ── Authors Enhancement ──
        if self._should_enhance(enhanced.authors.score):
            logger.info(
                f"Authors score {enhanced.authors.score:.4f} < {LLM_ENHANCEMENT_THRESHOLD} "
                f"→ calling LLM"
            )
            enhanced.authors = self._enhance_field(
                field_validation=enhanced.authors,
                prompt=self._build_author_prompt(authors or [], ctx, enhanced.authors.issues),
                field_name="authors",
            )
            llm_called_any = True
        else:
            logger.info(
                f"Authors score {enhanced.authors.score:.4f} >= {LLM_ENHANCEMENT_THRESHOLD} "
                f"→ LLM skipped"
            )

        # ── Abstract Enhancement ──
        if self._should_enhance(enhanced.abstract.score):
            logger.info(
                f"Abstract score {enhanced.abstract.score:.4f} < {LLM_ENHANCEMENT_THRESHOLD} "
                f"→ calling LLM"
            )
            enhanced.abstract = self._enhance_field(
                field_validation=enhanced.abstract,
                prompt=self._build_abstract_prompt(abstract, ctx, enhanced.abstract.issues),
                field_name="abstract",
            )
            llm_called_any = True
        else:
            logger.info(
                f"Abstract score {enhanced.abstract.score:.4f} >= {LLM_ENHANCEMENT_THRESHOLD} "
                f"→ LLM skipped"
            )

        # ── Recompute Overall Score ──
        enhanced.overall_score = ValidationScorer.compute_overall_score(
            enhanced.title, enhanced.authors, enhanced.abstract
        )
        enhanced.passed = ValidationScorer.is_passed(enhanced.overall_score)
        enhanced.llm_enhanced = llm_called_any

        elapsed = time.time() - start_time
        logger.info(
            f"LLM enhancement complete: "
            f"title={enhanced.title.score:.4f} "
            f"authors={enhanced.authors.score:.4f} "
            f"abstract={enhanced.abstract.score:.4f} "
            f"overall={enhanced.overall_score:.4f} "
            f"llm_called={llm_called_any} "
            f"time={elapsed:.3f}s"
        )

        return enhanced

    # ── Internal: Enhance a single field ──

    def _should_enhance(self, score: float) -> bool:
        """Determine whether M9 should verify a candidate field."""
        return self._validate_all_fields or score < LLM_ENHANCEMENT_THRESHOLD

    def _enhance_field(
        self,
        field_validation: FieldValidation,
        prompt: str,
        field_name: str,
    ) -> FieldValidation:
        """
        Enhance a single field with LLM assessment.

        Args:
            field_validation: Current rule-based validation.
            prompt: Formatted prompt for LLM.
            field_name: "title", "authors", or "abstract".

        Returns:
            Updated FieldValidation with LLM scores.
        """
        rule_score = field_validation.score
        llm_start = time.time()

        try:
            raw_response = self._llm.generate(prompt)
            llm_latency = time.time() - llm_start

            logger.info(
                f"LLM response for {field_name}: "
                f"latency={llm_latency:.3f}s, "
                f"provider={self._provider}, "
                f"response_len={len(raw_response)}"
            )

            parsed = LLMValidator._parse_response(raw_response)

            if parsed is None:
                # Parse failed → keep rule score
                logger.warning(
                    f"LLM parse failed for {field_name} — keeping rule score"
                )
                field_validation.llm_called = True
                field_validation.llm_score = None
                field_validation.llm_reason = "LLM response parse failed"
                field_validation.warnings.append(
                    f"LLM response could not be parsed for {field_name}"
                )
                return field_validation

            llm_confidence = parsed["confidence"]
            llm_reason = parsed.get("reason", "")

            # Combine scores
            final_score = (
                LLM_SCORE_WEIGHT_RULE * rule_score
                + LLM_SCORE_WEIGHT_LLM * llm_confidence
            )
            final_score = min(final_score, 1.0)

            logger.info(
                f"Score combine for {field_name}: "
                f"rule={rule_score:.4f} × {LLM_SCORE_WEIGHT_RULE} + "
                f"llm={llm_confidence:.4f} × {LLM_SCORE_WEIGHT_LLM} = "
                f"final={final_score:.4f}"
            )

            # Update field
            field_validation.score = final_score
            field_validation.passed = final_score >= VALIDATION_PASS_THRESHOLD
            field_validation.llm_called = True
            field_validation.llm_score = llm_confidence
            field_validation.llm_reason = llm_reason

            return field_validation

        except Exception as e:
            llm_latency = time.time() - llm_start
            logger.error(
                f"LLM error for {field_name}: {e} "
                f"(latency={llm_latency:.3f}s) — keeping rule score"
            )
            field_validation.llm_called = True
            field_validation.llm_score = None
            field_validation.llm_reason = f"LLM error: {e}"
            field_validation.warnings.append(
                f"LLM error for {field_name}: {e}"
            )
            return field_validation

    # ── Prompt Builders ──

    @staticmethod
    def _build_title_prompt(
        title: str | None,
        context: str,
        issues: list[str],
    ) -> str:
        """Build title validation prompt."""
        return LLM_TITLE_PROMPT.format(
            title=title or "(none)",
            context=context or "(no context available)",
            issues=", ".join(issues) if issues else "none",
        )

    @staticmethod
    def _build_author_prompt(
        authors: list[str],
        context: str,
        issues: list[str],
    ) -> str:
        """Build author validation prompt."""
        return LLM_AUTHOR_PROMPT.format(
            authors_json=json.dumps(authors, ensure_ascii=False),
            context=context or "(no context available)",
            issues=", ".join(issues) if issues else "none",
        )

    @staticmethod
    def _build_abstract_prompt(
        abstract: str | None,
        context: str,
        issues: list[str],
    ) -> str:
        """Build abstract validation prompt."""
        preview = ""
        if abstract:
            preview = abstract[:LLM_MAX_ABSTRACT_CHARS]
        return LLM_ABSTRACT_PROMPT.format(
            abstract_preview=preview or "(none)",
            issues=", ".join(issues) if issues else "none",
        )

    # ── Response Parsing ──

    @staticmethod
    def _parse_response(raw: str) -> dict | None:
        """
        Parse LLM JSON response.

        Handles:
        - Valid JSON directly
        - JSON inside markdown code fences (```json ... ```)
        - Missing fields
        - confidence out of [0, 1] range
        - is_valid=false with high confidence (capped)
        - Invalid JSON → None
        - Empty response → None

        Args:
            raw: Raw LLM output string.

        Returns:
            {"is_valid": bool, "confidence": float, "reason": str} or None.
        """
        if not raw or not raw.strip():
            logger.warning("LLM returned empty response")
            return None

        text = raw.strip()

        # Try to extract JSON from code fence first
        fence_match = _CODE_FENCE_RE.search(text)
        if fence_match:
            text = fence_match.group(1).strip()

        # Try to parse JSON
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON-like content in the text
            json_match = re.search(r"\{[^{}]*\}", text)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    logger.warning(f"Could not parse LLM JSON: {text[:100]}...")
                    return None
            else:
                logger.warning(f"No JSON found in LLM response: {text[:100]}...")
                return None

        if not isinstance(data, dict):
            logger.warning(f"LLM response is not a dict: {type(data)}")
            return None

        # Extract fields with defaults
        is_valid = data.get("is_valid", True)
        confidence = data.get("confidence", 0.5)
        reason = data.get("reason", "")

        # Ensure confidence is numeric
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            logger.warning(f"Invalid confidence value: {confidence}")
            confidence = 0.5

        # Clamp to [0, 1]
        confidence = max(LLM_MIN_CONFIDENCE, min(LLM_MAX_CONFIDENCE, confidence))

        # Handle paradox: is_valid=false but high confidence
        # → LLM is confident it's INVALID → cap the score low
        if not is_valid and confidence > LLM_INVALID_CONFIDENCE_CAP:
            logger.info(
                f"LLM says invalid with confidence {confidence:.4f} "
                f"→ capping to {LLM_INVALID_CONFIDENCE_CAP}"
            )
            confidence = LLM_INVALID_CONFIDENCE_CAP

        return {
            "is_valid": bool(is_valid),
            "confidence": confidence,
            "reason": str(reason),
        }
