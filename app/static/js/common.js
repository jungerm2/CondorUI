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

// API client wrapper with timeout
async function api(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };

    // Add a 30-second timeout to prevent hanging
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);

    try {
        const response = await fetch(url, {
            ...options,
            headers,
            signal: options.signal || controller.signal,
        });
        clearTimeout(timeoutId);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || `HTTP error! status: ${response.status}`);
        }
        return data;
    } catch (error) {
        clearTimeout(timeoutId);
        if (error.name === 'AbortError') {
            console.error(`API Timeout (${endpoint}): Request timed out after 30s`);
            throw new Error('Request timed out. The server may be unavailable.');
        }
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
    let savedTheme = localStorage.getItem('theme');
    if (!savedTheme) {
        savedTheme = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }
    document.documentElement.classList.toggle('light-theme', savedTheme === 'light');

    const toggle = $('#theme-toggle');
    if (toggle) {
        toggle.addEventListener('click', () => {
            const isLight = document.documentElement.classList.contains('light-theme');
            document.documentElement.classList.toggle('light-theme', !isLight);
            localStorage.setItem('theme', isLight ? 'dark' : 'light');
        });
    }
}

// Connection Status Monitor
function initConnectionMonitor() {
    const statusDot = $('.connection-status .status-dot');
    const statusText = $('.connection-status .status-text');

    async function checkStatus() {
        try {
            const response = await fetch('/api/health');
            if (response.ok) {
                statusDot.className = 'status-dot status-connected';
                statusText.textContent = 'Connected';
            } else {
                throw new Error('Not OK');
            }
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
