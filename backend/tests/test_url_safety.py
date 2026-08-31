"""Regression tests for the scraper's outbound-request trust boundary."""

import socket
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from config.settings import settings
from infrastructure.scraper.url_safety import UnsafeURL, validate_public_http_url
from infrastructure.scraper.pdf_scraper import ScrapeStatus


def _addresses(*values: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (value, 443)) for value in values]


class TestPublicHTTPURLs:
    def test_accepts_public_https_host(self):
        with patch("socket.getaddrinfo", return_value=_addresses("8.8.8.8")):
            assert validate_public_http_url("https://example.org/papers") == "https://example.org/papers"

    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "ftp://example.org/archive",
        "http://localhost:8000/admin",
        "http://127.0.0.1:8000/admin",
        "http://user:password@example.org/private",
    ])
    def test_rejects_non_public_or_non_http_urls(self, url):
        with patch("socket.getaddrinfo", return_value=_addresses("127.0.0.1")):
            with pytest.raises(UnsafeURL):
                validate_public_http_url(url)

    def test_rejects_private_resolved_ip(self):
        with patch("socket.getaddrinfo", return_value=_addresses("10.0.0.7")):
            with pytest.raises(UnsafeURL):
                validate_public_http_url("https://papers.example.org")


class TestScrapeStatus:
    def test_discovery_progress_is_exposed_in_status_snapshot(self):
        status = ScrapeStatus()
        status.try_start()
        status.set_discovery_progress("issues", 37, 379, "https://journal.example/issue/37")

        snapshot = status.to_dict()

        assert snapshot["discovery_phase"] == "issues"
        assert snapshot["discovery_current"] == 37
        assert snapshot["discovery_total"] == 379

    def test_only_one_job_can_reserve_the_in_process_slot(self):
        status = ScrapeStatus()
        assert status.try_start() is True
        assert status.try_start() is False
        assert status.request_stop() is True
        status.complete()
        assert status.try_start() is True


class TestProductionWriteGuard:
    def test_rejects_unauthenticated_mutation_in_production(self, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "API_KEY", "test-key")
        with TestClient(create_app()) as client:
            assert client.post("/api/scrape", json={"url": "https://example.org"}).status_code == 401

    def test_accepts_authenticated_mutation_in_production(self, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "API_KEY", "test-key")
        with TestClient(create_app()) as client:
            response = client.post("/api/scrape", json={"url": "http://127.0.0.1"}, headers={"X-API-Key": "test-key"})
        # Authentication succeeds; the SSRF guard is then responsible for
        # rejecting the unsafe destination.
        assert response.status_code == 400
