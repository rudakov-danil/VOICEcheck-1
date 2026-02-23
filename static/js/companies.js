/**
 * VOICEcheck — Companies Module
 * CMP-001..CMP-005  CSV Import
 * CMP-010..CMP-013  Company CRUD / list / card
 * CMP-021           Link company to dialog
 * CMP-022           Auto-suggest company from transcript
 */

const companiesModule = (() => {
    // ─── State ───────────────────────────────────────────────────────────────
    let state = {
        page: 1,
        perPage: 20,
        total: 0,
        search: '',
        industry: '',
        funnelStage: '',
        sortBy: 'created_at',
        sortDir: 'desc',
        editingId: null,          // null = create mode
        csvData: null,            // upload response
        _searchTimer: null,
    };

    // ─── Init ─────────────────────────────────────────────────────────────────
    function init() {
        // Bind static buttons
        const createBtn = document.getElementById('createCompanyBtn');
        if (createBtn) createBtn.addEventListener('click', () => openCompanyForm(null));

        const importBtn = document.getElementById('importCsvBtn');
        if (importBtn) importBtn.addEventListener('click', openCsvImport);

        const backBtn = document.getElementById('backToCompaniesBtn');
        if (backBtn) backBtn.addEventListener('click', backToList);

        // Filters
        const searchInput = document.getElementById('companySearch');
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                clearTimeout(state._searchTimer);
                state._searchTimer = setTimeout(() => {
                    state.search = searchInput.value.trim();
                    state.page = 1;
                    loadCompanies();
                }, 400);
            });
        }

        const sortBySelect = document.getElementById('companySortBy');
        if (sortBySelect) {
            sortBySelect.addEventListener('change', () => {
                state.sortBy = sortBySelect.value;
                state.page = 1;
                loadCompanies();
            });
        }

        // Company form submit
        const companyForm = document.getElementById('companyForm');
        if (companyForm) {
            companyForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                await submitCompanyForm();
            });
        }

        // CSV drop zone
        initCsvDropZone();
    }

    // ─── Load list (CMP-010) ──────────────────────────────────────────────────
    async function loadCompanies() {
        const tbody = document.getElementById('companiesTbody');
        if (!tbody) return;
        tbody.innerHTML = '<tr><td colspan="6" class="no-data"><span class="spinner"></span> Загрузка...</td></tr>';

        const params = new URLSearchParams({
            page: state.page,
            limit: state.perPage,
            sort_by: state.sortBy,
            sort_dir: state.sortDir,
        });
        if (state.search) params.append('search', state.search);

        try {
            const resp = await authFetch(`/companies?${params}`);
            if (!resp.ok) throw new Error('Ошибка загрузки');
            const data = await resp.json();
            state.total = data.total || 0;
            renderCompaniesTable(data.items || []);
            renderCompaniesPagination(data.total_pages || 1);
        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="6" class="no-data" style="color:var(--red)">Ошибка: ${e.message}</td></tr>`;
        }
    }

    function renderCompaniesTable(items) {
        const tbody = document.getElementById('companiesTbody');
        if (!tbody) return;
        if (!items.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="no-data">Нет компаний. Добавьте вручную или импортируйте CSV.</td></tr>';
            return;
        }
        tbody.innerHTML = items.map(c => {
            const scoreHtml = c.avg_score != null
                ? `<span class="company-score ${scoreClass(c.avg_score)}">${c.avg_score}</span>`
                : '<span class="company-score no-score">—</span>';
            const lastDate = c.last_meeting_date
                ? new Date(c.last_meeting_date).toLocaleDateString('ru-RU')
                : '—';
            return `
            <tr class="company-row" data-id="${c.id}">
                <td>
                    <div class="company-name-cell">
                        <span class="company-name">${escHtml(c.name)}</span>
                        ${c.inn ? `<span class="company-inn">ИНН ${escHtml(c.inn)}</span>` : ''}
                    </div>
                </td>
                <td>${escHtml(c.contact_person || '—')}</td>
                <td><span class="meetings-badge">${c.meetings_count}</span></td>
                <td class="text-muted">${lastDate}</td>
                <td>${scoreHtml}</td>
                <td class="company-actions">
                    <button class="btn-icon" title="Редактировать" onclick="companiesModule.openCompanyForm('${c.id}', event)">✎</button>
                    <button class="btn-icon btn-icon-danger" title="Удалить" onclick="companiesModule.deleteCompany('${c.id}', '${escHtml(c.name)}', event)">✕</button>
                </td>
            </tr>`;
        }).join('');

        // Row click → open detail
        tbody.querySelectorAll('.company-row').forEach(row => {
            row.addEventListener('click', (e) => {
                if (e.target.closest('.company-actions')) return;
                openCompanyDetail(row.dataset.id);
            });
        });
    }

    function renderCompaniesPagination(totalPages) {
        const container = document.getElementById('companiesPagination');
        if (!container) return;
        if (totalPages <= 1) { container.innerHTML = ''; return; }
        let html = `<button class="page-btn" ${state.page === 1 ? 'disabled' : ''} onclick="companiesModule.goToPage(${state.page - 1})">&#8592;</button>`;
        const start = Math.max(1, state.page - 2);
        const end = Math.min(totalPages, state.page + 2);
        if (start > 1) { html += `<button class="page-btn" onclick="companiesModule.goToPage(1)">1</button>`; if (start > 2) html += `<span class="page-dots">...</span>`; }
        for (let i = start; i <= end; i++) {
            html += `<button class="page-btn ${i === state.page ? 'active' : ''}" onclick="companiesModule.goToPage(${i})">${i}</button>`;
        }
        if (end < totalPages) { if (end < totalPages - 1) html += `<span class="page-dots">...</span>`; html += `<button class="page-btn" onclick="companiesModule.goToPage(${totalPages})">${totalPages}</button>`; }
        html += `<button class="page-btn" ${state.page === totalPages ? 'disabled' : ''} onclick="companiesModule.goToPage(${state.page + 1})">&#8594;</button>`;
        container.innerHTML = html;
    }

    function goToPage(page) { state.page = page; loadCompanies(); }

    // ─── Company detail (CMP-011) ─────────────────────────────────────────────
    async function openCompanyDetail(id) {
        document.getElementById('companiesListView').style.display = 'none';
        document.getElementById('companyDetailView').style.display = 'block';
        const content = document.getElementById('companyDetailContent');
        content.innerHTML = '<p style="color:var(--text-1)"><span class="spinner"></span> Загрузка...</p>';

        try {
            const resp = await authFetch(`/companies/${id}`);
            if (!resp.ok) throw new Error('Ошибка загрузки');
            const c = await resp.json();
            renderCompanyDetail(c);
        } catch (e) {
            content.innerHTML = `<p style="color:var(--red)">Ошибка: ${e.message}</p>`;
        }
    }

    function renderCompanyDetail(c) {
        const content = document.getElementById('companyDetailContent');
        const avgScore = c.avg_score != null ? `<span class="company-score ${scoreClass(c.avg_score)} large">${c.avg_score}</span>` : '—';

        const infoRows = [
            c.inn ? `<div class="info-row"><span class="info-label">ИНН</span><span>${escHtml(c.inn)}</span></div>` : '',
            c.external_id ? `<div class="info-row"><span class="info-label">Внешний ID</span><span>${escHtml(c.external_id)}</span></div>` : '',
            c.contact_person ? `<div class="info-row"><span class="info-label">Контакт</span><span>${escHtml(c.contact_person)}</span></div>` : '',
            c.phone ? `<div class="info-row"><span class="info-label">Телефон</span><span>${escHtml(c.phone)}</span></div>` : '',
            c.email ? `<div class="info-row"><span class="info-label">Email</span><span>${escHtml(c.email)}</span></div>` : '',
            c.address ? `<div class="info-row"><span class="info-label">Адрес</span><span>${escHtml(c.address)}</span></div>` : '',
            c.industry ? `<div class="info-row"><span class="info-label">Отрасль</span><span>${escHtml(c.industry)}</span></div>` : '',
            c.funnel_stage ? `<div class="info-row"><span class="info-label">Этап воронки</span><span class="funnel-badge">${escHtml(c.funnel_stage)}</span></div>` : '',
        ].filter(Boolean).join('');

        // Custom fields
        let customHtml = '';
        if (c.custom_fields && Object.keys(c.custom_fields).length) {
            customHtml = Object.entries(c.custom_fields)
                .map(([k, v]) => `<div class="info-row"><span class="info-label">${escHtml(k)}</span><span>${escHtml(v)}</span></div>`)
                .join('');
        }

        // Status counts
        const statusMap = { dealed: 'Сделки', in_progress: 'В работе', rejected: 'Отказы' };
        const statusHtml = Object.entries(c.status_counts || {})
            .map(([s, cnt]) => `<div class="status-stat"><span class="status-badge ${s}">${statusMap[s] || s}</span> <b>${cnt}</b></div>`)
            .join('');

        // Meetings list
        const meetingsHtml = (c.meetings || []).length
            ? c.meetings.map(m => {
                const score = m.overall_score != null ? `<span class="company-score ${scoreClass(m.overall_score)}">${m.overall_score.toFixed(1)}</span>` : '';
                const date = m.created_at ? new Date(m.created_at).toLocaleDateString('ru-RU') : '';
                return `<div class="meeting-row">
                    <div class="meeting-info">
                        <span class="meeting-name">${escHtml(m.filename)}</span>
                        <span class="text-muted" style="font-size:.8rem;">${date}${m.seller_name ? ' · ' + escHtml(m.seller_name) : ''}</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:8px;">
                        ${score}
                        <span class="status-badge ${m.status}">${getStatusText(m.status)}</span>
                    </div>
                </div>`;
            }).join('')
            : '<p class="no-data">Встреч нет</p>';

        // Score trend (simple inline sparkline)
        const trendHtml = c.score_trend && c.score_trend.length > 1
            ? renderSparkline(c.score_trend)
            : '<p class="no-data">Недостаточно данных</p>';

        // Objections
        const objectionsHtml = (c.objections || []).length
            ? c.objections.map((o, i) => `<span class="objection-chip">${escHtml(o)}</span>`).join('')
            : '<p class="no-data">Нет данных</p>';

        content.innerHTML = `
        <div class="company-detail">
            <div class="company-detail-header">
                <div>
                    <h2 class="company-detail-name">${escHtml(c.name)}</h2>
                    <div class="company-detail-meta">
                        Добавлена ${c.created_at ? new Date(c.created_at).toLocaleDateString('ru-RU') : ''}
                        · Встреч: <b>${c.meetings_count}</b>
                        · Ср. балл: ${avgScore}
                    </div>
                </div>
                <div class="company-detail-actions">
                    <button class="btn btn-small btn-secondary" onclick="companiesModule.openCompanyForm('${c.id}')">✎ Редактировать</button>
                    <button class="btn btn-small btn-danger" onclick="companiesModule.deleteCompany('${c.id}', '${escHtml(c.name)}')">Удалить</button>
                </div>
            </div>

            <div class="company-detail-grid">
                <div class="card company-info-card">
                    <h3>Реквизиты</h3>
                    ${infoRows || '<p class="no-data">Нет данных</p>'}
                    ${customHtml}
                </div>

                <div class="card">
                    <h3>Статистика по статусам</h3>
                    <div class="status-stats">${statusHtml || '<p class="no-data">Нет данных</p>'}</div>
                </div>
            </div>

            <div class="card" style="margin-top:16px;">
                <h3>Динамика скорринга</h3>
                ${trendHtml}
            </div>

            <div class="card" style="margin-top:16px;">
                <h3>История встреч (${c.meetings_count})</h3>
                <div class="meetings-list">${meetingsHtml}</div>
            </div>

            <div class="card" style="margin-top:16px;">
                <h3>Возражения</h3>
                <div class="objections-cloud">${objectionsHtml}</div>
            </div>
        </div>`;
    }

    function renderSparkline(trend) {
        const validTrend = trend.filter(t => t.score != null);
        if (!validTrend.length) return '<p class="no-data">Нет данных</p>';
        const w = 320, h = 60;
        const scores = validTrend.map(t => t.score);
        const minS = Math.min(...scores);
        const maxS = Math.max(...scores);
        const range = maxS - minS || 1;
        const pts = validTrend.map((t, i) => {
            const x = (i / Math.max(validTrend.length - 1, 1)) * (w - 20) + 10;
            const y = h - 10 - ((t.score - minS) / range) * (h - 20);
            return `${x},${y}`;
        }).join(' ');
        return `<div class="sparkline-wrap">
            <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="overflow:visible">
                <polyline points="${pts}" fill="none" stroke="var(--accent-light)" stroke-width="2" stroke-linejoin="round"/>
                ${validTrend.map((t, i) => {
                    const x = (i / Math.max(validTrend.length - 1, 1)) * (w - 20) + 10;
                    const y = h - 10 - ((t.score - minS) / range) * (h - 20);
                    return `<circle cx="${x}" cy="${y}" r="3" fill="var(--accent-light)">
                        <title>${t.date}: ${t.score}</title>
                    </circle>`;
                }).join('')}
            </svg>
            <div class="sparkline-dates">
                <span>${validTrend[0].date}</span>
                <span>${validTrend[validTrend.length - 1].date}</span>
            </div>
        </div>`;
    }

    function backToList() {
        document.getElementById('companiesListView').style.display = '';
        document.getElementById('companyDetailView').style.display = 'none';
    }

    // ─── Create / Edit company (CMP-012, CMP-013) ─────────────────────────────
    async function openCompanyForm(id, event) {
        if (event) event.stopPropagation();
        state.editingId = id || null;

        const modal = document.getElementById('companyFormModal');
        const title = document.getElementById('companyFormTitle');
        title.textContent = id ? 'Редактировать компанию' : 'Добавить компанию';

        // Clear form
        ['name','inn','contact_person','phone','email','address']
            .forEach(f => { const el = document.getElementById('cf_' + f); if (el) el.value = ''; });

        // Load sellers for "Ответственный" dropdown
        const responsibleSelect = document.getElementById('cf_responsible');
        if (responsibleSelect) {
            responsibleSelect.innerHTML = '<option value="">— Не назначен —</option>';
            try {
                // Try to get members from current org
                const orgsResp = await authFetch('/auth/organizations');
                if (orgsResp.ok) {
                    const orgs = await orgsResp.json();
                    if (orgs.length > 0) {
                        const membersResp = await authFetch(`/organizations/${orgs[0].id}/members`);
                        if (membersResp.ok) {
                            const members = await membersResp.json();
                            members.filter(m => m.role === 'member' || m.role === 'admin')
                                .forEach(m => {
                                    responsibleSelect.innerHTML += `<option value="${m.full_name}">${m.full_name}</option>`;
                                });
                        }
                    }
                }
            } catch (e) {}
        }

        if (id) {
            // Load data
            try {
                const resp = await authFetch(`/companies/${id}`);
                if (resp.ok) {
                    const c = await resp.json();
                    ['name','inn','contact_person','phone','email','address']
                        .forEach(f => {
                            const el = document.getElementById('cf_' + f);
                            if (el && c[f]) el.value = c[f];
                        });
                    // Set responsible person
                    if (responsibleSelect && c.responsible) {
                        // Add option if not in list
                        let found = false;
                        for (const opt of responsibleSelect.options) {
                            if (opt.value === c.responsible) { found = true; break; }
                        }
                        if (!found && c.responsible) {
                            responsibleSelect.innerHTML += `<option value="${c.responsible}">${c.responsible}</option>`;
                        }
                        responsibleSelect.value = c.responsible;
                    }
                }
            } catch (e) {}
        }

        modal.classList.add('active');
    }

    function closeCompanyForm() {
        document.getElementById('companyFormModal').classList.remove('active');
        state.editingId = null;
    }

    async function submitCompanyForm() {
        const btn = document.getElementById('companyFormSubmitBtn');
        btn.disabled = true;
        btn.textContent = 'Сохранение...';

        const payload = {};
        ['name','inn','contact_person','phone','email','address']
            .forEach(f => {
                const el = document.getElementById('cf_' + f);
                if (el && el.value.trim()) payload[f] = el.value.trim();
            });
        const responsibleEl = document.getElementById('cf_responsible');
        if (responsibleEl && responsibleEl.value) payload.responsible = responsibleEl.value;

        if (!payload.name) {
            btn.disabled = false; btn.textContent = 'Сохранить';
            alert('Введите название компании');
            return;
        }

        try {
            const url = state.editingId ? `/companies/${state.editingId}` : '/companies/';
            const method = state.editingId ? 'PUT' : 'POST';
            const resp = await authFetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                const detail = err.detail;
                if (Array.isArray(detail)) {
                    throw new Error(detail.map(e => e.msg || JSON.stringify(e)).join('; '));
                }
                throw new Error(detail || 'Ошибка сохранения');
            }
            closeCompanyForm();
            loadCompanies();
        } catch (e) {
            alert('Ошибка: ' + e.message);
        } finally {
            btn.disabled = false; btn.textContent = 'Сохранить';
        }
    }

    // ─── Delete company (CMP-013) ─────────────────────────────────────────────
    async function deleteCompany(id, name, event) {
        if (event) event.stopPropagation();
        if (!confirm(`Удалить компанию "${name}"?\n\nВстречи будут сохранены, но отвязаны от компании.`)) return;
        try {
            const resp = await authFetch(`/companies/${id}`, { method: 'DELETE' });
            if (!resp.ok && resp.status !== 204) throw new Error('Ошибка удаления');
            loadCompanies();
            // If we're in detail view, go back
            if (document.getElementById('companyDetailView').style.display !== 'none') {
                backToList();
            }
        } catch (e) {
            alert('Ошибка: ' + e.message);
        }
    }

    // ─── CSV Import (CMP-001..CMP-005) ────────────────────────────────────────
    function openCsvImport() {
        csvReset();
        document.getElementById('csvImportModal').classList.add('active');
    }

    function closeCsvImport() {
        document.getElementById('csvImportModal').classList.remove('active');
    }

    function csvReset() {
        state.csvData = null;
        showCsvStep(1);
        document.getElementById('csvFileInput').value = '';
        document.getElementById('csvUploadError').textContent = '';
    }

    function csvBack() { showCsvStep(1); }

    function showCsvStep(n) {
        [1,2,3].forEach(i => {
            const el = document.getElementById('csvStep' + i);
            if (el) el.style.display = i === n ? '' : 'none';
        });
    }

    function initCsvDropZone() {
        const zone = document.getElementById('csvDropZone');
        const input = document.getElementById('csvFileInput');
        if (!zone || !input) return;

        zone.addEventListener('click', () => input.click());
        input.addEventListener('change', e => {
            if (e.target.files[0]) handleCsvFile(e.target.files[0]);
        });

        ['dragenter','dragover','dragleave','drop'].forEach(ev => {
            zone.addEventListener(ev, e => { e.preventDefault(); e.stopPropagation(); });
        });
        zone.addEventListener('dragover', () => zone.classList.add('dragover'));
        zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
        zone.addEventListener('drop', e => {
            zone.classList.remove('dragover');
            if (e.dataTransfer.files[0]) handleCsvFile(e.dataTransfer.files[0]);
        });
    }

    async function handleCsvFile(file) {
        const errEl = document.getElementById('csvUploadError');
        errEl.textContent = '';

        if (!file.name.endsWith('.csv')) {
            errEl.textContent = 'Ожидается CSV файл'; return;
        }

        const formData = new FormData();
        formData.append('file', file);

        try {
            errEl.textContent = 'Загрузка...';
            const resp = await authFetch('/companies/import/upload', { method: 'POST', body: formData });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                errEl.textContent = err.detail || 'Ошибка загрузки файла';
                return;
            }
            const data = await resp.json();
            state.csvData = data;
            errEl.textContent = '';
            renderCsvStep2(data);
            showCsvStep(2);
        } catch (e) {
            errEl.textContent = 'Ошибка: ' + e.message;
        }
    }

    function renderCsvStep2(data) {
        // Stats
        document.getElementById('csvFileStats').innerHTML =
            `<b>${data.filename}</b> · ${data.total_rows} строк · кодировка: <code>${data.encoding}</code>`;

        // Preview table
        const table = document.getElementById('csvPreviewTable');
        let html = '<thead><tr>' + data.headers.map(h => `<th>${escHtml(h)}</th>`).join('') + '</tr></thead><tbody>';
        data.preview.forEach(row => {
            html += '<tr>' + row.map(cell => `<td>${escHtml(cell)}</td>`).join('') + '</tr>';
        });
        html += '</tbody>';
        table.innerHTML = html;

        // Mapping table
        const tbody = document.getElementById('mappingTableBody');
        const FIELD_LABELS = {
            name: 'Название компании *',
            inn: 'ИНН',
            contact_person: 'Контактное лицо',
            phone: 'Телефон',
            email: 'Email',
            address: 'Адрес',
            responsible: 'Ответственный',
            custom_1: 'Произвольное поле 1',
            custom_2: 'Произвольное поле 2',
            custom_3: 'Произвольное поле 3',
            custom_4: 'Произвольное поле 4',
            custom_5: 'Произвольное поле 5',
            __skip__: '— Пропустить —',
        };
        tbody.innerHTML = data.headers.map(h => {
            const guessed = (data.auto_mapping || {})[h] || '__skip__';
            const options = (data.system_fields || []).map(f =>
                `<option value="${f}" ${f === guessed ? 'selected' : ''}>${FIELD_LABELS[f] || f}</option>`
            ).join('');
            return `<tr>
                <td><code>${escHtml(h)}</code></td>
                <td><select class="form-input mapping-select" data-col="${escHtml(h)}">${options}</select></td>
            </tr>`;
        }).join('');

        // Saved mappings
        const savedSelect = document.getElementById('savedMappingSelect');
        savedSelect.innerHTML = '<option value="">— выбрать —</option>';
        (data.saved_mappings || []).forEach(m => {
            savedSelect.innerHTML += `<option value="${m.id}" data-mapping='${JSON.stringify(m.mapping)}'>${escHtml(m.name)}</option>`;
        });
        savedSelect.onchange = () => {
            const opt = savedSelect.selectedOptions[0];
            if (!opt || !opt.dataset.mapping) return;
            const mapping = JSON.parse(opt.dataset.mapping);
            tbody.querySelectorAll('.mapping-select').forEach(sel => {
                const col = sel.dataset.col;
                if (mapping[col]) sel.value = mapping[col];
            });
        };
    }

    function getCurrentMapping() {
        const tbody = document.getElementById('mappingTableBody');
        const mapping = {};
        tbody.querySelectorAll('.mapping-select').forEach(sel => {
            mapping[sel.dataset.col] = sel.value;
        });
        return mapping;
    }

    async function csvProcess() {
        if (!state.csvData) return;

        const mapping = getCurrentMapping();
        const duplicateAction = document.getElementById('duplicateAction').value;

        // Save mapping if requested
        const saveCheck = document.getElementById('saveMappingCheck');
        const saveName = document.getElementById('saveMappingName').value.trim();
        if (saveCheck && saveCheck.checked && saveName) {
            await authFetch('/companies/import/mappings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: saveName, mapping }),
            }).catch(() => {});
        }

        // Process
        showCsvStep(3);
        document.getElementById('csvImportResult').innerHTML =
            '<p><span class="spinner"></span> Идёт импорт...</p>';

        try {
            const resp = await authFetch('/companies/import/process', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_content: state.csvData.file_content_b64,
                    encoding: state.csvData.encoding,
                    mapping,
                    duplicate_action: duplicateAction,
                }),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || 'Ошибка импорта');
            }
            const result = await resp.json();
            renderCsvResult(result);
            loadCompanies();
        } catch (e) {
            document.getElementById('csvImportResult').innerHTML =
                `<div class="import-error"><b>Ошибка импорта:</b> ${escHtml(e.message)}</div>`;
        }
    }

    function renderCsvResult(r) {
        let html = `
        <div class="import-summary ${r.errors_count ? 'has-errors' : 'success'}">
            <div class="import-stat"><span class="import-num success-num">${r.imported}</span><span>Добавлено</span></div>
            <div class="import-stat"><span class="import-num update-num">${r.updated}</span><span>Обновлено</span></div>
            <div class="import-stat"><span class="import-num skip-num">${r.skipped}</span><span>Пропущено</span></div>
            ${r.errors_count ? `<div class="import-stat"><span class="import-num error-num">${r.errors_count}</span><span>Ошибок</span></div>` : ''}
        </div>
        <p class="import-message">${escHtml(r.message)}</p>`;

        if (r.errors && r.errors.length) {
            html += `<details class="import-errors-detail">
                <summary>Показать ошибки (${r.errors.length})</summary>
                <table class="error-table">
                    <thead><tr><th>Строка</th><th>Ошибка</th></tr></thead>
                    <tbody>${r.errors.map(e => `<tr><td>${e.row}</td><td>${escHtml(e.error)}</td></tr>`).join('')}</tbody>
                </table>
            </details>`;
        }
        document.getElementById('csvImportResult').innerHTML = html;
    }

    // ─── CMP-021  Link company to dialog (called from dialog modal) ───────────
    async function loadCompaniesForSelect(selectEl, selectedId) {
        try {
            const resp = await authFetch('/companies/search?limit=100');
            if (!resp.ok) return;
            const companies = await resp.json();
            selectEl.innerHTML = '<option value="">— Не привязана —</option>';
            companies.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c.id;
                opt.textContent = c.name + (c.inn ? ` (ИНН ${c.inn})` : '');
                if (c.id === selectedId) opt.selected = true;
                selectEl.appendChild(opt);
            });
        } catch (e) {}
    }

    async function linkCompanyToDialog(dialogId, companyId) {
        try {
            const resp = await authFetch(`/companies/link-dialog/${dialogId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ company_id: companyId || null }),
            });
            return resp.ok;
        } catch (e) {
            return false;
        }
    }

    // ─── CMP-022  Auto-suggest from dialog card ───────────────────────────────
    async function suggestCompany(dialogId, suggestionContainer) {
        suggestionContainer.innerHTML = '<span class="text-muted" style="font-size:.85rem;"><span class="spinner" style="width:12px;height:12px;"></span> Поиск компании...</span>';
        try {
            const resp = await authFetch(`/companies/suggest/${dialogId}`);
            if (!resp.ok) { suggestionContainer.innerHTML = ''; return; }
            const data = await resp.json();
            if (!data.suggestions || !data.suggestions.length) {
                suggestionContainer.innerHTML = '<span class="text-muted" style="font-size:.85rem;">Компания не определена</span>';
                return;
            }
            const top = data.suggestions[0];
            suggestionContainer.innerHTML = `
                <div class="company-suggestion">
                    <span class="suggestion-icon">💡</span>
                    <span>Возможно, это встреча с <b>${escHtml(top.company_name)}</b>?</span>
                    <button class="btn btn-small" onclick="companiesModule.acceptSuggestion('${dialogId}','${top.company_id}','${escHtml(top.company_name)}',this)">Привязать</button>
                    <button class="btn-icon btn-icon-sm" onclick="this.parentElement.parentElement.innerHTML=''" title="Закрыть">✕</button>
                </div>`;
        } catch (e) {
            suggestionContainer.innerHTML = '';
        }
    }

    async function acceptSuggestion(dialogId, companyId, companyName, btn) {
        btn.disabled = true; btn.textContent = '...';
        const ok = await linkCompanyToDialog(dialogId, companyId);
        if (ok) {
            btn.closest('.company-suggestion').innerHTML =
                `<span style="color:var(--green)">✓ Привязано: ${escHtml(companyName)}</span>`;
        } else {
            btn.disabled = false; btn.textContent = 'Привязать';
        }
    }

    // ─── Helpers ──────────────────────────────────────────────────────────────
    function escHtml(str) {
        if (str == null) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function scoreClass(v) {
        if (v >= 8) return 'score-high';
        if (v >= 5) return 'score-mid';
        return 'score-low';
    }

    function getStatusText(s) {
        const m = { completed: 'В работе', dealed: 'Сделка состоялась', in_progress: 'В работе', rejected: 'Отказ', pending: 'Ожидание', processing: 'Обработка', failed: 'Ошибка' };
        return m[s] || s;
    }

    // ─── Public API ───────────────────────────────────────────────────────────
    return {
        init,
        loadCompanies,
        openCompanyForm,
        closeCompanyForm,
        deleteCompany,
        openCsvImport,
        closeCsvImport,
        csvBack,
        csvProcess,
        csvReset,
        goToPage,
        loadCompaniesForSelect,
        linkCompanyToDialog,
        suggestCompany,
        acceptSuggestion,
    };
})();

// Init on DOM ready (called after app.js DOMContentLoaded)
document.addEventListener('DOMContentLoaded', () => {
    companiesModule.init();
});
