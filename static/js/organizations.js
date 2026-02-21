/**
 * VOICEcheck - Organizations Management
 * Handles organization CRUD, members, departments, and org profile card.
 * Depends on: api.js (APIClient), utils.js (escapeHtml, etc.)
 */

let viewingOrgId = null;
let viewingOrgData = null;

// ============================================================
// Organization List
// ============================================================

async function loadOrganizationsForTab() {
    const organizationsList = document.getElementById('organizationsList');
    if (!organizationsList) return;

    try {
        const response = await fetch('/auth/organizations', {
            headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
        });

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
                <div class="empty-state">
                    <div class="empty-icon">🏢</div>
                    <p>У вас пока нет организаций</p>
                    <button class="btn btn-primary" onclick="showCreateOrgForm()" style="width:auto; margin-top:12px;">Создать организацию</button>
                </div>
            `;
            return;
        }

        let html = '<div class="organizations-grid">';
        organizations.forEach(org => {
            html += `
                <div class="glass-card org-card-item" onclick="viewOrganization('${org.id}')">
                    <div class="org-card-icon">${escapeHtml(org.name.charAt(0).toUpperCase())}</div>
                    <div class="org-card-body">
                        <h3 class="org-card-name">${escapeHtml(org.name)}</h3>
                        <span class="role-badge role-${org.role}">${getRoleLabel(org.role)}</span>
                    </div>
                    <div class="org-card-arrow">→</div>
                </div>
            `;
        });
        html += '</div>';
        organizationsList.innerHTML = html;

    } catch (error) {
        console.error('Error loading organizations:', error);
        organizationsList.innerHTML = '<p class="error">Ошибка загрузки организаций</p>';
    }
}

function getRoleLabel(role) {
    const labels = {
        'owner': 'Владелец',
        'admin': 'Администратор',
        'member': 'Участник',
        'viewer': 'Зритель'
    };
    return labels[role] || role;
}

// ============================================================
// Create Organization
// ============================================================

function showCreateOrgForm() {
    const modal = document.getElementById('createOrgModal');
    const form = document.getElementById('createOrgForm');
    const orgNameInput = document.getElementById('orgNameInput');

    form.reset();
    clearAllErrors();

    modal.classList.add('active');
    if (orgNameInput) orgNameInput.focus();
}

function closeCreateOrgModal() {
    document.getElementById('createOrgModal').classList.remove('active');
}

async function createOrganization(name) {
    try {
        const response = await fetch('/organizations', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + localStorage.getItem('access_token')
            },
            body: JSON.stringify({ name })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create organization');
        }

        closeCreateOrgModal();
        loadOrganizationsForTab();
    } catch (error) {
        showFieldError('orgNameInput', error.message);
    }
}

// ============================================================
// Organization Profile Card (Detail View)
// ============================================================

async function viewOrganization(orgId) {
    viewingOrgId = orgId;

    document.getElementById('organizationListView').style.display = 'none';
    document.getElementById('organizationDetailView').style.display = 'block';

    // Load org details + stats + members + departments in parallel
    const token = localStorage.getItem('access_token');
    const headers = { 'Authorization': 'Bearer ' + token };

    try {
        const [orgRes, statsRes, membersRes, deptsRes] = await Promise.all([
            fetch(`/organizations/${orgId}`, { headers }),
            fetch(`/organizations/${orgId}/stats`, { headers }),
            fetch(`/organizations/${orgId}/members`, { headers }),
            fetch(`/organizations/${orgId}/departments`, { headers }).catch(() => ({ ok: false }))
        ]);

        const org = orgRes.ok ? await orgRes.json() : null;
        const stats = statsRes.ok ? await statsRes.json() : null;
        const members = membersRes.ok ? await membersRes.json() : [];
        const departments = deptsRes.ok ? await deptsRes.json() : [];

        viewingOrgData = { org, stats, members, departments };
        renderOrgProfile(org, stats, members, departments);
    } catch (error) {
        console.error('Error loading organization:', error);
    }
}

function renderOrgProfile(org, stats, members, departments) {
    const container = document.getElementById('orgProfileContent');
    if (!container) return;

    const loginLink = `${location.origin}/login/${org?.access_code || ''}`;

    // Determine if current user is the owner (to show delete button)
    const currentUser = JSON.parse(localStorage.getItem('user') || '{}');
    const myMembership = members.find(m => m.id === currentUser?.id);
    const isOwner = myMembership?.role === 'owner';

    container.innerHTML = `
        <!-- Org Header Card -->
        <div class="glass-card org-profile-header">
            <div class="org-profile-icon">${escapeHtml((org?.name || '?').charAt(0).toUpperCase())}</div>
            <div class="org-profile-info">
                <h2 class="org-profile-name">${escapeHtml(org?.name || 'Организация')}</h2>
                <div class="org-profile-meta">
                    <span class="org-profile-code" title="Код доступа">${org?.access_code || ''}</span>
                    <span class="org-profile-slug">${escapeHtml(org?.slug || '')}</span>
                </div>
            </div>
            ${isOwner ? `
            <div class="org-profile-actions">
                <button class="btn btn-small btn-danger" onclick="deleteOrganization('${org?.id}', '${escapeHtml(org?.name || '')}')">Удалить организацию</button>
            </div>
            ` : ''}
        </div>

        <!-- Login Link -->
        <div class="glass-card org-login-link-card">
            <div class="org-login-link-label">Ссылка для входа сотрудников</div>
            <div class="org-login-link-row">
                <input type="text" class="form-input org-login-link-input" value="${loginLink}" readonly onclick="this.select()">
                <button class="btn btn-small" onclick="copyOrgLoginLink('${org?.access_code || ''}')">Копировать</button>
            </div>
        </div>

        <!-- Stats -->
        ${stats ? `
        <div class="org-stats-row">
            <div class="glass-card org-stat">
                <div class="org-stat-value">${stats.total_members || 0}</div>
                <div class="org-stat-label">Сотрудников</div>
            </div>
            <div class="glass-card org-stat">
                <div class="org-stat-value">${departments.length || 0}</div>
                <div class="org-stat-label">Отделов</div>
            </div>
            <div class="glass-card org-stat">
                <div class="org-stat-value">${stats.dialogs || 0}</div>
                <div class="org-stat-label">Диалогов</div>
            </div>
        </div>
        ` : ''}

        <!-- Departments Section -->
        <div class="glass-card org-section">
            <div class="section-header">
                <h3>Отделы</h3>
                <button class="btn btn-small btn-primary" onclick="showCreateDeptForm()">+ Отдел</button>
            </div>
            <div id="departmentsList">
                ${renderDepartments(departments, members)}
            </div>
        </div>

        <!-- Members Section -->
        <div class="glass-card org-section org-section-members">
            <div class="section-header">
                <h3>Сотрудники</h3>
                <button class="btn btn-small btn-primary" onclick="showAddMemberForm()">+ Сотрудник</button>
            </div>
            <div id="membersList">
                ${renderMembers(members, departments)}
            </div>
        </div>
    `;
}

function renderDepartments(departments, members) {
    if (!departments || departments.length === 0) {
        return '<p class="text-muted">Нет отделов. Создайте первый отдел и добавьте в него сотрудников.</p>';
    }

    return departments.map(dept => {
        const headMember = members.find(m => m.id === dept.head_user_id);
        const deptMembers = members.filter(m => m.department_id === dept.id);

        const memberChips = deptMembers.length > 0
            ? deptMembers.map(m => `<span class="dept-member-chip">${escapeHtml(m.full_name)}</span>`).join('')
            : '<span class="text-muted" style="font-size:0.8rem;">Нет сотрудников — нажмите «Редактировать» чтобы добавить</span>';

        return `
            <div class="dept-card">
                <div class="dept-card-header">
                    <div class="dept-card-name">${escapeHtml(dept.name)}</div>
                    <div class="dept-card-actions">
                        <button class="btn btn-small btn-secondary" onclick="editDepartment('${dept.id}')">Редактировать</button>
                        <button class="btn-icon btn-icon-danger" onclick="deleteDepartment('${dept.id}')" title="Удалить">✕</button>
                    </div>
                </div>
                <div class="dept-card-meta">
                    ${headMember
                        ? `<span class="dept-head">Руководитель: ${escapeHtml(headMember.full_name)}</span>`
                        : '<span class="text-muted dept-head-empty">Нет руководителя</span>'}
                    <span class="dept-count">${deptMembers.length} чел.</span>
                </div>
                <div class="dept-members-list">${memberChips}</div>
            </div>
        `;
    }).join('');
}

function renderMembers(members, departments) {
    if (!members || members.length === 0) {
        return '<p class="text-muted">Нет сотрудников</p>';
    }

    const currentUser = JSON.parse(localStorage.getItem('user') || '{}');

    return '<div class="members-grid">' + members.map(member => {
        const dept = departments?.find(d => d.id === member.department_id);
        const displayId = member.username || member.email || 'Нет логина';
        const isCurrentUser = member.email === currentUser?.email || member.id === currentUser?.id;

        return `
            <div class="member-card-item">
                <div class="member-avatar">${escapeHtml((member.full_name || '?').charAt(0).toUpperCase())}</div>
                <div class="member-details">
                    <div class="member-name">${escapeHtml(member.full_name)}</div>
                    <div class="member-login">${escapeHtml(displayId)}</div>
                    <div class="member-badges">
                        <span class="role-badge role-${member.role}">${getRoleLabel(member.role)}</span>
                        ${dept ? `<span class="dept-badge">${escapeHtml(dept.name)}</span>` : ''}
                    </div>
                </div>
                ${!isCurrentUser && member.role !== 'owner' ? `
                <div class="member-actions-menu">
                    <select class="role-select" onchange="changeMemberRole('${viewingOrgId}', '${member.id}', this.value)">
                        <option value="admin" ${member.role === 'admin' ? 'selected' : ''}>Админ</option>
                        <option value="member" ${member.role === 'member' ? 'selected' : ''}>Участник</option>
                        <option value="viewer" ${member.role === 'viewer' ? 'selected' : ''}>Зритель</option>
                    </select>
                    <button class="btn-icon btn-icon-danger" onclick="removeMember('${viewingOrgId}', '${member.id}', '${escapeHtml(member.full_name)}')" title="Удалить">✕</button>
                </div>
                ` : ''}
            </div>
        `;
    }).join('') + '</div>';
}

function copyOrgLoginLink(accessCode) {
    const link = `${location.origin}/login/${accessCode}`;
    navigator.clipboard.writeText(link).catch(() => {});
    const btn = event.target;
    const orig = btn.textContent;
    btn.textContent = 'Скопировано!';
    setTimeout(() => { btn.textContent = orig; }, 2000);
}

// ============================================================
// Select Organization
// ============================================================

async function selectOrganization(orgId) {
    try {
        const response = await fetch(`/auth/select-organization/${orgId}`, {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
        });

        if (!response.ok) throw new Error('Failed to select organization');

        const data = await response.json();
        if (data.access_token) localStorage.setItem('access_token', data.access_token);
        if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token);

        location.reload();
    } catch (error) {
        console.error('Error selecting organization:', error);
    }
}

// ============================================================
// Member Management
// ============================================================

function showAddMemberForm() {
    if (!viewingOrgId) return;
    const modal = document.getElementById('addMemberModal');
    const form = document.getElementById('addMemberForm');
    form.reset();
    clearAllErrors();

    // Populate department dropdown
    const deptSelect = document.getElementById('memberDepartment');
    if (deptSelect && viewingOrgData?.departments) {
        deptSelect.innerHTML = '<option value="">Без отдела</option>';
        viewingOrgData.departments.forEach(d => {
            deptSelect.innerHTML += `<option value="${d.id}">${escapeHtml(d.name)}</option>`;
        });
    }

    modal.classList.add('active');
    document.getElementById('memberUsername')?.focus();
}

function closeAddMemberModal() {
    document.getElementById('addMemberModal').classList.remove('active');
}

async function submitAddMemberForm(e) {
    e.preventDefault();
    if (!viewingOrgId) return;

    const username = document.getElementById('memberUsername').value.trim();
    const password = document.getElementById('memberPassword').value.trim();
    const fullName = document.getElementById('memberFullName').value.trim();
    const role = document.getElementById('memberRole').value;
    const deptId = document.getElementById('memberDepartment')?.value || '';

    clearAllErrors();
    let hasError = false;

    if (!username || username.length < 2) {
        showFieldError('memberUsername', 'Минимум 2 символа'); hasError = true;
    }
    if (!password || password.length < 8) {
        showFieldError('memberPassword', 'Минимум 8 символов'); hasError = true;
    }
    if (!fullName) {
        showFieldError('memberFullName', 'Введите имя'); hasError = true;
    }
    if (hasError) return;

    try {
        const body = { username, password, full_name: fullName, role };
        const response = await fetch(`/organizations/${viewingOrgId}/add-member`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + localStorage.getItem('access_token')
            },
            body: JSON.stringify(body)
        });

        if (!response.ok) {
            const error = await response.json();
            const msg = typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail);
            throw new Error(msg);
        }

        const newMember = await response.json();

        // Assign to department if selected
        if (deptId && newMember.id) {
            await fetch(`/organizations/${viewingOrgId}/departments/${deptId}/members`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + localStorage.getItem('access_token')
                },
                body: JSON.stringify({ user_id: newMember.id })
            }).catch(() => {});
        }

        closeAddMemberModal();
        await viewOrganization(viewingOrgId);
    } catch (error) {
        showFieldError('memberUsername', error.message);
    }
}

async function changeMemberRole(orgId, userId, newRole) {
    try {
        const response = await fetch(`/organizations/${orgId}/members/${userId}/role`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + localStorage.getItem('access_token')
            },
            body: JSON.stringify({ role: newRole })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to change role');
        }

        await viewOrganization(orgId);
    } catch (error) {
        console.error('Error changing role:', error);
        await viewOrganization(orgId);
    }
}

async function removeMember(orgId, userId, memberName) {
    if (!confirm(`Удалить сотрудника «${memberName}» из организации?`)) return;

    try {
        const response = await fetch(`/organizations/${orgId}/members/${userId}`, {
            method: 'DELETE',
            headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
        });

        if (!response.ok) {
            const error = await response.json();
            const msg = typeof error.detail === 'string' ? error.detail
                : (error.detail?.detail || error.detail?.error || 'Ошибка удаления сотрудника');
            alert(msg);
            return;
        }

        await viewOrganization(orgId);
    } catch (error) {
        console.error('Error removing member:', error);
        alert('Не удалось удалить сотрудника. Проверьте подключение.');
    }
}

async function deleteOrganization(orgId, orgName) {
    if (!confirm(`Удалить организацию «${orgName}»?\n\nЭто действие необратимо — все данные будут деактивированы.`)) return;

    try {
        const response = await fetch(`/organizations/${orgId}`, {
            method: 'DELETE',
            headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
        });

        if (!response.ok) {
            const error = await response.json();
            const msg = typeof error.detail === 'string' ? error.detail
                : (error.detail?.detail || error.detail?.error || 'Ошибка удаления организации');
            alert(msg);
            return;
        }

        // Go back to list and reload
        backToOrganizations();
        await loadOrganizationsForTab();
    } catch (error) {
        console.error('Error deleting organization:', error);
        alert('Не удалось удалить организацию. Проверьте подключение.');
    }
}

// ============================================================
// Department Management
// ============================================================

function showCreateDeptForm() {
    if (!viewingOrgId) return;
    const modal = document.getElementById('createDeptModal');
    const form = document.getElementById('createDeptForm');
    form.reset();

    // Populate head selector with current members
    const headSelect = document.getElementById('deptHead');
    if (headSelect && viewingOrgData?.members) {
        headSelect.innerHTML = '<option value="">Без руководителя</option>';
        viewingOrgData.members.forEach(m => {
            headSelect.innerHTML += `<option value="${m.id}">${escapeHtml(m.full_name)}</option>`;
        });
    }

    modal.classList.add('active');
    document.getElementById('deptName')?.focus();
}

function closeCreateDeptModal() {
    document.getElementById('createDeptModal').classList.remove('active');
}

async function submitCreateDeptForm(e) {
    e.preventDefault();
    if (!viewingOrgId) return;

    const name = document.getElementById('deptName').value.trim();
    const headUserId = document.getElementById('deptHead').value || null;

    if (!name) return;

    try {
        const response = await fetch(`/organizations/${viewingOrgId}/departments`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + localStorage.getItem('access_token')
            },
            body: JSON.stringify({ name, head_user_id: headUserId })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create department');
        }

        closeCreateDeptModal();
        await viewOrganization(viewingOrgId);
    } catch (error) {
        console.error('Error creating department:', error);
    }
}

function editDepartment(deptId) {
    const dept = viewingOrgData?.departments?.find(d => d.id === deptId);
    if (!dept) return;

    const modal = document.getElementById('editDeptModal');
    if (!modal) return;

    // Set current dept id
    modal.dataset.deptId = deptId;

    // Fill name
    const nameInput = document.getElementById('editDeptName');
    if (nameInput) nameInput.value = dept.name;

    // Fill head selector
    const headSelect = document.getElementById('editDeptHead');
    if (headSelect && viewingOrgData?.members) {
        headSelect.innerHTML = '<option value="">Без руководителя</option>';
        viewingOrgData.members.forEach(m => {
            const sel = m.id === dept.head_user_id ? 'selected' : '';
            headSelect.innerHTML += `<option value="${m.id}" ${sel}>${escapeHtml(m.full_name)}</option>`;
        });
    }

    // Fill member checkboxes — only regular members/viewers, exclude head/owner/admin
    const membersList = document.getElementById('editDeptMembersList');
    if (membersList && viewingOrgData?.members) {
        const deptMemberIds = new Set(
            viewingOrgData.members.filter(m => m.department_id === deptId).map(m => m.id)
        );

        // Eligible: not the head, not owner, not admin (they manage, not belong to depts as regular staff)
        const eligibleMembers = viewingOrgData.members.filter(m =>
            m.id !== dept.head_user_id &&
            m.role !== 'owner' &&
            m.role !== 'admin'
        );

        if (eligibleMembers.length === 0) {
            membersList.innerHTML = '<p class="text-muted" style="padding:12px;font-size:0.85rem;">Нет доступных сотрудников для добавления в отдел</p>';
        } else {
            membersList.innerHTML = eligibleMembers.map(m => `
                <label class="dept-member-checkbox">
                    <input type="checkbox" value="${m.id}" ${deptMemberIds.has(m.id) ? 'checked' : ''}>
                    <span>${escapeHtml(m.full_name)}</span>
                    <span style="color:var(--text-2);font-size:0.78rem;margin-left:auto;">${m.username || m.email || ''}</span>
                </label>
            `).join('');
        }
    }

    modal.classList.add('active');
    if (nameInput) nameInput.focus();
}

async function submitEditDeptForm(e) {
    e.preventDefault();
    const modal = document.getElementById('editDeptModal');
    const deptId = modal?.dataset.deptId;
    if (!deptId || !viewingOrgId) return;

    const name = document.getElementById('editDeptName').value.trim();
    const headUserId = document.getElementById('editDeptHead').value || null;

    if (!name) return;

    // Collect selected member ids
    const checkedBoxes = document.querySelectorAll('#editDeptMembersList input[type=checkbox]:checked');
    const selectedMemberIds = Array.from(checkedBoxes).map(cb => cb.value);

    const token = localStorage.getItem('access_token');
    const headers = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token };

    try {
        // 1. Update dept name and head
        const res = await fetch(`/organizations/${viewingOrgId}/departments/${deptId}`, {
            method: 'PUT',
            headers,
            body: JSON.stringify({ name, head_user_id: headUserId })
        });
        if (!res.ok) {
            const err = await res.json();
            alert(typeof err.detail === 'string' ? err.detail : (err.detail?.detail || 'Ошибка'));
            return;
        }

        // 2. Sync members: first remove all existing, then add selected
        //    Get current dept members
        const currentDeptMembers = (viewingOrgData?.members || []).filter(m => m.department_id === deptId);
        const currentIds = new Set(currentDeptMembers.map(m => m.id));
        const targetIds = new Set(selectedMemberIds);

        // Remove members no longer selected
        for (const id of currentIds) {
            if (!targetIds.has(id)) {
                await fetch(`/organizations/${viewingOrgId}/departments/${deptId}/members/${id}`, {
                    method: 'DELETE', headers: { 'Authorization': 'Bearer ' + token }
                }).catch(() => {});
            }
        }

        // Add newly selected members
        for (const id of targetIds) {
            if (!currentIds.has(id)) {
                await fetch(`/organizations/${viewingOrgId}/departments/${deptId}/members`, {
                    method: 'POST', headers,
                    body: JSON.stringify({ user_id: id })
                }).catch(() => {});
            }
        }

        closeEditDeptModal();
        await viewOrganization(viewingOrgId);
    } catch (error) {
        console.error('Error updating department:', error);
        alert('Ошибка сохранения отдела');
    }
}

function closeEditDeptModal() {
    document.getElementById('editDeptModal')?.classList.remove('active');
}

async function deleteDepartment(deptId) {
    if (!confirm('Удалить этот отдел?')) return;

    try {
        await fetch(`/organizations/${viewingOrgId}/departments/${deptId}`, {
            method: 'DELETE',
            headers: { 'Authorization': 'Bearer ' + localStorage.getItem('access_token') }
        });
        await viewOrganization(viewingOrgId);
    } catch (error) {
        console.error('Error deleting department:', error);
    }
}

// ============================================================
// Back to list
// ============================================================

function backToOrganizations() {
    viewingOrgId = null;
    viewingOrgData = null;
    document.getElementById('organizationDetailView').style.display = 'none';
    document.getElementById('organizationListView').style.display = 'block';
}
