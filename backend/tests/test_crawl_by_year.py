from pathlib import Path
import hashlib

import pytest
from bs4 import BeautifulSoup
from fastapi import HTTPException

from app.routers.scraper_router import _has_pipeline_result, _normalize_year_range
from infrastructure.scraper.publication_date import PublicationDate, PublicationDateExtractor
from infrastructure.scraper.scraped_pdf_path import ScrapedPDFPathBuilder
from infrastructure.scraper.adapters.ojs import OJSSiteAdapter
from infrastructure.scraper.pdf_scraper import PDFScraper
from infrastructure.database.persistence_service import PersistenceService
from core.pipeline.full_pipeline import PipelineResult
from core.title_detection.rules import is_noise
from core.author_detection.cleaner import AuthorCleaner
from core.validators.abstract_validator import AbstractValidator


def test_publication_date_prefers_html_metadata():
    soup = BeautifulSoup(
        '<meta name="citation_publication_date" content="2024/03/20">',
        "lxml",
    )
    result = PublicationDateExtractor(current_year=2026).extract(soup)
    assert (result.year, result.source) == (2024, "meta:citation_publication_date")


def test_publication_date_reads_json_ld_and_falls_back_to_issue_year():
    json_ld = '<script type="application/ld+json">{"datePublished":"2023-08-15"}</script>'
    assert PublicationDateExtractor(current_year=2026).extract(
        BeautifulSoup(json_ld, "lxml")
    ).year == 2023
    assert PublicationDateExtractor(current_year=2026).extract(
        BeautifulSoup("<html></html>", "lxml"), inherited_year=2022
    ).source == "issue-or-archive"


def test_publication_date_never_uses_a_random_year_from_article_text():
    extractor = PublicationDateExtractor(current_year=2026)
    article = BeautifulSoup(
        "<h1>Study conducted from 2021 to 2023</h1>"
        "<p>Reference published in 1999</p>",
        "lxml",
    )
    result = extractor.extract(article, inherited_year=2024)
    assert (result.year, result.source) == (2024, "issue-or-archive")

    labeled = BeautifulSoup(
        "<div><span>Ngày xuất bản:</span><span>20/04/2025</span></div>",
        "lxml",
    )
    result = extractor.extract(labeled, inherited_year=2024)
    assert (result.year, result.source) == (2025, "published-label")


def test_publication_date_url_is_last_resort_and_unknown_stays_unknown():
    extractor = PublicationDateExtractor(current_year=2026)
    assert extractor.extract(BeautifulSoup("<html></html>", "lxml"), "/2021/article").source == "url"
    assert extractor.extract(BeautifulSoup("<html></html>", "lxml")).year is None


def test_scraped_pdf_path_is_domain_year_and_windows_safe(tmp_path: Path):
    path = ScrapedPDFPathBuilder(tmp_path).build_path(
        "https://www.tapchiyhocvietnam.vn/article/view/123",
        2024,
        'long:title?.pdf',
    )
    assert path == tmp_path.resolve() / "tapchiyhocvietnam.vn" / "2024" / "long-title.pdf"


def test_year_range_is_inclusive_and_future_end_is_capped(monkeypatch):
    monkeypatch.setattr("app.routers.scraper_router.settings.MAX_YEAR_RANGE", 20)
    assert _normalize_year_range(2022, 2024) == (2022, 2024)
    assert _normalize_year_range(2025, 2100)[1] <= 2026
    with pytest.raises(HTTPException):
        _normalize_year_range(2024, 2022)


def test_lightweight_crawl_record_is_not_treated_as_extracted(monkeypatch):
    monkeypatch.setattr(
        "app.routers.scraper_router.settings.LLM_VALIDATE_ALL_FIELDS", False
    )
    assert not _has_pipeline_result({"processing": {"steps_completed": ["scrape"]}})
    assert not _has_pipeline_result(
        {"processing": {"steps_completed": ["scrape", "precheck"]}}
    )
    assert _has_pipeline_result(
        {"processing": {"steps_completed": ["precheck", "text_extraction"]}}
    )


def test_ojs_skips_out_of_range_issue_before_discovering_articles():
    issue_url = "https://journal.example/issue/view/1"
    issue_html = """
        <html><head><meta name='citation_publication_date' content='2021-01-01'></head>
        <body><a href='/article/view/one'>Paper</a></body></html>
    """
    adapter = OJSSiteAdapter()

    def fetch_page(url):
        assert url == issue_url
        return issue_html, url

    articles = adapter.discover_articles(
        issue_url,
        BeautifulSoup("<html></html>", "lxml"),
        fetch_page,
        start_year=2024,
        end_year=2024,
    )
    assert articles == []


def test_ojs_reads_structured_published_block_before_collecting_articles():
    """OJS may publish an issue date in its semantic published block, not meta."""
    issue_url = "https://journal.example/issue/view/special"
    issue_html = """
        <div class='published'><span>Date Published:</span><span>06/04/2026</span></div>
        <a href='/article/view/one'>Paper</a>
    """

    articles = OJSSiteAdapter().discover_articles(
        issue_url,
        BeautifulSoup("<html></html>", "lxml"),
        lambda url: (issue_html, url),
        start_year=2024,
        end_year=2025,
    )

    assert articles == []


def test_ojs_keeps_article_order_from_the_issue_page():
    """Repeated crawls must select the same articles before a result limit."""
    issue_url = "https://journal.example/issue/view/2024"
    issue_html = """
        <html><head><meta name='citation_publication_date' content='2024-01-01'></head>
        <body>
            <a href='/article/view/first'>First</a>
            <a href='/article/view/second'>Second</a>
            <a href='/article/view/first'>Duplicate first</a>
            <a href='/article/view/third'>Third</a>
        </body></html>
    """

    def fetch_page(url):
        assert url == issue_url
        return issue_html, url

    articles = OJSSiteAdapter().discover_articles(
        issue_url,
        BeautifulSoup("<html></html>", "lxml"),
        fetch_page,
        start_year=2024,
        end_year=2024,
    )
    assert articles == [
        "https://journal.example/article/view/first",
        "https://journal.example/article/view/second",
        "https://journal.example/article/view/third",
    ]


def test_ojs_collects_direct_pdf_galleys_from_issue_page():
    issue_url = "https://journal.example/index.php/vmj/issue/view/2024-special"
    issue_html = """
        <meta name='citation_publication_date' content='2024-06-01'>
        <a href='/index.php/vmj/article/view/article-1'>Title</a>
        <a href='/index.php/vmj/article/view/article-1/galley-1'>PDF</a>
    """
    adapter = OJSSiteAdapter()

    articles = adapter.discover_articles(
        issue_url,
        BeautifulSoup("<html></html>", "lxml"),
        lambda url: (issue_html, url),
        start_year=2024,
        end_year=2024,
    )

    article_url = "https://journal.example/index.php/vmj/article/view/article-1"
    assert articles == [article_url]
    assert adapter.article_pdf_urls[article_url] == [
        "https://journal.example/index.php/vmj/article/download/article-1/galley-1"
    ]


def test_scraper_uses_issue_galley_without_refetching_article(monkeypatch, tmp_path: Path):
    from infrastructure.scraper.pdf_scraper import scrape_status

    article_url = "https://journal.example/article/view/1"
    pdf_url = "https://journal.example/article/download/1/1"

    class DirectOJS:
        name = "OJS"
        article_years = {article_url: 2024}
        article_pdf_urls = {article_url: [pdf_url]}

        def discover_articles(self, *_args, **_kwargs):
            return [article_url]

        def find_pdf_urls(self, *_args, **_kwargs):
            raise AssertionError("The direct issue galley should be used")

    scraper = PDFScraper(output_dir=str(tmp_path))
    scraper._start_year = scraper._end_year = 2024
    monkeypatch.setattr(scraper, "_fetch_page", lambda *_: (_ for _ in ()).throw(AssertionError("Unexpected article fetch")))
    monkeypatch.setattr("infrastructure.scraper.pdf_scraper.settings.CRAWL_DISCOVERY_WORKERS", 1)
    scrape_status.reset()

    assert scraper._discover_with_adapter(DirectOJS(), article_url, BeautifulSoup("<html></html>", "lxml"), 2) == [pdf_url]
    assert scraper._pdf_article_urls[pdf_url] == article_url
    assert scraper._pdf_publications[pdf_url].year == 2024


def test_download_defers_metadata_extraction_until_the_pdf_pipeline(monkeypatch, tmp_path: Path):
    """Downloading a PDF must not make another request to its article page."""
    from infrastructure.scraper.pdf_scraper import scrape_status

    pdf_url = "https://journal.example/article/download/1/1"
    article_url = "https://journal.example/article/view/1"
    content = b"%PDF-1.7\n" + (b"x" * 1100)
    requested_urls = []

    class FakeResponse:
        headers = {"Content-Type": "application/pdf", "Content-Length": str(len(content))}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield content

        def close(self):
            return None

    class FakeRepo:
        def get_by_hash(self, _file_hash):
            return None

    scraper = PDFScraper(output_dir=str(tmp_path))
    scraper._start_year = scraper._end_year = 2024
    monkeypatch.setattr(
        scraper,
        "_safe_get",
        lambda url, **_kwargs: requested_urls.append(url) or FakeResponse(),
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page",
        lambda *_: (_ for _ in ()).throw(AssertionError("article metadata must be deferred")),
    )
    monkeypatch.setattr(
        "infrastructure.database.repositories.paper_repository.PaperRepository",
        FakeRepo,
    )
    scrape_status.reset()

    record = scraper._download_and_save_pdf(
        pdf_url,
        article_url,
        PublicationDate(2024, "2024-01-01", "detected", "meta:citation_publication_date"),
    )

    assert requested_urls == [pdf_url]
    assert record is not None
    assert record["filename"].startswith("pdf_")
    assert record["extracted"] == {"title": "", "authors": [], "abstract": ""}
    assert Path(record["file_path"]).is_file()


def test_source_citation_metadata_is_read_only_during_explicit_extraction(monkeypatch):
    scraper = PDFScraper()
    html = """
        <meta name="citation_title" content="A structured article title">
        <meta name="citation_author" content="Nguyen Van A">
        <meta name="citation_author" content="Tran Thi B">
        <meta name="citation_abstract" content="A complete abstract from the journal page.">
    """
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: (html, "https://journal.example/article/1"))

    assert scraper.extract_source_metadata("https://journal.example/article/1") == {
        "title": "A structured article title",
        "authors": ["Nguyen Van A", "Tran Thi B"],
        "abstract": "A complete abstract from the journal page.",
        "source_url": "https://journal.example/article/1",
    }


def test_source_metadata_prefers_vietnamese_abstract_when_both_exist(monkeypatch):
    scraper = PDFScraper()
    english = "This study reports the clinical characteristics and treatment outcomes of patients."
    vietnamese = "Nghiên cứu mô tả đặc điểm lâm sàng và đánh giá kết quả điều trị của người bệnh."
    html = f"""
        <meta name="citation_abstract" content="{english}">
        <meta name="dc.description" content="{vietnamese}">
    """
    monkeypatch.setattr(scraper, "_fetch_page", lambda _url: (html, "https://journal.example/article/2"))

    metadata = scraper.extract_source_metadata("https://journal.example/article/2")

    assert metadata["abstract"] == vietnamese


def test_source_metadata_wins_over_a_low_quality_pdf_candidate():
    result = PipelineResult(
        title="TẠP CHÍ Y HỌC VIỆT NAM TẬP 554 - THÁNG 9 - SỐ 1 - 2025",
        authors=["nhiều nhất là 400ml"],
        abstract="A short broken PDF candidate.",
    )
    source = {
        "title": "Facial shape analysis in medical students",
        "authors": ["Nguyen Van A", "Tran Thi B"],
        "abstract": "This study describes facial shape classification in medical students. It reports a clear and complete research summary with methods and results.",
    }

    _, provenance = PersistenceService._apply_source_metadata(result, source)

    assert result.title == source["title"]
    assert result.authors == source["authors"]
    assert result.abstract == source["abstract"]
    assert provenance == {
        "title": "article_citation_metadata",
        "authors": "article_citation_metadata",
        "abstract": "article_citation_metadata",
    }
    assert result.confidence["overall"] < 1.0


def test_english_source_abstract_does_not_replace_vietnamese_pdf_abstract():
    vietnamese = (
        "Nghiên cứu này mô tả đặc điểm lâm sàng của người bệnh và đánh giá kết quả "
        "điều trị. Kết quả cho thấy phương pháp mang lại hiệu quả rõ rệt."
    )
    result = PipelineResult(
        title="Tiêu đề từ PDF",
        authors=["Nguyễn Văn A"],
        abstract=vietnamese,
    )
    source = {
        "title": "Structured source title",
        "authors": ["Nguyen Van A"],
        "abstract": "This study describes clinical characteristics and treatment outcomes in patients.",
    }

    _, provenance = PersistenceService._apply_source_metadata(result, source)

    assert result.abstract == vietnamese
    assert provenance["abstract"] == "pdf_pipeline"


def test_quality_rules_reject_masthead_body_text_and_keyword_leakage():
    assert is_noise("TẠP CHÍ Y HỌC VIỆT NAM TẬP 554 - THÁNG 9 - SỐ 1 - 2025")
    assert AuthorCleaner().split_and_clean("nhiều nhất là 400ml") == []
    leaked = (
        "The last sentence of an abstract. Từ khóa: medical data, research. "
        "SUMMARY This text continues with a different section and should not be accepted."
    )
    assert AbstractValidator.validate(leaked).score < 1.0


def test_ojs_discovers_all_articles_in_the_requested_year_range(monkeypatch):
    """Discovery is complete; the save quota belongs to PDFScraper."""
    archive_url = "https://journal.example/issue/archive"
    archive_html = """
        <a href='/issue/view/2025-a'>Vol. 2025 A</a>
        <a href='/issue/view/2025-b'>Vol. 2025 B</a>
        <a href='/issue/view/2024-a'>Vol. 2024 A</a>
        <a href='/issue/view/2024-b'>Vol. 2024 B</a>
    """
    pages = {
        archive_url: archive_html,
        "https://journal.example/issue/view/2025-a": """
            <meta name='citation_publication_date' content='2025-01-01'>
            <a href='/article/view/2025-1'>A</a><a href='/article/view/2025-2'>B</a>
        """,
        "https://journal.example/issue/view/2025-b": """
            <meta name='citation_publication_date' content='2025-02-01'>
            <a href='/article/view/2025-3'>C</a><a href='/article/view/2025-4'>D</a>
        """,
        "https://journal.example/issue/view/2024-a": """
            <meta name='citation_publication_date' content='2024-01-01'>
            <a href='/article/view/2024-1'>A</a><a href='/article/view/2024-2'>B</a>
        """,
        "https://journal.example/issue/view/2024-b": """
            <meta name='citation_publication_date' content='2024-02-01'>
            <a href='/article/view/2024-3'>C</a><a href='/article/view/2024-4'>D</a>
        """,
    }

    def fetch_page(url):
        return pages.get(url), url

    monkeypatch.setattr("infrastructure.scraper.adapters.ojs.time.sleep", lambda *_: None)
    articles = OJSSiteAdapter().discover_articles(
        archive_url,
        BeautifulSoup(archive_html, "lxml"),
        fetch_page,
        start_year=2024,
        end_year=2025,
    )

    assert articles == [
        "https://journal.example/article/view/2025-1",
        "https://journal.example/article/view/2025-2",
        "https://journal.example/article/view/2025-3",
        "https://journal.example/article/view/2025-4",
        "https://journal.example/article/view/2024-1",
        "https://journal.example/article/view/2024-2",
        "https://journal.example/article/view/2024-3",
        "https://journal.example/article/view/2024-4",
    ]


def test_ojs_discovers_archive_pages_beyond_the_old_19_page_ceiling(monkeypatch):
    """Older issues remain reachable when OJS paginates a long archive."""
    archive_url = "https://journal.example/issue/archive"
    pages = {}
    for page_number in range(1, 21):
        page_url = archive_url if page_number == 1 else f"{archive_url}/{page_number}"
        issue_url = f"https://journal.example/issue/view/{page_number}"
        pages[page_url] = f"<a href='/issue/view/{page_number}'>Issue {page_number}</a>"
        pages[issue_url] = (
            "<meta name='citation_publication_date' content='2024-01-01'>"
            f"<a href='/article/view/paper-{page_number}'>Paper</a>"
        )

    monkeypatch.setattr("infrastructure.scraper.adapters.ojs.time.sleep", lambda *_: None)
    articles = OJSSiteAdapter().discover_articles(
        archive_url,
        BeautifulSoup(pages[archive_url], "lxml"),
        lambda url: (pages.get(url, "<html></html>"), url),
        start_year=2024,
        end_year=2024,
    )

    assert len(articles) == 20
    assert articles[-1] == "https://journal.example/article/view/paper-20"


def test_ojs_uses_issue_metadata_for_special_issue_year(monkeypatch):
    """Special-issue link text and archive headings never decide the year."""
    archive_url = "https://journal.example/issue/archive"
    archive_html = """
        <h2>2026</h2><a href='/issue/view/newest'>Publisher title only</a>
        <h2>2024</h2><a href='/issue/view/in-range'>Conference title only</a>
    """
    pages = {
        archive_url: archive_html,
        "https://journal.example/issue/view/newest": """
            <meta name='citation_publication_date' content='2026-02-01'>
            <a href='/article/view/2026-paper'>Paper</a>
        """,
        "https://journal.example/issue/view/in-range": """
            <meta name='citation_publication_date' content='2024-06-01'>
            <a href='/article/view/2024-paper'>Paper</a>
        """,
    }

    monkeypatch.setattr("infrastructure.scraper.adapters.ojs.time.sleep", lambda *_: None)
    articles = OJSSiteAdapter().discover_articles(
        archive_url,
        BeautifulSoup(archive_html, "lxml"),
        lambda url: (pages.get(url), url),
        start_year=2024,
        end_year=2024,
    )

    assert articles == ["https://journal.example/article/view/2024-paper"]


def test_scraper_skips_known_urls_then_uses_quota_for_new_pdfs(monkeypatch, tmp_path: Path):
    """A later new PDF must be saved after earlier URLs are duplicates."""
    from infrastructure.scraper import pdf_scraper as scraper_module
    from infrastructure.scraper.pdf_scraper import scrape_status

    duplicate = "https://journal.example/article/download/known"
    fresh_urls = [
        "https://journal.example/article/download/new-1",
        "https://journal.example/article/download/new-2",
        "https://journal.example/article/download/new-3",
    ]
    calls: list[str] = []
    scraper = PDFScraper(output_dir=str(tmp_path))

    monkeypatch.setattr(scraper_module, "MAX_PDFS", 2)
    monkeypatch.setattr(
        scraper_module.SiteDetector,
        "detect",
        lambda *_: type("OJSAdapter", (), {"name": "OJS"})(),
    )
    monkeypatch.setattr(scraper, "_is_medical_content", lambda *_: True)
    monkeypatch.setattr(scraper, "_fetch_page", lambda url: ("<html></html>", url))
    monkeypatch.setattr(scraper, "_discover_with_adapter", lambda *_: [duplicate, *fresh_urls])
    monkeypatch.setattr(scraper, "_load_stored_hashes", lambda: set())
    monkeypatch.setattr(scraper, "_load_stored_pdf_urls", lambda: {duplicate})
    # This test exercises the legacy quota rule only. Keep it hermetic rather
    # than attempting a real MongoDB connection for the optional manifest.
    monkeypatch.setattr(scraper, "_get_manifest_store", lambda: None)
    monkeypatch.setattr(scraper, "_check_robots_txt", lambda *_: True)
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        scraper_module.time,
        "sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    def download(pdf_url, *_args):
        calls.append(pdf_url)
        return {
            "paper_id": str(len(calls)), "filename": f"{len(calls)}.pdf",
            "publication_year": 2024,
        }

    monkeypatch.setattr(scraper, "_download_and_save_pdf", download)
    scrape_status.reset()
    assert scrape_status.try_start()

    scraper.scrape("https://journal.example/archive", status_started=True)

    assert scrape_status.total_found == 4
    assert scrape_status.duplicates == 1
    assert scrape_status.downloaded == 2
    assert calls == fresh_urls[:2]
    # The final successful download reaches the quota and must break before
    # another rate-limit sleep. Processed candidates may exceed the download
    # quota because duplicates are inspected but never counted as new PDFs.
    assert len(sleep_calls) == 1
    assert scrape_status.batch_processed == 3


def test_scraper_indexes_existing_files_for_duplicate_detection(tmp_path: Path):
    """A stopped crawl's local PDF remains duplicate-safe without MongoDB."""
    content = b"%PDF-1.7\nexisting corpus file"
    stored = tmp_path / "journal.example" / "2024" / "paper.pdf"
    stored.parent.mkdir(parents=True)
    stored.write_bytes(content)

    scraper = PDFScraper(output_dir=str(tmp_path))
    assert scraper._load_stored_hashes() == {hashlib.sha256(content).hexdigest()}


class _FakeManifestStore:
    """In-memory manifest double for crawler lifecycle tests."""

    def __init__(self):
        self.manifest: dict | None = None
        self.rows: list[dict] = []
        self.retries: list[tuple[str, str]] = []
        self.replace_calls = 0

    def find_ready(self, *_args):
        return self.manifest

    def replace_ready(self, *_args):
        candidates = _args[-1]
        self.replace_calls += 1
        self.manifest = {
            "manifest_id": "manifest-1",
            "candidate_total": len(candidates),
            "pending_count": len(candidates),
        }
        self.rows = [
            {**candidate, "state": "pending", "position": position}
            for position, candidate in enumerate(candidates, 1)
        ]
        return self.manifest

    def pending_candidates(self, _manifest_id):
        return [row.copy() for row in self.rows if row["state"] == "pending"]

    def mark_terminal(self, _manifest_id, pdf_url, state):
        for row in self.rows:
            if row["pdf_url"] == pdf_url and row["state"] == "pending":
                row["state"] = state
                return True
        return False

    def record_retry(self, _manifest_id, pdf_url, error=""):
        self.retries.append((pdf_url, error))

    def mark_known_urls(self, _manifest_id, urls, state="duplicate"):
        known = set(urls)
        count = 0
        for row in self.rows:
            if row["state"] == "pending" and row["pdf_url"] in known:
                row["state"] = state
                count += 1
        return count


def _configure_manifest_scraper(monkeypatch, scraper, candidates, stored_urls=None):
    """Stub network discovery/download prerequisites for manifest tests."""
    from infrastructure.scraper import pdf_scraper as scraper_module

    monkeypatch.setattr(
        scraper_module.SiteDetector,
        "detect",
        lambda *_: type("OJSAdapter", (), {"name": "OJS"})(),
    )
    monkeypatch.setattr(scraper, "_is_medical_content", lambda *_: True)
    monkeypatch.setattr(scraper, "_fetch_page", lambda url: ("<html></html>", url))
    monkeypatch.setattr(scraper, "_discover_with_adapter", lambda *_: list(candidates))
    monkeypatch.setattr(scraper, "_load_stored_hashes", lambda: set())
    monkeypatch.setattr(scraper, "_load_stored_pdf_urls", lambda: set(stored_urls or ()))
    monkeypatch.setattr(scraper, "_check_robots_txt", lambda *_: True)
    monkeypatch.setattr(scraper_module.time, "sleep", lambda *_: None)


def test_manifest_resumes_next_batch_without_rediscovering(monkeypatch, tmp_path: Path):
    """The next quota batch reads only pending rows from the durable catalog."""
    from infrastructure.scraper import pdf_scraper as scraper_module
    from infrastructure.scraper.pdf_scraper import scrape_status

    known = "https://journal.example/article/download/known"
    fresh = [
        "https://journal.example/article/download/new-1",
        "https://journal.example/article/download/new-2",
        "https://journal.example/article/download/new-3",
    ]
    store = _FakeManifestStore()
    scraper = PDFScraper(output_dir=str(tmp_path))
    _configure_manifest_scraper(monkeypatch, scraper, [known, *fresh], {known})
    monkeypatch.setattr(scraper_module, "MAX_PDFS", 2)
    monkeypatch.setattr(scraper, "_get_manifest_store", lambda: store)

    downloads: list[str] = []

    def download(pdf_url, *_args):
        downloads.append(pdf_url)
        return {"paper_id": pdf_url, "filename": f"{len(downloads)}.pdf", "pdf_url": pdf_url}

    monkeypatch.setattr(scraper, "_download_and_save_pdf", download)
    scrape_status.reset()
    assert scrape_status.try_start()
    scraper.scrape("https://journal.example/archive", status_started=True)

    first_records = scrape_status.snapshot_pdf_records()
    scraper.finalize_manifest_records(
        first_records, {record["pdf_url"] for record in first_records}
    )
    assert downloads == fresh[:2]
    assert [row["state"] for row in store.rows] == [
        "duplicate", "saved", "saved", "pending"
    ]

    def should_not_rediscover(*_args):
        raise AssertionError("A ready manifest must avoid rediscovery")

    monkeypatch.setattr(scraper, "_discover_with_adapter", should_not_rediscover)
    scrape_status.reset()
    assert scrape_status.try_start()
    scraper.scrape("https://journal.example/archive", status_started=True)

    assert downloads == fresh
    assert store.replace_calls == 1


def test_manifest_keeps_transient_failure_pending_and_finalizes_terminal_states(
    monkeypatch, tmp_path: Path
):
    """Only retryable download failures remain in the next crawl queue."""
    from infrastructure.scraper.pdf_scraper import scrape_status

    stored = "https://journal.example/article/download/stored"
    robots = "https://journal.example/article/download/robots"
    invalid = "https://journal.example/article/download/invalid"
    retry = "https://journal.example/article/download/retry"
    store = _FakeManifestStore()
    scraper = PDFScraper(output_dir=str(tmp_path))
    _configure_manifest_scraper(
        monkeypatch, scraper, [stored, robots, invalid, retry], {stored}
    )
    monkeypatch.setattr(scraper, "_get_manifest_store", lambda: store)
    monkeypatch.setattr(scraper, "_check_robots_txt", lambda pdf_url: pdf_url != robots)

    def download(pdf_url, *_args):
        scraper._last_download_outcome = "invalid" if pdf_url == invalid else "retry"
        return None

    monkeypatch.setattr(scraper, "_download_and_save_pdf", download)
    scrape_status.reset()
    assert scrape_status.try_start()
    scraper.scrape("https://journal.example/archive", status_started=True)

    states = {row["pdf_url"]: row["state"] for row in store.rows}
    assert states == {
        stored: "duplicate",
        robots: "blocked",
        invalid: "invalid",
        retry: "pending",
    }
    assert store.retries and store.retries[0][0] == retry


def test_incomplete_ojs_discovery_is_never_published_as_a_manifest(
    monkeypatch, tmp_path: Path
):
    """A transient metadata failure cannot make papers disappear from later runs."""
    from infrastructure.scraper.pdf_scraper import scrape_status

    store = _FakeManifestStore()
    scraper = PDFScraper(output_dir=str(tmp_path))
    candidate = "https://journal.example/article/download/one"
    _configure_manifest_scraper(monkeypatch, scraper, [candidate])
    monkeypatch.setattr(scraper, "_get_manifest_store", lambda: store)

    def incomplete_discovery(*_args):
        scraper._discovery_complete = False
        return [candidate]

    monkeypatch.setattr(scraper, "_discover_with_adapter", incomplete_discovery)
    monkeypatch.setattr(
        scraper,
        "_download_and_save_pdf",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not download partial catalog")),
    )
    scrape_status.reset()
    assert scrape_status.try_start()
    scraper.scrape("https://journal.example/archive", status_started=True)

    assert store.replace_calls == 0


def test_router_finalizes_manifest_only_after_record_persistence(monkeypatch):
    """The router owns the final saved/duplicate transition after MongoDB."""
    from pymongo.errors import DuplicateKeyError

    import app.routers.scraper_router as scraper_router
    from infrastructure.scraper.pdf_scraper import scrape_status

    saved_url = "https://journal.example/article/download/saved"
    duplicate_url = "https://journal.example/article/download/duplicate"

    class FakeScraper:
        def __init__(self):
            self.finalized = None

        def scrape(self, **_kwargs):
            for pdf_url in (saved_url, duplicate_url):
                scrape_status.add_pdf_record({"paper_id": pdf_url, "pdf_url": pdf_url})

        def finalize_manifest_records(self, records, persisted_urls, duplicate_urls):
            self.finalized = (records, persisted_urls, duplicate_urls)

    class FakeRepo:
        def insert_paper(self, record):
            if record["pdf_url"] == duplicate_url:
                raise DuplicateKeyError("duplicate hash")
            return record["paper_id"]

    fake_scraper = FakeScraper()
    monkeypatch.setattr(scraper_router, "_scraper", fake_scraper)
    monkeypatch.setattr(scraper_router, "_get_repo", lambda: FakeRepo())
    monkeypatch.setattr(scraper_router, "validate_public_http_url", lambda url: url)
    scrape_status.reset()

    response = scraper_router.start_scrape(
        scraper_router.ScrapeRequest(url="https://journal.example/archive"), None
    )
    assert response["status"] == "started"
    scraper_router._scrape_thread.join(timeout=2)

    assert fake_scraper.finalized is not None
    _, persisted_urls, duplicate_urls = fake_scraper.finalized
    assert persisted_urls == {saved_url}
    assert duplicate_urls == {duplicate_url}
