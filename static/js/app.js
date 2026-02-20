/**
 * VOICEcheck - Main Application
 * Handles navigation, file upload, dialogs list, evaluation display, and dashboard
 */

// Get API headers with auth if available
function getAPIHeaders() {
    const token = localStorage.getItem('access_token');
    const headers = { 'Content-Type': 'application/json' };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    return headers;
}

// Auth-enabled fetch wrapper
function authFetch(url, options = {}) {
    const token = localStorage.getItem('access_token');
    if (token) {
        options.headers = options.headers || {};
        options.headers['Authorization'] = `Bearer ${token}`;
    }

    return fetch(url, options).then(response => {
        // Redirect to auth page on 401
        if (response.status === 401 && !url.includes('/auth/')) {
            localStorage.clear();
            window.location.href = '/static/auth.html';
        }
        return response;
    });
}

// Check authentication on page load
function checkAuth() {
    const token = localStorage.getItem('access_token');
    if (!token && window.location.pathname !== '/static/auth.html' && !window.location.pathname.includes('/auth-org/')) {
        window.location.href = '/static/auth.html';
        return false;
    }
    return true;
}

// Run auth check
if (!checkAuth()) {
    // If not authenticated, stop loading
    throw new Error('Authentication required');
}

// Current user and organization
let currentUser = null;
let currentOrg = null;

// Try to load from localStorage
try {
    currentUser = JSON.parse(localStorage.getItem('user') || 'null');
    currentOrg = JSON.parse(localStorage.getItem('current_org') || 'null');
} catch (e) {}

class VoiceCheckApp {
    constructor() {
        this.currentTab = 'upload';

        // Upload state
        this.fileId = null;
        this.taskId = null;
        this.selectedFile = null;
        this.statusCheckInterval = null;

        // Dialogs state
        this.currentPage = 1;
        this.dialogsPerPage = 20;
        this.dialogs = [];
        this.totalDialogs = 0;
        this.filters = {
            status: '',
            date_from: '',
            date_to: '',
            search: '',
            seller_name: '',
            min_score: ''
        };

        // Evaluation state
        this.currentDialogId = null;
        this.evaluationData = null;

        // Chart.js instances
        this.speakingTimeChart = null;
        this.scoringDynamicsChart = null;

        // Audio state
        this.audioElement = null;

        // Debounce timers
        this._searchTimer = null;
        this._sellerTimer = null;

        this.initElements();
        this.attachEventListeners();
        this.addAuthUI();
        this.loadSellers();
    }

    addAuthUI() {
        // Add auth info to header if logged in
        if (currentUser) {
            const header = document.querySelector('.header-content');
            if (header) {
                const authInfo = document.createElement('div');
                authInfo.className = 'auth-info';
                authInfo.style.cssText = 'margin-top: 8px; font-size: 13px; color: #64748b;';
                let orgText = currentOrg ? ` | ${currentOrg.name}` : '';
                authInfo.innerHTML = `
                    ${currentUser.email}${orgText}
                    <a href="/static/organizations.html" style="color: #1e3a5f; margin-left: 8px;">Организации</a>
                    <a href="#" onclick="logout()" style="color: #ef4444; margin-left: 8px;">Выйти</a>
                `;
                header.appendChild(authInfo);
            }
        }
    }

    initElements() {
        // Tab navigation
        this.tabBtns = document.querySelectorAll('.tab-btn');
        this.tabPanes = document.querySelectorAll('.tab-pane');

        // Upload elements
        this.uploadArea = document.querySelector('#upload-tab .upload-area');
        this.fileInput = document.querySelector('#upload-tab #fileInput');
        this.fileInfo = document.querySelector('#upload-tab .file-info');
        this.fileName = document.querySelector('#upload-tab .file-name');
        this.fileSize = document.querySelector('#upload-tab .file-size');
        this.changeFileBtn = document.getElementById('changeFileBtn');
        this.uploadBtn = document.getElementById('uploadBtn');
        this.languageSelector = document.getElementById('languageSelector');
        this.languageSelect = document.getElementById('languageSelect');
        this.sellerInput = document.getElementById('sellerInput');
        this.sellerNameInput = document.getElementById('sellerName');

        // Status elements
        this.statusArea = document.getElementById('statusArea');
        this.statusMessage = document.getElementById('statusMessage');
        this.progressFill = document.getElementById('progressFill');

        // Result elements
        this.resultArea = document.getElementById('resultArea');
        this.resultText = document.getElementById('resultText');
        this.resultMeta = document.getElementById('resultMeta');
        this.copyBtn = document.getElementById('copyBtn');
        this.newTranscriptionBtn = document.getElementById('newTranscriptionBtn');

        // Error element
        this.errorMessage = document.getElementById('errorMessage');

        // Dialogs elements
        this.dialogsList = document.getElementById('dialogsList');
        this.pagination = document.getElementById('pagination');
        this.statusFilter = document.getElementById('statusFilter');
        this.dateFromFilter = document.getElementById('dateFromFilter');
        this.dateToFilter = document.getElementById('dateToFilter');
        this.searchFilter = document.getElementById('searchFilter');
        this.sellerFilter = document.getElementById('sellerFilter');
        this.scoreFilter = document.getElementById('scoreFilter');

        // Dashboard elements
        this.statsGrid = document.getElementById('statsGrid');
        this.dashDateFrom = document.getElementById('dashDateFrom');
        this.dashDateTo = document.getElementById('dashDateTo');
        this.dashSellerFilter = document.getElementById('dashSellerFilter');
        this.dashRefreshBtn = document.getElementById('dashRefreshBtn');
        this.objectionsListContainer = document.getElementById('objectionsListContainer');

        // Modal elements
        this.modal = document.getElementById('evaluationModal');
        this.modalClose = document.querySelector('.close-btn');
        this.evaluationContent = document.getElementById('evaluationContent');
    }

    attachEventListeners() {
        // Tab navigation
        this.tabBtns.forEach(btn => {
            btn.addEventListener('click', () => this.switchTab(btn.dataset.tab));
        });

        // Upload
        this.attachUploadEventListeners();

        // Dialog filters
        this.statusFilter.addEventListener('change', () => {
            this.filters.status = this.statusFilter.value;
            this.currentPage = 1;
            this.loadDialogs();
        });
        this.dateFromFilter.addEventListener('change', () => {
            this.filters.date_from = this.dateFromFilter.value;
            this.currentPage = 1;
            this.loadDialogs();
        });
        this.dateToFilter.addEventListener('change', () => {
            this.filters.date_to = this.dateToFilter.value;
            this.currentPage = 1;
            this.loadDialogs();
        });
        this.searchFilter.addEventListener('input', () => {
            clearTimeout(this._searchTimer);
            this._searchTimer = setTimeout(() => {
                this.filters.search = this.searchFilter.value.trim();
                this.currentPage = 1;
                this.loadDialogs();
            }, 400);
        });
        this.sellerFilter.addEventListener('change', () => {
            this.filters.seller_name = this.sellerFilter.value;
            this.currentPage = 1;
            this.loadDialogs();
        });
        this.scoreFilter.addEventListener('change', () => {
            this.filters.min_score = this.scoreFilter.value;
            this.currentPage = 1;
            this.loadDialogs();
        });

        // Dashboard
        this.dashRefreshBtn.addEventListener('click', () => this.loadDashboard());

        // Organizations
        const createOrgBtn = document.getElementById('createOrgBtn');
        if (createOrgBtn) {
            createOrgBtn.addEventListener('click', () => showCreateOrgForm());
        }

        const backToOrgsBtn = document.getElementById('backToOrgsBtn');
        if (backToOrgsBtn) {
            backToOrgsBtn.addEventListener('click', () => backToOrganizations());
        }

        const addMemberBtn = document.getElementById('addMemberBtn');
        if (addMemberBtn) {
            addMemberBtn.addEventListener('click', () => addMember());
        }

        // Modal
        this.modalClose.addEventListener('click', () => this.closeModal());
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) this.closeModal();
        });
    }

    attachUploadEventListeners() {
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            document.body.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
            }, false);
        });

        this.uploadArea.addEventListener('click', () => this.fileInput.click());

        this.fileInput.addEventListener('change', (e) => {
            this.handleFileSelect(e.target.files[0]);
        });

        this.uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            this.uploadArea.classList.add('dragover');
        });
        this.uploadArea.addEventListener('dragleave', () => {
            this.uploadArea.classList.remove('dragover');
        });
        this.uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            this.uploadArea.classList.remove('dragover');
            if (e.dataTransfer.files[0]) this.handleFileSelect(e.dataTransfer.files[0]);
        });

        this.changeFileBtn.addEventListener('click', () => this.fileInput.click());
        this.uploadBtn.addEventListener('click', () => this.uploadFile());
        this.copyBtn.addEventListener('click', () => this.copyToClipboard());
        this.newTranscriptionBtn.addEventListener('click', () => this.resetUpload());

        // Handle "new seller" option in upload dropdown
        this.sellerNameInput.addEventListener('change', () => {
            if (this.sellerNameInput.value === '__new__') {
                const name = prompt('Введите имя нового продавца:');
                if (name && name.trim()) {
                    const opt = document.createElement('option');
                    opt.value = name.trim();
                    opt.textContent = name.trim();
                    // Insert before the "__new__" option
                    const newOpt = this.sellerNameInput.querySelector('option[value="__new__"]');
                    this.sellerNameInput.insertBefore(opt, newOpt);
                    this.sellerNameInput.value = name.trim();
                } else {
                    this.sellerNameInput.value = '';
                }
            }
        });
    }

    // -----------------------------------------------------------------------
    // Tab navigation
    // -----------------------------------------------------------------------

    switchTab(tab) {
        this.currentTab = tab;
        this.tabBtns.forEach(btn => btn.classList.toggle('active', btn.dataset.tab === tab));
        this.tabPanes.forEach(pane => pane.classList.toggle('active', pane.id === `${tab}-tab`));

        if (tab === 'dialogs') this.loadDialogs();
        if (tab === 'organizations') loadOrganizationsForTab();
        if (tab === 'dashboard') this.loadDashboard();
    }

    // -----------------------------------------------------------------------
    // Upload methods
    // -----------------------------------------------------------------------

    handleFileSelect(file) {
        if (!file) return;

        const allowedExtensions = ['.mp3', '.wav', '.m4a', '.ogg', '.flac', '.mp4', '.webm'];
        const ext = '.' + file.name.split('.').pop().toLowerCase();

        if (!file.type.startsWith('audio/') && !file.type.startsWith('video/') &&
            !allowedExtensions.includes(ext)) {
            this.showError('Пожалуйста, выберите аудиофайл (MP3, WAV, M4A, OGG, FLAC)');
            return;
        }

        if (file.size > 50 * 1024 * 1024) {
            this.showError('Файл слишком большой. Максимальный размер: 50MB');
            return;
        }

        this.selectedFile = file;
        this.hideError();

        this.fileName.textContent = file.name;
        this.fileSize.textContent = this.formatFileSize(file.size);
        this.uploadArea.style.display = 'none';
        this.fileInfo.classList.add('active');
        this.languageSelector.style.display = 'block';
        this.sellerInput.style.display = 'block';
        this.uploadBtn.disabled = false;
    }

    async uploadFile() {
        if (!this.selectedFile) return;

        this.hideError();
        this.uploadBtn.disabled = true;
        this.uploadBtn.textContent = 'Загрузка...';

        const formData = new FormData();
        formData.append('file', this.selectedFile);

        const sellerName = this.sellerNameInput.value;
        if (sellerName && sellerName !== '__new__') {
            formData.append('seller_name', sellerName);
        }

        try {
            const response = await authFetch('/upload', { method: 'POST', body: formData });
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Ошибка загрузки файла');
            }

            const data = await response.json();
            this.fileId = data.file_id;
            await this.startTranscription();
        } catch (error) {
            this.showError(error.message);
            this.uploadBtn.disabled = false;
            this.uploadBtn.textContent = 'Загрузить файл';
        }
    }

    async startTranscription() {
        this.statusArea.classList.add('active');
        this.statusMessage.textContent = 'Подготовка к транскрибации...';

        const language = this.languageSelect.value;

        try {
            const response = await authFetch(`/transcribe/${this.fileId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `language=${language}&with_speakers=true`
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Ошибка начала транскрибации');
            }

            const data = await response.json();
            this.taskId = data.task_id;
            this.startStatusPolling();
        } catch (error) {
            this.showError(error.message);
            this.statusArea.classList.remove('active');
        }
    }

    startStatusPolling() {
        this.checkStatus();
        this.statusCheckInterval = setInterval(() => this.checkStatus(), 1000);
    }

    async checkStatus() {
        if (!this.taskId) return;

        try {
            const response = await authFetch(`/status/${this.taskId}`);
            if (!response.ok) throw new Error('Ошибка получения статуса');

            const data = await response.json();

            if (this.progressFill) this.progressFill.style.width = `${data.progress}%`;

            if (data.status === 'processing') {
                this.statusMessage.textContent = data.message || 'Транскрибация...';
            } else if (data.status === 'completed') {
                this.stopPolling();
                this.showResult(data);
            } else if (data.status === 'failed') {
                this.stopPolling();
                this.showError(data.message || 'Ошибка транскрибации');
                this.statusArea.classList.remove('active');
            }
        } catch (error) {
            console.error('Status check error:', error);
        }
    }

    stopPolling() {
        if (this.statusCheckInterval) {
            clearInterval(this.statusCheckInterval);
            this.statusCheckInterval = null;
        }
    }

    showResult(data) {
        this.statusArea.classList.remove('active');
        this.resultArea.classList.add('active');

        if (data.result) {
            const duration = this.formatDuration(data.result.duration);
            const language = data.result.language.toUpperCase();
            this.resultMeta.textContent = `Длительность: ${duration} | Язык: ${language}`;

            const segments = data.result.segments || [];
            if (segments.length > 0 && segments.some(s => s.speaker)) {
                // Merge consecutive segments from the same speaker
                const merged = [];
                for (const seg of segments) {
                    const speaker = seg.speaker || 'SPEAKER_00';
                    const last = merged[merged.length - 1];
                    if (last && last.speaker === speaker) {
                        last.text += ' ' + seg.text;
                        last.end = seg.end;
                    } else {
                        merged.push({ speaker, text: seg.text, start: seg.start, end: seg.end });
                    }
                }
                // Render merged blocks
                this.resultText.innerHTML = merged.map(seg => {
                    const label = seg.speaker === 'SPEAKER_00' ? 'Продавец' : (seg.speaker === 'SPEAKER_01' ? 'Клиент' : seg.speaker);
                    const cls = seg.speaker === 'SPEAKER_00' ? 'result-speaker-sales' : 'result-speaker-customer';
                    const time = this.formatDuration(seg.start);
                    return `<div class="result-segment"><span class="result-seg-time">[${time}]</span> <span class="result-seg-speaker ${cls}">${label}:</span> ${seg.text}</div>`;
                }).join('');
            } else {
                this.resultText.textContent = data.result.text;
            }
        }
    }

    async copyToClipboard() {
        try {
            await navigator.clipboard.writeText(this.resultText.textContent);
            this.copyBtn.textContent = 'Скопировано!';
            setTimeout(() => { this.copyBtn.textContent = 'Копировать'; }, 2000);
        } catch {
            const ta = document.createElement('textarea');
            ta.value = this.resultText.textContent;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            this.copyBtn.textContent = 'Скопировано!';
            setTimeout(() => { this.copyBtn.textContent = 'Копировать'; }, 2000);
        }
    }

    resetUpload() {
        this.fileId = null;
        this.taskId = null;
        this.selectedFile = null;

        this.fileInput.value = '';
        this.uploadArea.style.display = 'block';
        this.fileInfo.classList.remove('active');
        this.languageSelector.style.display = 'none';
        this.sellerInput.style.display = 'none';
        this.sellerNameInput.value = '';  // reset to "Не указан"
        this.uploadBtn.disabled = true;
        this.uploadBtn.textContent = 'Загрузить файл';
        this.statusArea.classList.remove('active');
        this.resultArea.classList.remove('active');
        this.progressFill.style.width = '0%';
        this.hideError();
    }

    showError(message) {
        this.errorMessage.textContent = message;
        this.errorMessage.classList.add('active');
    }

    hideError() {
        this.errorMessage.classList.remove('active');
    }

    // -----------------------------------------------------------------------
    // Dialogs list
    // -----------------------------------------------------------------------

    async loadDialogs() {
        try {
            const params = new URLSearchParams();
            params.append('page', this.currentPage);
            params.append('limit', this.dialogsPerPage);
            if (this.filters.status) params.append('status', this.filters.status);
            if (this.filters.date_from) params.append('date_from', this.filters.date_from);
            if (this.filters.date_to) params.append('date_to', this.filters.date_to);
            if (this.filters.search) params.append('search', this.filters.search);
            if (this.filters.seller_name) params.append('seller_name', this.filters.seller_name);
            if (this.filters.min_score) params.append('min_score', this.filters.min_score);

            const response = await authFetch(`/dialogs?${params}`);

            if (response.status === 404) {
                this.dialogs = [];
                this.totalDialogs = 0;
                this.renderDialogs();
                return;
            }
            if (!response.ok) throw new Error('Ошибка загрузки диалогов');

            const data = await response.json();
            this.dialogs = data.items || [];
            this.totalDialogs = data.total || 0;
            this.renderDialogs();
            this.renderPagination();
        } catch (error) {
            console.error('Error loading dialogs:', error);
            this.dialogs = [];
            this.totalDialogs = 0;
            this.renderDialogs();
        }
    }

    renderDialogs() {
        if (this.dialogs.length === 0) {
            this.dialogsList.innerHTML = '<div class="no-dialogs"><p>Нет диалогов</p></div>';
            return;
        }

        this.dialogsList.innerHTML = this.dialogs.map(dialog => {
            const scoreDisplay = dialog.overall_score != null
                ? dialog.overall_score.toFixed(1)
                : (dialog.has_analysis ? '...' : '-');

            const sellerTag = dialog.seller_name
                ? `<span class="dialog-seller">${dialog.seller_name}</span>`
                : '';

            return `
                <div class="dialog-item" data-dialog-id="${dialog.id}">
                    <div class="dialog-info">
                        <div class="dialog-filename">${dialog.filename}</div>
                        <div class="dialog-meta">
                            <span class="dialog-date">${new Date(dialog.created_at).toLocaleDateString('ru-RU')}</span>
                            <span class="dialog-duration">${this.formatDuration(dialog.duration)}</span>
                            <span class="status-badge ${dialog.status}">${this.getStatusText(dialog.status)}</span>
                            ${sellerTag}
                        </div>
                    </div>
                    <div class="dialog-score">
                        <div class="dialog-score-value">${scoreDisplay}</div>
                        <div class="dialog-score-label">Балл</div>
                    </div>
                </div>
            `;
        }).join('');

        this.dialogsList.querySelectorAll('.dialog-item').forEach(item => {
            item.addEventListener('click', () => this.openEvaluation(item.dataset.dialogId));
        });
    }

    renderPagination() {
        const totalPages = Math.ceil(this.totalDialogs / this.dialogsPerPage);
        if (totalPages <= 1) { this.pagination.innerHTML = ''; return; }

        let html = '';
        html += `<button class="page-btn" ${this.currentPage === 1 ? 'disabled' : ''} onclick="app.goToPage(${this.currentPage - 1})">&#8592;</button>`;

        const start = Math.max(1, this.currentPage - 2);
        const end = Math.min(totalPages, this.currentPage + 2);

        if (start > 1) {
            html += `<button class="page-btn" onclick="app.goToPage(1)">1</button>`;
            if (start > 2) html += `<span class="page-dots">...</span>`;
        }

        for (let i = start; i <= end; i++) {
            html += `<button class="page-btn ${i === this.currentPage ? 'active' : ''}" onclick="app.goToPage(${i})">${i}</button>`;
        }

        if (end < totalPages) {
            if (end < totalPages - 1) html += `<span class="page-dots">...</span>`;
            html += `<button class="page-btn" onclick="app.goToPage(${totalPages})">${totalPages}</button>`;
        }

        html += `<button class="page-btn" ${this.currentPage === totalPages ? 'disabled' : ''} onclick="app.goToPage(${this.currentPage + 1})">&#8594;</button>`;
        this.pagination.innerHTML = html;
    }

    goToPage(page) {
        this.currentPage = page;
        this.loadDialogs();
    }

    getStatusText(status) {
        const map = {
            'completed': 'Завершен',
            'dealed': 'Сделка',
            'in_progress': 'В работе',
            'rejected': 'Отклонен',
            'pending': 'Ожидание',
            'processing': 'Обработка',
            'failed': 'Ошибка'
        };
        return map[status] || status;
    }

    // -----------------------------------------------------------------------
    // Evaluation modal
    // -----------------------------------------------------------------------

    async openEvaluation(dialogId) {
        this.currentDialogId = dialogId;
        this.modal.classList.add('active');

        this.evaluationContent.innerHTML = '<p style="text-align:center;color:var(--text-muted)">Загрузка...</p>';

        try {
            const response = await authFetch(`/dialogs/${dialogId}`);
            if (!response.ok) throw new Error('Ошибка загрузки диалога');

            this.evaluationData = await response.json();
            this.renderEvaluation();
        } catch (error) {
            console.error('Error loading evaluation:', error);
            this.evaluationContent.innerHTML = '<p style="color:var(--danger-color)">Ошибка загрузки данных</p>';
        }
    }

    renderEvaluation() {
        if (!this.evaluationData) return;

        const d = this.evaluationData;
        const scores = d.analysis?.scores || {};
        const overallScore = scores.overall || 0;
        const summary = d.analysis?.summary || null;
        const speakingTime = d.analysis?.speaking_time || { sales: 0, customer: 0 };
        const totalTime = (speakingTime.sales || 0) + (speakingTime.customer || 0);
        const salesPct = totalTime > 0 ? ((speakingTime.sales / totalTime) * 100).toFixed(0) : 0;
        const customerPct = totalTime > 0 ? ((speakingTime.customer / totalTime) * 100).toFixed(0) : 0;

        this.evaluationContent.innerHTML = `
            <div class="evaluation-header">
                <h2 class="evaluation-title">${d.filename}</h2>
                <div class="evaluation-meta">
                    ${new Date(d.created_at).toLocaleDateString('ru-RU')} |
                    ${this.formatDuration(d.duration)}
                    ${d.seller_name ? ' | ' + d.seller_name : ''}
                </div>
            </div>

            ${summary ? `
            <div class="summary-section">
                <h3>Резюме встречи</h3>
                <p class="summary-text">${summary}</p>
            </div>
            ` : ''}

            <!-- Audio Player -->
            <div class="audio-player-section">
                <h3>Аудиозапись</h3>
                <audio id="dialogAudio" controls preload="none">
                    <source src="/dialogs/${d.id}/audio" type="audio/mpeg">
                </audio>
            </div>

            <!-- Scores -->
            <div class="scores-section">
                <h3>Оценка диалога</h3>
                <div class="scores-grid">
                    ${this.renderScoreItem('Приветствие и контакт', scores.greeting)}
                    ${this.renderScoreItem('Выявление потребностей', scores.needs_discovery)}
                    ${this.renderScoreItem('Презентация решения', scores.presentation)}
                    ${this.renderScoreItem('Работа с возражениями', scores.objection_handling)}
                    ${this.renderScoreItem('Закрытие / CTA', scores.closing)}
                    ${this.renderScoreItem('Активное слушание', scores.active_listening)}
                    ${this.renderScoreItem('Эмпатия и тон', scores.empathy)}
                    <div class="score-item overall-score">
                        <div class="score-label">Общий балл</div>
                        <div class="score-value">${overallScore.toFixed(1)}</div>
                    </div>
                </div>
            </div>

            <!-- Deal Status -->
            <div class="deal-status-section">
                <h3>Статус встречи</h3>
                <div class="status-selector">
                    ${this.renderStatusOption('dealed', 'Сделка состоялась', d.status === 'dealed')}
                    ${this.renderStatusOption('in_progress', 'В работе', d.status === 'in_progress')}
                    ${this.renderStatusOption('rejected', 'Отказ', d.status === 'rejected')}
                </div>
            </div>

            <!-- Speaking Time -->
            <div class="speaking-time-section">
                <h3>Время говорения</h3>
                <div class="speaking-stats">
                    <span class="speaking-stat sales">Продавец: ${(speakingTime.sales || 0).toFixed(0)}с (${salesPct}%)</span>
                    <span class="speaking-stat customer">Клиент: ${(speakingTime.customer || 0).toFixed(0)}с (${customerPct}%)</span>
                </div>
                <div class="speaking-timeline-track">
                    <div class="speaking-bar sales" style="width:${salesPct}%"></div>
                    <div class="speaking-bar customer" style="width:${customerPct}%"></div>
                </div>
                <div class="chart-container">
                    <canvas id="speakingTimeChart"></canvas>
                </div>
                <p class="guideline-text">Оптимальное соотношение: 40% продавец / 60% клиент</p>
            </div>

            <!-- Timeline -->
            <div class="timeline-section">
                <h3>Таймлайн ключевых моментов</h3>
                <div class="timeline">
                    <div class="timeline-line"></div>
                    <div class="timeline-moments">${this.renderTimelineMoments()}</div>
                </div>
            </div>

            <!-- Recommendations -->
            <div class="recommendations-section">
                <h3>Рекомендации</h3>
                ${this.renderRecommendations()}
            </div>

            <!-- Transcript -->
            ${d.segments && d.segments.length > 0 ? `
            <div class="transcript-section">
                <div class="transcript-header">
                    <h3>Транскрипция</h3>
                    <div class="transcript-toggle">
                        <button class="transcript-toggle-btn" data-mode="detailed">Подробная</button>
                        <button class="transcript-toggle-btn active" data-mode="simple">Упрощённая</button>
                    </div>
                </div>
                <div class="transcript-container" id="transcriptContainer">
                    ${this.renderTranscript('simple')}
                </div>
            </div>
            ` : ''}
        `;

        // Attach status option listeners
        this.evaluationContent.querySelectorAll('.status-option').forEach(opt => {
            opt.addEventListener('click', () => this.updateDialogStatus(opt.dataset.status));
        });

        // Transcript toggle
        this.evaluationContent.querySelectorAll('.transcript-toggle-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.evaluationContent.querySelectorAll('.transcript-toggle-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const container = document.getElementById('transcriptContainer');
                if (container) {
                    container.innerHTML = this.renderTranscript(btn.dataset.mode);
                    // Re-attach click-to-seek on new segments
                    container.querySelectorAll('.transcript-segment').forEach(seg => {
                        seg.addEventListener('click', () => {
                            if (this.audioElement) {
                                this.audioElement.currentTime = parseFloat(seg.dataset.start);
                                this.audioElement.play();
                            }
                        });
                    });
                }
            });
        });

        // Init chart and audio after DOM update
        setTimeout(() => {
            this.initSpeakingTimeChart();
            this.initAudioSync();
        }, 100);
    }

    renderScoreItem(label, value) {
        const scoreClass = value != null ? this.getScoreClass(value) : '';
        return `
            <div class="score-item">
                <div class="score-label">${label}</div>
                <div class="score-value ${scoreClass}">${value != null ? value.toFixed(1) : '-'}</div>
            </div>
        `;
    }

    getScoreClass(value) {
        if (value >= 8) return 'score-high';
        if (value >= 5) return 'score-mid';
        return 'score-low';
    }

    renderStatusOption(value, label, selected) {
        return `<div class="status-option ${selected ? 'selected' : ''}" data-status="${value}">${label}</div>`;
    }

    renderTimelineMoments() {
        const moments = this.evaluationData.analysis?.key_moments || [];
        if (moments.length === 0) return '<p class="no-data">Нет ключевых моментов</p>';

        return moments.map((moment, i) => {
            const side = i % 2 === 0 ? 'left' : 'right';
            return `
                <div class="timeline-moment ${side}">
                    <div class="timeline-marker ${moment.type || ''}"></div>
                    <div class="timeline-content">
                        <div class="timeline-time">${this.formatDuration(moment.time)}</div>
                        <div class="timeline-text">${moment.text}</div>
                    </div>
                </div>
            `;
        }).join('');
    }

    renderRecommendations() {
        const recs = this.evaluationData.analysis?.recommendations || [];
        if (recs.length === 0) return '<p class="no-data">Нет рекомендаций</p>';

        return recs.map((rec, i) => `
            <div class="recommendation-item">
                <div class="recommendation-number">${i + 1}</div>
                <div class="recommendation-body">
                    <div class="recommendation-text">${rec.text}</div>
                    ${rec.time_range ? `
                        <div class="recommendation-link" data-time="${rec.time_range[0]}">
                            ${this.formatDuration(rec.time_range[0])} - ${this.formatDuration(rec.time_range[1])}
                        </div>
                    ` : ''}
                </div>
            </div>
        `).join('');
    }

    renderTranscript(mode = 'detailed') {
        const segments = this.evaluationData.segments || [];
        if (mode === 'simple') {
            // Merge consecutive segments from the same speaker
            const merged = [];
            for (const seg of segments) {
                const speaker = seg.speaker || 'SPEAKER_00';
                const last = merged[merged.length - 1];
                if (last && last.speaker === speaker) {
                    last.text += ' ' + seg.text;
                    last.end = seg.end;
                } else {
                    merged.push({ speaker, text: seg.text, start: seg.start, end: seg.end });
                }
            }
            return merged.map(seg => {
                const label = this.getSpeakerLabel(seg.speaker);
                const cls = seg.speaker === 'SPEAKER_00' ? 'speaker-sales' : 'speaker-customer';
                return `
                    <div class="transcript-segment ${cls}" data-start="${seg.start}" data-end="${seg.end}">
                        <span class="seg-time">[${this.formatDuration(seg.start)}]</span>
                        <span class="seg-speaker ${cls}">${label}:</span>
                        <span class="seg-text">${seg.text}</span>
                    </div>
                `;
            }).join('');
        }
        // Detailed mode — each segment separately
        return segments.map((seg, i) => {
            const speakerLabel = this.getSpeakerLabel(seg.speaker);
            const speakerClass = seg.speaker === 'SPEAKER_00' ? 'speaker-sales' : 'speaker-customer';
            return `
                <div class="transcript-segment ${speakerClass}" data-index="${i}" data-start="${seg.start}" data-end="${seg.end}">
                    <span class="seg-time">[${this.formatDuration(seg.start)}]</span>
                    <span class="seg-speaker ${speakerClass}">${speakerLabel}:</span>
                    <span class="seg-text">${seg.text}</span>
                </div>
            `;
        }).join('');
    }

    getSpeakerLabel(speaker) {
        if (speaker === 'SPEAKER_00') return 'Продавец';
        if (speaker === 'SPEAKER_01') return 'Клиент';
        return speaker;
    }

    // -----------------------------------------------------------------------
    // Audio sync
    // -----------------------------------------------------------------------

    initAudioSync() {
        this.audioElement = document.getElementById('dialogAudio');
        if (!this.audioElement) return;

        const container = document.getElementById('transcriptContainer');
        if (!container) return;

        // Track manual scrolling — disable auto-scroll when user scrolls
        let userScrolling = false;
        let scrollTimer = null;

        // Listen on the modal content area (the scrollable parent)
        const modalBody = this.modal.querySelector('.modal-body') || this.modal;
        modalBody.addEventListener('wheel', () => {
            userScrolling = true;
            clearTimeout(scrollTimer);
            scrollTimer = setTimeout(() => { userScrolling = false; }, 5000);
        }, { passive: true });
        modalBody.addEventListener('touchmove', () => {
            userScrolling = true;
            clearTimeout(scrollTimer);
            scrollTimer = setTimeout(() => { userScrolling = false; }, 5000);
        }, { passive: true });

        // Highlight active segment on timeupdate
        this.audioElement.addEventListener('timeupdate', () => {
            const currentTime = this.audioElement.currentTime;
            const segments = container.querySelectorAll('.transcript-segment');
            segments.forEach(seg => {
                const start = parseFloat(seg.dataset.start);
                const end = parseFloat(seg.dataset.end);
                const isActive = currentTime >= start && currentTime < end;
                seg.classList.toggle('active', isActive);
                // Only auto-scroll if user is not manually scrolling
                if (isActive && !userScrolling && !seg.classList.contains('scrolled-to')) {
                    seg.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                    seg.classList.add('scrolled-to');
                }
            });
            // Reset scrolled-to flags for non-active
            container.querySelectorAll('.transcript-segment:not(.active)').forEach(s => {
                s.classList.remove('scrolled-to');
            });
        });

        // Click on segment to seek audio
        container.querySelectorAll('.transcript-segment').forEach(seg => {
            seg.addEventListener('click', () => {
                if (this.audioElement) {
                    this.audioElement.currentTime = parseFloat(seg.dataset.start);
                    this.audioElement.play();
                }
            });
        });

        // Click on recommendation time to seek
        this.evaluationContent.querySelectorAll('.recommendation-link[data-time]').forEach(link => {
            link.addEventListener('click', () => {
                if (this.audioElement) {
                    this.audioElement.currentTime = parseFloat(link.dataset.time);
                    this.audioElement.play();
                }
            });
        });
    }

    // -----------------------------------------------------------------------
    // Speaking time chart
    // -----------------------------------------------------------------------

    initSpeakingTimeChart() {
        const ctx = document.getElementById('speakingTimeChart');
        if (!ctx) return;

        const st = this.evaluationData.analysis?.speaking_time || { sales: 0, customer: 0 };

        if (this.speakingTimeChart) this.speakingTimeChart.destroy();

        this.speakingTimeChart = new Chart(ctx, {
            type: 'pie',
            data: {
                labels: ['Продавец', 'Клиент'],
                datasets: [{
                    data: [st.sales || 0, st.customer || 0],
                    backgroundColor: ['rgba(0, 212, 255, 0.8)', 'rgba(123, 44, 191, 0.8)'],
                    borderColor: ['rgba(0, 212, 255, 1)', 'rgba(123, 44, 191, 1)'],
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { color: '#f1f5f9', padding: 20, font: { size: 14 } }
                    },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                                const pct = ((ctx.parsed / total) * 100).toFixed(1);
                                return `${ctx.label}: ${ctx.parsed.toFixed(0)} сек (${pct}%)`;
                            }
                        }
                    }
                }
            }
        });
    }

    // -----------------------------------------------------------------------
    // Status update
    // -----------------------------------------------------------------------

    updateDialogStatus(status) {
        this.evaluationContent.querySelectorAll('.status-option').forEach(opt => {
            opt.classList.toggle('selected', opt.dataset.status === status);
        });

        fetch(`/dialogs/${this.currentDialogId}/status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status })
        }).catch(err => console.error('Error updating status:', err));
    }

    closeModal() {
        this.modal.classList.remove('active');
        if (this.speakingTimeChart) { this.speakingTimeChart.destroy(); this.speakingTimeChart = null; }
        if (this.audioElement) { this.audioElement.pause(); this.audioElement = null; }
    }

    highlightTimeline(time) {
        const moments = document.querySelectorAll('.timeline-moment');
        if (!moments.length) return;

        const closest = Array.from(moments).reduce((c, m) => {
            const mt = parseFloat(m.querySelector('.timeline-time')?.textContent) || 0;
            const ct = parseFloat(c.querySelector('.timeline-time')?.textContent) || 0;
            return Math.abs(mt - time) < Math.abs(ct - time) ? m : c;
        }, moments[0]);

        closest.querySelector('.timeline-marker').style.transform = 'scale(1.5)';
        closest.querySelector('.timeline-content').style.boxShadow = '0 0 20px rgba(0, 212, 255, 0.5)';
        closest.scrollIntoView({ behavior: 'smooth', block: 'center' });

        setTimeout(() => {
            closest.querySelector('.timeline-marker').style.transform = 'scale(1)';
            closest.querySelector('.timeline-content').style.boxShadow = '';
        }, 3000);
    }

    // -----------------------------------------------------------------------
    // Dashboard
    // -----------------------------------------------------------------------

    async loadDashboard() {
        try {
            const params = new URLSearchParams();
            if (this.dashDateFrom.value) params.append('date_from', this.dashDateFrom.value);
            if (this.dashDateTo.value) params.append('date_to', this.dashDateTo.value);
            if (this.dashSellerFilter.value) params.append('seller_name', this.dashSellerFilter.value);

            const response = await authFetch(`/dialogs/dashboard/stats?${params}`);
            if (!response.ok) throw new Error('Ошибка загрузки дашборда');

            const data = await response.json();
            this.renderDashboardStats(data);
            this.renderScoringDynamicsChart(data.scoring_dynamics || []);
            this.renderObjectionsList(data.common_objections || []);
        } catch (error) {
            console.error('Dashboard error:', error);
            this.statsGrid.innerHTML = '<p class="no-data">Не удалось загрузить статистику</p>';
        }
    }

    renderDashboardStats(data) {
        const avgScore = data.avg_overall_score != null ? data.avg_overall_score.toFixed(1) : '-';
        const dealRate = data.deal_rate != null ? (data.deal_rate * 100).toFixed(1) + '%' : '-';

        this.statsGrid.innerHTML = `
            <div class="stat-card">
                <div class="stat-label">Всего диалогов</div>
                <div class="stat-value">${data.total_dialogs || 0}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Средний балл</div>
                <div class="stat-value">${avgScore}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Конверсия в сделку</div>
                <div class="stat-value">${dealRate}</div>
            </div>
        `;

        // Render category averages if available
        const cats = data.avg_category_scores;
        if (cats && Object.keys(cats).length > 0) {
            const catLabels = {
                greeting: 'Приветствие',
                needs_discovery: 'Потребности',
                presentation: 'Презентация',
                objection_handling: 'Возражения',
                closing: 'Закрытие',
                active_listening: 'Слушание',
                empathy: 'Эмпатия'
            };

            let catHtml = '<div class="stat-card wide"><div class="stat-label">Средние по категориям</div><div class="category-bars">';
            for (const [key, label] of Object.entries(catLabels)) {
                const val = cats[key] || 0;
                const pct = (val / 10) * 100;
                catHtml += `
                    <div class="category-bar-row">
                        <span class="cat-label">${label}</span>
                        <div class="cat-bar-track"><div class="cat-bar-fill" style="width:${pct}%"></div></div>
                        <span class="cat-value">${val.toFixed(1)}</span>
                    </div>
                `;
            }
            catHtml += '</div></div>';
            this.statsGrid.innerHTML += catHtml;
        }
    }

    renderScoringDynamicsChart(dynamics) {
        const canvas = document.getElementById('scoringDynamicsChart');
        if (!canvas) return;

        if (this.scoringDynamicsChart) this.scoringDynamicsChart.destroy();

        if (dynamics.length === 0) {
            canvas.parentElement.innerHTML = '<p class="no-data">Нет данных для графика</p>';
            return;
        }

        this.scoringDynamicsChart = new Chart(canvas, {
            type: 'line',
            data: {
                labels: dynamics.map(d => d.date),
                datasets: [{
                    label: 'Средний балл',
                    data: dynamics.map(d => d.overall_score),
                    borderColor: 'rgba(0, 212, 255, 1)',
                    backgroundColor: 'rgba(0, 212, 255, 0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 4,
                    pointBackgroundColor: 'rgba(0, 212, 255, 1)'
                }]
            },
            options: {
                responsive: true,
                scales: {
                    y: {
                        min: 0,
                        max: 10,
                        ticks: { color: '#94a3b8' },
                        grid: { color: 'rgba(255,255,255,0.05)' }
                    },
                    x: {
                        ticks: { color: '#94a3b8' },
                        grid: { color: 'rgba(255,255,255,0.05)' }
                    }
                },
                plugins: {
                    legend: { labels: { color: '#f1f5f9' } }
                }
            }
        });
    }

    renderObjectionsList(objections) {
        if (objections.length === 0) {
            this.objectionsListContainer.innerHTML = '<p class="no-data">Нет данных о возражениях</p>';
            return;
        }

        this.objectionsListContainer.innerHTML = objections.map((o, i) => `
            <div class="objection-item">
                <span class="objection-rank">${i + 1}</span>
                <span class="objection-text">${o.text}</span>
                <span class="objection-count">${o.count}x</span>
            </div>
        `).join('');
    }

    // -----------------------------------------------------------------------
    // Sellers list
    // -----------------------------------------------------------------------

    async loadSellers() {
        try {
            const response = await authFetch('/dialogs/sellers');
            if (!response.ok) return;
            const sellers = await response.json();
            this.populateSellerDropdowns(sellers);
        } catch (e) {
            console.error('Failed to load sellers:', e);
        }
    }

    populateSellerDropdowns(sellers) {
        // Upload seller dropdown
        const uploadSelect = this.sellerNameInput;
        const currentUpload = uploadSelect.value;
        uploadSelect.innerHTML = '<option value="">Не указан</option>';
        sellers.forEach(name => {
            uploadSelect.innerHTML += `<option value="${name}">${name}</option>`;
        });
        uploadSelect.innerHTML += '<option value="__new__">+ Новый продавец...</option>';
        uploadSelect.value = currentUpload;

        // Dialog filter dropdown
        const filterSelect = this.sellerFilter;
        const currentFilter = filterSelect.value;
        filterSelect.innerHTML = '<option value="">Все продавцы</option>';
        sellers.forEach(name => {
            filterSelect.innerHTML += `<option value="${name}">${name}</option>`;
        });
        filterSelect.value = currentFilter;

        // Dashboard filter dropdown
        const dashSelect = this.dashSellerFilter;
        const currentDash = dashSelect.value;
        dashSelect.innerHTML = '<option value="">Все продавцы</option>';
        sellers.forEach(name => {
            dashSelect.innerHTML += `<option value="${name}">${name}</option>`;
        });
        dashSelect.value = currentDash;
    }

    // -----------------------------------------------------------------------
    // Utilities
    // -----------------------------------------------------------------------

    formatFileSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    formatDuration(seconds) {
        if (seconds == null || isNaN(seconds)) return '0:00';
        const s = Math.floor(seconds);
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        const sec = s % 60;
        if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
        return `${m}:${sec.toString().padStart(2, '0')}`;
    }
}

// Load Chart.js dynamically
function loadChartJS() {
    return new Promise((resolve, reject) => {
        if (window.Chart) { resolve(); return; }
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/chart.js';
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
    });
}

// Logout function
function logout() {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user');
    localStorage.removeItem('current_org');
    window.location.href = '/static/auth.html';
}

// ============================================================
// Organizations Management
// ============================================================

// Current viewing organization
let viewingOrgId = null;

// Load organizations for the organizations tab
async function loadOrganizationsForTab() {
    const organizationsList = document.getElementById('organizationsList');
    if (!organizationsList) return;

    try {
        const response = await authFetch('/auth/organizations');
        if (!response.ok) {
            if (response.status === 401) {
                organizationsList.innerHTML = '<p class="text-muted">Войдите чтобы управлять организациями</p>';
                return;
            }
            throw new Error('Failed to load organizations');
        }

        const organizations = await response.json();

        if (organizations.length === 0) {
            organizationsList.innerHTML = `
                <div class="text-center" style="padding: 40px;">
                    <p class="text-muted">У вас пока нет организаций</p>
                    <button class="btn btn-primary" onclick="showCreateOrgForm()">Создать организацию</button>
                </div>
            `;
            return;
        }

        let html = '<div class="organizations-grid">';
        organizations.forEach(org => {
            html += `
                <div class="card org-card">
                    <div class="org-header">
                        <h3>${escapeHtml(org.name)}</h3>
                        <span class="badge">${escapeHtml(org.role)}</span>
                    </div>
                    <p class="text-muted">Slug: ${escapeHtml(org.slug)}</p>
                    <div class="org-actions">
                        <button class="btn btn-small btn-view-org" data-org-id="${org.id}" data-org-name="${org.name.replace(/"/g, '&quot;')}">Управление</button>
                        <button class="btn btn-small btn-secondary btn-select-org" data-org-id="${org.id}">Выбрать</button>
                    </div>
                </div>
            `;
        });
        html += '</div>';
        organizationsList.innerHTML = html;

        // Attach event listeners
        document.querySelectorAll('.btn-view-org').forEach(btn => {
            btn.addEventListener('click', () => {
                viewOrganization(btn.dataset.orgId, btn.dataset.orgName);
            });
        });
        document.querySelectorAll('.btn-select-org').forEach(btn => {
            btn.addEventListener('click', () => {
                selectOrganization(btn.dataset.orgId);
            });
        });

    } catch (error) {
        console.error('Error loading organizations:', error);
        organizationsList.innerHTML = '<p class="error">Ошибка загрузки организаций</p>';
    }
}

// Create organization
async function createOrganization(name) {
    try {
        const response = await authFetch('/organizations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create organization');
        }

        const org = await response.json();
        closeCreateOrgModal();
        loadOrganizationsForTab();
        return org;
    } catch (error) {
        console.error('Error creating organization:', error);
        const errorDiv = document.getElementById('orgNameError');
        if (errorDiv) {
            errorDiv.textContent = error.message;
            errorDiv.style.display = 'block';
        }
        throw error;
    }
}

// Show create organization modal
function showCreateOrgForm() {
    const modal = document.getElementById('createOrgModal');
    const form = document.getElementById('createOrgForm');
    const orgNameInput = document.getElementById('orgName');
    const errorDiv = document.getElementById('orgNameError');

    // Reset form
    form.reset();
    if (errorDiv) {
        errorDiv.textContent = '';
        errorDiv.style.display = 'none';
    }

    // Show modal
    modal.classList.add('active');
    orgNameInput.focus();
}

// Close create organization modal
function closeCreateOrgModal() {
    const modal = document.getElementById('createOrgModal');
    modal.classList.remove('active');
}

// Handle create organization form submit
document.addEventListener('DOMContentLoaded', () => {
    const createOrgForm = document.getElementById('createOrgForm');
    if (createOrgForm) {
        createOrgForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const name = document.getElementById('orgName').value.trim();
            if (name) {
                await createOrganization(name);
            }
        });
    }
});

// Select organization (set as current)
async function selectOrganization(orgId) {
    try {
        const response = await authFetch(`/auth/select-organization/${orgId}`, {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error('Failed to select organization');
        }

        const data = await response.json();
        if (data.access_token) {
            localStorage.setItem('access_token', data.access_token);
        }

        alert('Организация выбрана! Теперь работаете в её контексте.');
        location.reload();
    } catch (error) {
        console.error('Error selecting organization:', error);
        alert('Ошибка при выборе организации');
    }
}

// View organization details (show members)
async function viewOrganization(orgId, orgName) {
    viewingOrgId = orgId;

    // Show detail view
    document.getElementById('organizationListView').style.display = 'none';
    document.getElementById('organizationDetailView').style.display = 'block';
    document.getElementById('orgDetailName').textContent = orgName;

    // Load members
    await loadOrganizationMembers(orgId);
}

// Load organization members
async function loadOrganizationMembers(orgId) {
    const membersList = document.getElementById('membersList');
    if (!membersList) return;

    try {
        const response = await authFetch(`/organizations/${orgId}/members`);

        if (!response.ok) {
            if (response.status === 401) {
                membersList.innerHTML = '<p class="text-muted">Необходимо авторизоваться</p>';
                return;
            }
            if (response.status === 403) {
                membersList.innerHTML = '<p class="text-muted">У вас нет прав для просмотра сотрудников</p>';
                return;
            }
            throw new Error('Failed to load members');
        }

        const members = await response.json();

        if (members.length === 0) {
            membersList.innerHTML = '<p class="text-muted">В организации пока нет сотрудников</p>';
            return;
        }

        const roleLabels = {
            'owner': 'Владелец',
            'admin': 'Администратор',
            'member': 'Участник',
            'viewer': 'Зритель'
        };

        let html = '<div class="members-grid">';
        members.forEach(member => {
            const displayIdentifier = member.username || member.email || 'Нет логина';
            const canManage = member.role !== 'owner' || displayIdentifier === (currentUser?.username || currentUser?.email);
            html += `
                <div class="card member-card">
                    <div class="member-info">
                        <h4>${escapeHtml(member.full_name)}</h4>
                        <p class="text-muted">${escapeHtml(displayIdentifier)}</p>
                        <span class="badge">${roleLabels[member.role] || member.role}</span>
                    </div>
                    ${canManage ? `
                    <div class="member-actions">
                        <select class="role-select" onchange="changeMemberRole('${orgId}', '${member.id}', this.value)">
                            <option value="owner" ${member.role === 'owner' ? 'selected' : ''}>Владелец</option>
                            <option value="admin" ${member.role === 'admin' ? 'selected' : ''}>Администратор</option>
                            <option value="member" ${member.role === 'member' ? 'selected' : ''}>Участник</option>
                            <option value="viewer" ${member.role === 'viewer' ? 'selected' : ''}>Зритель</option>
                        </select>
                        ${member.email !== (currentUser?.email) ? `
                        <button class="btn btn-small btn-secondary" onclick="removeMember('${orgId}', '${member.id}', '${escapeHtml(member.full_name)}')">Удалить</button>
                        ` : ''}
                    </div>
                    ` : ''}
                </div>
            `;
        });
        html += '</div>';
        membersList.innerHTML = html;

    } catch (error) {
        console.error('Error loading members:', error);
        membersList.innerHTML = '<p class="error">Ошибка загрузки сотрудников</p>';
    }
}

// Add member to organization
async function addMember() {
    if (!viewingOrgId) return;

    const modal = document.getElementById('addMemberModal');
    const form = document.getElementById('addMemberForm');

    // Reset form and errors
    form.reset();
    document.querySelectorAll('#addMemberModal .error-message').forEach(el => {
        el.textContent = '';
        el.style.display = 'none';
    });

    // Show modal
    modal.classList.add('active');
    document.getElementById('memberUsername').focus();
}

// Close add member modal
function closeAddMemberModal() {
    const modal = document.getElementById('addMemberModal');
    modal.classList.remove('active');
}

// Submit add member form
async function submitAddMemberForm(e) {
    e.preventDefault();

    if (!viewingOrgId) return;

    const username = document.getElementById('memberUsername').value.trim();
    const password = document.getElementById('memberPassword').value.trim();
    const fullName = document.getElementById('memberFullName').value.trim();
    const role = document.getElementById('memberRole').value;

    // Validation
    let hasError = false;
    document.querySelectorAll('#addMemberModal .error-message').forEach(el => {
        el.textContent = '';
        el.style.display = 'none';
    });

    if (!username) {
        showError('memberUsername', 'Введите логин');
        hasError = true;
    } else if (username.length < 2) {
        showError('memberUsername', 'Логин должен содержать минимум 2 символа');
        hasError = true;
    }

    if (!password) {
        showError('memberPassword', 'Введите пароль');
        hasError = true;
    } else if (password.length < 8) {
        showError('memberPassword', 'Пароль должен содержать минимум 8 символов');
        hasError = true;
    }

    if (!fullName) {
        showError('memberFullName', 'Введите полное имя');
        hasError = true;
    }

    if (hasError) return;

    try {
        // Prepare request body - only include fields that are set
        const requestBody = {
            username: username,
            password: password,
            full_name: fullName,
            role: role
        };

        console.log('Sending request body:', JSON.stringify(requestBody, null, 2));

        const response = await authFetch(`/organizations/${viewingOrgId}/add-member`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });

        if (!response.ok) {
            const error = await response.json();
            console.error('Server error response:', JSON.stringify(error, null, 2));

            // Handle validation errors
            if (response.status === 422 || response.status === 400) {
                // Parse error detail
                let errorMessage = 'Ошибка валидации';

                if (typeof error.detail === 'string') {
                    errorMessage = error.detail;
                } else if (Array.isArray(error.detail)) {
                    // Pydantic validation errors
                    console.log('Validation errors array:', JSON.stringify(error.detail, null, 2));
                    errorMessage = error.detail.map((err, index) => {
                        const errStr = JSON.stringify(err, null, 2);
                        console.log(`Error ${index}:`, errStr);
                        if (err.msg) {
                            // Try to get field name from loc
                            if (err.loc && err.loc.length > 0) {
                                const field = err.loc[err.loc.length - 1];
                                return `${field}: ${err.msg}`;
                            }
                            return err.msg;
                        }
                        return JSON.stringify(err);
                    }).join('\n');
                } else if (error.detail) {
                    errorMessage = JSON.stringify(error.detail, null, 2);
                }

                // Also check for error object format
                if (error.error) {
                    errorMessage = error.error + ': ' + (error.detail || '');
                }

                alert('Ошибка валидации:\n' + errorMessage);
                showError('memberUsername', errorMessage);
                return;
            }

            throw new Error(error.detail || 'Failed to add member');
        }

        // Success - close modal and reload members
        closeAddMemberModal();
        await loadOrganizationMembers(viewingOrgId);
    } catch (error) {
        console.error('Error adding member:', error);
        showError('memberUsername', error.message || 'Произошла ошибка');
    }
}

function showError(fieldId, message) {
    const errorDiv = document.getElementById(fieldId + 'Error');
    if (errorDiv) {
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
    }
}

// Change member role
async function changeMemberRole(orgId, userId, newRole) {
    try {
        const response = await authFetch(`/organizations/${orgId}/members/${userId}/role`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role: newRole })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to change role');
        }

        alert('Роль изменена!');
        await loadOrganizationMembers(orgId);
    } catch (error) {
        console.error('Error changing role:', error);
        alert('Ошибка: ' + error.message);
        // Reload to revert UI
        await loadOrganizationMembers(orgId);
    }
}

// Remove member from organization
async function removeMember(orgId, userId, memberName) {
    if (!confirm(`Удалить сотрудника "${memberName}" из организации?`)) {
        return;
    }

    try {
        const response = await authFetch(`/organizations/${orgId}/members/${userId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to remove member');
        }

        alert('Сотрудник удален!');
        await loadOrganizationMembers(orgId);
    } catch (error) {
        console.error('Error removing member:', error);
        alert('Ошибка: ' + error.message);
    }
}

// Back to organization list
function backToOrganizations() {
    viewingOrgId = null;
    document.getElementById('organizationDetailView').style.display = 'none';
    document.getElementById('organizationListView').style.display = 'block';
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Init
document.addEventListener('DOMContentLoaded', async () => {
    // Check if auth is enabled on the server
    try {
        const healthResponse = await fetch('/health');
        if (healthResponse.ok) {
            const health = await healthResponse.json();
            // If auth is required but not logged in, redirect
            const token = localStorage.getItem('access_token');
            if (!token && health.database === 'available') {
                // Check if this is the auth flow
                if (!window.location.pathname.includes('auth.html') &&
                    !window.location.pathname.includes('select-organization.html')) {
                    // For now, allow access - auth is optional
                    // window.location.href = '/static/auth.html';
                }
            }
        }
    } catch (e) {
        // Health check failed - continue normally
    }

    // Add member form handler
    const addMemberForm = document.getElementById('addMemberForm');
    if (addMemberForm) {
        addMemberForm.addEventListener('submit', submitAddMemberForm);
    }

    // Close modals on backdrop click
    document.querySelectorAll('#addMemberModal, #createOrgModal').forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.classList.remove('active');
            }
        });
    });

    await loadChartJS();
    window.app = new VoiceCheckApp();
});
