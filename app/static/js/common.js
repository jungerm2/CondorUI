// Query selectors helpers
const $ = selector => document.querySelector(selector);
const $$ = selector => document.querySelectorAll(selector);

// Global State / Configurations
const API_BASE = '/api';

// Toast Notifications
function toast(message, type = 'info') {
    const container = $('#toast-container');
    if (!container) return;

    const toastEl = document.createElement('div');
    toastEl.className = `toast toast-${type}`;
    toastEl.textContent = message;

    container.appendChild(toastEl);

    // Fade in
    setTimeout(() => toastEl.classList.add('visible'), 10);

    // Remove after 3 seconds
    setTimeout(() => {
        toastEl.classList.remove('visible');
        setTimeout(() => toastEl.remove(), 300);
    }, 3000);
}

// API client wrapper
async function api(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };

    try {
        const response = await fetch(url, { ...options, headers });
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || `HTTP error! status: ${response.status}`);
        }
        return data;
    } catch (error) {
        console.error(`API Error (${endpoint}):`, error);
        throw error;
    }
}

// Common Formatting Helpers
function formatDate(timestamp) {
    if (!timestamp) return '—';
    const date = new Date(timestamp * 1000);
    return date.toLocaleString();
}

function formatDuration(seconds) {
    if (!seconds && seconds !== 0) return '—';
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    if (mins < 60) return `${mins}m ${secs}s`;
    const hours = Math.floor(mins / 60);
    const remMins = mins % 60;
    return `${hours}h ${remMins}m`;
}

function getStatusClass(statusCode) {
    switch (parseInt(statusCode)) {
        case 1: return 'status-idle';
        case 2: return 'status-running';
        case 3: return 'status-removed';
        case 4: return 'status-completed';
        case 5: return 'status-held';
        case 6: return 'status-transferring';
        default: return 'status-unknown';
    }
}

function getStatusName(statusCode) {
    switch (parseInt(statusCode)) {
        case 1: return 'Idle';
        case 2: return 'Running';
        case 3: return 'Removed';
        case 4: return 'Completed';
        case 5: return 'Held';
        case 6: return 'Transferring';
        default: return 'Unknown';
    }
}

function basename(path) {
    if (!path) return '';
    return path.split(/[/\\]/).pop();
}

// Theme Management
function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);

    const toggle = $('#theme-toggle');
    if (toggle) {
        toggle.addEventListener('click', () => {
            const current = document.documentElement.getAttribute('data-theme');
            const newTheme = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
        });
    }
}

// Connection Status Monitor
function initConnectionMonitor() {
    const statusDot = $('.connection-status .status-dot');
    const statusText = $('.connection-status .status-text');

    async function checkStatus() {
        try {
            await api('/stats');
            statusDot.className = 'status-dot status-connected';
            statusText.textContent = 'Connected';
        } catch (error) {
            statusDot.className = 'status-dot status-disconnected';
            statusText.textContent = 'Disconnected';
        }
    }

    checkStatus();
    setInterval(checkStatus, 10000);
}

// Run basic initializations on DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initConnectionMonitor();
});
