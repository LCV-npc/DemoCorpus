(() => {
    'use strict';

    const API_BASE = window.location.port === '5173'
        ? 'http://127.0.0.1:8000/api'
        : '/api';
    const POLL_INTERVAL = 1800;
    const pageLimit = 20;
    const resultsLimit = 10;
    let currentPage = 1;
    let resultsPage = 1;
    let pollTimer = null;
    let extractionPollTimer = null;
    let extractionObservedRunning = false;
    let isMetadataExtractionRunning = false;
    let currentModalPaperId = null;
    let currentModalIsTransient = false;
    let lastFocusedElement = null;
    let isUploading = false;

    const $ = (selector) => document.querySelector(selector);
    const $$ = (selector) => [...document.querySelectorAll(selector)];
    const dom = {
        sidebar: $('#app-sidebar'), sidebarBackdrop: $('#sidebar-backdrop'), sidebarToggle: $('#btn-sidebar-toggle'),
        topbarTitle: $('#topbar-title'), topbarJob: $('#topbar-job-status'),
        sidebarHealth: $('#sidebar-health'), sidebarHealthDetail: $('#sidebar-health-detail'), sidebarHealthDot: $('#sidebar-health-dot'),
        overviewTotal: $('#overview-total'), overviewDownloaded: $('#overview-downloaded'), overviewDuplicates: $('#overview-duplicates'), overviewErrors: $('#overview-errors'), overviewJobCaption: $('#overview-job-caption'), overviewRunBadge: $('#overview-run-badge'), overviewCurrentUrl: $('#overview-current-url'), overviewProgress: $('#overview-progress'),
        scrapeForm: $('#scrape-form'), scrapeUrl: $('#scrape-url'), startYear: $('#start-year'), endYear: $('#end-year'), maxDepth: $('#max-depth'), scrapeFormError: $('#scrape-form-error'), startScrape: $('#btn-start-scrape'), stopScrape: $('#btn-stop-scrape'), scraperStatus: $('#scraper-status-badge'), scraperStatusText: $('#scraper-status-text'),
        progressPanel: $('#scrape-progress-container'), progressLabel: $('#progress-label'), progressCount: $('#progress-count'), progressFill: $('#scrape-progress-fill'), logConsole: $('#log-console'), clearLog: $('#btn-clear-log'),
        uploadZone: $('#upload-zone'), fileUpload: $('#file-upload'), uploadProgress: $('#upload-progress'), uploadProgressFill: $('#upload-progress-fill'), uploadProgressText: $('#upload-progress-text'), uploadResultSection: $('#upload-result-section'), uploadResultStatus: $('#upload-result-status'), uploadResultPaperId: $('#upload-result-paper-id'), uploadResultTitle: $('#upload-result-title'), uploadResultAuthors: $('#upload-result-authors'), uploadResultAbstract: $('#upload-result-abstract'), uploadResultConfidence: $('#upload-result-confidence'), uploadResultTitleScore: $('#upload-result-title-score'), uploadResultAuthorsScore: $('#upload-result-authors-score'), uploadResultAbstractScore: $('#upload-result-abstract-score'), uploadResultTime: $('#upload-result-time'), uploadResultStages: $('#upload-result-stages'),
        searchInput: $('#search-input'), libraryContext: $('#library-context'), extractScraped: $('#btn-extract-scraped'), stopExtraction: $('#btn-stop-extraction'), refreshLibrary: $('#btn-refresh-library'), pdfTableBody: $('#pdf-table-body'), prevPage: $('#btn-prev-page'), nextPage: $('#btn-next-page'), paginationInfo: $('#pagination-info'),
        resultsSearchInput: $('#results-search-input'), refreshResults: $('#btn-refresh-results'), resultsTableBody: $('#results-table-body'), resultsPrev: $('#btn-results-prev'), resultsNext: $('#btn-results-next'), resultsPaginationInfo: $('#results-pagination-info'),
        statTotal: $('#stat-total'), statDownloaded: $('#stat-downloaded'), statDuplicates: $('#stat-duplicates'), statErrors: $('#stat-errors'),
        modalOverlay: $('#paper-detail-modal'), modal: $('#paper-detail-modal .modal'), closeModal: $('#btn-close-modal'), modalPaperId: $('#modal-paper-id'), modalTitle: $('#modal-title'), modalAuthors: $('#modal-authors'), modalAbstract: $('#modal-abstract'), modalSource: $('#modal-source'), modalCreated: $('#modal-created'), modalConfidenceOverall: $('#modal-confidence-overall'), modalConfidenceTitle: $('#modal-confidence-title'), modalConfidenceAuthors: $('#modal-confidence-authors'), modalConfidenceAbstract: $('#modal-confidence-abstract'), modalValidationSection: $('#modal-validation-section'), modalValidationDetails: $('#modal-validation-details'), modalStages: $('#modal-stages'), modalReviewCheckbox: $('#modal-review-checkbox'), modalReviewNotes: $('#modal-review-notes'), saveReview: $('#btn-save-review'),
        toastContainer: $('#toast-container'),
    };

    const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
    const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#039;', '"': '&quot;' }[char]));
    const formatProse = (value) => typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : '';
    const truncate = (value, length = 80) => { const text = formatProse(value); return text.length > length ? `${text.slice(0, length - 1)}…` : text; };
    const formatPercent = (value) => `${Math.round((Number(value) || 0) * 100)}%`;
    const formatFileSize = (bytes) => {
        const value = Number(bytes) || 0;
        if (value < 1024) return `${value} B`;
        if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
        return `${(value / (1024 * 1024)).toFixed(1)} MB`;
    };
    const formatTime = (value) => {
        if (!value) return '—';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return '—';
        return new Intl.DateTimeFormat('vi-VN', { dateStyle: 'short', timeStyle: 'short' }).format(date);
    };

    async function api(endpoint, options = {}) {
        const response = await fetch(`${API_BASE}${endpoint}`, options);
        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            throw new Error(body.detail || body.message || response.statusText || 'Yêu cầu không thành công');
        }
        return response.json();
    }
    const apiGet = (endpoint) => api(endpoint);
    const apiPost = (endpoint, body) => api(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const apiPatch = (endpoint, body) => api(endpoint, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

    function showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast toast--${type}`;
        const content = document.createElement('span');
        content.textContent = message;
        const close = document.createElement('button');
        close.type = 'button'; close.setAttribute('aria-label', 'Đóng thông báo'); close.textContent = '×';
        close.addEventListener('click', () => toast.remove());
        toast.append(content, close);
        dom.toastContainer.appendChild(toast);
        window.setTimeout(() => toast.remove(), 5500);
    }

    function setStatusText(element, text, type = 'idle') {
        const dot = element?.querySelector('.status-indicator');
        if (dot) dot.className = `status-indicator ${type === 'running' ? 'is-running' : type === 'error' ? 'is-error' : type === 'warning' ? 'is-warning' : type === 'ok' || type === 'done' ? 'is-ok' : ''}`;
        const target = element?.querySelector('span:last-child');
        if (target) target.textContent = text;
    }

    function setTableState(target, colspan, kind, message) {
        const visual = kind === 'error' ? 'alert' : kind === 'loading' ? 'refresh' : kind === 'empty' ? 'file' : 'library';
        target.innerHTML = `<tr><td colspan="${colspan}"><div class="table-state">${icon(visual)}<p>${escapeHtml(message)}</p></div></td></tr>`;
    }

    function openSidebar() {
        dom.sidebar.classList.add('is-open'); dom.sidebarBackdrop.hidden = false; dom.sidebarToggle.setAttribute('aria-expanded', 'true');
    }
    function closeSidebar() {
        dom.sidebar.classList.remove('is-open'); dom.sidebarBackdrop.hidden = true; dom.sidebarToggle.setAttribute('aria-expanded', 'false');
    }

    function updateNav(sectionId) {
        const section = document.getElementById(sectionId);
        $$('.nav-item').forEach((item) => item.classList.toggle('is-active', item.dataset.navTarget === sectionId));
        if (section?.dataset.sectionTitle) dom.topbarTitle.textContent = section.dataset.sectionTitle;
    }

    function initializeNavigation() {
        dom.sidebarToggle.addEventListener('click', () => dom.sidebar.classList.contains('is-open') ? closeSidebar() : openSidebar());
        dom.sidebarBackdrop.addEventListener('click', closeSidebar);
        $$('.nav-item').forEach((item) => item.addEventListener('click', () => { closeSidebar(); updateNav(item.dataset.navTarget); }));
        const observer = new IntersectionObserver((entries) => {
            const active = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
            if (active) updateNav(active.target.id);
        }, { rootMargin: '-20% 0px -62% 0px', threshold: [0, .25, .6] });
        $$('.page-section[data-section-title]').forEach((section) => observer.observe(section));
    }

    function showFormError(message = '') {
        dom.scrapeFormError.hidden = !message;
        dom.scrapeFormError.textContent = message;
    }

    async function startScrape() {
        const url = dom.scrapeUrl.value.trim();
        const startYear = Number.parseInt(dom.startYear.value, 10);
        const endYear = Number.parseInt(dom.endYear.value, 10);
        const depth = Number.parseInt(dom.maxDepth.value, 10);
        try {
            const parsed = new URL(url);
            if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error();
        } catch { showFormError('Nhập URL công khai hợp lệ, bắt đầu bằng http:// hoặc https://.'); dom.scrapeUrl.focus(); return; }
        if (!Number.isInteger(startYear) || !Number.isInteger(endYear) || startYear > endYear) { showFormError('Khoảng năm không hợp lệ. “Từ năm” phải nhỏ hơn hoặc bằng “Đến năm”.'); dom.startYear.focus(); return; }
        if (!Number.isInteger(depth) || depth < 0 || depth > 5) { showFormError('Độ sâu crawl phải nằm trong khoảng từ 0 đến 5.'); dom.maxDepth.focus(); return; }
        showFormError(); dom.startScrape.disabled = true;
        try {
            const result = await apiPost('/crawl', { website_url: url, start_year: startYear, end_year: endYear, max_depth: depth });
            if (result.end_year !== endYear) showToast(`Năm kết thúc được giới hạn ở ${result.end_year}.`, 'warning');
            dom.resultsSearchInput.value = '';
            loadResults(1);
            switchCrawlerControls(true);
            startPolling();
            showToast('Đã bắt đầu lượt quét PDF.', 'success');
        } catch (error) {
            showFormError(error.message);
            dom.startScrape.disabled = false;
        }
    }

    async function stopScrape() {
        try { await apiPost('/scrape/stop', {}); showToast('Đã gửi yêu cầu dừng lượt quét.', 'info'); }
        catch (error) { showToast(error.message, 'error'); }
    }

    function switchCrawlerControls(running) {
        dom.startScrape.hidden = running;
        dom.stopScrape.hidden = !running;
        dom.progressPanel.hidden = !running;
        if (!running) dom.startScrape.disabled = false;
    }

    function updateJobStatus(status) {
        const finished = status.done && !status.running;
        const state = status.running ? 'running' : status.errors ? 'warning' : finished ? 'done' : 'idle';
        const statusText = status.running ? 'Đang quét' : finished ? 'Đã hoàn tất' : 'Sẵn sàng';
        setStatusText(dom.scraperStatus, statusText, state);
        const badgeClass = status.running ? 'status-badge status-badge--success' : status.errors ? 'status-badge status-badge--error' : 'status-badge';
        dom.overviewRunBadge.className = badgeClass;
        dom.overviewRunBadge.textContent = status.running ? 'Đang chạy' : finished ? 'Đã hoàn tất' : 'Chưa có lượt quét';
        const total = Number(status.total_found) || 0;
        // A duplicate is already included in `skipped`; counting it twice
        // made the old progress bar exceed the number of candidates.
        const legacyComplete = (Number(status.downloaded) || 0) + (Number(status.skipped) || 0) + (Number(status.errors) || 0);
        const shownTotal = total || legacyComplete;
        const catalogTotal = Number(status.catalog_total) || 0;
        const catalogPending = Number(status.catalog_pending) || 0;
        const batchTotal = Number(status.batch_total) || 0;
        const batchProcessed = Number(status.batch_processed) || 0;
        const usingCatalog = catalogTotal > 0;
        const processingTotal = usingCatalog
            ? Math.max(batchTotal, batchProcessed)
            : shownTotal;
        const processingComplete = usingCatalog
            ? Math.min(batchProcessed, processingTotal)
            : legacyComplete;
        const discovering = status.running && total === 0;
        const discoveryPhase = status.discovery_phase || 'archive';
        const discoveryCurrent = Number(status.discovery_current) || 0;
        const discoveryTotal = Number(status.discovery_total) || 0;
        const discoveryPercent = discoveryTotal ? Math.min(100, Math.round((discoveryCurrent / discoveryTotal) * 100)) : 0;
        const discoveryText = discoveryPhase === 'issues'
            ? `Đang kiểm tra metadata số báo ${discoveryCurrent}/${discoveryTotal}`
            : discoveryPhase === 'articles'
                ? `Đang xác minh metadata bài ứng viên ${discoveryCurrent}/${discoveryTotal}`
                : `Đang lập danh sách số báo · trang ${Math.max(1, discoveryCurrent)}`;
        const catalogText = usingCatalog
            ? `Danh mục ${catalogTotal.toLocaleString('vi-VN')} PDF · ${catalogPending.toLocaleString('vi-VN')} mục chưa hoàn tất`
            : '';
        const batchText = usingCatalog
            ? `Lô hiện tại ${processingComplete}/${processingTotal || 0}`
            : `Đang xử lý ${processingComplete}/${processingTotal || '—'} mục`;
        dom.overviewDownloaded.textContent = status.downloaded ?? 0;
        dom.overviewDuplicates.textContent = status.duplicates ?? 0;
        dom.overviewErrors.textContent = status.errors ?? 0;
        dom.statDownloaded.textContent = status.downloaded ?? 0;
        dom.statDuplicates.textContent = status.duplicates ?? 0;
        dom.statErrors.textContent = status.errors ?? 0;
        dom.overviewJobCaption.textContent = status.running
            ? (discovering ? discoveryText : `${batchText} · ${catalogText || 'đang xử lý'}`)
            : finished
                ? (catalogText || 'Kết quả lượt quét gần nhất')
                : 'Chưa có lượt quét đang chạy';
        dom.overviewCurrentUrl.textContent = status.current_url || 'Chưa có URL';
        dom.overviewCurrentUrl.title = status.current_url || '';
        dom.overviewProgress.textContent = usingCatalog
            ? `${batchText} · ${catalogPending}/${catalogTotal} chờ xử lý`
            : `${processingComplete} / ${processingTotal}`;
        dom.progressLabel.textContent = discovering
            ? discoveryText
            : usingCatalog
                ? `${status.manifest_reused ? 'Tiếp tục từ danh mục đã lưu' : 'Đang tải lô đầu tiên'} · ${batchText}`
                : status.current_url ? `Đang xử lý: ${truncate(status.current_url, 105)}` : 'Đang chuẩn bị lượt quét…';
        dom.progressLabel.title = status.current_url || '';
        dom.progressCount.textContent = discovering
            ? (discoveryTotal ? `${discoveryCurrent} / ${discoveryTotal} · ${discoveryPercent}%` : `Trang ${Math.max(1, discoveryCurrent)}`)
            : usingCatalog
                ? `${batchText} · ${catalogPending.toLocaleString('vi-VN')} chờ xử lý`
                : `${processingComplete} / ${processingTotal}`;
        dom.progressFill.classList.toggle('is-indeterminate', discovering && !discoveryTotal);
        dom.progressFill.style.width = `${discovering ? (discoveryTotal ? discoveryPercent : 0) : (processingTotal ? Math.min(100, (processingComplete / processingTotal) * 100) : 0)}%`;
        dom.topbarJob.innerHTML = `<span class="status-indicator ${status.running ? 'is-running' : finished ? 'is-ok' : ''}"></span><span>${status.running ? 'Đang có lượt quét chạy' : finished ? 'Lượt quét đã hoàn tất' : 'Chưa có lượt quét đang chạy'}</span>`;
        renderLogs(status.log_messages || []);
    }

    function renderLogs(logs) {
        if (!logs.length) { dom.logConsole.innerHTML = '<p class="log-console__placeholder">Sẵn sàng. Thiết lập URL và bắt đầu lượt quét để xem nhật ký.</p>'; return; }
        dom.logConsole.innerHTML = logs.map((entry) => {
            const text = entry.message || '';
            const level = entry.level === 'error' ? 'error' : entry.level === 'warning' ? 'warning' : /Đã lưu|Hoàn tất|Tải xong/i.test(text) ? 'success' : 'info';
            return `<div class="log-entry log-entry--${level}"><span class="log-time">${escapeHtml(entry.time || '')}</span><span class="log-msg">${escapeHtml(text)}</span></div>`;
        }).join('');
        dom.logConsole.scrollTop = dom.logConsole.scrollHeight;
    }

    function startPolling() { stopPolling(); pollStatus(); pollTimer = window.setInterval(pollStatus, POLL_INTERVAL); }
    function stopPolling() { if (pollTimer) { window.clearInterval(pollTimer); pollTimer = null; } }
    async function pollStatus() {
        try {
            const status = await apiGet('/scrape/status');
            updateJobStatus(status);
            if (!status.running && (status.done || !status.should_stop)) {
                stopPolling(); switchCrawlerControls(false);
                if (status.done) { loadPdfList(currentPage); loadResults(1); loadStats(); }
            }
        } catch (error) { console.error('Không thể cập nhật trạng thái crawl:', error); }
    }

    async function handleUpload(file) {
        if (!file || isUploading) return;
        if (!file.name.toLowerCase().endsWith('.pdf')) { showToast('Chỉ chấp nhận tệp PDF.', 'warning'); return; }
        if (file.size > 50 * 1024 * 1024) { showToast('Tệp vượt quá giới hạn 50 MB.', 'warning'); return; }
        isUploading = true; dom.uploadZone.setAttribute('aria-disabled', 'true'); dom.uploadZone.classList.add('is-uploading'); dom.uploadProgress.hidden = false; dom.uploadProgressFill.style.width = '12%'; dom.uploadProgressText.textContent = `Đang xử lý ${file.name}…`;
        const formData = new FormData(); formData.append('file', file);
        try {
            dom.uploadProgressFill.style.width = '42%';
            const response = await fetch(`${API_BASE}/upload`, { method: 'POST', body: formData });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(payload.detail || payload.message || 'Không thể upload PDF');
            dom.uploadProgressFill.style.width = '100%';
            displayUploadResult(payload); showToast(`Đã xử lý ${file.name}.`, 'success'); loadPdfList(1); loadStats();
        } catch (error) { showToast(error.message, 'error'); }
        finally { isUploading = false; dom.uploadZone.removeAttribute('aria-disabled'); dom.uploadZone.classList.remove('is-uploading'); dom.fileUpload.value = ''; window.setTimeout(() => { dom.uploadProgress.hidden = true; dom.uploadProgressFill.style.width = '0%'; }, 1800); }
    }

    function displayUploadResult(data) {
        const confidence = data.confidence || {};
        const processing = data.processing || {};
        dom.uploadResultSection.hidden = false;
        dom.uploadResultStatus.textContent = data.status === 'completed' ? 'Hoàn tất' : 'Hoàn tất một phần';
        dom.uploadResultStatus.className = `status-badge ${data.status === 'completed' ? 'status-badge--success' : 'status-badge--pending'}`;
        dom.uploadResultPaperId.textContent = `ID: ${data.paper_id || '—'}`;
        dom.uploadResultTitle.textContent = formatProse(data.title) || 'Không trích xuất được';
        dom.uploadResultAuthors.textContent = data.authors?.length ? data.authors.join(', ') : 'Không trích xuất được';
        dom.uploadResultAbstract.textContent = formatProse(data.abstract) || 'Không trích xuất được';
        dom.uploadResultConfidence.textContent = formatPercent(confidence.overall);
        dom.uploadResultTitleScore.textContent = formatPercent(confidence.title?.score ?? confidence.title);
        dom.uploadResultAuthorsScore.textContent = formatPercent(confidence.authors?.score ?? confidence.authors);
        dom.uploadResultAbstractScore.textContent = formatPercent(confidence.abstract?.score ?? confidence.abstract);
        dom.uploadResultTime.textContent = processing.elapsed_seconds ? `${Number(processing.elapsed_seconds).toFixed(1)} giây` : '—';
        dom.uploadResultStages.innerHTML = (processing.stages_completed || []).map((stage) => `<span class="stage ${/failed|skipped/i.test(stage) ? 'is-failed' : ''}">${escapeHtml(stage)}</span>`).join('');
        dom.uploadResultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    async function loadPdfList(page = 1, { preserveViewport = false } = {}) {
        const scrollTop = window.scrollY;
        const tableScroll = dom.pdfTableBody.closest('.table-scroll');
        const horizontalScroll = tableScroll?.scrollLeft || 0;
        const panel = dom.pdfTableBody.closest('.data-panel');
        currentPage = page;
        if (preserveViewport && dom.pdfTableBody.children.length) {
            panel?.classList.add('is-loading');
            panel?.setAttribute('aria-busy', 'true');
        } else {
            setTableState(dom.pdfTableBody, 6, 'loading', 'Đang tải thư viện PDF…');
        }
        try {
            const query = dom.searchInput.value.trim();
            const data = await apiGet(`/pdfs?page=${page}&limit=${pageLimit}&q=${encodeURIComponent(query)}`);
            renderPdfTable(data.items, data.total, page, query);
        } catch (error) { setTableState(dom.pdfTableBody, 6, 'error', `Không thể tải thư viện: ${error.message}`); }
        finally {
            panel?.classList.remove('is-loading');
            panel?.removeAttribute('aria-busy');
            if (preserveViewport) {
                window.requestAnimationFrame(() => {
                    window.scrollTo({ top: scrollTop, left: window.scrollX, behavior: 'auto' });
                    if (tableScroll) tableScroll.scrollLeft = horizontalScroll;
                });
            }
        }
    }

    function renderPdfTable(items, total, page, query) {
        if (!items?.length) {
            setTableState(dom.pdfTableBody, 6, 'empty', query ? 'Không tìm thấy tài liệu phù hợp với từ khóa này.' : 'Chưa có PDF trong thư mục lưu trữ. Hãy bắt đầu thu thập hoặc upload PDF.');
        } else {
            dom.pdfTableBody.innerHTML = items.map((item) => {
                const extracted = item.extracted || {};
                const title = formatProse(extracted.title);
                const authors = Array.isArray(extracted.authors) ? extracted.authors.join(', ') : '';
                const ready = Boolean(item.extracted_ready);
                const paperId = item.paper_id || '';
                const canView = ready && paperId;
                const canExtract = Boolean(paperId) && !isMetadataExtractionRunning;
                return `<tr><td data-label="Tài liệu"><strong class="doc-title" title="${escapeHtml(item.filename)}">${escapeHtml(item.filename || 'Không rõ tên tệp')}</strong><span class="doc-subtitle">${formatFileSize(item.file_size_bytes)}</span></td><td data-label="Metadata"><div class="metadata-preview"><strong title="${escapeHtml(title)}">${escapeHtml(title || 'Chưa trích xuất metadata')}</strong><span title="${escapeHtml(authors)}">${escapeHtml(authors || 'Chưa có tác giả')}</span></div></td><td data-label="Nguồn"><span class="source-text">${item.source === 'scrape' ? 'Web scraper' : escapeHtml(item.source || '—')}</span></td><td data-label="Trạng thái"><span class="status-badge ${ready ? 'status-badge--success' : 'status-badge--pending'}">${ready ? 'Đã trích xuất' : 'Chờ trích xuất'}</span></td><td data-label="Cập nhật"><span class="cell-time">${formatTime(item.scraped_at || item.processing?.created_at)}</span></td><td class="table-action"><div class="table-actions"><button class="btn btn--secondary btn--sm" type="button" data-paper-id="${escapeHtml(paperId)}" ${canView ? '' : 'disabled'} title="${canView ? 'Xem metadata' : 'Hãy trích xuất metadata trước khi xem chi tiết'}">${icon('eye')}Xem</button><button class="btn btn--ghost btn--sm" type="button" data-extract-paper-id="${escapeHtml(paperId)}" ${canExtract ? '' : 'disabled'} title="${ready ? 'Trích xuất lại metadata của tài liệu này' : 'Trích xuất metadata của tài liệu này'}">${icon('file')}${ready ? 'Trích xuất lại' : 'Trích xuất'}</button></div></td></tr>`;
            }).join('');
        }
        const pages = Math.max(1, Math.ceil(total / pageLimit));
        dom.paginationInfo.textContent = `Trang ${page} / ${pages} · ${total} tài liệu`;
        dom.prevPage.disabled = page <= 1; dom.nextPage.disabled = page >= pages;
        dom.libraryContext.textContent = query ? `Kết quả tìm kiếm trong PDF đang lưu: ${total} tài liệu.` : `Hiển thị ${total} PDF đang tồn tại trong thư mục lưu trữ.`;
    }

    async function loadResults(page = 1) {
        resultsPage = page; setTableState(dom.resultsTableBody, 5, 'loading', 'Đang tải kết quả lượt quét…');
        try {
            const query = dom.resultsSearchInput.value.trim();
            const data = await apiGet(`/scrape/results?page=${page}&limit=${resultsLimit}&q=${encodeURIComponent(query)}`);
            renderResultsTable(data.items, data.total, page, query);
        } catch (error) { setTableState(dom.resultsTableBody, 5, 'error', `Không thể tải kết quả: ${error.message}`); }
    }

    function renderResultsTable(items, total, page, query) {
        if (!items?.length) {
            setTableState(dom.resultsTableBody, 5, 'empty', query ? 'Không có kết quả phù hợp trong lượt quét này.' : 'Chưa có PDF trong lượt quét hiện tại. Khi bắt đầu quét mới, bảng này sẽ được làm mới.');
        } else {
            dom.resultsTableBody.innerHTML = items.map((item) => {
                const extracted = item.extracted || {};
                const title = formatProse(extracted.title);
                const authors = Array.isArray(extracted.authors) ? extracted.authors.join(', ') : '';
                return `<tr><td data-label="Tài liệu"><strong class="doc-title" title="${escapeHtml(item.filename)}">${escapeHtml(item.filename || 'Không rõ tên tệp')}</strong><span class="doc-subtitle">${formatFileSize(item.file_size_bytes)}</span></td><td data-label="Metadata"><div class="metadata-preview"><strong title="${escapeHtml(title)}">${escapeHtml(title || 'Chưa trích xuất metadata')}</strong><span title="${escapeHtml(authors)}">${escapeHtml(authors || 'Chưa có tác giả')}</span></div></td><td data-label="Trạng thái"><span class="status-badge status-badge--pending">Đã tải · chờ trích xuất</span></td><td data-label="Thời điểm"><span class="cell-time">${formatTime(item.scraped_at || item.processing?.created_at)}</span></td><td class="table-action"><button class="btn btn--secondary btn--sm" type="button" data-paper-id="${escapeHtml(item.paper_id || '')}" disabled title="Hãy trích xuất metadata trước khi xem chi tiết">${icon('eye')}Xem</button></td></tr>`;
            }).join('');
        }
        const pages = Math.max(1, Math.ceil(total / resultsLimit));
        dom.resultsPaginationInfo.textContent = `Trang ${page} / ${pages} · ${total} PDF`;
        dom.resultsPrev.disabled = page <= 1; dom.resultsNext.disabled = page >= pages;
    }

    async function openPaperDetail(paperId) {
        if (!paperId) return;
        try {
            let paper; let transient = false;
            try { paper = await apiGet(`/scrape/results/${encodeURIComponent(paperId)}`); transient = true; }
            catch { paper = await apiGet(`/results/${encodeURIComponent(paperId)}`); }
            currentModalPaperId = paperId; currentModalIsTransient = transient; lastFocusedElement = document.activeElement;
            populateModal(paper, transient); dom.modalOverlay.hidden = false; document.body.style.overflow = 'hidden'; dom.modal.focus();
        } catch (error) { showToast(`Không thể mở chi tiết: ${error.message}`, 'error'); }
    }

    function populateModal(paper, transient) {
        const extracted = paper.extracted || {}; const confidence = paper.confidence || {}; const processing = paper.processing || {}; const review = paper.review || {}; const validation = paper.validation || {};
        dom.modalPaperId.textContent = paper.paper_id || '—';
        dom.modalTitle.textContent = formatProse(extracted.title) || 'Chưa có';
        dom.modalAuthors.textContent = extracted.authors?.length ? extracted.authors.join(', ') : 'Chưa có';
        dom.modalAbstract.textContent = formatProse(extracted.abstract) || 'Chưa có';
        dom.modalSource.textContent = paper.source_journal_domain || paper.source || '—';
        dom.modalCreated.textContent = formatTime(processing.created_at || paper.scraped_at);
        dom.modalConfidenceOverall.textContent = formatPercent(confidence.overall);
        dom.modalConfidenceTitle.textContent = formatPercent(confidence.title?.score ?? confidence.title);
        dom.modalConfidenceAuthors.textContent = formatPercent(confidence.authors?.score ?? confidence.authors);
        dom.modalConfidenceAbstract.textContent = formatPercent(confidence.abstract?.score ?? confidence.abstract);
        const validationEntries = Object.entries(validation).filter(([, value]) => value && typeof value === 'object');
        dom.modalValidationSection.hidden = validationEntries.length === 0;
        dom.modalValidationDetails.innerHTML = validationEntries.map(([field, value]) => {
            const issues = value.issues || [];
            return issues.length
                ? `<p><strong>${escapeHtml(field)}</strong></p><ul class="validation-list">${issues.map((issue) => `<li>${escapeHtml(issue)}</li>`).join('')}</ul>`
                : `<p><strong>${escapeHtml(field)}</strong>: Không có vấn đề.</p>`;
        }).join('');
        const stages = processing.steps_completed || processing.stages_completed || [];
        dom.modalStages.innerHTML = stages.length ? stages.map((stage) => `<span class="stage ${/failed|skipped/i.test(stage) ? 'is-failed' : ''}">${escapeHtml(stage)}</span>`).join('') : '<span class="stage">Chưa có thông tin</span>';
        dom.modalReviewCheckbox.checked = Boolean(review.is_reviewed);
        dom.modalReviewNotes.value = review.reviewer_notes || '';
        [dom.modalReviewCheckbox, dom.modalReviewNotes, dom.saveReview].forEach((element) => { element.disabled = transient; });
        dom.saveReview.title = transient ? 'Hãy mở lại tài liệu từ Kho tài liệu sau khi metadata đã được lưu để đánh giá.' : '';
    }

    function closePaperDetail() {
        dom.modalOverlay.hidden = true; document.body.style.overflow = ''; currentModalPaperId = null; currentModalIsTransient = false;
        if (lastFocusedElement instanceof HTMLElement) lastFocusedElement.focus();
    }

    async function saveReview() {
        if (!currentModalPaperId || currentModalIsTransient) return;
        dom.saveReview.disabled = true;
        try { await apiPatch(`/results/${encodeURIComponent(currentModalPaperId)}/review`, { is_reviewed: dom.modalReviewCheckbox.checked, reviewer_notes: dom.modalReviewNotes.value.trim() }); showToast('Đã lưu đánh giá tài liệu.', 'success'); loadPdfList(currentPage); }
        catch (error) { showToast(`Không thể lưu đánh giá: ${error.message}`, 'error'); }
        finally { dom.saveReview.disabled = false; }
    }

    function trapModalFocus(event) {
        if (event.key === 'Escape' && !dom.modalOverlay.hidden) { closePaperDetail(); return; }
        if (event.key !== 'Tab' || dom.modalOverlay.hidden) return;
        const focusable = $$(`#paper-detail-modal button:not(:disabled), #paper-detail-modal input:not(:disabled), #paper-detail-modal textarea:not(:disabled), #paper-detail-modal [tabindex="0"]`);
        if (!focusable.length) return;
        const first = focusable[0], last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }

    function updateExtractionButton(status) {
        const running = Boolean(status?.running);
        isMetadataExtractionRunning = running;
        $$('button[data-extract-paper-id]').forEach((button) => { button.disabled = running || !button.dataset.extractPaperId; });
        dom.stopExtraction.hidden = !running;
        dom.stopExtraction.disabled = Boolean(status?.stop_requested);
        dom.stopExtraction.innerHTML = status?.stop_requested ? `${icon('stop')}Đang dừng…` : `${icon('stop')}Dừng trích xuất`;
        if (running) {
            extractionObservedRunning = true;
            dom.extractScraped.disabled = true;
            dom.extractScraped.textContent = `Đang trích xuất ${status.completed || 0}/${status.total || 0}`;
            return;
        }
        dom.extractScraped.disabled = false; dom.extractScraped.innerHTML = `${icon('file')}Trích xuất metadata`;
    }
    function stopExtractionPolling() { if (extractionPollTimer) { window.clearTimeout(extractionPollTimer); extractionPollTimer = null; } }
    async function pollExtractionStatus() {
        try {
            const status = await apiGet('/scrape/extract/status'); updateExtractionButton(status);
            if (status.running) { extractionPollTimer = window.setTimeout(pollExtractionStatus, POLL_INTERVAL); return; }
            stopExtractionPolling();
            if (status.done && status.total && extractionObservedRunning) {
                const message = status.stopped
                    ? `Đã dừng sau ${status.completed}/${status.total} PDF. Các bài chưa xử lý vẫn giữ trạng thái chờ.`
                    : `Đã trích xuất metadata cho ${status.extracted}/${status.total} PDF${status.failed ? `; lỗi: ${status.failed}` : ''}.`;
                showToast(message, status.stopped || status.failed ? 'warning' : 'success');
                extractionObservedRunning = false;
                loadPdfList(currentPage);
            }
        } catch (error) { stopExtractionPolling(); updateExtractionButton(); }
    }
    async function startScrapedExtraction() {
        dom.extractScraped.disabled = true;
        try {
            const result = await apiPost('/scrape/extract', {});
            if (result.status === 'nothing_to_extract') { showToast('Tất cả PDF đã được trích xuất metadata; không có bài nào cần xử lý.', 'info'); updateExtractionButton(); return; }
            extractionObservedRunning = true;
            showToast(`Đang trích xuất metadata cho ${result.total_files} PDF.`, 'info'); stopExtractionPolling(); pollExtractionStatus();
        } catch (error) { updateExtractionButton(); showToast(`Không thể bắt đầu trích xuất: ${error.message}`, 'error'); }
    }

    async function startSingleMetadataExtraction(paperId) {
        if (!paperId || isMetadataExtractionRunning) return;
        updateExtractionButton({ running: true, completed: 0, total: 1 });
        try {
            const result = await apiPost(`/pdfs/${encodeURIComponent(paperId)}/extract`, {});
            extractionObservedRunning = true;
            showToast(`Đang trích xuất metadata cho ${result.filename || 'tài liệu đã chọn'}.`, 'info');
            stopExtractionPolling();
            pollExtractionStatus();
        } catch (error) {
            extractionObservedRunning = false;
            updateExtractionButton();
            showToast(`Không thể trích xuất tài liệu này: ${error.message}`, 'error');
        }
    }

    async function stopMetadataExtraction() {
        if (!isMetadataExtractionRunning) return;
        dom.stopExtraction.disabled = true;
        dom.stopExtraction.innerHTML = `${icon('stop')}Đang dừng…`;
        try {
            await apiPost('/scrape/extract/stop', {});
            showToast('Đã yêu cầu dừng. Hệ thống sẽ kết thúc an toàn sau bài đang xử lý.', 'info');
            stopExtractionPolling();
            pollExtractionStatus();
        } catch (error) {
            dom.stopExtraction.disabled = false;
            showToast(`Không thể dừng trích xuất: ${error.message}`, 'error');
        }
    }

    async function loadStats() {
        try {
            const stats = await apiGet('/stats');
            dom.overviewTotal.textContent = stats.total ?? '—'; dom.statTotal.textContent = stats.total ?? '—';
        } catch (error) { dom.overviewTotal.textContent = '—'; dom.statTotal.textContent = '—'; }
    }
    async function checkHealth() {
        try {
            const health = await apiGet('/health'); const connected = health.database === 'connected';
            dom.sidebarHealth.textContent = connected ? 'Hệ thống sẵn sàng' : 'Cần kiểm tra cơ sở dữ liệu'; dom.sidebarHealthDetail.textContent = connected ? 'API và cơ sở dữ liệu đã kết nối' : 'API hoạt động, cơ sở dữ liệu chưa kết nối'; dom.sidebarHealthDot.className = `status-indicator ${connected ? 'is-ok' : 'is-warning'}`;
        } catch { dom.sidebarHealth.textContent = 'Không thể kết nối API'; dom.sidebarHealthDetail.textContent = 'Kiểm tra backend rồi thử lại'; dom.sidebarHealthDot.className = 'status-indicator is-error'; }
    }
    async function checkInitialStatus() {
        try { const status = await apiGet('/scrape/status'); updateJobStatus(status); if (status.running) { switchCrawlerControls(true); startPolling(); } else switchCrawlerControls(false); }
        catch (error) { showToast('Không thể lấy trạng thái crawler.', 'warning'); }
    }

    function debounce(callback, delay = 300) { let timer; return (...args) => { window.clearTimeout(timer); timer = window.setTimeout(() => callback(...args), delay); }; }

    function bindEvents() {
        dom.scrapeForm.addEventListener('submit', (event) => { event.preventDefault(); startScrape(); });
        dom.stopScrape.addEventListener('click', stopScrape);
        dom.clearLog.addEventListener('click', () => { dom.logConsole.innerHTML = '<p class="log-console__placeholder">Nhật ký hiển thị đã được xóa. Lần cập nhật trạng thái tiếp theo có thể nạp lại nhật ký từ backend.</p>'; });
        dom.uploadZone.addEventListener('click', () => { if (!isUploading) dom.fileUpload.click(); });
        dom.uploadZone.addEventListener('keydown', (event) => { if ((event.key === 'Enter' || event.key === ' ') && !isUploading) { event.preventDefault(); dom.fileUpload.click(); } });
        dom.fileUpload.addEventListener('change', () => handleUpload(dom.fileUpload.files?.[0]));
        ['dragenter', 'dragover'].forEach((eventName) => dom.uploadZone.addEventListener(eventName, (event) => { event.preventDefault(); if (!isUploading) dom.uploadZone.classList.add('is-dragover'); }));
        ['dragleave', 'drop'].forEach((eventName) => dom.uploadZone.addEventListener(eventName, (event) => { event.preventDefault(); dom.uploadZone.classList.remove('is-dragover'); }));
        dom.uploadZone.addEventListener('drop', (event) => handleUpload(event.dataTransfer.files?.[0]));
        dom.searchInput.addEventListener('input', debounce(() => loadPdfList(1)));
        dom.refreshLibrary.addEventListener('click', () => loadPdfList(currentPage, { preserveViewport: true })); dom.prevPage.addEventListener('click', () => { if (currentPage > 1) loadPdfList(currentPage - 1, { preserveViewport: true }); }); dom.nextPage.addEventListener('click', () => loadPdfList(currentPage + 1, { preserveViewport: true }));
        dom.extractScraped.addEventListener('click', startScrapedExtraction);
        dom.stopExtraction.addEventListener('click', stopMetadataExtraction);
        dom.pdfTableBody.addEventListener('click', (event) => {
            const button = event.target.closest('button[data-extract-paper-id]');
            if (button?.dataset.extractPaperId) startSingleMetadataExtraction(button.dataset.extractPaperId);
        });
        dom.resultsSearchInput.addEventListener('input', debounce(() => loadResults(1))); dom.refreshResults.addEventListener('click', () => loadResults(resultsPage)); dom.resultsPrev.addEventListener('click', () => { if (resultsPage > 1) loadResults(resultsPage - 1); }); dom.resultsNext.addEventListener('click', () => loadResults(resultsPage + 1));
        [dom.pdfTableBody, dom.resultsTableBody].forEach((container) => container.addEventListener('click', (event) => { const button = event.target.closest('button[data-paper-id]'); if (button?.dataset.paperId) openPaperDetail(button.dataset.paperId); }));
        dom.closeModal.addEventListener('click', closePaperDetail); dom.modalOverlay.addEventListener('click', (event) => { if (event.target === dom.modalOverlay) closePaperDetail(); }); dom.saveReview.addEventListener('click', saveReview); document.addEventListener('keydown', trapModalFocus);
    }

    function init() {
        initializeNavigation(); bindEvents(); checkHealth(); checkInitialStatus(); pollExtractionStatus(); loadStats(); loadPdfList(); loadResults();
    }
    init();
})();
