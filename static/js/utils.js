/**
 * VOICEcheck - Shared Utility Functions
 * Common functions used across auth pages, org pages, and main app.
 */

// Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Password visibility toggle
function togglePassword(inputId) {
    const input = document.getElementById(inputId);
    const btn = input.nextElementSibling;
    if (input.type === 'password') {
        input.type = 'text';
        btn.textContent = 'Скрыть';
    } else {
        input.type = 'password';
        btn.textContent = 'Показать';
    }
}

// Show message banner
function showMessage(text, type = 'error') {
    const msg = document.getElementById('authMessage');
    if (!msg) return;
    msg.textContent = text;
    msg.className = 'auth-message show ' + type;
}

// Hide message banner
function hideMessage() {
    const msg = document.getElementById('authMessage');
    if (!msg) return;
    msg.className = 'auth-message';
}

// Show field-level error
function showFieldError(fieldId, text) {
    const field = document.getElementById(fieldId);
    const error = document.getElementById(fieldId + 'Error');
    if (field) field.classList.add('error');
    if (error) {
        error.textContent = text;
        error.classList.add('show');
        error.style.display = 'block';
    }
}

// Clear field-level error
function clearFieldError(fieldId) {
    const field = document.getElementById(fieldId);
    const error = document.getElementById(fieldId + 'Error');
    if (field) field.classList.remove('error');
    if (error) {
        error.classList.remove('show');
        error.style.display = 'none';
    }
}

// Clear all form errors
function clearAllErrors() {
    document.querySelectorAll('.form-input').forEach(input => {
        input.classList.remove('error');
    });
    document.querySelectorAll('.form-error, .error-message').forEach(error => {
        error.classList.remove('show');
        error.style.display = 'none';
    });
}

// Set button loading state
function setButtonLoading(btnId, loading, defaultText) {
    const btn = document.getElementById(btnId);
    const text = document.getElementById(btnId + 'Text');
    if (!btn) return;

    if (loading) {
        btn.disabled = true;
        if (text) text.innerHTML = '<span class="spinner"></span>';
    } else {
        btn.disabled = false;
        if (text) text.textContent = defaultText || 'Отправить';
    }
}

// Logout
function logout() {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user');
    localStorage.removeItem('current_org');
    window.location.href = '/static/auth.html';
}

// Copy text to clipboard with visual feedback
async function copyToClipboard(text, feedbackEl) {
    try {
        await navigator.clipboard.writeText(text);
    } catch {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
    }
    if (feedbackEl) {
        const original = feedbackEl.textContent;
        feedbackEl.textContent = 'Скопировано!';
        setTimeout(() => { feedbackEl.textContent = original; }, 2000);
    }
}
