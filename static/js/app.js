/**
 * VOICEcheck - Main Application
 * Handles navigation, file upload, dialogs list, evaluation display, and dashboard
 * Depends on: api.js, utils.js, organizations.js
 */

// Check authentication on page load
function checkAuth() {
    const token = localStorage.getItem('access_token');
    if (!token && window.location.pathname !== '/static/auth.html' && !window.location.pathname.includes('/auth-org/') && !window.location.pathname.includes('/login/')) {
        window.location.href = '/static/auth.html';
        return false;
    }
    return true;
}

if (!checkAuth()) {
    throw new Error('Authentication required');
}

// Current user and organization
let currentUser = null;
let currentOrg = null;

try {
    currentUser = JSON.parse(localStorage.getItem('user') || 'null');
    currentOrg = JSON.parse(localStorage.getItem('current_org') || 'null');
} catch (e) {}

// Auth-enabled fetch wrapper (uses token from localStorage)
function authFetch(url, options = {}) {
    const token = localStorage.getItem('access_token');
    if (token) {
        options.headers = options.headers || {};
        options.headers['Authorization'] = `Bearer ${token}`;
    }
    return fetch(url, options).then(response => {
        if (response.status === 401 && !url.includes('/auth/')) {
            localStorage.clear();
            window.location.href = '/static/auth.html';
        }
        return response;
    });
}

class VoiceCheckApp {
    constructor() {
        this.currentTab = 'upload';
        this.fileId = null;
        this.taskId = null;
        this.selectedFile = null;
        this.statusCheckInterval = null;

        this.currentPage = 1;
        this.dialogsPerPage = 20;
        this.dialogs = [];
        this.totalDialogs = 0;
        this.filters = { status: '', date_from: '', date_to: '', search: '', seller_name: '', min_score: '' };

        this.currentDialogId = null;
        this.evaluationData = null;
        this.speakingTimeChart = null;
        this.scoringDynamicsChart = null;
        this.audioElement = null;
        this._searchTimer = null;

        this.initElements();
        this.attachEventListeners();
        this.addAuthUI();
        this.loadSellers();
    }

    addAuthUI() {
        const authInfoEl = document.getElementById('authInfo');
        const authLoginEl = document.getElementById('authLoginBtn');

        if (currentUser) {
            // Show name (full_name preferred, else email/username)
            const displayName = currentUser.full_name || currentUser.email || currentUser.username || 'Пользователь';
            const nameEl = document.getElementById('authUserName');
            if (nameEl) nameEl.textContent = displayName;

            // Show org name
            const orgName = document.getElementById('orgSwitcherName');
            if (orgName) orgName.textContent = currentOrg ? currentOrg.name : 'Без организации';

            if (authInfoEl) authInfoEl.style.display = 'flex';

            // Logout
            const logoutBtn = document.getElementById('logoutBtn');
            if (logoutBtn) logoutBtn.addEventListener('click', () => logout());

            // Profile settings
            const profileBtn = document.getElementById('profileSettingsBtn');
            if (profileBtn) profileBtn.addEventListener('click', () => { this.closeAllDropdowns(); this.openProfileModal(); });

            // Orgs menu button (admin/owner only)
            const orgsBtn = document.getElementById('orgsMenuBtn');
            const isAdmin = currentOrg && (currentOrg.role === 'owner' || currentOrg.role === 'admin');
            if (orgsBtn && isAdmin) {
                orgsBtn.style.display = '';
                orgsBtn.addEventListener('click', () => { this.closeAllDropdowns(); this.openOrgsModal(); });
            }

            // User menu toggle
            const userMenu = document.getElementById('userMenu');
            if (userMenu) {
                userMenu.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const dropdown = document.getElementById('userMenuDropdown');
                    const orgDropdown = document.getElementById('orgSwitcherDropdown');
                    orgDropdown.style.display = 'none';
                    dropdown.style.display = dropdown.style.display === 'block' ? 'none' : 'block';
                });
            }

            // Org switcher toggle
            const orgSwitcher = document.getElementById('orgSwitcher');
            if (orgSwitcher) {
                orgSwitcher.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const dropdown = document.getElementById('orgSwitcherDropdown');
                    const userDropdown = document.getElementById('userMenuDropdown');
                    userDropdown.style.display = 'none';
                    const isOpen = dropdown.style.display === 'block';
                    if (!isOpen) this.loadOrgSwitcherList();
                    dropdown.style.display = isOpen ? 'none' : 'block';
                });
            }

            // Close dropdowns on outside click
            document.addEventListener('click', () => this.closeAllDropdowns());

            // Auto-select org on load if missing
            this.ensureActiveOrg();
        } else {
            if (authInfoEl) authInfoEl.style.display = 'none';
            if (authLoginEl) authLoginEl.style.display = 'block';
        }
    }

    closeAllDropdowns() {
        const d1 = document.getElementById('userMenuDropdown');
        const d2 = document.getElementById('orgSwitcherDropdown');
        if (d1) d1.style.display = 'none';
        if (d2) d2.style.display = 'none';
    }

    // Auto-select first org if user has no active org in JWT
    async ensureActiveOrg() {
        if (currentOrg) return; // already have one
        try {
            const resp = await authFetch('/auth/organizations');
            if (!resp.ok) return;
            const orgs = await resp.json();
            if (orgs.length === 0) return;
            // Prefer owned org, else first
            const owned = orgs.find(o => o.role === 'owner') || orgs[0];
            await this.switchOrg(owned.id, owned);
        } catch (e) { console.error('ensureActiveOrg:', e); }
    }

    async loadOrgSwitcherList() {
        const dropdown = document.getElementById('orgSwitcherDropdown');
        dropdown.innerHTML = '<div style="padding:8px 12px;color:var(--text-2);font-size:0.8rem;">Загрузка...</div>';
        try {
            const resp = await authFetch('/auth/organizations');
            if (!resp.ok) return;
            const orgs = await resp.json();
            if (orgs.length <= 1) {
                dropdown.innerHTML = '<div style="padding:8px 12px;color:var(--text-2);font-size:0.8rem;">Только одна организация</div>';
                return;
            }
            dropdown.innerHTML = orgs.map(o => {
                const active = currentOrg && currentOrg.id === o.id;
                return `<div class="org-switcher-item${active ? ' active' : ''}" onclick="app.switchOrg('${o.id}', ${JSON.stringify(o).replace(/"/g, '&quot;')})">
                    ${active ? '✓ ' : ''}${o.name}
                    <span style="font-size:0.7rem;color:var(--text-2);margin-left:4px;">${o.role}</span>
                </div>`;
            }).join('');
        } catch (e) {
            dropdown.innerHTML = '<div style="padding:8px 12px;color:var(--red);font-size:0.8rem;">Ошибка загрузки</div>';
        }
    }

    async switchOrg(orgId, orgData) {
        try {
            const resp = await authFetch(`/auth/select-organization/${orgId}`, { method: 'POST' });
            if (!resp.ok) throw new Error('Failed to switch org');
            const data = await resp.json();
            // Store new tokens
            localStorage.setItem('access_token', data.access_token);
            localStorage.setItem('refresh_token', data.refresh_token);
            // Update current org
            const newOrg = orgData || { id: orgId };
            localStorage.setItem('current_org', JSON.stringify(newOrg));
            currentOrg = newOrg;
            // Update display
            const orgName = document.getElementById('orgSwitcherName');
            if (orgName) orgName.textContent = newOrg.name || 'Организация';
            this.closeAllDropdowns();
            // Show admin orgs button if owner/admin
            const orgsBtn = document.getElementById('orgsMenuBtn');
            if (orgsBtn) orgsBtn.style.display = (newOrg.role === 'owner' || newOrg.role === 'admin') ? '' : 'none';
            // Reload data
            this.loadDialogs();
            if (typeof companiesModule !== 'undefined') companiesModule.loadCompanies();
        } catch (e) { console.error('switchOrg error:', e); }
    }

    // Profile modal
    openProfileModal() {
        const modal = document.getElementById('profileModal');
        if (!modal) return;
        const nameInput = document.getElementById('profileNameInput');
        if (nameInput) nameInput.value = currentUser ? (currentUser.full_name || '') : '';
        document.getElementById('profileCurrentPassword').value = '';
        document.getElementById('profileNewPassword').value = '';
        document.getElementById('profileError').style.display = 'none';
        document.getElementById('profileSuccess').style.display = 'none';
        modal.classList.add('active');
    }

    closeProfileModal() {
        const modal = document.getElementById('profileModal');
        if (modal) modal.classList.remove('active');
    }

    async saveProfile() {
        const fullName = document.getElementById('profileNameInput').value.trim();
        const currentPwd = document.getElementById('profileCurrentPassword').value;
        const newPwd = document.getElementById('profileNewPassword').value;
        const errEl = document.getElementById('profileError');
        const okEl = document.getElementById('profileSuccess');
        errEl.style.display = 'none';
        okEl.style.display = 'none';

        const payload = {};
        if (fullName) payload.full_name = fullName;
        if (newPwd) { payload.current_password = currentPwd; payload.new_password = newPwd; }
        if (Object.keys(payload).length === 0) { this.closeProfileModal(); return; }

        try {
            const resp = await authFetch('/auth/profile', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await resp.json();
            if (!resp.ok) { errEl.textContent = data.detail || 'Ошибка сохранения'; errEl.style.display = 'block'; return; }
            // Update localStorage
            if (currentUser) {
                currentUser.full_name = data.full_name;
                localStorage.setItem('user', JSON.stringify(currentUser));
            }
            const nameEl = document.getElementById('authUserName');
            if (nameEl) nameEl.textContent = data.full_name || data.email || 'Пользователь';
            okEl.style.display = 'block';
            setTimeout(() => this.closeProfileModal(), 1200);
        } catch (e) { errEl.textContent = 'Ошибка подключения'; errEl.style.display = 'block'; }
    }

    // Open organizations panel by switching to the organizations tab
    openOrgsModal() {
        this.switchTab('organizations');
    }

    initElements() {
        this.tabBtns = document.querySelectorAll('.tab-btn');
        this.tabPanes = document.querySelectorAll('.tab-pane');
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
        this.statusArea = document.getElementById('statusArea');
        this.statusMessage = document.getElementById('statusMessage');
        this.progressFill = document.getElementById('progressFill');
        this.resultArea = document.getElementById('resultArea');
        this.resultText = document.getElementById('resultText');
        this.resultMeta = document.getElementById('resultMeta');
        this.copyBtn = document.getElementById('copyBtn');
        this.newTranscriptionBtn = document.getElementById('newTranscriptionBtn');
        this.errorMessage = document.getElementById('errorMessage');
        this.dialogsList = document.getElementById('dialogsList');
        this.pagination = document.getElementById('pagination');
        this.statusFilter = document.getElementById('statusFilter');
        this.dateFromFilter = document.getElementById('dateFromFilter');
        this.dateToFilter = document.getElementById('dateToFilter');
        this.searchFilter = document.getElementById('searchFilter');
        this.sellerFilter = document.getElementById('sellerFilter');
        this.scoreFilter = document.getElementById('scoreFilter');
        this.statsGrid = document.getElementById('statsGrid');
        this.dashDateFrom = document.getElementById('dashDateFrom');
        this.dashDateTo = document.getElementById('dashDateTo');
        this.dashSellerFilter = document.getElementById('dashSellerFilter');
        this.dashRefreshBtn = document.getElementById('dashRefreshBtn');
        this.objectionsListContainer = document.getElementById('objectionsListContainer');
        this.modal = document.getElementById('evaluationModal');
        this.modalClose = document.querySelector('.close-btn');
        this.evaluationContent = document.getElementById('evaluationContent');
    }

    attachEventListeners() {
        this.tabBtns.forEach(btn => {
            btn.addEventListener('click', () => this.switchTab(btn.dataset.tab));
        });
        this.attachUploadEventListeners();

        this.statusFilter.addEventListener('change', () => { this.filters.status = this.statusFilter.value; this.currentPage = 1; this.loadDialogs(); });
        this.dateFromFilter.addEventListener('change', () => { this.filters.date_from = this.dateFromFilter.value; this.currentPage = 1; this.loadDialogs(); });
        this.dateToFilter.addEventListener('change', () => { this.filters.date_to = this.dateToFilter.value; this.currentPage = 1; this.loadDialogs(); });
        this.searchFilter.addEventListener('input', () => {
            clearTimeout(this._searchTimer);
            this._searchTimer = setTimeout(() => { this.filters.search = this.searchFilter.value.trim(); this.currentPage = 1; this.loadDialogs(); }, 400);
        });
        this.sellerFilter.addEventListener('change', () => { this.filters.seller_name = this.sellerFilter.value; this.currentPage = 1; this.loadDialogs(); });
        this.scoreFilter.addEventListener('change', () => { this.filters.min_score = this.scoreFilter.value; this.currentPage = 1; this.loadDialogs(); });

        this.dashRefreshBtn.addEventListener('click', () => this.loadDashboard());

        const createOrgBtn = document.getElementById('createOrgBtn');
        if (createOrgBtn) createOrgBtn.addEventListener('click', () => showCreateOrgForm());
        const backToOrgsBtn = document.getElementById('backToOrgsBtn');
        if (backToOrgsBtn) backToOrgsBtn.addEventListener('click', () => backToOrganizations());
        const addMemberBtn = document.getElementById('addMemberBtn');
        if (addMemberBtn) addMemberBtn.addEventListener('click', () => showAddMemberForm());

        this.modalClose.addEventListener('click', () => this.closeModal());
        this.modal.addEventListener('click', (e) => { if (e.target === this.modal) this.closeModal(); });
    }

    attachUploadEventListeners() {
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            document.body.addEventListener(eventName, (e) => { e.preventDefault(); e.stopPropagation(); }, false);
        });
        this.uploadArea.addEventListener('click', () => this.fileInput.click());
        this.fileInput.addEventListener('change', (e) => this.handleFileSelect(e.target.files[0]));
        this.uploadArea.addEventListener('dragover', (e) => { e.preventDefault(); this.uploadArea.classList.add('dragover'); });
        this.uploadArea.addEventListener('dragleave', () => this.uploadArea.classList.remove('dragover'));
        this.uploadArea.addEventListener('drop', (e) => {
            e.preventDefault(); this.uploadArea.classList.remove('dragover');
            if (e.dataTransfer.files[0]) this.handleFileSelect(e.dataTransfer.files[0]);
        });
        this.changeFileBtn.addEventListener('click', () => this.fileInput.click());
        this.uploadBtn.addEventListener('click', () => this.uploadFile());
        this.copyBtn.addEventListener('click', () => this.copyResult());
        this.newTranscriptionBtn.addEventListener('click', () => this.resetUpload());
        this.sellerNameInput.addEventListener('change', () => {
            if (this.sellerNameInput.value === '__new__') {
                const name = prompt('Введите имя нового продавца:');
                if (name && name.trim()) {
                    const opt = document.createElement('option');
                    opt.value = name.trim(); opt.textContent = name.trim();
                    const newOpt = this.sellerNameInput.querySelector('option[value="__new__"]');
                    this.sellerNameInput.insertBefore(opt, newOpt);
                    this.sellerNameInput.value = name.trim();
                } else { this.sellerNameInput.value = ''; }
            }
        });
    }

    switchTab(tab) {
        this.currentTab = tab;
        this.tabBtns.forEach(btn => btn.classList.toggle('active', btn.dataset.tab === tab));
        this.tabPanes.forEach(pane => pane.classList.toggle('active', pane.id === `${tab}-tab`));
        if (tab === 'dialogs') this.loadDialogs();
        if (tab === 'companies') companiesModule.loadCompanies();
        if (tab === 'organizations') loadOrganizationsForTab();
        if (tab === 'dashboard') this.loadDashboard();
    }

    // Upload
    handleFileSelect(file) {
        if (!file) return;
        const allowedExtensions = ['.mp3', '.wav', '.m4a', '.ogg', '.flac', '.mp4', '.webm'];
        const ext = '.' + file.name.split('.').pop().toLowerCase();
        if (!file.type.startsWith('audio/') && !file.type.startsWith('video/') && !allowedExtensions.includes(ext)) {
            this.showError('Пожалуйста, выберите аудиофайл (MP3, WAV, M4A, OGG, FLAC)'); return;
        }
        if (file.size > 50 * 1024 * 1024) { this.showError('Файл слишком большой. Максимальный размер: 50MB'); return; }
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
        this.hideError(); this.uploadBtn.disabled = true; this.uploadBtn.textContent = 'Загрузка...';
        const formData = new FormData();
        formData.append('file', this.selectedFile);
        const sellerName = this.sellerNameInput.value;
        if (sellerName && sellerName !== '__new__') formData.append('seller_name', sellerName);
        try {
            const response = await authFetch('/upload', { method: 'POST', body: formData });
            if (!response.ok) { const error = await response.json(); throw new Error(error.detail || 'Ошибка загрузки файла'); }
            const data = await response.json();
            this.fileId = data.file_id;
            await this.startTranscription();
        } catch (error) {
            this.showError(error.message); this.uploadBtn.disabled = false; this.uploadBtn.textContent = 'Загрузить файл';
        }
    }

    async startTranscription() {
        this.statusArea.classList.add('active');
        this.statusMessage.textContent = 'Подготовка к транскрибации...';
        const language = this.languageSelect.value;
        try {
            const response = await authFetch(`/transcribe/${this.fileId}`, {
                method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `language=${language}&with_speakers=true`
            });
            if (!response.ok) { const error = await response.json(); throw new Error(error.detail || 'Ошибка начала транскрибации'); }
            const data = await response.json();
            this.taskId = data.task_id;
            this.startStatusPolling();
        } catch (error) { this.showError(error.message); this.statusArea.classList.remove('active'); }
    }

    startStatusPolling() { this.checkStatus(); this.statusCheckInterval = setInterval(() => this.checkStatus(), 1000); }

    async checkStatus() {
        if (!this.taskId) return;
        try {
            const response = await authFetch(`/status/${this.taskId}`);
            if (!response.ok) throw new Error('Ошибка получения статуса');
            const data = await response.json();
            if (this.progressFill) this.progressFill.style.width = `${data.progress}%`;
            if (data.status === 'processing') { this.statusMessage.textContent = data.message || 'Транскрибация...'; }
            else if (data.status === 'completed') { this.stopPolling(); this.showResult(data); }
            else if (data.status === 'failed') { this.stopPolling(); this.showError(data.message || 'Ошибка транскрибации'); this.statusArea.classList.remove('active'); }
        } catch (error) { console.error('Status check error:', error); }
    }

    stopPolling() { if (this.statusCheckInterval) { clearInterval(this.statusCheckInterval); this.statusCheckInterval = null; } }

    showResult(data) {
        this.statusArea.classList.remove('active');
        this.resultArea.classList.add('active');
        // Debug: fetch and log z.ai diarization response to DevTools console
        api.get('/dialogs/debug/zai-last')
            .then(dbg => console.log('%c[Z.AI DIARIZATION DEBUG]', 'color: #818cf8; font-weight: bold; font-size: 13px;', dbg))
            .catch(() => {});
        if (data.result) {
            const duration = this.formatDuration(data.result.duration);
            const language = data.result.language.toUpperCase();
            this.resultMeta.textContent = `Длительность: ${duration} | Язык: ${language}`;
            const segments = data.result.segments || [];
            if (segments.length > 0 && segments.some(s => s.speaker)) {
                const merged = [];
                for (const seg of segments) {
                    const speaker = seg.speaker || 'SPEAKER_00';
                    const last = merged[merged.length - 1];
                    if (last && last.speaker === speaker) { last.text += ' ' + seg.text; last.end = seg.end; }
                    else { merged.push({ speaker, text: seg.text, start: seg.start, end: seg.end }); }
                }
                this.resultText.innerHTML = merged.map(seg => {
                    const label = seg.speaker === 'SPEAKER_00' ? 'Продавец' : (seg.speaker === 'SPEAKER_01' ? 'Клиент' : seg.speaker);
                    const cls = seg.speaker === 'SPEAKER_00' ? 'result-speaker-sales' : 'result-speaker-customer';
                    const time = this.formatDuration(seg.start);
                    return `<div class="result-segment"><span class="result-seg-time">[${time}]</span> <span class="result-seg-speaker ${cls}">${label}:</span> ${seg.text}</div>`;
                }).join('');
            } else { this.resultText.textContent = data.result.text; }
        }
    }

    async copyResult() {
        try {
            await navigator.clipboard.writeText(this.resultText.textContent);
            this.copyBtn.textContent = 'Скопировано!';
            setTimeout(() => { this.copyBtn.textContent = 'Копировать'; }, 2000);
        } catch {
            const ta = document.createElement('textarea'); ta.value = this.resultText.textContent;
            document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
            this.copyBtn.textContent = 'Скопировано!';
            setTimeout(() => { this.copyBtn.textContent = 'Копировать'; }, 2000);
        }
    }

    resetUpload() {
        this.fileId = null; this.taskId = null; this.selectedFile = null; this.fileInput.value = '';
        this.uploadArea.style.display = 'block'; this.fileInfo.classList.remove('active');
        this.languageSelector.style.display = 'none'; this.sellerInput.style.display = 'none';
        this.sellerNameInput.value = ''; this.uploadBtn.disabled = true; this.uploadBtn.textContent = 'Загрузить файл';
        this.statusArea.classList.remove('active'); this.resultArea.classList.remove('active');
        this.progressFill.style.width = '0%'; this.hideError();
    }

    showError(message) { this.errorMessage.textContent = message; this.errorMessage.classList.add('active'); }
    hideError() { this.errorMessage.classList.remove('active'); }

    // Dialogs
    async loadDialogs() {
        try {
            const params = new URLSearchParams();
            params.append('page', this.currentPage); params.append('limit', this.dialogsPerPage);
            if (this.filters.status) params.append('status', this.filters.status);
            if (this.filters.date_from) params.append('date_from', this.filters.date_from);
            if (this.filters.date_to) params.append('date_to', this.filters.date_to);
            if (this.filters.search) params.append('search', this.filters.search);
            if (this.filters.seller_name) params.append('seller_name', this.filters.seller_name);
            if (this.filters.min_score) params.append('min_score', this.filters.min_score);
            const response = await authFetch(`/dialogs?${params}`);
            if (response.status === 404) { this.dialogs = []; this.totalDialogs = 0; this.renderDialogs(); return; }
            if (!response.ok) throw new Error('Ошибка загрузки диалогов');
            const data = await response.json();
            this.dialogs = data.items || []; this.totalDialogs = data.total || 0;
            this.renderDialogs(); this.renderPagination();
        } catch (error) { console.error('Error loading dialogs:', error); this.dialogs = []; this.totalDialogs = 0; this.renderDialogs(); }
    }

    renderDialogs() {
        if (this.dialogs.length === 0) {
            this.dialogsList.innerHTML = '<div class="no-dialogs"><p>Нет диалогов</p></div>'; return;
        }
        this.dialogsList.innerHTML = this.dialogs.map(dialog => {
            const scoreDisplay = dialog.overall_score != null ? dialog.overall_score.toFixed(1) : (dialog.has_analysis ? '...' : '-');
            const sellerTag = dialog.seller_name ? `<span class="dialog-seller">${dialog.seller_name}</span>` : '';
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
                </div>`;
        }).join('');
        this.dialogsList.querySelectorAll('.dialog-item').forEach(item => {
            item.addEventListener('click', () => this.openEvaluation(item.dataset.dialogId));
        });
    }

    renderPagination() {
        const totalPages = Math.ceil(this.totalDialogs / this.dialogsPerPage);
        if (totalPages <= 1) { this.pagination.innerHTML = ''; return; }
        let html = `<button class="page-btn" ${this.currentPage === 1 ? 'disabled' : ''} onclick="app.goToPage(${this.currentPage - 1})">&#8592;</button>`;
        const start = Math.max(1, this.currentPage - 2); const end = Math.min(totalPages, this.currentPage + 2);
        if (start > 1) { html += `<button class="page-btn" onclick="app.goToPage(1)">1</button>`; if (start > 2) html += `<span class="page-dots">...</span>`; }
        for (let i = start; i <= end; i++) { html += `<button class="page-btn ${i === this.currentPage ? 'active' : ''}" onclick="app.goToPage(${i})">${i}</button>`; }
        if (end < totalPages) { if (end < totalPages - 1) html += `<span class="page-dots">...</span>`; html += `<button class="page-btn" onclick="app.goToPage(${totalPages})">${totalPages}</button>`; }
        html += `<button class="page-btn" ${this.currentPage === totalPages ? 'disabled' : ''} onclick="app.goToPage(${this.currentPage + 1})">&#8594;</button>`;
        this.pagination.innerHTML = html;
    }

    goToPage(page) { this.currentPage = page; this.loadDialogs(); }

    getStatusText(status) {
        const map = { 'completed': 'В работе', 'dealed': 'Сделка состоялась', 'in_progress': 'В работе', 'rejected': 'Отказ', 'pending': 'Ожидание', 'processing': 'Обработка', 'failed': 'Ошибка' };
        return map[status] || status;
    }

    // Evaluation modal
    async openEvaluation(dialogId) {
        this.currentDialogId = dialogId; this.modal.classList.add('active');
        this.evaluationContent.innerHTML = '<p style="text-align:center;color:var(--text-muted)">Загрузка...</p>';
        try {
            const response = await authFetch(`/dialogs/${dialogId}`);
            if (!response.ok) throw new Error('Ошибка загрузки диалога');
            this.evaluationData = await response.json(); this.renderEvaluation();
        } catch (error) { console.error('Error loading evaluation:', error); this.evaluationContent.innerHTML = '<p style="color:var(--danger-color)">Ошибка загрузки данных</p>'; }
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
                <div class="evaluation-meta">${new Date(d.created_at).toLocaleDateString('ru-RU')} | ${this.formatDuration(d.duration)}${d.seller_name ? ' | ' + d.seller_name : ''}</div>
            </div>
            <div class="company-link-section">
                <div class="company-link-row">
                    <label class="company-link-label">Компания:</label>
                    <div class="company-autocomplete" id="companyAutocomplete">
                        <input type="text" id="dialogCompanyInput" class="form-input" placeholder="Выберите компанию..." autocomplete="off">
                        <input type="hidden" id="dialogCompanyId">
                        <div class="company-ac-dropdown" id="companyAcDropdown"></div>
                    </div>
                    <button class="btn btn-small" id="saveCompanyLinkBtn">Сохранить</button>
                    <button class="btn btn-small btn-secondary" id="clearCompanyLinkBtn" title="Отвязать" style="padding:6px 10px;">✕</button>
                </div>
                <div id="companySuggestionContainer" style="margin-top:6px;"></div>
            </div>
            ${summary ? `<div class="summary-section"><h3>Резюме встречи</h3><p class="summary-text">${summary}</p></div>` : ''}
            <div class="audio-player-section"><h3>Аудиозапись</h3><audio id="dialogAudio" controls preload="none"><source src="/dialogs/${d.id}/audio" type="audio/mpeg"></audio></div>
            <div class="scores-section"><h3>Оценка диалога</h3><div class="scores-grid">
                ${this.renderScoreItem('Приветствие и контакт', scores.greeting)}
                ${this.renderScoreItem('Выявление потребностей', scores.needs_discovery)}
                ${this.renderScoreItem('Презентация решения', scores.presentation)}
                ${this.renderScoreItem('Работа с возражениями', scores.objection_handling)}
                ${this.renderScoreItem('Закрытие / CTA', scores.closing)}
                ${this.renderScoreItem('Активное слушание', scores.active_listening)}
                ${this.renderScoreItem('Эмпатия и тон', scores.empathy)}
                <div class="score-item overall-score"><div class="score-label">Общий балл</div><div class="score-value">${overallScore.toFixed(1)}</div></div>
            </div></div>
            <div class="deal-status-section"><h3>Статус встречи</h3><div class="status-selector">
                ${this.renderStatusOption('dealed', 'Сделка состоялась', d.status === 'dealed')}
                ${this.renderStatusOption('in_progress', 'В работе', d.status === 'in_progress' || d.status === 'completed')}
                ${this.renderStatusOption('rejected', 'Отказ', d.status === 'rejected')}
            </div></div>
            <div class="speaking-time-section"><h3>Время говорения</h3>
                <div class="speaking-stats"><span class="speaking-stat sales">Продавец: ${(speakingTime.sales || 0).toFixed(0)}с (${salesPct}%)</span><span class="speaking-stat customer">Клиент: ${(speakingTime.customer || 0).toFixed(0)}с (${customerPct}%)</span></div>
                <div class="speaking-timeline-track"><div class="speaking-bar sales" style="width:${salesPct}%"></div><div class="speaking-bar customer" style="width:${customerPct}%"></div></div>
                <div class="chart-container"><canvas id="speakingTimeChart"></canvas></div>
                <p class="guideline-text">Оптимальное соотношение: 40% продавец / 60% клиент</p>
            </div>
            <div class="timeline-section"><h3>Таймлайн ключевых моментов</h3><div class="timeline"><div class="timeline-line"></div><div class="timeline-moments">${this.renderTimelineMoments()}</div></div></div>
            <div class="recommendations-section"><h3>Рекомендации</h3>${this.renderRecommendations()}</div>
            ${d.segments && d.segments.length > 0 ? `<div class="transcript-section"><div class="transcript-header"><h3>Транскрипция</h3><div class="transcript-toggle"><button class="transcript-toggle-btn" data-mode="detailed">Подробная</button><button class="transcript-toggle-btn active" data-mode="simple">Упрощённая</button></div></div><div class="transcript-container" id="transcriptContainer">${this.renderTranscript('simple')}</div></div>` : ''}
        `;

        this.evaluationContent.querySelectorAll('.status-option').forEach(opt => {
            opt.addEventListener('click', () => this.updateDialogStatus(opt.dataset.status));
        });

        this.evaluationContent.querySelectorAll('.transcript-toggle-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.evaluationContent.querySelectorAll('.transcript-toggle-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const container = document.getElementById('transcriptContainer');
                if (container) {
                    container.innerHTML = this.renderTranscript(btn.dataset.mode);
                    container.querySelectorAll('.transcript-segment').forEach(seg => {
                        seg.addEventListener('click', () => { if (this.audioElement) { this.audioElement.currentTime = parseFloat(seg.dataset.start); this.audioElement.play(); } });
                    });
                }
            });
        });

        setTimeout(() => {
            this.initSpeakingTimeChart();
            this.initAudioSync();
            this.initCompanyLinkSection(d);
        }, 100);
    }

    renderScoreItem(label, value) {
        const scoreClass = value != null ? this.getScoreClass(value) : '';
        return `<div class="score-item"><div class="score-label">${label}</div><div class="score-value ${scoreClass}">${value != null ? value.toFixed(1) : '-'}</div></div>`;
    }

    getScoreClass(value) { if (value >= 8) return 'score-high'; if (value >= 5) return 'score-mid'; return 'score-low'; }

    renderStatusOption(value, label, selected) {
        return `<div class="status-option ${selected ? 'selected' : ''}" data-status="${value}">${label}</div>`;
    }

    renderTimelineMoments() {
        const moments = this.evaluationData.analysis?.key_moments || [];
        if (moments.length === 0) return '<p class="no-data">Нет ключевых моментов</p>';
        return moments.map((moment, i) => {
            const side = i % 2 === 0 ? 'left' : 'right';
            return `<div class="timeline-moment ${side}"><div class="timeline-marker ${moment.type || ''}"></div><div class="timeline-content"><div class="timeline-time">${this.formatDuration(moment.time)}</div><div class="timeline-text">${moment.text}</div></div></div>`;
        }).join('');
    }

    renderRecommendations() {
        const recs = this.evaluationData.analysis?.recommendations || [];
        if (recs.length === 0) return '<p class="no-data">Нет рекомендаций</p>';
        return recs.map((rec, i) => `<div class="recommendation-item"><div class="recommendation-number">${i + 1}</div><div class="recommendation-body"><div class="recommendation-text">${rec.text}</div>${rec.time_range ? `<div class="recommendation-link" data-time="${rec.time_range[0]}">${this.formatDuration(rec.time_range[0])} - ${this.formatDuration(rec.time_range[1])}</div>` : ''}</div></div>`).join('');
    }

    renderTranscript(mode = 'detailed') {
        const segments = this.evaluationData.segments || [];
        if (mode === 'simple') {
            const merged = [];
            for (const seg of segments) {
                const speaker = seg.speaker || 'SPEAKER_00'; const last = merged[merged.length - 1];
                if (last && last.speaker === speaker) { last.text += ' ' + seg.text; last.end = seg.end; }
                else { merged.push({ speaker, text: seg.text, start: seg.start, end: seg.end }); }
            }
            return merged.map(seg => {
                const label = this.getSpeakerLabel(seg.speaker); const cls = seg.speaker === 'SPEAKER_00' ? 'speaker-sales' : 'speaker-customer';
                return `<div class="transcript-segment ${cls}" data-start="${seg.start}" data-end="${seg.end}"><span class="seg-time">[${this.formatDuration(seg.start)}]</span> <span class="seg-speaker ${cls}">${label}:</span> <span class="seg-text">${seg.text}</span></div>`;
            }).join('');
        }
        return segments.map((seg, i) => {
            const speakerLabel = this.getSpeakerLabel(seg.speaker); const speakerClass = seg.speaker === 'SPEAKER_00' ? 'speaker-sales' : 'speaker-customer';
            return `<div class="transcript-segment ${speakerClass}" data-index="${i}" data-start="${seg.start}" data-end="${seg.end}"><span class="seg-time">[${this.formatDuration(seg.start)}]</span> <span class="seg-speaker ${speakerClass}">${speakerLabel}:</span> <span class="seg-text">${seg.text}</span></div>`;
        }).join('');
    }

    getSpeakerLabel(speaker) { if (speaker === 'SPEAKER_00') return 'Продавец'; if (speaker === 'SPEAKER_01') return 'Клиент'; return speaker; }

    // Audio sync
    initAudioSync() {
        this.audioElement = document.getElementById('dialogAudio');
        if (!this.audioElement) return;
        const container = document.getElementById('transcriptContainer');
        if (!container) return;
        let userScrolling = false; let scrollTimer = null;
        const modalBody = this.modal.querySelector('.modal-body') || this.modal;
        modalBody.addEventListener('wheel', () => { userScrolling = true; clearTimeout(scrollTimer); scrollTimer = setTimeout(() => { userScrolling = false; }, 5000); }, { passive: true });
        modalBody.addEventListener('touchmove', () => { userScrolling = true; clearTimeout(scrollTimer); scrollTimer = setTimeout(() => { userScrolling = false; }, 5000); }, { passive: true });
        this.audioElement.addEventListener('timeupdate', () => {
            const currentTime = this.audioElement.currentTime;
            const segments = container.querySelectorAll('.transcript-segment');
            segments.forEach(seg => {
                const start = parseFloat(seg.dataset.start); const end = parseFloat(seg.dataset.end);
                const isActive = currentTime >= start && currentTime < end;
                seg.classList.toggle('active', isActive);
                if (isActive && !userScrolling && !seg.classList.contains('scrolled-to')) { seg.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); seg.classList.add('scrolled-to'); }
            });
            container.querySelectorAll('.transcript-segment:not(.active)').forEach(s => s.classList.remove('scrolled-to'));
        });
        container.querySelectorAll('.transcript-segment').forEach(seg => {
            seg.addEventListener('click', () => { if (this.audioElement) { this.audioElement.currentTime = parseFloat(seg.dataset.start); this.audioElement.play(); } });
        });
        this.evaluationContent.querySelectorAll('.recommendation-link[data-time]').forEach(link => {
            link.addEventListener('click', () => { if (this.audioElement) { this.audioElement.currentTime = parseFloat(link.dataset.time); this.audioElement.play(); } });
        });
    }

    // Company link section (CMP-021, CMP-022)
    initCompanyLinkSection(d) {
        const input = document.getElementById('dialogCompanyInput');
        const hiddenId = document.getElementById('dialogCompanyId');
        const dropdown = document.getElementById('companyAcDropdown');
        const saveBtn = document.getElementById('saveCompanyLinkBtn');
        const clearBtn = document.getElementById('clearCompanyLinkBtn');
        const suggestionContainer = document.getElementById('companySuggestionContainer');
        if (!input || !saveBtn || !dropdown) return;

        let allCompanies = [];
        let dropdownOpen = false;

        // Load all companies
        const loadAll = async () => {
            try {
                const resp = await authFetch('/companies/search?limit=200');
                if (resp.ok) allCompanies = await resp.json();
            } catch (e) {}
        };

        const renderDropdown = (items) => {
            if (!items.length) {
                dropdown.innerHTML = '<div class="company-ac-item no-result">Ничего не найдено</div>';
            } else {
                dropdown.innerHTML = items.map(c =>
                    `<div class="company-ac-item" data-id="${c.id}" data-name="${c.name}">${c.name}${c.inn ? ' <span class="text-muted">(ИНН ' + c.inn + ')</span>' : ''}</div>`
                ).join('');
            }
            dropdown.style.display = 'block';
            dropdownOpen = true;
            dropdown.querySelectorAll('.company-ac-item[data-id]').forEach(item => {
                item.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    input.value = item.dataset.name;
                    hiddenId.value = item.dataset.id;
                    dropdown.style.display = 'none';
                    dropdownOpen = false;
                });
            });
        };

        const filterAndShow = () => {
            const q = input.value.trim().toLowerCase();
            const filtered = q
                ? allCompanies.filter(c => c.name.toLowerCase().includes(q) || (c.inn && c.inn.includes(q)))
                : allCompanies;
            renderDropdown(filtered);
        };

        // Open dropdown on focus/click - show all companies
        input.addEventListener('focus', () => {
            if (!allCompanies.length) {
                loadAll().then(filterAndShow);
            } else {
                filterAndShow();
            }
        });

        input.addEventListener('click', () => {
            if (!dropdownOpen) filterAndShow();
        });

        input.addEventListener('input', () => {
            hiddenId.value = '';
            filterAndShow();
        });

        input.addEventListener('blur', () => {
            setTimeout(() => {
                dropdown.style.display = 'none';
                dropdownOpen = false;
            }, 200);
        });

        // Set initial value if company is linked
        if (d.company_id && d.company_name) {
            input.value = d.company_name;
            hiddenId.value = d.company_id;
        }

        // Save button
        saveBtn.addEventListener('click', async () => {
            const companyId = hiddenId.value || null;
            if (!companyId && input.value.trim()) {
                // Try to find exact match
                const match = allCompanies.find(c => c.name.toLowerCase() === input.value.trim().toLowerCase());
                if (match) hiddenId.value = match.id;
            }
            const finalId = hiddenId.value || null;
            saveBtn.disabled = true; saveBtn.textContent = '...';
            if (typeof companiesModule !== 'undefined') {
                const ok = await companiesModule.linkCompanyToDialog(d.id, finalId);
                saveBtn.textContent = ok ? '✓' : 'Ошибка';
                setTimeout(() => { saveBtn.disabled = false; saveBtn.textContent = 'Сохранить'; }, 2000);
            }
        });

        // Clear button
        if (clearBtn) {
            clearBtn.addEventListener('click', async () => {
                input.value = '';
                hiddenId.value = '';
                clearBtn.disabled = true;
                if (typeof companiesModule !== 'undefined') {
                    const ok = await companiesModule.linkCompanyToDialog(d.id, null);
                    if (ok && suggestionContainer) {
                        suggestionContainer.innerHTML = '<span class="text-muted" style="font-size:.85rem;">Компания отвязана</span>';
                    }
                }
                clearBtn.disabled = false;
            });
        }

        // Load companies list in background
        loadAll();

        // Auto-suggest if no company linked yet (CMP-022)
        if (!d.company_id && suggestionContainer && typeof companiesModule !== 'undefined') {
            companiesModule.suggestCompany(d.id, suggestionContainer);
        } else if (d.company_id && d.company_name && suggestionContainer) {
            suggestionContainer.innerHTML = `<span style="color:var(--green);font-size:.85rem;">Привязана: <b>${d.company_name}</b></span>`;
        }
    }

    // Speaking time chart
    initSpeakingTimeChart() {
        const ctx = document.getElementById('speakingTimeChart');
        if (!ctx) return;
        const st = this.evaluationData.analysis?.speaking_time || { sales: 0, customer: 0 };
        if (this.speakingTimeChart) this.speakingTimeChart.destroy();
        this.speakingTimeChart = new Chart(ctx, {
            type: 'pie',
            data: { labels: ['Продавец', 'Клиент'], datasets: [{ data: [st.sales || 0, st.customer || 0], backgroundColor: ['rgba(0, 212, 255, 0.8)', 'rgba(123, 44, 191, 0.8)'], borderColor: ['rgba(0, 212, 255, 1)', 'rgba(123, 44, 191, 1)'], borderWidth: 2 }] },
            options: { responsive: true, maintainAspectRatio: true, plugins: { legend: { position: 'bottom', labels: { color: '#f1f5f9', padding: 20, font: { size: 14 } } }, tooltip: { callbacks: { label: (ctx) => { const total = ctx.dataset.data.reduce((a, b) => a + b, 0); const pct = ((ctx.parsed / total) * 100).toFixed(1); return `${ctx.label}: ${ctx.parsed.toFixed(0)} сек (${pct}%)`; } } } } }
        });
    }

    // Status update
    updateDialogStatus(status) {
        this.evaluationContent.querySelectorAll('.status-option').forEach(opt => { opt.classList.toggle('selected', opt.dataset.status === status); });
        fetch(`/dialogs/${this.currentDialogId}/status`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) }).catch(err => console.error('Error updating status:', err));
    }

    closeModal() {
        this.modal.classList.remove('active');
        if (this.speakingTimeChart) { this.speakingTimeChart.destroy(); this.speakingTimeChart = null; }
        if (this.audioElement) { this.audioElement.pause(); this.audioElement = null; }
    }

    // Dashboard
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
        } catch (error) { console.error('Dashboard error:', error); this.statsGrid.innerHTML = '<p class="no-data">Не удалось загрузить статистику</p>'; }
    }

    renderDashboardStats(data) {
        const avgScore = data.avg_overall_score != null ? data.avg_overall_score.toFixed(1) : '-';
        const dealRate = data.deal_rate != null ? (data.deal_rate * 100).toFixed(1) + '%' : '-';
        this.statsGrid.innerHTML = `
            <div class="stat-card"><div class="stat-label">Всего диалогов</div><div class="stat-value">${data.total_dialogs || 0}</div></div>
            <div class="stat-card"><div class="stat-label">Средний балл</div><div class="stat-value">${avgScore}</div></div>
            <div class="stat-card"><div class="stat-label">Конверсия в сделку</div><div class="stat-value">${dealRate}</div></div>`;
        const cats = data.avg_category_scores;
        if (cats && Object.keys(cats).length > 0) {
            const catLabels = { greeting: 'Приветствие', needs_discovery: 'Потребности', presentation: 'Презентация', objection_handling: 'Возражения', closing: 'Закрытие', active_listening: 'Слушание', empathy: 'Эмпатия' };
            let catHtml = '<div class="stat-card wide"><div class="stat-label">Средние по категориям</div><div class="category-bars">';
            for (const [key, label] of Object.entries(catLabels)) {
                const val = cats[key] || 0; const pct = (val / 10) * 100;
                catHtml += `<div class="category-bar-row"><span class="cat-label">${label}</span><div class="cat-bar-track"><div class="cat-bar-fill" style="width:${pct}%"></div></div><span class="cat-value">${val.toFixed(1)}</span></div>`;
            }
            catHtml += '</div></div>';
            this.statsGrid.innerHTML += catHtml;
        }
    }

    renderScoringDynamicsChart(dynamics) {
        const canvas = document.getElementById('scoringDynamicsChart');
        if (!canvas) return;
        if (this.scoringDynamicsChart) this.scoringDynamicsChart.destroy();
        if (dynamics.length === 0) { canvas.parentElement.innerHTML = '<p class="no-data">Нет данных для графика</p>'; return; }
        this.scoringDynamicsChart = new Chart(canvas, {
            type: 'line',
            data: { labels: dynamics.map(d => d.date), datasets: [{ label: 'Средний балл', data: dynamics.map(d => d.overall_score), borderColor: 'rgba(0, 212, 255, 1)', backgroundColor: 'rgba(0, 212, 255, 0.1)', fill: true, tension: 0.3, pointRadius: 4, pointBackgroundColor: 'rgba(0, 212, 255, 1)' }] },
            options: { responsive: true, scales: { y: { min: 0, max: 10, ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } }, x: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } } }, plugins: { legend: { labels: { color: '#f1f5f9' } } } }
        });
    }

    renderObjectionsList(objections) {
        if (objections.length === 0) { this.objectionsListContainer.innerHTML = '<p class="no-data">Нет данных о возражениях</p>'; return; }
        this.objectionsListContainer.innerHTML = objections.map((o, i) => `<div class="objection-item"><span class="objection-rank">${i + 1}</span><span class="objection-text">${o.text}</span><span class="objection-count">${o.count}x</span></div>`).join('');
    }

    // Sellers
    async loadSellers() {
        try {
            const response = await authFetch('/dialogs/sellers');
            if (!response.ok) return;
            const sellers = await response.json();
            this.populateSellerDropdowns(sellers);
        } catch (e) { console.error('Failed to load sellers:', e); }
    }

    populateSellerDropdowns(sellers) {
        const uploadSelect = this.sellerNameInput;
        uploadSelect.innerHTML = '<option value="">Не указан</option>';
        sellers.forEach(name => { uploadSelect.innerHTML += `<option value="${name}">${name}</option>`; });
        uploadSelect.innerHTML += '<option value="__new__">+ Новый продавец...</option>';

        const filterSelect = this.sellerFilter;
        filterSelect.innerHTML = '<option value="">Все продавцы</option>';
        sellers.forEach(name => { filterSelect.innerHTML += `<option value="${name}">${name}</option>`; });

        const dashSelect = this.dashSellerFilter;
        dashSelect.innerHTML = '<option value="">Все продавцы</option>';
        sellers.forEach(name => { dashSelect.innerHTML += `<option value="${name}">${name}</option>`; });
    }

    // Utilities
    formatFileSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    formatDuration(seconds) {
        if (seconds == null || isNaN(seconds)) return '0:00';
        const s = Math.floor(seconds); const h = Math.floor(s / 3600); const m = Math.floor((s % 3600) / 60); const sec = s % 60;
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
        script.onload = resolve; script.onerror = reject;
        document.head.appendChild(script);
    });
}

// Init
document.addEventListener('DOMContentLoaded', async () => {
    // Close profile/orgs modals on backdrop click
    document.querySelectorAll('#profileModal, #orgsModal, #addMemberModal, #createOrgModal, #createDeptModal').forEach(modal => {
        modal.addEventListener('click', (e) => { if (e.target === modal) modal.classList.remove('active'); });
    });

    // Org form handlers (used inside orgsModal)
    document.addEventListener('submit', async (e) => {
        if (e.target.id === 'createOrgForm') {
            e.preventDefault();
            const name = document.getElementById('orgNameInput')?.value.trim();
            if (name) await createOrganization(name);
        }
        if (e.target.id === 'addMemberForm') { e.preventDefault(); await submitAddMemberForm(e); }
        if (e.target.id === 'createDeptForm') { e.preventDefault(); await submitCreateDeptForm(e); }
    });

    await loadChartJS();
    window.app = new VoiceCheckApp();
});
