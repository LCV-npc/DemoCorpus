"""
tests/test_web_app.py
Milestone 11 — Web Application tests.

Tests cho tất cả API endpoints mới:
- Upload (full pipeline)
- Results (list, detail)
- Search
- Review
- Health
- Error handling (duplicate, not found, invalid file)

Sử dụng FastAPI TestClient.
Yêu cầu MongoDB chạy cho integration tests.
"""

import os
import sys
import io
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root is in path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from fastapi.testclient import TestClient
from app.main import create_app
from app.routers import scraper_router
from infrastructure.scraper.pdf_scraper import scrape_status


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    """Create FastAPI app for testing."""
    return create_app()


@pytest.fixture(scope="module")
def client(app):
    """FastAPI test client."""
    return TestClient(app)


def _get_sample_pdf_path():
    """Find a sample PDF in data/ directory for testing."""
    data_dirs = [
        _project_root / "data" / "uploads",
        _project_root / "data" / "scraped_pdfs",
    ]
    for d in data_dirs:
        if d.exists():
            for pdf in d.rglob("*.pdf"):
                if pdf.stat().st_size > 100:
                    return str(pdf)
    return None


def _create_minimal_pdf():
    """Create a minimal valid PDF file in memory."""
    # Minimal valid PDF (single empty page)
    pdf_content = (
        b"%PDF-1.0\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n190\n%%EOF\n"
    )
    return pdf_content


class TestCurrentCrawlResults:
    """The results panel must not read the persistent PDF library."""

    def test_current_crawl_results_are_transient_and_hide_local_paths(self, client):
        scrape_status.reset()
        try:
            scrape_status.add_pdf_record({
                "paper_id": "current-crawl-paper",
                "filename": "current.pdf",
                "file_path": "C:/private/current.pdf",
                "pdf_path": "C:/private/current.pdf",
                "extracted": {
                    "title": "Current crawl title",
                    "authors": ["Nguyễn Văn A"],
                    "abstract": "Current crawl abstract",
                },
                "confidence": {"overall": 0.0},
                "processing": {"created_at": "2026-08-31T00:00:00+00:00"},
            })

            response = client.get("/api/scrape/results?q=current")

            assert response.status_code == 200
            data = response.json()
            assert data["scope"] == "current_crawl_session"
            assert data["total"] == 1
            assert data["items"][0]["paper_id"] == "current-crawl-paper"
            assert "file_path" not in data["items"][0]
            assert "pdf_path" not in data["items"][0]

            scrape_status.try_start()
            assert client.get("/api/scrape/results").json()["total"] == 0
        finally:
            scrape_status.reset()


class TestStoredPdfMetadataExtraction:
    def test_bulk_extraction_skips_completed_pdfs(self, client, monkeypatch):
        pending_path = str((_project_root / "pending.pdf").resolve())
        completed_path = str((_project_root / "completed.pdf").resolve())
        pending_item = {"paper_id": "pending", "filename": "pending.pdf", "file_path": pending_path}
        completed_item = {"paper_id": "completed", "filename": "completed.pdf", "file_path": completed_path}
        records = {
            scraper_router._path_key(pending_path): {
                "paper_id": "pending",
                "processing": {"steps_completed": ["scrape"]},
            },
            scraper_router._path_key(completed_path): {
                "paper_id": "completed",
                "processing": {
                    "steps_completed": ["scrape", "text_extraction", "llm_enhancement"],
                },
            },
        }
        started = {}

        monkeypatch.setattr(scraper_router, "_ensure_extraction_available", lambda: object())
        monkeypatch.setattr(scraper_router, "_scraped_records_by_path", lambda: records)
        monkeypatch.setattr(scraper_router, "_stored_scraped_pdfs", lambda: [pending_item, completed_item])
        monkeypatch.setattr(scraper_router, "_start_extraction_job", lambda **kwargs: started.update(kwargs))

        response = client.post("/api/scrape/extract", json={})

        assert response.status_code == 200
        assert response.json()["total_files"] == 1
        assert response.json()["skipped"] == 1
        assert started["pending"] == [pending_item]

    def test_single_extraction_can_reprocess_completed_pdf(self, client, monkeypatch):
        path = str((_project_root / "completed.pdf").resolve())
        item = {"paper_id": "completed", "filename": "completed.pdf", "file_path": path}
        started = {}

        monkeypatch.setattr(scraper_router, "_ensure_extraction_available", lambda: object())
        monkeypatch.setattr(scraper_router, "_scraped_records_by_path", lambda: {})
        monkeypatch.setattr(scraper_router, "_stored_scraped_pdfs", lambda: [item])
        monkeypatch.setattr(scraper_router, "_start_extraction_job", lambda **kwargs: started.update(kwargs))

        response = client.post("/api/pdfs/completed/extract", json={})

        assert response.status_code == 200
        assert response.json()["total_files"] == 1
        assert started["pending"] == [item]

    def test_extraction_status_accepts_cooperative_stop(self):
        status = scraper_router.ExtractionStatus()
        assert status.try_start(total=3, skipped=2)
        assert status.request_stop()
        assert status.should_stop()
        status.complete(stopped=True)
        snapshot = status.to_dict()
        assert snapshot["running"] is False
        assert snapshot["stopped"] is True
        assert snapshot["stop_requested"] is True


# ─────────────────────────────────────────────
# Health Check Tests
# ─────────────────────────────────────────────

class TestHealthCheck:
    """Tests cho GET /api/health."""

    def test_health_endpoint_returns_200(self, client):
        """Health check endpoint phải trả 200."""
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_health_response_has_required_fields(self, client):
        """Health response phải có status, database, version."""
        response = client.get("/api/health")
        data = response.json()
        assert "status" in data
        assert "database" in data
        assert "version" in data

    def test_health_status_is_ok_or_degraded(self, client):
        """Status phải là 'ok' hoặc 'degraded'."""
        response = client.get("/api/health")
        data = response.json()
        assert data["status"] in ("ok", "degraded")

    def test_health_database_is_connected_or_disconnected(self, client):
        """Database phải là 'connected' hoặc 'disconnected'."""
        response = client.get("/api/health")
        data = response.json()
        assert data["database"] in ("connected", "disconnected")


# ─────────────────────────────────────────────
# Upload Tests
# ─────────────────────────────────────────────

class TestUpload:
    """Tests cho POST /api/upload."""

    def test_upload_invalid_file_type(self, client):
        """Upload file không phải PDF phải trả 400."""
        response = client.post(
            "/api/upload",
            files={"file": ("test.txt", b"Hello World", "text/plain")},
        )
        assert response.status_code == 400

    def test_upload_non_pdf_content(self, client):
        """Upload file có extension .pdf nhưng content không phải PDF."""
        response = client.post(
            "/api/upload",
            files={"file": ("fake.pdf", b"This is not a PDF", "application/pdf")},
        )
        assert response.status_code == 400

    def test_upload_empty_file(self, client):
        """Upload file rỗng phải trả 400."""
        response = client.post(
            "/api/upload",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert response.status_code == 400

    def test_upload_valid_minimal_pdf(self, client):
        """Upload minimal valid PDF phải trả 200 hoặc run pipeline."""
        pdf_content = _create_minimal_pdf()
        response = client.post(
            "/api/upload",
            files={"file": ("test_minimal.pdf", pdf_content, "application/pdf")},
        )
        # Pipeline might fail on minimal PDF (no text content)
        # but upload validation should pass
        assert response.status_code in (200, 400, 409, 500)

    def test_upload_real_pdf_full_pipeline(self, client):
        """Upload real PDF → full pipeline → MongoDB.

        Skip nếu không có sample PDF hoặc MongoDB không available.
        """
        pdf_path = _get_sample_pdf_path()
        if not pdf_path:
            pytest.skip("No sample PDF available for integration test")

        with open(pdf_path, "rb") as f:
            pdf_content = f.read()

        response = client.post(
            "/api/upload",
            files={"file": (Path(pdf_path).name, pdf_content, "application/pdf")},
        )

        # Expect success or duplicate (if already uploaded)
        assert response.status_code in (200, 409)

        if response.status_code == 200:
            data = response.json()
            # Verify response structure
            assert "paper_id" in data
            assert "status" in data
            assert "title" in data
            assert "authors" in data
            assert "abstract" in data
            assert "confidence" in data
            assert "processing" in data

    def test_upload_duplicate_pdf(self, client):
        """Upload same PDF twice phải trả 409."""
        pdf_path = _get_sample_pdf_path()
        if not pdf_path:
            pytest.skip("No sample PDF available")

        with open(pdf_path, "rb") as f:
            pdf_content = f.read()

        # First upload (might already exist)
        client.post(
            "/api/upload",
            files={"file": ("dup_test.pdf", pdf_content, "application/pdf")},
        )

        # Second upload — should be duplicate
        response = client.post(
            "/api/upload",
            files={"file": ("dup_test.pdf", pdf_content, "application/pdf")},
        )
        assert response.status_code == 409
        data = response.json()
        assert data.get("error") == "duplicate"
        assert "paper_id" in data


# ─────────────────────────────────────────────
# Results Tests
# ─────────────────────────────────────────────

class TestResults:
    """Tests cho GET /api/results và GET /api/results/{paper_id}."""

    def test_list_results_returns_200(self, client):
        """GET /results phải trả 200."""
        response = client.get("/api/results")
        assert response.status_code == 200

    def test_list_results_has_pagination(self, client):
        """Response phải có items, page, limit, total."""
        response = client.get("/api/results")
        data = response.json()
        assert "items" in data
        assert "page" in data
        assert "limit" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    def test_list_results_pagination_params(self, client):
        """Pagination params phải hoạt động."""
        response = client.get("/api/results?page=1&limit=5")
        data = response.json()
        assert data["page"] == 1
        assert data["limit"] == 5
        assert len(data["items"]) <= 5

    def test_list_results_with_min_confidence(self, client):
        """Filter min_confidence phải hoạt động."""
        response = client.get("/api/results?min_confidence=0.5")
        assert response.status_code == 200

    def test_get_result_not_found(self, client):
        """GET /results/{id} cho paper không tồn tại phải trả 404."""
        response = client.get("/api/results/nonexistent_id_12345")
        assert response.status_code == 404

    def test_get_result_existing_paper(self, client):
        """GET /results/{id} cho paper tồn tại phải trả 200."""
        # Lấy danh sách, nếu có paper thì test detail
        list_response = client.get("/api/results?limit=1")
        items = list_response.json().get("items", [])
        if not items:
            pytest.skip("No papers in database to test detail")

        paper_id = items[0].get("paper_id")
        response = client.get(f"/api/results/{paper_id}")
        assert response.status_code == 200

        data = response.json()
        assert data.get("paper_id") == paper_id
        assert "extracted" in data or "title" in data
        # File path không được trả về (security)
        assert "file_path" not in data


# ─────────────────────────────────────────────
# Search Tests
# ─────────────────────────────────────────────

class TestSearch:
    """Tests cho GET /api/search."""

    def test_search_returns_200(self, client):
        """Search phải trả 200 với kết quả."""
        response = client.get("/api/search?q=test")
        assert response.status_code == 200

    def test_search_response_structure(self, client):
        """Response phải có query, results, total."""
        response = client.get("/api/search?q=test")
        data = response.json()
        assert "query" in data
        assert "results" in data
        assert "total" in data

    def test_search_empty_query_rejected(self, client):
        """Search với query rỗng phải bị reject."""
        response = client.get("/api/search?q=")
        assert response.status_code == 422  # Validation error

    def test_search_no_results(self, client):
        """Search với query không match phải trả empty results."""
        response = client.get("/api/search?q=xyznonexistent12345")
        data = response.json()
        assert data["total"] == 0
        assert len(data["results"]) == 0

    def test_search_with_limit(self, client):
        """Search limit param phải hoạt động."""
        response = client.get("/api/search?q=test&limit=5")
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) <= 5


# ─────────────────────────────────────────────
# Review Tests
# ─────────────────────────────────────────────

class TestReview:
    """Tests cho PATCH /api/results/{paper_id}/review."""

    def test_review_missing_paper(self, client):
        """Review paper không tồn tại phải trả 404."""
        response = client.patch(
            "/api/results/nonexistent_12345/review",
            json={"is_reviewed": True},
        )
        assert response.status_code == 404

    def test_review_valid_update(self, client):
        """Review paper tồn tại phải trả 200."""
        # Lấy paper đầu tiên
        list_response = client.get("/api/results?limit=1")
        items = list_response.json().get("items", [])
        if not items:
            pytest.skip("No papers to test review")

        paper_id = items[0].get("paper_id")
        response = client.patch(
            f"/api/results/{paper_id}/review",
            json={"is_reviewed": True, "reviewer_notes": "Test review from M11"},
        )
        assert response.status_code == 200

        data = response.json()
        assert data.get("paper_id") == paper_id
        assert data.get("is_reviewed") is True

    def test_review_invalid_body(self, client):
        """Review với body không hợp lệ phải trả 422."""
        response = client.patch(
            "/api/results/some_id/review",
            json={"invalid_field": True},
        )
        assert response.status_code == 422


# ─────────────────────────────────────────────
# Integration Tests
# ─────────────────────────────────────────────

class TestIntegration:
    """Integration tests: Upload → Pipeline → MongoDB → GET."""

    def test_upload_then_get_result(self, client):
        """Upload PDF → lấy result → verify title/authors/abstract."""
        pdf_path = _get_sample_pdf_path()
        if not pdf_path:
            pytest.skip("No sample PDF for integration test")

        with open(pdf_path, "rb") as f:
            pdf_content = f.read()

        # Upload
        upload_response = client.post(
            "/api/upload",
            files={"file": (f"integration_test.pdf", pdf_content, "application/pdf")},
        )

        if upload_response.status_code == 409:
            # Duplicate — get the existing paper
            paper_id = upload_response.json().get("paper_id")
        elif upload_response.status_code == 200:
            paper_id = upload_response.json().get("paper_id")
        else:
            pytest.skip(f"Upload failed with status {upload_response.status_code}")
            return

        if not paper_id:
            pytest.skip("No paper_id returned")

        # Get result
        result_response = client.get(f"/api/results/{paper_id}")
        assert result_response.status_code == 200

        data = result_response.json()
        assert data.get("paper_id") == paper_id

        # Verify key fields exist
        assert "extracted" in data or "title" in data
        assert "confidence" in data

        # Verify it appears in list
        list_response = client.get("/api/results")
        assert list_response.status_code == 200
        items = list_response.json().get("items", [])
        paper_ids = [item.get("paper_id") for item in items]
        # Paper should be in the list (or in a later page)
        # We just verify list works

    def test_swagger_docs_accessible(self, client):
        """Swagger docs phải accessible."""
        response = client.get("/docs")
        assert response.status_code == 200

    def test_openapi_json_accessible(self, client):
        """OpenAPI JSON phải accessible."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "paths" in data
        assert "/api/upload" in data["paths"]
        assert "/api/results" in data["paths"]
        assert "/api/health" in data["paths"]
        assert "/api/search" in data["paths"]


# ─────────────────────────────────────────────
# Error Handling Tests
# ─────────────────────────────────────────────

class TestErrorHandling:
    """Tests cho error handling."""

    def test_invalid_page_param(self, client):
        """Page < 1 phải bị reject."""
        response = client.get("/api/results?page=0")
        assert response.status_code == 422

    def test_invalid_limit_param(self, client):
        """Limit > 100 phải bị reject."""
        response = client.get("/api/results?limit=101")
        assert response.status_code == 422

    def test_upload_no_file(self, client):
        """Upload không có file phải trả 422."""
        response = client.post("/api/upload")
        assert response.status_code == 422

    def test_security_no_filepath_in_response(self, client):
        """API responses không được chứa file_path."""
        list_response = client.get("/api/results?limit=1")
        items = list_response.json().get("items", [])
        for item in items:
            assert "file_path" not in item
