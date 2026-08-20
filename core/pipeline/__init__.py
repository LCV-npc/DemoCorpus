# core.pipeline package
"""
Pipeline modules for PDF processing.

- ExtractorPipeline: M1 precheck + delegates to FullPipeline.
- FullPipeline: End-to-end M2→M9 orchestrator.
"""
from core.pipeline.extractor_pipeline import ExtractorPipeline, PipelineError
from core.pipeline.full_pipeline import FullPipeline, PipelineResult

__all__ = [
    "ExtractorPipeline",
    "PipelineError",
    "FullPipeline",
    "PipelineResult",
]
