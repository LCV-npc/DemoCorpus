"""
tests/test_mongodb_persistence.py
Comprehensive tests cho Milestone 10 — MongoDB Persistence.

Tests cover:
- Insert / get / get_by_hash
- Duplicate hash rejection
- List / pagination / min_confidence
- Search (full-text)
- Update
- Count
- Processing jobs (create, progress, complete, get)
- Vietnamese character integrity
- Author list / abstract / confidence integrity
- Integration: pipeline → MongoDB → roundtrip
- Duplicate PDF detection (same file processed twice)
- Basic performance measurements

Database: Uses 'pdf_extractor_test' (NOT production).
Requires: Running MongoDB instance on localhost:27017.
"""

import sys
import time
import uuid
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from config.settings import settings
from core.models.metadata import (
    ExtractedMetadata,
    FieldConfidence,
    FilterResult,
    ProcessingStep,
    ValidationResult,
)
from infrastructure.database.repositories.paper_repository import PaperRepository


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

def _is_mongo_available() -> bool:
    """Check if MongoDB is running on localhost."""
    try:
        client = MongoClient(
            settings.MONGODB_URI,
            serverSelectionTimeoutMS=2000,
        )
        client.admin.command("ping")
        client.close()
        return True
    except Exception:
        return False


# Skip all tests in this module if MongoDB is not available
pytestmark = pytest.mark.skipif(
    not _is_mongo_available(),
    reason="MongoDB not available on localhost:27017",
)


@pytest.fixture(scope="module")
def test_db():
    """
    Tạo test database connection.
    Dùng pdf_extractor_test, KHÔNG dùng production DB.
    """
    client = MongoClient(
        settings.MONGODB_URI,
        serverSelectionTimeoutMS=5000,
    )
    db = client[settings.MONGODB_TEST_DB]
    yield db
    # Cleanup: drop test database after all tests
    client.drop_database(settings.MONGODB_TEST_DB)
    client.close()


@pytest.fixture
def repo(test_db):
    """PaperRepository sử dụng test database."""
    # Clean collections before each test
    test_db["papers"].delete_many({})
    test_db["processing_jobs"].delete_many({})
    return PaperRepository(db=test_db)


@pytest.fixture
def sample_metadata() -> ExtractedMetadata:
    """Tạo sample ExtractedMetadata cho testing."""
    return ExtractedMetadata(
        paper_id=str(uuid.uuid4()),
        source="upload",
        source_url="https://example.com/article/123",
        pdf_url="https://example.com/article/123.pdf",
        file_path="/data/uploads/test.pdf",
        file_hash_sha256="a" * 64,
        title="Nghiên cứu hiệu quả điều trị đau thắt lưng bằng phương pháp vật lý trị liệu",
        authors=[
            "Nguyễn Văn An",
            "Trần Thị Bình",
            "Lê Hoàng Cường",
        ],
        abstract=(
            "Mục tiêu: Đánh giá hiệu quả điều trị đau thắt lưng mạn tính "
            "bằng phương pháp vật lý trị liệu kết hợp tại Bệnh viện Đại học Y Hà Nội. "
            "Phương pháp: Nghiên cứu tiến cứu, can thiệp lâm sàng trên 120 bệnh nhân "
            "từ tháng 01/2024 đến tháng 06/2024."
        ),
        confidence=ValidationResult(
            title=FieldConfidence(field_name="title", score=0.85, method="heuristic"),
            authors=FieldConfidence(field_name="authors", score=0.72, method="ner"),
            abstract=FieldConfidence(field_name="abstract", score=0.90, method="rule"),
        ),
        filter_result=FilterResult(
            passed=True,
            flags=[],
            non_alpha_ratio=0.12,
            cbs_score=0.3,
        ),
        steps_completed=["precheck", "text_extraction", "layout_analysis",
                         "title_detection", "author_detection", "abstract_detection",
                         "data_cleaning", "validation"],
        is_reviewed=False,
        reviewer_notes="",
    )


def _make_doc(paper_id: str = "", file_hash: str = "") -> dict:
    """Helper: tạo minimal paper document dict."""
    if not paper_id:
        paper_id = str(uuid.uuid4())
    if not file_hash:
        file_hash = uuid.uuid4().hex + uuid.uuid4().hex  # 64 hex chars
    return {
        "paper_id": paper_id,
        "file_hash_sha256": file_hash,
        "source": "upload",
        "source_url": "",
        "pdf_url": "",
        "file_path": "/data/test.pdf",
        "extracted": {
            "title": "Test Title",
            "authors": ["Author A"],
            "abstract": "Test abstract content.",
        },
        "confidence": {
            "overall": 0.75,
            "title": {"score": 0.8, "issues": [], "method": "heuristic"},
            "authors": {"score": 0.7, "issues": [], "method": "ner"},
            "abstract": {"score": 0.75, "issues": [], "method": "rule"},
        },
        "filter_result": None,
        "processing": {
            "steps_completed": ["precheck", "text_extraction"],
            "processing_steps": [],
            "created_at": "2024-01-15T10:00:00+00:00",
        },
        "review": {
            "is_reviewed": False,
            "reviewer_notes": "",
        },
    }


# ─────────────────────────────────────────────
# CRUD Tests
# ─────────────────────────────────────────────

class TestInsertPaper:
    """Test insert operations."""

    def test_insert_paper_success(self, repo):
        """Insert paper và verify paper_id trả về."""
        doc = _make_doc()
        paper_id = repo.insert_paper(doc)
        assert paper_id == doc["paper_id"]
        assert len(paper_id) > 0

    def test_insert_paper_has_timestamps(self, repo):
        """Insert paper tự động thêm timestamps."""
        doc = _make_doc()
        # Remove timestamps to verify auto-add
        doc.pop("updated_at", None)
        repo.insert_paper(doc)
        saved = repo.get_paper(doc["paper_id"])
        assert saved is not None
        assert "updated_at" in saved
        assert saved["processing"]["created_at"] is not None


class TestGetPaper:
    """Test get operations."""

    def test_get_paper_found(self, repo):
        """Get paper theo paper_id, verify fields đúng."""
        doc = _make_doc()
        repo.insert_paper(doc)
        result = repo.get_paper(doc["paper_id"])
        assert result is not None
        assert result["paper_id"] == doc["paper_id"]
        assert result["extracted"]["title"] == "Test Title"

    def test_get_paper_not_found(self, repo):
        """Get paper không tồn tại trả về None."""
        result = repo.get_paper("nonexistent-id-12345")
        assert result is None

    def test_get_paper_no_mongo_id(self, repo):
        """Get paper không chứa _id field."""
        doc = _make_doc()
        repo.insert_paper(doc)
        result = repo.get_paper(doc["paper_id"])
        assert "_id" not in result


class TestGetByHash:
    """Test duplicate detection by hash."""

    def test_get_by_hash_found(self, repo):
        """Tìm paper theo SHA-256 hash."""
        doc = _make_doc(file_hash="b" * 64)
        repo.insert_paper(doc)
        result = repo.get_by_hash("b" * 64)
        assert result is not None
        assert result["paper_id"] == doc["paper_id"]

    def test_get_by_hash_not_found(self, repo):
        """Hash không tồn tại trả về None."""
        result = repo.get_by_hash("nonexistent" + "0" * 54)
        assert result is None


class TestDuplicateHash:
    """Test duplicate hash rejection."""

    def test_duplicate_hash_raises(self, repo):
        """Insert hai paper cùng hash → DuplicateKeyError."""
        hash_val = "c" * 64
        doc1 = _make_doc(file_hash=hash_val)
        doc2 = _make_doc(file_hash=hash_val)  # Different paper_id, same hash

        repo.insert_paper(doc1)
        with pytest.raises(DuplicateKeyError):
            repo.insert_paper(doc2)

    def test_duplicate_paper_id_raises(self, repo):
        """Insert hai paper cùng paper_id → DuplicateKeyError."""
        pid = "duplicate-test-id"
        doc1 = _make_doc(paper_id=pid, file_hash="d" * 64)
        doc2 = _make_doc(paper_id=pid, file_hash="e" * 64)

        repo.insert_paper(doc1)
        with pytest.raises(DuplicateKeyError):
            repo.insert_paper(doc2)


class TestListPapers:
    """Test list and pagination."""

    def test_list_papers_empty(self, repo):
        """List trả về [] khi không có papers."""
        result = repo.list_papers()
        assert result == []

    def test_list_papers_basic(self, repo):
        """List trả về tất cả papers đã insert."""
        for i in range(3):
            repo.insert_paper(_make_doc())
        result = repo.list_papers(limit=10)
        assert len(result) == 3

    def test_list_papers_pagination(self, repo):
        """Pagination hoạt động đúng."""
        for i in range(5):
            repo.insert_paper(_make_doc())

        page1 = repo.list_papers(page=1, limit=2)
        page2 = repo.list_papers(page=2, limit=2)
        page3 = repo.list_papers(page=3, limit=2)

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1

        # No overlap between pages
        ids_p1 = {p["paper_id"] for p in page1}
        ids_p2 = {p["paper_id"] for p in page2}
        assert ids_p1.isdisjoint(ids_p2)

    def test_list_papers_min_confidence(self, repo):
        """Filter papers theo min_confidence."""
        # Insert papers with different confidence levels
        for overall in [0.3, 0.5, 0.7, 0.9]:
            doc = _make_doc()
            doc["confidence"]["overall"] = overall
            repo.insert_paper(doc)

        result = repo.list_papers(min_confidence=0.6)
        assert len(result) == 2
        for paper in result:
            assert paper["confidence"]["overall"] >= 0.6


class TestSearchPapers:
    """Test full-text search."""

    def test_search_papers_found(self, repo):
        """Search tìm đúng paper theo title."""
        doc = _make_doc()
        doc["extracted"]["title"] = "Machine Learning in Medical Diagnosis"
        doc["extracted"]["abstract"] = "This paper explores ML applications."
        repo.insert_paper(doc)

        # MongoDB text index needs a moment
        results = repo.search_papers("Machine Learning")
        assert len(results) >= 1
        assert any("Machine Learning" in r["extracted"]["title"] for r in results)

    def test_search_papers_no_match(self, repo):
        """Search không tìm thấy trả về []."""
        doc = _make_doc()
        repo.insert_paper(doc)
        results = repo.search_papers("xyznonexistentterm999")
        assert len(results) == 0


class TestUpdatePaper:
    """Test update operations."""

    def test_update_paper_success(self, repo):
        """Update fields và verify."""
        doc = _make_doc()
        repo.insert_paper(doc)

        updated = repo.update_paper(doc["paper_id"], {
            "review.is_reviewed": True,
            "review.reviewer_notes": "Looks good",
        })
        assert updated is True

        result = repo.get_paper(doc["paper_id"])
        assert result["review"]["is_reviewed"] is True
        assert result["review"]["reviewer_notes"] == "Looks good"
        # updated_at should be auto-set
        assert "updated_at" in result

    def test_update_paper_not_found(self, repo):
        """Update paper không tồn tại trả về False."""
        result = repo.update_paper("nonexistent-id", {"review.is_reviewed": True})
        assert result is False


class TestCount:
    """Test count operations."""

    def test_count_empty(self, repo):
        """Count = 0 khi collection rỗng."""
        assert repo.count() == 0

    def test_count_with_papers(self, repo):
        """Count đúng số papers."""
        for _ in range(4):
            repo.insert_paper(_make_doc())
        assert repo.count() == 4

    def test_count_with_query(self, repo):
        """Count với filter query."""
        doc1 = _make_doc()
        doc1["source"] = "upload"
        doc2 = _make_doc()
        doc2["source"] = "scrape"
        repo.insert_paper(doc1)
        repo.insert_paper(doc2)

        assert repo.count({"source": "upload"}) == 1
        assert repo.count({"source": "scrape"}) == 1
        assert repo.count() == 2


class TestDeletePaper:
    """Test delete operations."""

    def test_delete_paper_success(self, repo):
        """Delete paper và verify."""
        doc = _make_doc()
        repo.insert_paper(doc)
        assert repo.count() == 1

        deleted = repo.delete_paper(doc["paper_id"])
        assert deleted is True
        assert repo.count() == 0

    def test_delete_paper_not_found(self, repo):
        """Delete paper không tồn tại trả về False."""
        result = repo.delete_paper("nonexistent-id")
        assert result is False


# ─────────────────────────────────────────────
# Processing Jobs Tests
# ─────────────────────────────────────────────

class TestProcessingJobs:
    """Test processing job lifecycle."""

    def test_create_job(self, repo):
        """Create job và verify."""
        job_id = repo.create_job(total_files=10)
        assert len(job_id) > 0

        job = repo.get_job(job_id)
        assert job is not None
        assert job["status"] == "pending"
        assert job["total_files"] == 10
        assert job["processed_files"] == 0

    def test_update_job_progress_success(self, repo):
        """Update progress cho job."""
        job_id = repo.create_job(total_files=3)

        repo.update_job_progress(job_id, paper_id="paper-1")
        job = repo.get_job(job_id)
        assert job["processed_files"] == 1
        assert job["status"] == "running"
        assert "paper-1" in job["paper_ids"]

    def test_update_job_progress_failed(self, repo):
        """Update progress khi file fail."""
        job_id = repo.create_job(total_files=3)

        repo.update_job_progress(
            job_id,
            failed=True,
            error_msg="Extraction failed: corrupted PDF",
        )
        job = repo.get_job(job_id)
        assert job["processed_files"] == 1
        assert job["failed_files"] == 1
        assert "Extraction failed" in job["errors"][0]

    def test_complete_job(self, repo):
        """Complete job và verify."""
        job_id = repo.create_job(total_files=1)
        repo.update_job_progress(job_id, paper_id="paper-1")
        repo.complete_job(job_id)

        job = repo.get_job(job_id)
        assert job["status"] == "completed"
        assert job["completed_at"] is not None

    def test_get_job_not_found(self, repo):
        """Get job không tồn tại trả về None."""
        result = repo.get_job("nonexistent-job-id")
        assert result is None


# ─────────────────────────────────────────────
# Data Integrity Tests
# ─────────────────────────────────────────────

class TestDataIntegrity:
    """Test data integrity — đặc biệt tiếng Việt."""

    def test_vietnamese_title(self, repo, sample_metadata):
        """Tiếng Việt title survives MongoDB roundtrip."""
        doc = sample_metadata.to_dict()
        repo.insert_paper(doc)
        result = repo.get_paper(doc["paper_id"])

        assert result["extracted"]["title"] == sample_metadata.title
        # Verify specific Vietnamese characters
        assert "điều trị" in result["extracted"]["title"]
        assert "đau thắt lưng" in result["extracted"]["title"]
        assert "vật lý trị liệu" in result["extracted"]["title"]

    def test_vietnamese_authors(self, repo, sample_metadata):
        """Vietnamese author names survive roundtrip."""
        doc = sample_metadata.to_dict()
        repo.insert_paper(doc)
        result = repo.get_paper(doc["paper_id"])

        authors = result["extracted"]["authors"]
        assert len(authors) == 3
        assert "Nguyễn Văn An" in authors
        assert "Trần Thị Bình" in authors
        assert "Lê Hoàng Cường" in authors

    def test_vietnamese_abstract(self, repo, sample_metadata):
        """Vietnamese abstract survives roundtrip."""
        doc = sample_metadata.to_dict()
        repo.insert_paper(doc)
        result = repo.get_paper(doc["paper_id"])

        abstract = result["extracted"]["abstract"]
        assert "Đánh giá hiệu quả" in abstract
        assert "bệnh nhân" in abstract
        assert "Bệnh viện Đại học Y Hà Nội" in abstract

    def test_author_list_integrity(self, repo):
        """Author list preserved exactly (order and count)."""
        authors = ["Author Một", "Author Hai", "Author Ba", "Author Bốn"]
        doc = _make_doc()
        doc["extracted"]["authors"] = authors
        repo.insert_paper(doc)

        result = repo.get_paper(doc["paper_id"])
        assert result["extracted"]["authors"] == authors

    def test_abstract_integrity(self, repo):
        """Long abstract with special characters preserved."""
        abstract = (
            "Tóm tắt: Nghiên cứu này đánh giá hiệu quả (p < 0.05) "
            "của phương pháp mới.\n\n"
            "Kết quả: 85% bệnh nhân cải thiện — có ý nghĩa thống kê "
            "(χ² = 12.5, df = 3).\n"
            "Kết luận: Phương pháp hiệu quả & an toàn."
        )
        doc = _make_doc()
        doc["extracted"]["abstract"] = abstract
        repo.insert_paper(doc)

        result = repo.get_paper(doc["paper_id"])
        assert result["extracted"]["abstract"] == abstract

    def test_confidence_integrity(self, repo, sample_metadata):
        """Confidence scores preserved as floats."""
        doc = sample_metadata.to_dict()
        repo.insert_paper(doc)
        result = repo.get_paper(doc["paper_id"])

        conf = result["confidence"]
        assert isinstance(conf["title"]["score"], (int, float))
        assert abs(conf["title"]["score"] - 0.85) < 1e-6
        assert abs(conf["authors"]["score"] - 0.72) < 1e-6
        assert abs(conf["abstract"]["score"] - 0.90) < 1e-6

    def test_filter_result_integrity(self, repo, sample_metadata):
        """FilterResult survives roundtrip."""
        doc = sample_metadata.to_dict()
        repo.insert_paper(doc)
        result = repo.get_paper(doc["paper_id"])

        fr = result["filter_result"]
        assert fr is not None
        assert fr["passed"] is True
        assert isinstance(fr["non_alpha_ratio"], (int, float))
        assert abs(fr["non_alpha_ratio"] - 0.12) < 1e-6


# ─────────────────────────────────────────────
# ExtractedMetadata Roundtrip Tests
# ─────────────────────────────────────────────

class TestMetadataRoundtrip:
    """Test to_dict() → MongoDB → from_dict() roundtrip."""

    def test_roundtrip_basic(self, repo, sample_metadata):
        """Full roundtrip: ExtractedMetadata → dict → MongoDB → dict → ExtractedMetadata."""
        # Save
        doc = sample_metadata.to_dict()
        repo.insert_paper(doc)

        # Retrieve
        saved_doc = repo.get_paper(doc["paper_id"])
        assert saved_doc is not None

        # Reconstruct
        restored = ExtractedMetadata.from_dict(saved_doc)

        # Verify fields
        assert restored.paper_id == sample_metadata.paper_id
        assert restored.source == sample_metadata.source
        assert restored.source_url == sample_metadata.source_url
        assert restored.title == sample_metadata.title
        assert restored.authors == sample_metadata.authors
        assert restored.abstract == sample_metadata.abstract
        assert restored.file_hash_sha256 == sample_metadata.file_hash_sha256
        assert restored.is_reviewed == sample_metadata.is_reviewed

    def test_roundtrip_confidence(self, repo, sample_metadata):
        """Confidence scores survive roundtrip via from_dict."""
        doc = sample_metadata.to_dict()
        repo.insert_paper(doc)
        saved_doc = repo.get_paper(doc["paper_id"])
        restored = ExtractedMetadata.from_dict(saved_doc)

        assert restored.confidence is not None
        assert abs(restored.confidence.title.score - 0.85) < 1e-6
        assert abs(restored.confidence.authors.score - 0.72) < 1e-6
        assert abs(restored.confidence.abstract.score - 0.90) < 1e-6
        assert abs(restored.overall_confidence - sample_metadata.overall_confidence) < 1e-6

    def test_roundtrip_steps(self, repo, sample_metadata):
        """Processing steps survive roundtrip."""
        doc = sample_metadata.to_dict()
        repo.insert_paper(doc)
        saved_doc = repo.get_paper(doc["paper_id"])
        restored = ExtractedMetadata.from_dict(saved_doc)

        assert restored.steps_completed == sample_metadata.steps_completed
        assert "precheck" in restored.steps_completed
        assert "validation" in restored.steps_completed


# ─────────────────────────────────────────────
# Performance Tests (Basic)
# ─────────────────────────────────────────────

class TestPerformance:
    """Basic performance measurements."""

    def test_insert_performance(self, repo):
        """Measure insert time — should be < 100ms per document."""
        times = []
        for _ in range(10):
            doc = _make_doc()
            start = time.time()
            repo.insert_paper(doc)
            elapsed = time.time() - start
            times.append(elapsed)

        avg_ms = (sum(times) / len(times)) * 1000
        max_ms = max(times) * 1000
        print(f"\n  Insert: avg={avg_ms:.1f}ms, max={max_ms:.1f}ms")
        # Should be reasonably fast (< 100ms avg for local MongoDB)
        assert avg_ms < 500  # generous threshold for CI

    def test_query_performance(self, repo):
        """Measure query time — should be < 50ms."""
        # Insert some data first
        docs = []
        for _ in range(20):
            doc = _make_doc()
            repo.insert_paper(doc)
            docs.append(doc)

        # Measure get_paper
        times = []
        for doc in docs[:10]:
            start = time.time()
            repo.get_paper(doc["paper_id"])
            elapsed = time.time() - start
            times.append(elapsed)

        avg_ms = (sum(times) / len(times)) * 1000
        print(f"\n  Query (get_paper): avg={avg_ms:.1f}ms")
        assert avg_ms < 500

    def test_list_performance(self, repo):
        """Measure list time."""
        for _ in range(30):
            repo.insert_paper(_make_doc())

        start = time.time()
        results = repo.list_papers(page=1, limit=20)
        elapsed_ms = (time.time() - start) * 1000

        print(f"\n  List (20 items): {elapsed_ms:.1f}ms")
        assert len(results) == 20
        assert elapsed_ms < 500

    def test_search_performance(self, repo):
        """Measure search time."""
        for i in range(20):
            doc = _make_doc()
            doc["extracted"]["title"] = f"Research paper number {i} about medicine"
            repo.insert_paper(doc)

        start = time.time()
        results = repo.search_papers("medicine research")
        elapsed_ms = (time.time() - start) * 1000

        print(f"\n  Search: {elapsed_ms:.1f}ms, found={len(results)}")
        assert elapsed_ms < 1000


# ─────────────────────────────────────────────
# PersistenceService Tests
# ─────────────────────────────────────────────

class TestPersistenceService:
    """Test PersistenceService integration."""

    def test_save_extracted_metadata(self, repo):
        """Save ExtractedMetadata via PersistenceService."""
        from infrastructure.database.persistence_service import PersistenceService

        service = PersistenceService(repo=repo)
        metadata = ExtractedMetadata(
            source="upload",
            file_path="/test/paper.pdf",
            file_hash_sha256="f" * 64,
            title="Test Paper Title",
            authors=["Author A"],
            abstract="Test abstract.",
        )

        paper_id = service.save_extracted_metadata(metadata)
        assert paper_id == metadata.paper_id

        # Verify retrieval
        result = service.get_paper(paper_id)
        assert result is not None
        assert result["extracted"]["title"] == "Test Paper Title"

    def test_save_duplicate_raises(self, repo):
        """Save duplicate raises DuplicatePaperError."""
        from infrastructure.database.persistence_service import (
            DuplicatePaperError,
            PersistenceService,
        )

        service = PersistenceService(repo=repo)
        hash_val = "g" * 64

        meta1 = ExtractedMetadata(
            file_hash_sha256=hash_val,
            title="Paper 1",
        )
        meta2 = ExtractedMetadata(
            file_hash_sha256=hash_val,
            title="Paper 2 (same hash)",
        )

        service.save_extracted_metadata(meta1)
        with pytest.raises(DuplicatePaperError) as exc_info:
            service.save_extracted_metadata(meta2)

        assert exc_info.value.file_hash == hash_val
        assert exc_info.value.existing_paper_id == meta1.paper_id

    def test_get_paper_as_metadata(self, repo):
        """Retrieve paper as ExtractedMetadata domain object."""
        from infrastructure.database.persistence_service import PersistenceService

        service = PersistenceService(repo=repo)
        metadata = ExtractedMetadata(
            source="local",
            file_hash_sha256="h" * 64,
            title="Domain Object Test",
            authors=["Nguyễn Thị Hương"],
            abstract="Tóm tắt bài báo.",
            confidence=ValidationResult(
                title=FieldConfidence(field_name="title", score=0.9),
                authors=FieldConfidence(field_name="authors", score=0.8),
                abstract=FieldConfidence(field_name="abstract", score=0.7),
            ),
        )

        paper_id = service.save_extracted_metadata(metadata)
        restored = service.get_paper_as_metadata(paper_id)

        assert restored is not None
        assert restored.title == "Domain Object Test"
        assert restored.authors == ["Nguyễn Thị Hương"]
        assert restored.abstract == "Tóm tắt bài báo."
        assert abs(restored.overall_confidence - 0.8) < 1e-6

    def test_save_pipeline_result(self, repo):
        """Save PipelineResult via PersistenceService."""
        from core.pipeline.full_pipeline import PipelineResult
        from infrastructure.database.persistence_service import PersistenceService

        service = PersistenceService(repo=repo)
        result = PipelineResult(
            file_path="/test/paper.pdf",
            title="Pipeline Result Title",
            authors=["Author X"],
            abstract="Pipeline abstract.",
            success=True,
            stages_completed=["text_extraction", "layout_analysis"],
            confidence={"overall": 0.82, "title": 0.9, "authors": 0.8, "abstract": 0.76},
            elapsed_seconds=1.234,
        )

        paper_id = service.save_pipeline_result(
            result=result,
            file_hash="i" * 64,
            source="upload",
        )

        saved = service.get_paper(paper_id)
        assert saved is not None
        assert saved["extracted"]["title"] == "Pipeline Result Title"
        assert saved["extracted"]["authors"] == ["Author X"]
        assert saved["confidence"]["overall"] == 0.82
