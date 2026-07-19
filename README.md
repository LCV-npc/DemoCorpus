# Medical PDF Corpus Builder 🏥📄

> Hệ thống thu thập và xây dựng kho ngữ liệu y tế tiếng Việt

## Tổng quan

**Medical PDF Corpus Builder** là công cụ tự động thu thập bài báo y khoa dạng PDF từ các tạp chí khoa học trực tuyến. Hệ thống hỗ trợ:

- 🌐 **Web Scraper** — Dán URL tạp chí → tự động tìm và tải tất cả PDF
- 📤 **Upload thủ công** — Upload file PDF riêng lẻ
- 🔍 **Pre-check** — Kiểm tra tính hợp lệ (magic bytes, file size, SHA-256 dedup)
- 📊 **Dashboard** — Giao diện web theo dõi realtime

## Cài đặt

### Yêu cầu
- Python 3.10+
- MongoDB (tùy chọn, hệ thống chạy được không cần DB)

### Bước 1: Clone & cài đặt dependencies

```bash
cd "d:\Nghiên cứu khoa học\pdf_collector"
pip install -r requirements.txt
```

### Bước 2: Cấu hình

```bash
# Copy file env mẫu
copy .env.example .env

# Sửa .env nếu cần (MongoDB URI, thư mục lưu trữ, etc.)
```

### Bước 3: Chạy server

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Mở trình duyệt: **http://localhost:8000**

## Cấu trúc project

```
pdf_collector/
├── config/
│   ├── constants.py          # Hằng số, regex, keywords y khoa
│   └── settings.py           # Cấu hình từ .env
├── core/
│   ├── models/
│   │   ├── document.py       # TextBlock, Page, Document
│   │   └── metadata.py       # ExtractedMetadata, FieldConfidence
│   └── pipeline/
│       └── extractor_pipeline.py  # Pre-check logic
├── infrastructure/
│   ├── storage/
│   │   └── file_storage.py   # Lưu trữ file PDF
│   ├── database/
│   │   ├── mongo_client.py   # MongoDB connection
│   │   └── repositories/
│   │       └── paper_repository.py  # CRUD operations
│   └── scraper/
│       └── pdf_scraper.py    # Web crawler
├── app/
│   ├── main.py               # FastAPI application
│   ├── routers/
│   │   └── scraper_router.py # API endpoints
│   └── static/
│       ├── index.html         # Frontend UI
│       ├── index.css          # Styling
│       └── script.js          # Frontend logic
└── tests/
    ├── test_models.py         # Domain model tests
    ├── test_storage.py        # Storage tests
    └── test_pipeline.py       # Pipeline tests
```

## API Endpoints

| Method | Endpoint | Mô tả |
|--------|----------|--------|
| `POST` | `/api/scrape` | Bắt đầu scraping từ URL |
| `GET` | `/api/scrape/status` | Trạng thái scraping realtime |
| `POST` | `/api/scrape/stop` | Dừng scraping |
| `POST` | `/api/upload` | Upload PDF thủ công |
| `GET` | `/api/pdfs` | Danh sách PDF (phân trang) |
| `GET` | `/api/stats` | Thống kê tổng quan |

## Scraper hỗ trợ

- **OJS (Open Journal Systems)** — Tự động phát hiện và crawl archive → issues → articles → PDF
- **Generic website** — BFS crawl tìm tất cả link `.pdf` và `citation_pdf_url`
- **Medical filter** — Lọc nội dung y khoa dựa trên keywords (tiếng Việt + tiếng Anh)

## Chạy tests

```bash
cd "d:\Nghiên cứu khoa học\pdf_collector"
python -m pytest tests/ -v
```

## Milestones

- [x] **Milestone 0** — Foundation: project structure, domain models, config
- [x] **Milestone 1** — PDF pre-check, file storage, SHA-256 hashing, web scraper
- [ ] **Milestone 2** — Text extraction (PyMuPDF)
- [ ] **Milestone 3** — Layout analysis
- [ ] **Milestone 4** — Heuristic metadata extraction
- [ ] **Milestone 5** — NER-based extraction
- [ ] **Milestone 6** — Data cleaning & normalization
- [ ] **Milestone 7** — Validation & scoring
- [ ] **Milestone 8** — LLM enhancement
- [ ] **Milestone 9** — MongoDB persistence
- [ ] **Milestone 10** — Web application (full)

## License

Dự án nghiên cứu khoa học — Sử dụng nội bộ.
