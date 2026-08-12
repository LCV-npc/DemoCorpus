"""
config/constants.py
Hằng số, regex patterns, thresholds, và keyword lists cho toàn bộ pipeline.
"""

import re


# ─────────────────────────────────────────────
# Zone Types — phân loại vùng trong trang PDF
# ─────────────────────────────────────────────
class ZoneType:
    """Labels cho layout zone classification."""
    TITLE = "TITLE"
    AUTHOR = "AUTHOR"
    ABSTRACT = "ABSTRACT"
    AFFILIATION = "AFFILIATION"
    BODY = "BODY"
    HEADER = "HEADER"
    FOOTER = "FOOTER"
    UNKNOWN = "UNKNOWN"


# ─────────────────────────────────────────────
# File & Size Limits
# ─────────────────────────────────────────────
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
PDF_MAGIC_BYTES = b"%PDF"
MIN_TEXT_CHARS_BORN_DIGITAL = 100

# ─────────────────────────────────────────────
# Layout Analysis Thresholds
# ─────────────────────────────────────────────
HEADER_ZONE_FRACTION = 0.05       # Top 5% → HEADER
FOOTER_ZONE_FRACTION = 0.10       # Bottom 10% → FOOTER
TITLE_ZONE_FRACTION = 0.35        # Top 35% → candidate for TITLE
CBS_THRESHOLD = 0.75              # Composite Badness Score threshold

# ─────────────────────────────────────────────
# Abstract Detection Thresholds (Milestone 6)
# ─────────────────────────────────────────────
ABSTRACT_MIN_LENGTH = 50          # Minimum characters cho abstract hợp lệ
ABSTRACT_MAX_LENGTH = 4000        # Maximum characters cho abstract
NEWLINE_RATIO_THRESHOLD = 0.10    # newline_count / text_length → warning flag

# ─────────────────────────────────────────────
# Data Cleaning & Noise Detection Thresholds (Milestone 7)
# ─────────────────────────────────────────────
NOISE_NON_ALPHA_THRESHOLD = 0.50      # >50% non-alpha chars → noisy
NOISE_WHITESPACE_THRESHOLD = 0.40     # >40% whitespace → noisy
NOISE_DUPLICATE_LINE_THRESHOLD = 0.50 # >50% duplicate lines → noisy
NOISE_SYMBOL_THRESHOLD = 0.15         # >15% suspicious symbols → noisy

# ─────────────────────────────────────────────
# Regex Patterns
# ─────────────────────────────────────────────
ABSTRACT_START_PATTERN = re.compile(
    r"^\s*(abstract|tóm\s*tắt|tổng\s*quan)\s*[:\.\-]?\s*",
    re.IGNORECASE | re.MULTILINE
)

ABSTRACT_END_PATTERN = re.compile(
    r"^\s*("
    r"keywords?\s*[:\.]|"
    r"từ\s*khóa\s*[:\.]|"
    r"1\s*[\.\)]\s*(introduction|giới\s*thiệu)|"
    r"i\s*[\.\)]\s*introduction|"
    r"index\s*terms?"
    r")\s*",
    re.IGNORECASE | re.MULTILINE
)

HEADER_FOOTER_PATTERNS = [
    re.compile(r"doi\s*:\s*10\.\d{4,}", re.IGNORECASE),
    re.compile(r"©\s*\d{4}"),
    re.compile(r"^\s*\d+\s*$"),                          # Page numbers
    re.compile(r"vol\.\s*\d+", re.IGNORECASE),
    re.compile(r"issn\s*[\d\-]+", re.IGNORECASE),
    re.compile(r"received\s*:?\s*\d{1,2}", re.IGNORECASE),
    re.compile(r"accepted\s*:?\s*\d{1,2}", re.IGNORECASE),
]

# ─────────────────────────────────────────────
# Character Substitution Map (Milestone 7)
# ─────────────────────────────────────────────
CHAR_SUBSTITUTION_MAP = {
    "\u00b8": ",",      # cedilla → comma
    "\ufb01": "fi",     # ﬁ ligature
    "\ufb02": "fl",     # ﬂ ligature
    "\ufb00": "ff",     # ﬀ ligature
    "\ufb03": "ffi",    # ﬃ ligature
    "\ufb04": "ffl",    # ﬄ ligature
    "\u201c": '"',      # left smart quote
    "\u201d": '"',      # right smart quote
    "\u2018": "'",      # left single smart quote
    "\u2019": "'",      # right single smart quote
    "\u2013": "-",      # en dash
    "\u2014": "--",     # em dash
    "\u2026": "...",    # ellipsis
    "\u00a0": " ",      # non-breaking space
}

# ─────────────────────────────────────────────
# Affiliation Keywords
# ─────────────────────────────────────────────
AFFILIATION_KEYWORDS = [
    "university", "institute", "department", "faculty", "school of",
    "college", "laboratory", "hospital", "research center",
    "đại học", "học viện", "bệnh viện",
    "trung tâm nghiên cứu", "phòng thí nghiệm",
    "khoa y", "chuyên khoa", "đa khoa", "trường cao đẳng", "trường đại học", "bộ môn"
]

# ─────────────────────────────────────────────
# Medical Keywords — Filter cho web scraper
# Dùng để xác định nội dung y khoa
# ─────────────────────────────────────────────
MEDICAL_KEYWORDS_VI = [
    # Chuyên ngành y khoa
    "y học", "y tế", "y khoa", "y dược", "dược học", "dược phẩm",
    "lâm sàng", "bệnh viện", "bác sĩ", "bệnh nhân",
    "điều trị", "chẩn đoán", "phẫu thuật", "nội khoa", "ngoại khoa",
    "sản khoa", "nhi khoa", "da liễu", "tim mạch", "thần kinh",
    "ung thư", "ung bướu", "huyết học", "miễn dịch", "vi sinh",
    "giải phẫu", "sinh lý", "sinh hóa", "dịch tễ", "dịch tễ học",
    "sức khỏe", "sức khỏe cộng đồng", "y tế công cộng",
    "dinh dưỡng", "phục hồi chức năng", "vật lý trị liệu",
    "răng hàm mặt", "mắt", "tai mũi họng",
    "truyền nhiễm", "hô hấp", "tiêu hóa", "nội tiết",
    "cơ xương khớp", "thận", "tiết niệu", "gan mật",
    "hồi sức", "cấp cứu", "gây mê", "hồi sức cấp cứu",
    "chăm sóc sức khỏe", "nghiên cứu y học", "tạp chí y học",
    "thuốc", "kháng sinh", "vắc xin", "vaccine",
    "xét nghiệm", "chẩn đoán hình ảnh", "siêu âm", "x-quang",
    "CT", "MRI", "nội soi", "sinh thiết",
    "tế bào", "gen", "di truyền", "protein", "enzyme",
    "đột biến", "ung thư", "khối u", "tân sinh",
    "covid", "sars", "sốt xuất huyết", "viêm gan",
    "đái tháo đường", "tăng huyết áp", "suy tim",
    "đột quỵ", "alzheimer", "parkinson",
    "nhiễm trùng", "viêm", "dị ứng", "tự miễn",
    "lão khoa", "tâm thần", "tâm lý", "trầm cảm",
    "y học cổ truyền", "đông y", "châm cứu",
    "điều dưỡng", "hộ sinh", "kỹ thuật y học",
]

MEDICAL_KEYWORDS_EN = [
    # English medical terms
    "medical", "medicine", "clinical", "hospital", "patient",
    "treatment", "diagnosis", "surgery", "healthcare", "health",
    "pharmaceutical", "pharmacology", "drug", "therapy",
    "cardiology", "neurology", "oncology", "immunology",
    "pathology", "radiology", "dermatology", "pediatrics",
    "obstetrics", "gynecology", "orthopedics", "urology",
    "gastroenterology", "pulmonology", "endocrinology",
    "hematology", "nephrology", "rheumatology",
    "epidemiology", "public health", "biomedical",
    "anatomy", "physiology", "biochemistry", "microbiology",
    "genetics", "genomics", "proteomics",
    "nursing", "dentistry", "ophthalmology",
    "vaccine", "antibiotic", "biomarker",
    "MRI", "CT scan", "X-ray", "ultrasound",
    "cancer", "tumor", "diabetes", "hypertension",
    "stroke", "infection", "inflammation",
    "COVID", "SARS", "pandemic",
    "randomized controlled trial", "RCT", "meta-analysis",
    "systematic review", "cohort study", "case report",
    "clinical trial",
]

# Kết hợp tất cả keywords (lowercase)
MEDICAL_KEYWORDS_ALL = [kw.lower() for kw in MEDICAL_KEYWORDS_VI + MEDICAL_KEYWORDS_EN]

# Ngưỡng: cần ít nhất bao nhiêu keyword match để coi là y khoa
MEDICAL_KEYWORD_THRESHOLD = 2

# ─────────────────────────────────────────────
# Scraper Constants
# ─────────────────────────────────────────────
DEFAULT_RATE_LIMIT_MIN = 1.5  # seconds
DEFAULT_RATE_LIMIT_MAX = 3.5  # seconds
MAX_PAGES_TO_CRAWL = 200      # Giới hạn số trang crawl
REQUEST_TIMEOUT = 30           # seconds
SUPPORTED_PDF_EXTENSIONS = [".pdf"]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
