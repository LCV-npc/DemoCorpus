# Kho ngữ liệu Y tế tiếng Việt

Hệ thống thu thập PDF từ các tạp chí y khoa, quản lý kho tài liệu và trích xuất metadata phục vụ xây dựng corpus tiếng Việt. Backend sử dụng FastAPI và MongoDB; frontend là HTML/CSS/JavaScript chạy bằng Vite.

## Chức năng hiện có

- Thu thập PDF từ OJS, liên kết PDF trực tiếp và website y khoa thông thường.
- Lọc tài liệu theo khoảng năm bao gồm cả năm bắt đầu và năm kết thúc.
- Xác định năm từ metadata bài báo, JSON-LD, trường ngày xuất bản và metadata số/tập; URL chỉ là phương án heuristic cuối cùng.
- Với nguồn OJS, khám phá đầy đủ danh mục bài báo trước khi tải; crawler generic duyệt theo độ sâu và giới hạn an toàn. Cả hai đều hiển thị tiến độ và nhật ký theo thời gian thực.
- Lưu manifest crawl trong MongoDB để lần chạy sau tiếp tục phần còn lại mà không phải khám phá lại toàn bộ kho.
- Mỗi lượt lưu tối đa 500 PDF mới; URL đã tồn tại được đánh dấu trùng và không tính vào hạn mức này.
- Crawl và trích xuất metadata là hai giai đoạn riêng biệt, giúp tải PDF nhanh hơn.
- Trích xuất hàng loạt chỉ xử lý PDF chưa trích xuất; hỗ trợ dừng an toàn và trích xuất lại từng bài.
- Pipeline xử lý PDF nhiều cột, phát hiện tiêu đề, tác giả và tóm tắt, làm sạch dữ liệu, kiểm tra chất lượng và chấm confidence.
- Với bài song ngữ, ưu tiên tóm tắt tiếng Việt; dùng `Abstract` hoặc `Summary` tiếng Anh khi không có bản tiếng Việt hợp lệ.
- Chống trùng bằng SHA-256 và URL nguồn.
- Tìm kiếm, phân trang, xem chi tiết metadata và ghi chú kiểm tra tài liệu.
- Upload một PDF riêng lẻ và chạy trực tiếp pipeline đầy đủ.
- Giao diện responsive, có trạng thái loading, empty, error, tiến độ crawl và tiến độ trích xuất.

Hệ thống hiện tập trung vào corpus PDF y khoa. Chức năng hỏi đáp y tế và gán nhãn thực thể chưa được triển khai.

## Luồng xử lý

```text
URL tạp chí
  → kiểm tra URL và nhận diện loại website
  → khám phá số/tập và bài báo trong khoảng năm
  → xác minh năm từ metadata bài báo
  → lưu crawl manifest và danh sách ứng viên vào MongoDB
  → bỏ qua URL/hash đã có, tải tối đa 500 PDF mới mỗi lượt
  → lưu bản ghi nhẹ vào collection papers
  → người dùng yêu cầu trích xuất metadata
  → text extraction → layout/reading order → title/authors/abstract
  → cleaning → validation/confidence → LLM tùy chọn
  → cập nhật metadata vào MongoDB
```

Phần **Kết quả lượt quét** chỉ chứa PDF vừa tải trong tiến trình backend hiện tại và sẽ được làm mới khi bắt đầu lượt crawl mới hoặc khởi động lại backend. Toàn bộ PDF bền vững vẫn nằm trong **Kho tài liệu**.

## Công nghệ

- Python 3.10+
- FastAPI và Uvicorn
- MongoDB và PyMongo
- PyMuPDF
- Beautiful Soup, lxml và Requests
- Gemini qua endpoint tương thích OpenAI ở bước M9, không bắt buộc
- HTML, CSS, JavaScript và Vite
- Pytest

## Cấu trúc dự án

```text
pdf_collector/
├── backend/
│   ├── app/
│   │   ├── routers/              # API paper, crawler và metadata extraction
│   │   ├── schemas/              # Request/response schemas
│   │   └── services/             # Application services
│   ├── config/                   # Settings và hằng số
│   ├── core/
│   │   ├── text_extraction/      # Đọc nội dung PDF
│   │   ├── layout_analysis/      # Cột, vùng và reading order
│   │   ├── title_detection/
│   │   ├── author_detection/
│   │   ├── abstract_detection/   # Tóm tắt song ngữ, ưu tiên tiếng Việt
│   │   ├── data_cleaning/
│   │   ├── validators/
│   │   └── pipeline/
│   ├── infrastructure/
│   │   ├── database/             # MongoDB repositories và persistence
│   │   ├── nlp/                  # NER/LLM loaders
│   │   ├── scraper/              # OJS, generic crawler, year và manifest
│   │   └── storage/
│   ├── tests/
│   ├── data/                     # Dữ liệu runtime, không commit PDF
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── css/index.css
│   ├── js/script.js
│   ├── package.json
│   └── vite.config.js
├── .gitignore
└── README.md
```

## Cài đặt

### 1. Clone repository

```powershell
git clone -b master https://github.com/LCV-npc/DemoCorpus.git pdf_collector
cd pdf_collector
```

### 2. Khởi động MongoDB

Có thể dùng MongoDB cài trực tiếp hoặc Docker:

```powershell
docker run --name medical-corpus-mongo -d -p 27017:27017 mongo:7
```

Không cần script tạo bảng như MySQL. Khi backend sử dụng repository lần đầu, MongoDB sẽ tự tạo database/collection và hệ thống tự tạo index cần thiết.

Các collection chính:

| Collection | Chức năng |
|---|---|
| `papers` | Bản ghi PDF, nguồn, hash, metadata trích xuất, confidence và review |
| `crawl_manifests` | Danh mục crawl theo URL, khoảng năm và trạng thái tổng thể |
| `crawl_candidates` | Hàng đợi từng bài/PDF để tiếp tục các lượt tải sau |
| `processing_jobs` | Trạng thái các job xử lý nhiều tệp |

### 3. Cài đặt và chạy backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload --port 8000
```

Trên macOS/Linux, kích hoạt môi trường bằng `source .venv/bin/activate` và sao chép cấu hình bằng `cp .env.example .env`.

- API: <http://localhost:8000>
- Swagger UI: <http://localhost:8000/docs>
- OpenAPI JSON: <http://localhost:8000/openapi.json>

### 4. Cài đặt và chạy frontend

Mở terminal khác tại thư mục gốc:

```powershell
cd frontend
npm ci
npm run dev
```

Mở <http://localhost:5173>. Vite chuyển tiếp `/api` đến backend tại cổng `8000`.

## Cấu hình môi trường

Tạo `backend/.env` từ `backend/.env.example`. Không commit tệp `.env` hoặc API key.

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `MONGODB_URI` | `mongodb://localhost:27017` | Chuỗi kết nối MongoDB |
| `MONGODB_DB` | `medical_corpus` | Database ứng dụng |
| `MONGODB_TEST_DB` | `pdf_extractor_test` | Database dành cho integration test |
| `UPLOAD_DIR` | `data/uploads` | Nơi lưu PDF upload thủ công |
| `SCRAPE_DIR` | `data/scraped_pdfs` | Nơi lưu PDF tải từ crawler |
| `MAX_FILE_SIZE_MB` | `50` | Kích thước PDF upload tối đa |
| `MAX_YEAR_RANGE` | `20` | Số năm tối đa trong một yêu cầu crawl |
| `UNKNOWN_YEAR_POLICY` | `skip` | `skip` bỏ qua hoặc `store` lưu bài chưa xác định năm |
| `CRAWL_DISCOVERY_WORKERS` | `3` | Số worker kiểm tra metadata số/tập OJS, giới hạn 1–6 |
| `LOG_LEVEL` | `INFO` | Mức log backend |
| `NER_MODEL_PATH` | rỗng | Đường dẫn model NER cục bộ tùy chọn |
| `LLM_MODEL_PATH` | rỗng | Đường dẫn model LLM cục bộ tùy chọn |
| `GEMINI_API_KEY` | rỗng | Bật lớp kiểm tra M9 bằng Gemini |
| `GEMINI_API_URL` | Google OpenAI-compatible API | Endpoint Gemini |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model Gemini |
| `LLM_VALIDATE_ALL_FIELDS` | `true` | Kiểm tra title, authors và abstract ở M9 |
| `OPENAI_API_KEY` | rỗng | Provider tương thích OpenAI dự phòng |
| `OPENAI_API_URL` | rỗng | Endpoint provider dự phòng |
| `OPENAI_MODEL` | `gpt-3.5-turbo` | Model provider dự phòng |
| `ENVIRONMENT` | `development` | Dùng `production` để bật yêu cầu API key |
| `API_KEY` | rỗng | Khóa cho các API thay đổi dữ liệu ở production |
| `CORS_ORIGINS` | localhost:5173 | Danh sách origin frontend, phân cách bằng dấu phẩy |

Nếu không cấu hình LLM, các bước trích xuất, làm sạch và validation xác định vẫn hoạt động; bước M9 sẽ được bỏ qua.

## Sử dụng

### Thu thập PDF theo năm

Trong giao diện **Thu thập PDF**, nhập URL nguồn, năm bắt đầu, năm kết thúc và độ sâu crawl. Khoảng năm là inclusive.

Ví dụ API:

```http
POST /api/crawl
Content-Type: application/json

{
  "website_url": "https://tapchiyhocvietnam.vn/index.php/vmj/issue/archive",
  "start_year": 2024,
  "end_year": 2025,
  "max_depth": 2
}
```

Với OJS, hệ thống kiểm tra metadata của toàn bộ số/tập, lập danh mục tất cả bài đúng năm rồi mới quản lý hạn mức tải. Nếu một lượt đã lưu đủ 500 PDF mới, lượt tiếp theo với cùng URL và khoảng năm sẽ tái sử dụng manifest, bỏ qua tài liệu đã có và tiếp tục phần còn lại.

PDF được tổ chức theo:

```text
backend/data/scraped_pdfs/<domain>/<year>/<file.pdf>
```

### Trích xuất metadata

- Nút **Trích xuất metadata** chỉ xử lý các PDF chưa có bước `text_extraction`.
- Nút **Dừng trích xuất** gửi yêu cầu dừng hợp tác: hoàn thành an toàn bài đang xử lý rồi dừng trước bài kế tiếp.
- Nút **Trích xuất** trên một dòng xử lý riêng bài đó.
- Nút **Trích xuất lại** cho phép cập nhật metadata của bài đã xử lý mà không chạy lại toàn bộ kho.
- Metadata từ trang bài báo được dùng làm nguồn đối chiếu, nhưng tóm tắt tiếng Anh không ghi đè tóm tắt tiếng Việt hợp lệ lấy từ PDF.

### Upload PDF thủ công

Kéo thả một PDF vào khu vực upload. Tệp hợp lệ sẽ chạy pipeline đầy đủ và được lưu vào MongoDB. Hệ thống từ chối file không phải PDF, file vượt giới hạn và file trùng hash.

## API chính

### Papers và upload

| Method | Endpoint | Mô tả |
|---|---|---|
| `POST` | `/api/upload` | Upload PDF, chạy pipeline và lưu MongoDB |
| `GET` | `/api/results` | Danh sách metadata đã xử lý, có phân trang/confidence |
| `GET` | `/api/results/{paper_id}` | Chi tiết metadata |
| `GET` | `/api/search?q=...` | Tìm kiếm text trên title và abstract |
| `PATCH` | `/api/results/{paper_id}/review` | Cập nhật trạng thái và ghi chú review |
| `GET` | `/api/health` | Kiểm tra API và MongoDB |

### Crawler và thư viện PDF

| Method | Endpoint | Mô tả |
|---|---|---|
| `POST` | `/api/scrape` | Bắt đầu crawl, khoảng năm có thể để trống |
| `POST` | `/api/crawl` | Bắt đầu crawl với khoảng năm bắt buộc |
| `GET` | `/api/scrape/status` | Tiến độ khám phá, tải và nhật ký realtime |
| `POST` | `/api/scrape/stop` | Yêu cầu dừng crawl |
| `GET` | `/api/scrape/results` | Kết quả tạm thời của lượt crawl hiện tại |
| `GET` | `/api/scrape/results/{paper_id}` | Một kết quả trong lượt crawl hiện tại |
| `GET` | `/api/pdfs` | Kho PDF thực tế trên đĩa, có tìm kiếm/phân trang |
| `POST` | `/api/scrape/extract` | Trích xuất hàng loạt các PDF chưa xử lý |
| `GET` | `/api/scrape/extract/status` | Tiến độ trích xuất metadata |
| `POST` | `/api/scrape/extract/stop` | Yêu cầu dừng trích xuất an toàn |
| `POST` | `/api/pdfs/{paper_id}/extract` | Trích xuất hoặc trích xuất lại một PDF |
| `GET` | `/api/stats` | Thống kê thư viện và lượt crawl hiện tại |

Các endpoint thay đổi dữ liệu yêu cầu header `X-API-Key` khi `ENVIRONMENT=production`.

## Kiểm thử và build

### Backend

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pytest -q
```

Trạng thái tại lần cập nhật README này: **593 passed, 25 skipped**. Các integration test MongoDB có thể được skip khi không có database test.

### Frontend

```powershell
cd frontend
npm ci
npm run build
```

Output production nằm trong `frontend/dist/` và không được commit. Backend không serve static frontend; khi triển khai production cần dùng static server/reverse proxy để phục vụ `dist` và chuyển tiếp `/api` đến FastAPI.

## Bảo mật và dữ liệu

- URL đầu vào chỉ chấp nhận HTTP/HTTPS công khai; lớp URL safety chặn localhost, private IP và redirect không an toàn.
- Production bắt buộc cấu hình `API_KEY` và danh sách `CORS_ORIGINS` rõ ràng.
- `.env`, virtual environment, `frontend/node_modules`, build output và PDF runtime đã được loại khỏi Git.
- Không commit corpus PDF nếu chưa kiểm tra giấy phép, quyền riêng tư và điều khoản của nguồn.
- Crawler có rate limit và số worker khám phá nhỏ; hãy tôn trọng `robots.txt` và chính sách website.

## Trạng thái pipeline

| Bước | Chức năng | Trạng thái |
|---|---|---|
| M0–M1 | Foundation, precheck, lưu file, SHA-256 và crawler | Hoàn thành |
| M2 | Text extraction bằng PyMuPDF | Hoàn thành |
| M3 | Layout analysis và reading order nhiều cột | Hoàn thành |
| M4 | Title detection | Hoàn thành |
| M5 | Author detection | Hoàn thành |
| M6 | Abstract detection song ngữ | Hoàn thành |
| M7 | Cleaning và normalization | Hoàn thành |
| M8 | Validation và confidence scoring | Hoàn thành |
| M9 | LLM validation/enhancement tùy chọn | Hoàn thành |
| M10 | MongoDB persistence, deduplication và indexes | Hoàn thành |
| M11 | FastAPI và frontend responsive | Hoàn thành |
