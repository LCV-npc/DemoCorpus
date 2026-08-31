"""
tests/test_pipeline.py
Unit tests cho ExtractorPipeline: pre-check, SHA-256 hashing.
Milestone 1 — Pipeline tests.
"""

import sys
import hashlib
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from core.pipeline.extractor_pipeline import ExtractorPipeline, PipelineError
from core.models.metadata import ExtractedMetadata
from config.constants import MAX_FILE_SIZE_BYTES


@pytest.fixture
def pipeline():
    """Tạo ExtractorPipeline instance."""
    return ExtractorPipeline()


@pytest.fixture
def valid_pdf(tmp_path):
    """Tạo file PDF hợp lệ (có magic bytes + nội dung)."""
    pdf_file = tmp_path / "valid.pdf"
    content = b"%PDF-1.4 this is a fake but valid-looking PDF file\n" + b"x" * 2048
    pdf_file.write_bytes(content)
    return str(pdf_file)


@pytest.fixture
def not_pdf(tmp_path):
    """Tạo file không phải PDF."""
    txt_file = tmp_path / "not_a_pdf.txt"
    txt_file.write_text("This is a plain text file, not a PDF.", encoding="utf-8")
    return str(txt_file)


class TestExtractorPipeline:
    """Tests cho ExtractorPipeline pre-check."""

    def test_precheck_file_not_found(self, pipeline):
        """PipelineError khi file không tồn tại."""
        metadata = ExtractedMetadata()
        with pytest.raises(PipelineError, match="File not found"):
            pipeline._step_precheck("/nonexistent/path.pdf", metadata)

    def test_precheck_file_too_large(self, pipeline, tmp_path):
        """PipelineError khi file vượt quá giới hạn."""
        large_file = tmp_path / "large.pdf"
        # Tạo file vừa đủ lớn hơn limit (write header + padding)
        content = b"%PDF" + b"\x00" * (MAX_FILE_SIZE_BYTES + 1)
        large_file.write_bytes(content)

        metadata = ExtractedMetadata()
        with pytest.raises(PipelineError, match="File too large"):
            pipeline._step_precheck(str(large_file), metadata)

    def test_precheck_not_pdf(self, pipeline, not_pdf):
        """PipelineError khi file không có magic bytes PDF."""
        metadata = ExtractedMetadata()
        with pytest.raises(PipelineError, match="Not a valid PDF"):
            pipeline._step_precheck(not_pdf, metadata)

    def test_precheck_valid_pdf(self, pipeline, valid_pdf):
        """Pre-check thành công với file PDF hợp lệ."""
        metadata = ExtractedMetadata()
        pipeline._step_precheck(valid_pdf, metadata)

        # SHA-256 hash phải được set
        assert metadata.file_hash_sha256 != ""
        assert len(metadata.file_hash_sha256) == 64  # SHA-256 hex length

        # 'precheck' phải nằm trong steps_completed
        assert "precheck" in metadata.steps_completed

        # processing_steps phải có entry
        assert len(metadata.processing_steps) == 1
        assert metadata.processing_steps[0].step_name == "precheck"
        assert metadata.processing_steps[0].success is True

    def test_sha256_deterministic(self, pipeline, valid_pdf):
        """SHA-256 cho cùng file phải cho cùng kết quả."""
        hash1 = pipeline._sha256(valid_pdf)
        hash2 = pipeline._sha256(valid_pdf)
        assert hash1 == hash2

    def test_sha256_matches_hashlib(self, pipeline, valid_pdf):
        """SHA-256 phải khớp với hashlib.sha256()."""
        pipeline_hash = pipeline._sha256(valid_pdf)

        # Tính hash bằng hashlib trực tiếp
        sha256 = hashlib.sha256()
        with open(valid_pdf, "rb") as f:
            sha256.update(f.read())
        expected = sha256.hexdigest()

        assert pipeline_hash == expected

    def test_precheck_metadata_tracking(self, pipeline, valid_pdf):
        """Pre-check ghi nhận processing step đúng cách."""
        metadata = ExtractedMetadata()
        pipeline._step_precheck(valid_pdf, metadata)

        step = metadata.processing_steps[0]
        assert step.started_at is not None
        assert step.completed_at is not None
        assert step.started_at <= step.completed_at

    def test_run_pipeline_basic(self, pipeline, valid_pdf):
        """run() chạy full pipeline (hiện chỉ có precheck)."""
        metadata = pipeline.run(valid_pdf, source="upload")

        assert metadata.source == "upload"
        assert metadata.file_path == valid_pdf
        assert metadata.file_hash_sha256 != ""
        assert "precheck" in metadata.steps_completed

    def test_precheck_error_tracking(self, pipeline):
        """Pipeline error phải track trong processing_steps."""
        metadata = ExtractedMetadata()
        with pytest.raises(PipelineError):
            pipeline._step_precheck("/nonexistent.pdf", metadata)

        # Step vẫn phải được record (với success=False)
        assert len(metadata.processing_steps) == 1
        assert metadata.processing_steps[0].success is False
