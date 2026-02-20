/**
 * API Client with Authentication
 *
 * Provides methods for making authenticated API requests.
 * Handles token refresh and 401 responses.
 */

const API_BASE = window.location.origin;

class APIClient {
    constructor() {
        this.token = localStorage.getItem('access_token');
        this.refreshToken = localStorage.getItem('refresh_token');
    }

    /**
     * Get authorization header
     */
    getAuthHeader() {
        return this.token ? { 'Authorization': `Bearer ${this.token}` } : {};
    }

    /**
     * Make an API request
     */
    async request(method, path, data = null) {
        const headers = {
            'Content-Type': 'application/json',
            ...this.getAuthHeader()
        };

        const config = {
            method,
            headers
        };

        if (data) {
            config.body = JSON.stringify(data);
        }

        let response = await fetch(API_BASE + path, config);

        // Handle 401 - try to refresh token
        if (response.status === 401 && this.refreshToken) {
            const refreshed = await this.refreshAccessToken();
            if (refreshed) {
                // Retry original request with new token
                headers['Authorization'] = `Bearer ${this.token}`;
                config.headers = headers;
                response = await fetch(API_BASE + path, config);
            }
        }

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new APIError(error.detail || error.message || 'Request failed', response.status);
        }

        // For 204 No Content
        if (response.status === 204) {
            return null;
        }

        return response.json();
    }

    /**
     * Refresh access token
     */
    async refreshAccessToken() {
        if (!this.refreshToken) return false;

        try {
            const response = await fetch(API_BASE + '/auth/refresh', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: this.refreshToken })
            });

            if (!response.ok) {
                // Refresh failed - clear tokens
                this.clearTokens();
                return false;
            }

            const data = await response.json();
            this.token = data.access_token;
            this.refreshToken = data.refresh_token;
            localStorage.setItem('access_token', this.token);
            localStorage.setItem('refresh_token', this.refreshToken);
            return true;

        } catch (err) {
            this.clearTokens();
            return false;
        }
    }

    /**
     * Clear all tokens
     */
    clearTokens() {
        this.token = null;
        this.refreshToken = null;
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user');
        localStorage.removeItem('current_org');
    }

    /**
     * GET request
     */
    async get(path, params = null) {
        let url = path;
        if (params) {
            const searchParams = new URLSearchParams(params);
            url += '?' + searchParams.toString();
        }
        return this.request('GET', url);
    }

    /**
     * POST request
     */
    async post(path, data) {
        return this.request('POST', path, data);
    }

    /**
     * PUT request
     */
    async put(path, data) {
        return this.request('PUT', path, data);
    }

    /**
     * PATCH request
     */
    async patch(path, data) {
        return this.request('PATCH', path, data);
    }

    /**
     * DELETE request
     */
    async delete(path) {
        return this.request('DELETE', path);
    }

    /**
     * Check if authenticated
     */
    isAuthenticated() {
        return !!this.token;
    }

    /**
     * Get current user
     */
    getCurrentUser() {
        const userStr = localStorage.getItem('user');
        return userStr ? JSON.parse(userStr) : null;
    }

    /**
     * Get current organization
     */
    getCurrentOrganization() {
        const orgStr = localStorage.getItem('current_org');
        return orgStr ? JSON.parse(orgStr) : null;
    }

    /**
     * Logout
     */
    async logout() {
        try {
            if (this.token) {
                await fetch(API_BASE + '/auth/logout', {
                    method: 'POST',
                    headers: this.getAuthHeader()
                });
            }
        } catch (err) {
            // Ignore logout errors
        } finally {
            this.clearTokens();
            window.location.href = '/static/auth.html';
        }
    }
}

class APIError extends Error {
    constructor(message, status) {
        super(message);
        this.name = 'APIError';
        this.status = status;
    }
}

// Create global API client
const api = new APIClient();

// Check auth on page load
window.addEventListener('load', async () => {
    const isAuthPage = window.location.pathname.includes('auth.html') ||
                       window.location.pathname.includes('select-organization.html');

    if (!isAuthPage && !api.isAuthenticated()) {
        // Not authenticated and not on auth page - redirect to login
        // But only if auth is enabled on the server
        try {
            const response = await fetch(API_BASE + '/health');
            if (response.ok) {
                const health = await response.json();
                if (health.database === 'available') {
                    // DB is available - check if auth is enabled
                    // For now, assume auth is required
                    window.location.href = '/static/auth.html';
                }
            }
        } catch (err) {
            // Can't check - continue normally
        }
    }
});
