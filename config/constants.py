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
MAX_PAGES_TO_CRAWL = 200      # Giới hạn số trang crawl (generic BFS)
MAX_ARTICLES = 500            # Giới hạn số bài báo per scrape
MAX_PDFS = 500                # Giới hạn số PDF per scrape
REQUEST_TIMEOUT = 30           # seconds
SUPPORTED_PDF_EXTENSIONS = [".pdf"]

# Robots.txt compliance
ROBOTS_TXT_ENABLED = True     # Respect robots.txt by default

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ─────────────────────────────────────────────
# Validation Thresholds (Milestone 8)
# ─────────────────────────────────────────────

# Title validation bounds
VALID_TITLE_MIN_LENGTH = 5            # Minimum chars for a valid title
VALID_TITLE_MAX_LENGTH = 350          # Maximum chars for a valid title
VALID_TITLE_MIN_WORDS = 2             # Minimum word count
VALID_TITLE_MAX_WORDS = 40            # Maximum word count

# Author validation bounds
VALID_AUTHOR_MAX_COUNT = 50           # Max reasonable number of authors
VALID_AUTHOR_NAME_MIN_WORDS = 1       # Minimum tokens in an author name
VALID_AUTHOR_NAME_MAX_LENGTH = 80     # Max chars per author name

# Abstract validation bounds
VALID_ABSTRACT_MIN_LENGTH = 80        # Minimum chars for a valid abstract
VALID_ABSTRACT_MAX_LENGTH = 5000      # Maximum chars for a valid abstract
VALID_ABSTRACT_MIN_WORDS = 20         # Minimum word count
VALID_ABSTRACT_MAX_SENTENCES = 50     # Max sentences (beyond this → suspicious)
VALID_ABSTRACT_MIN_SENTENCE_WORDS = 3 # Avg words per sentence threshold
VALID_ABSTRACT_NEWLINE_RATIO_WARN = 0.08   # Newline ratio warning threshold
VALID_ABSTRACT_GARBAGE_CHAR_THRESHOLD = 0.10  # Max garbage char ratio

# ─────────────────────────────────────────────
# Validation Pass Threshold
# ─────────────────────────────────────────────
VALIDATION_PASS_THRESHOLD = 0.60      # Overall score >= this → passed

# ─────────────────────────────────────────────
# Validation Rule Weights (Milestone 8)
# ─────────────────────────────────────────────
# Mỗi field có tổng weights = 1.0.
# Trọng số phản ánh mức độ quan trọng của từng rule:
#   - "not_null" / "not_empty": cao nhất vì không có data → fail
#   - Structural checks (length, prose): trung bình
#   - Pattern checks (DOI, URL): trung bình (noise phổ biến)
#   - Heuristic checks (title_like, sentence_structure): thấp hơn

# Title: 10 rules, sum = 1.0
TITLE_RULE_WEIGHTS = {
    "not_null":        0.15,   # Critical: must exist
    "length_ok":       0.10,   # Within [5, 350] chars
    "has_alpha":       0.10,   # Contains alphabetic characters
    "not_all_digits":  0.05,   # Not purely numeric
    "word_count_ok":   0.10,   # [2, 40] words
    "not_doi":         0.10,   # Not a DOI string
    "not_url":         0.10,   # Not a URL
    "not_footer":      0.10,   # Not header/footer noise
    "no_noise":        0.10,   # No noise patterns (arxiv, journal, etc.)
    "title_like":      0.10,   # Resembles a paper title (capitalization)
}

# Author: 9 rules, sum = 1.0
AUTHOR_RULE_WEIGHTS = {
    "not_empty":          0.20,   # Critical: list non-empty
    "count_ok":           0.10,   # [1, 50] authors
    "names_structured":   0.15,   # Each name has reasonable word structure
    "no_emails":          0.10,   # No email addresses in names
    "no_urls":            0.05,   # No URLs in names
    "no_affiliations":    0.10,   # No affiliation keywords
    "length_ok":          0.10,   # Each name ≤ 80 chars
    "not_all_digits":     0.10,   # Names not purely numeric
    "no_duplicates":      0.10,   # No exact duplicate names
}

# Abstract: 9 rules, sum = 1.0
ABSTRACT_RULE_WEIGHTS = {
    "not_null":               0.15,   # Critical: must exist
    "length_ok":              0.10,   # Within [80, 5000] chars
    "is_prose":               0.15,   # Has prose structure (sentences with periods)
    "word_count_ok":          0.10,   # >= 20 words
    "not_list":               0.10,   # Not predominantly bullet/numbered items
    "not_references":         0.10,   # Not "References" / "Bibliography" section
    "not_keywords":           0.10,   # Not "Keywords:" / "Index Terms" section
    "low_garbage":            0.10,   # Low garbage character ratio
    "sentence_structure_ok":  0.10,   # Avg sentence length >= 3 words
}

# ─────────────────────────────────────────────
# Overall Field Weights (Milestone 8)
# ─────────────────────────────────────────────
# Title (0.35): Most important for paper identification, citation, retrieval.
#               A wrong title makes the entire extraction result useless.
# Authors (0.30): Essential for attribution and deduplication.
#                 A slightly wrong author name is less catastrophic than a wrong title.
# Abstract (0.35): Core content for understanding the paper.
#                  Equal importance to title for downstream NLP tasks.
OVERALL_FIELD_WEIGHTS = {
    "title":    0.35,
    "authors":  0.30,
    "abstract": 0.35,
}

# ─────────────────────────────────────────────
# Validation Regex Patterns (Milestone 8)
# ─────────────────────────────────────────────
DOI_PATTERN = re.compile(r"doi\s*:\s*10\.\d{4,}", re.IGNORECASE)
URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
BULLET_LIST_PATTERN = re.compile(
    r"^\s*(?:[\-\*\•]\s|(?:\d+[\.\)]\s)|(?:[a-z][\.\)]\s))",
    re.MULTILINE,
)
REFERENCES_START_PATTERN = re.compile(
    r"^\s*(references|bibliography|works\s+cited|tài\s*liệu\s*tham\s*khảo)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
KEYWORDS_START_PATTERN = re.compile(
    r"^\s*(keywords?\s*[:\.]|index\s+terms?\s*[:\.]|từ\s*khóa\s*[:\.])",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────
# LLM Enhancement (Milestone 9)
# ─────────────────────────────────────────────

# Threshold: only call LLM when rule-based field score < this value.
# Fields scoring >= this threshold are considered "confident enough"
# and skip the LLM call entirely (cost control).
LLM_ENHANCEMENT_THRESHOLD = 0.7

# Score combining weights.
# Final = w_rule × rule_score + w_llm × llm_score
# Per milestones.md spec: average → w_rule=0.5, w_llm=0.5
# Rationale: equal weighting because rule-based catches structural issues
# while LLM catches semantic issues — neither should dominate.
LLM_SCORE_WEIGHT_RULE = 0.5
LLM_SCORE_WEIGHT_LLM = 0.5

# When LLM says is_valid=false but reports high confidence,
# cap the LLM score to prevent paradox (confident it's invalid = low score).
# Per milestones.md test: {"is_valid": false, "confidence": 0.95} → 0.3
LLM_INVALID_CONFIDENCE_CAP = 0.3

# LLM confidence bounds
LLM_MAX_CONFIDENCE = 1.0
LLM_MIN_CONFIDENCE = 0.0

# API settings
LLM_API_TIMEOUT_SECONDS = 30
LLM_MAX_CONTEXT_CHARS = 500    # Max chars of document context sent to LLM
LLM_MAX_ABSTRACT_CHARS = 1000  # Max chars of abstract sent to LLM

# ─────────────────────────────────────────────
# LLM Prompt Templates (Milestone 9)
# ─────────────────────────────────────────────

LLM_TITLE_PROMPT = """You are validating metadata extracted from a scientific paper.

TASK: Determine if the following candidate is a valid paper title.

CANDIDATE TITLE:
"{title}"

DOCUMENT CONTEXT (first ~500 chars):
"{context}"

CHECK:
- Is this a plausible scientific paper title?
- Is it NOT a DOI, URL, header, footer, or journal name?
- Is it NOT a sentence from the body text?
- Does it make semantic sense as a title?

RULE-BASED ISSUES FOUND: {issues}

Return ONLY valid JSON (no markdown, no explanation outside JSON):
{{"is_valid": true, "confidence": 0.0, "reason": "brief explanation"}}"""

LLM_AUTHOR_PROMPT = """You are validating metadata extracted from a scientific paper.

TASK: Determine if the following candidates are valid author names.

CANDIDATE AUTHORS:
{authors_json}

DOCUMENT CONTEXT (first ~500 chars):
"{context}"

CHECK:
- Are these plausible person names (not organizations, affiliations, or emails)?
- Are there obvious non-person entries mixed in?
- Do the names look like real researcher names?

RULE-BASED ISSUES FOUND: {issues}

Return ONLY valid JSON (no markdown, no explanation outside JSON):
{{"is_valid": true, "confidence": 0.0, "reason": "brief explanation"}}"""

LLM_ABSTRACT_PROMPT = """You are validating metadata extracted from a scientific paper.

TASK: Determine if the following candidate is a valid paper abstract.

CANDIDATE ABSTRACT (first ~1000 chars):
"{abstract_preview}"

CHECK:
- Is this a plausible scientific abstract (not introduction, keywords, or references)?
- Does it read as a self-contained summary of research?
- Is it prose (not a list, table, or bibliography)?

RULE-BASED ISSUES FOUND: {issues}

Return ONLY valid JSON (no markdown, no explanation outside JSON):
{{"is_valid": true, "confidence": 0.0, "reason": "brief explanation"}}"""
