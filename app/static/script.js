/**
 * script.js — Frontend logic for Medical PDF Corpus Builder
 * Handles: scraping control, status polling, upload, PDF table, stats
 */

(() => {
    'use strict';

    // ═══════════════════════════════════════════════
    // Config
    // ═══════════════════════════════════════════════
    const API_BASE = '/api';
    const POLL_INTERVAL = 1500; // ms

    // ═══════════════════════════════════════════════
    // DOM References
    // ═══════════════════════════════════════════════
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const dom = {
        // Scraper form
        scrapeForm: $('#scrape-form'),
        scrapeUrl: $('#scrape-url'),
        maxDepth: $('#max-depth'),
        btnStartScrape: $('#btn-start-scrape'),
        btnStopScrape: $('#btn-stop-scrape'),

        // Status
        statusBadge: $('#scraper-status-badge'),
        statusText: $('#scraper-status-text'),

        // Log console
        logConsole: $('#log-console'),
        btnClearLog: $('#btn-clear-log'),

        // Progress
        progressContainer: $('#scrape-progress-container'),
        progressFill: $('#scrape-progress-fill'),
        progressLabel: $('#progress-label'),
        progressCount: $('#progress-count'),

        // Upload
        uploadZone: $('#upload-zone'),
        fileUpload: $('#file-upload'),
        uploadProgress: $('#upload-progress'),
        uploadProgressFill: $('#upload-progress-fill'),
        uploadProgressText: $('#upload-progress-text'),

        // Stats
        statTotal: $('#stat-total'),
        statDownloaded: $('#stat-downloaded'),
        statDuplicates: $('#stat-duplicates'),
        statErrors: $('#stat-errors'),
        statTotalHero: $('#stat-total-hero'),
        statScrapedHero: $('#stat-scraped-hero'),
        statUploadedHero: $('#stat-uploaded-hero'),

        // Library
        pdfTableBody: $('#pdf-table-body'),
        searchInput: $('#search-input'),
        btnRefreshLibrary: $('#btn-refresh-library'),
        btnPrevPage: $('#btn-prev-page'),
        btnNextPage: $('#btn-next-page'),
        paginationInfo: $('#pagination-info'),

        // Toast
        toastContainer: $('#toast-container'),
    };

    // ═══════════════════════════════════════════════
    // State
    // ═══════════════════════════════════════════════
    let pollTimer = null;
    let lastLogCount = 0;
    let currentPage = 1;
    const pageLimit = 20;

    // ═══════════════════════════════════════════════
    // Toast System
    // ═══════════════════════════════════════════════
    function showToast(message, type = 'info') {
        const icons = {
            success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️'
        };

        const toast = document.createElement('div');
        toast.className = `toast toast--${type}`;
        toast.innerHTML = `
            <span class="toast__icon">${icons[type] || icons.info}</span>
            <span class="toast__msg">${escapeHtml(message)}</span>
        `;

        dom.toastContainer.appendChild(toast);

        setTimeout(() => {
            toast.classList.add('toast-out');
            toast.addEventListener('animationend', () => toast.remove());
        }, 4000);
    }

    // ═══════════════════════════════════════════════
    // API Helpers
    // ═══════════════════════════════════════════════
    async function apiGet(endpoint) {
        const res = await fetch(`${API_BASE}${endpoint}`);
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || res.statusText);
        }
        return res.json();
    }

    async function apiPost(endpoint, body) {
        const res = await fetch(`${API_BASE}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || res.statusText);
        }
        return res.json();
    }

    // ═══════════════════════════════════════════════
    // Scraping
    // ═══════════════════════════════════════════════
    async function startScrape() {
        const url = dom.scrapeUrl.value.trim();
        if (!url) {
            showToast('Vui lòng nhập URL', 'warning');
            dom.scrapeUrl.focus();
            return;
        }

        try {
            dom.btnStartScrape.disabled = true;
            await apiPost('/scrape', {
                url: url,
                max_depth: parseInt(dom.maxDepth.value) || 2,
            });

            showToast('Đã bắt đầu quét!', 'success');
            switchToRunning();
            startPolling();
        } catch (err) {
            showToast(err.message, 'error');
            dom.btnStartScrape.disabled = false;
        }
    }

    async function stopScrape() {
        try {
            await apiPost('/scrape/stop', {});
            showToast('Đã gửi yêu cầu dừng', 'info');
        } catch (err) {
            showToast(err.message, 'error');
        }
    }

    function switchToRunning() {
        dom.btnStartScrape.style.display = 'none';
        dom.btnStopScrape.style.display = 'flex';
        dom.progressContainer.style.display = 'block';
        updateStatusBadge('running', 'Đang quét...');
    }

    function switchToIdle() {
        dom.btnStartScrape.style.display = 'flex';
        dom.btnStartScrape.disabled = false;
        dom.btnStopScrape.style.display = 'none';
        dom.progressContainer.style.display = 'none';
    }

    function updateStatusBadge(state, text) {
        const dot = dom.statusBadge.querySelector('.status-dot');
        dot.className = `status-dot status-dot--${state}`;
        dom.statusText.textContent = text;
    }

    // ═══════════════════════════════════════════════
    // Polling
    // ═══════════════════════════════════════════════
    function startPolling() {
        stopPolling();
        lastLogCount = 0;
        pollStatus();
        pollTimer = setInterval(pollStatus, POLL_INTERVAL);
    }

    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    async function pollStatus() {
        try {
            const data = await apiGet('/scrape/status');
            updateFromStatus(data);

            if (data.done || (!data.running && !data.should_stop)) {
                stopPolling();
                switchToIdle();
                if (data.done) {
                    updateStatusBadge('done', 'Hoàn tất');
                    showToast(
                        `Hoàn tất! Tải: ${data.downloaded}, Bỏ qua: ${data.skipped}, Lỗi: ${data.errors}`,
                        data.errors > 0 ? 'warning' : 'success'
                    );
                    loadPdfList();
                    loadStats();
                }
            }
        } catch (err) {
            console.error('Poll error:', err);
        }
    }

    function updateFromStatus(data) {
        // Progress bar
        const total = data.total_found || 1;
        const done = data.downloaded + data.skipped + data.duplicates + data.errors;
        const pct = Math.min((done / total) * 100, 100);
        dom.progressFill.style.width = `${pct}%`;
        dom.progressLabel.textContent = data.current_url
            ? `Đang xử lý: ${truncateUrl(data.current_url, 60)}`
            : 'Đang quét...';
        dom.progressCount.textContent = `${done}/${data.total_found}`;

        // Scrape stats
        dom.statDownloaded.textContent = data.downloaded;
        dom.statDuplicates.textContent = data.duplicates;
        dom.statErrors.textContent = data.errors;

        // Log messages — append only new ones
        const logs = data.log_messages || [];
        if (logs.length > lastLogCount) {
            const newLogs = logs.slice(lastLogCount);
            for (const log of newLogs) {
                appendLogEntry(log);
            }
            lastLogCount = logs.length;
        }
    }

    // ═══════════════════════════════════════════════
    // Log Console
    // ═══════════════════════════════════════════════
    function appendLogEntry(log) {
        const entry = document.createElement('div');
        const level = classifyLogLevel(log.level, log.message);
        entry.className = `log-entry log-entry--${level}`;
        entry.innerHTML = `
            <span class="log-time">${escapeHtml(log.time)}</span>
            <span class="log-msg">${escapeHtml(log.message)}</span>
        `;
        dom.logConsole.appendChild(entry);
        dom.logConsole.scrollTop = dom.logConsole.scrollHeight;
    }

    function classifyLogLevel(level, message) {
        if (level === 'error') return 'error';
        if (level === 'warning') return 'warning';
        if (message.includes('✅') || message.includes('🏁')) return 'success';
        return 'info';
    }

    function clearLog() {
        dom.logConsole.innerHTML = `
            <div class="log-entry log-entry--info">
                <span class="log-time">--:--:--</span>
                <span class="log-msg">Log đã được xóa.</span>
            </div>
        `;
        lastLogCount = 0;
    }

    // ═══════════════════════════════════════════════
    // Upload
    // ═══════════════════════════════════════════════
    async function handleUpload(file) {
        if (!file || !file.name.toLowerCase().endsWith('.pdf')) {
            showToast('Chỉ chấp nhận file PDF', 'warning');
            return;
        }

        if (file.size > 50 * 1024 * 1024) {
            showToast('File quá lớn (giới hạn 50MB)', 'warning');
            return;
        }

        dom.uploadProgress.style.display = 'block';
        dom.uploadProgressFill.style.width = '30%';
        dom.uploadProgressText.textContent = `Đang upload: ${file.name}...`;

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch(`${API_BASE}/upload`, {
                method: 'POST',
                body: formData,
            });

            dom.uploadProgressFill.style.width = '100%';

            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: res.statusText }));
                throw new Error(err.detail || 'Upload thất bại');
            }

            const data = await res.json();
            showToast(`Upload thành công: ${file.name}`, 'success');
            loadPdfList();
            loadStats();
        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            setTimeout(() => {
                dom.uploadProgress.style.display = 'none';
                dom.uploadProgressFill.style.width = '0%';
            }, 1500);
        }
    }

    // ═══════════════════════════════════════════════
    // PDF Library
    // ═══════════════════════════════════════════════
    async function loadPdfList(page = 1) {
        currentPage = page;
        try {
            const data = await apiGet(`/pdfs?page=${page}&limit=${pageLimit}`);
            renderPdfTable(data.items, data.total, page);
        } catch (err) {
            console.error('Failed to load PDFs:', err);
        }
    }

    function renderPdfTable(items, total, page) {
        if (!items || items.length === 0) {
            dom.pdfTableBody.innerHTML = `
                <tr class="data-table__empty">
                    <td colspan="5">
                        <div class="empty-state">
                            <span class="empty-state__icon">📭</span>
                            <p class="empty-state__text">Chưa có PDF nào. Bắt đầu thu thập hoặc upload file.</p>
                        </div>
                    </td>
                </tr>
            `;
            dom.paginationInfo.textContent = 'Trang 1';
            dom.btnPrevPage.disabled = true;
            dom.btnNextPage.disabled = true;
            return;
        }

        const startIdx = (page - 1) * pageLimit;
        let html = '';

        for (let i = 0; i < items.length; i++) {
            const item = items[i];
            const filename = item.filename || item.file_path?.split(/[/\\]/).pop() || 'unknown.pdf';
            const source = item.source || 'scrape';
            const size = formatFileSize(item.file_size_bytes || 0);
            const time = formatTime(item.scraped_at || item.processing?.created_at);

            html += `
                <tr>
                    <td>${startIdx + i + 1}</td>
                    <td class="filename-cell" title="${escapeHtml(filename)}">${escapeHtml(filename)}</td>
                    <td>
                        <span class="source-badge source-badge--${source}">
                            ${source === 'scrape' ? '🌐 Scrape' : '📤 Upload'}
                        </span>
                    </td>
                    <td>${size}</td>
                    <td>${time}</td>
                </tr>
            `;
        }

        dom.pdfTableBody.innerHTML = html;

        // Pagination
        const totalPages = Math.ceil(total / pageLimit) || 1;
        dom.paginationInfo.textContent = `Trang ${page} / ${totalPages} (${total} files)`;
        dom.btnPrevPage.disabled = page <= 1;
        dom.btnNextPage.disabled = page >= totalPages;
    }

    // ═══════════════════════════════════════════════
    // Stats
    // ═══════════════════════════════════════════════
    async function loadStats() {
        try {
            const data = await apiGet('/stats');
            // Main stats
            dom.statTotal.textContent = data.total || 0;

            // Hero stats
            dom.statTotalHero.textContent = data.total || 0;
            dom.statScrapedHero.textContent = data.scraped || 0;
            dom.statUploadedHero.textContent = data.uploaded || 0;
        } catch (err) {
            console.error('Failed to load stats:', err);
        }
    }

    // ═══════════════════════════════════════════════
    // Utilities
    // ═══════════════════════════════════════════════
    function escapeHtml(str) {
        if (!str) return '';
        const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
        return String(str).replace(/[&<>"']/g, c => map[c]);
    }

    function truncateUrl(url, maxLen = 80) {
        if (!url || url.length <= maxLen) return url;
        return url.substring(0, maxLen) + '...';
    }

    function formatFileSize(bytes) {
        if (!bytes || bytes === 0) return '—';
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }

    function formatTime(timestamp) {
        if (!timestamp) return '—';
        try {
            // Handle Unix timestamp (number) or ISO string
            const date = typeof timestamp === 'number'
                ? new Date(timestamp * 1000)
                : new Date(timestamp);
            if (isNaN(date.getTime())) return '—';
            return date.toLocaleDateString('vi-VN', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
            });
        } catch {
            return '—';
        }
    }

    // ═══════════════════════════════════════════════
    // Event Listeners
    // ═══════════════════════════════════════════════
    function init() {
        // Scrape form
        dom.scrapeForm.addEventListener('submit', (e) => {
            e.preventDefault();
            startScrape();
        });

        dom.btnStopScrape.addEventListener('click', stopScrape);
        dom.btnClearLog.addEventListener('click', clearLog);

        // Upload
        dom.uploadZone.addEventListener('click', () => dom.fileUpload.click());
        dom.fileUpload.addEventListener('change', (e) => {
            if (e.target.files[0]) handleUpload(e.target.files[0]);
        });

        // Drag & drop
        dom.uploadZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dom.uploadZone.classList.add('drag-over');
        });
        dom.uploadZone.addEventListener('dragleave', () => {
            dom.uploadZone.classList.remove('drag-over');
        });
        dom.uploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dom.uploadZone.classList.remove('drag-over');
            if (e.dataTransfer.files[0]) handleUpload(e.dataTransfer.files[0]);
        });

        // Library
        dom.btnRefreshLibrary.addEventListener('click', () => loadPdfList(currentPage));
        dom.btnPrevPage.addEventListener('click', () => {
            if (currentPage > 1) loadPdfList(currentPage - 1);
        });
        dom.btnNextPage.addEventListener('click', () => {
            loadPdfList(currentPage + 1);
        });

        // Search (debounced)
        let searchTimeout;
        dom.searchInput.addEventListener('input', () => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                // Simple client-side filter (for filesystem fallback)
                loadPdfList(1);
            }, 300);
        });

        // Smooth scroll for nav links
        $$('.nav__link, .hero__actions .btn').forEach(link => {
            link.addEventListener('click', (e) => {
                const href = link.getAttribute('href');
                if (href && href.startsWith('#')) {
                    e.preventDefault();
                    const target = $(href);
                    if (target) {
                        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }
                }
            });
        });

        // Check if scraping is already running on page load
        checkInitialStatus();

        // Load initial data
        loadPdfList();
        loadStats();
    }

    async function checkInitialStatus() {
        try {
            const data = await apiGet('/scrape/status');
            if (data.running) {
                switchToRunning();
                startPolling();
                showToast('Đang có tiến trình quét...', 'info');
            }
        } catch (err) {
            // Server might not be ready yet
            console.debug('Initial status check skipped:', err.message);
        }
    }

    // ═══════════════════════════════════════════════
    // Bootstrap
    // ═══════════════════════════════════════════════
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
