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

// Simple escaping to prevent XSS in innerHTML
function escHtml(str) {
    if (str == null) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

// Common Formatting Helpers
function formatDate(timestamp) {
    if (!timestamp) return '—';
    const date = new Date(timestamp * 1000);
    return date.toLocaleString();
}

function formatDuration(seconds) {
    if (!seconds && seconds !== 0) return '—';
    if (seconds === 0) return '—';
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    if (mins < 60) return `${mins}m ${secs}s`;
    const hours = Math.floor(mins / 60);
    const remMins = mins % 60;
    return `${hours}h ${remMins}m`;
}

/**
 * Format a byte/size value into a human-readable string.
 * Accepts a value in KB and optionally the unit the value is in.
 * Returns a string like "1.5 GB", "800 MB", "4.2 KB", etc.
 */
function formatBytes(value, inputUnit = 'KB') {
    if (value === undefined || value === null || value === '—') return '—';
    const num = parseFloat(value);
    if (isNaN(num) || num === 0) return '0';

    // Normalize to bytes
    const unitLower = (inputUnit || '').toLowerCase();
    let bytes = num;
    if (unitLower === 'kb') bytes = num * 1024;
    else if (unitLower === 'mb') bytes = num * 1024 * 1024;
    else if (unitLower === 'gb') bytes = num * 1024 * 1024 * 1024;
    else if (unitLower === 'tb') bytes = num * 1024 * 1024 * 1024 * 1024;
    // If no unit or unknown, assume KB (HTCondor default)
    else bytes = num * 1024;

    const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
    let unitIndex = 0;
    let size = bytes;

    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex++;
    }

    return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

/**
 * Format memory value — accepts any input (e.g., "1 GB", "1024", "1024 MB")
 * and returns a human-readable string.
 */
function formatMemory(value) {
    if (!value || value === '—') return '—';
    const str = String(value);
    // Try to match "number unit" pattern
    const match = str.match(/^([\d.]+)\s*(GB|MB|KB|B)?$/i);
    if (match) {
        const num = parseFloat(match[1]);
        const unit = (match[2] || '').toUpperCase();
        if (unit === 'GB') return `${num} GB`;
        if (unit === 'MB') return `${num} MB`;
        if (unit === 'KB') return `${num} KB`;
        if (unit === 'B') return `${num} B`;
        // No unit — assume MB for memory
        return formatBytes(num, 'MB');
    }
    return str;
}

/**
 * Format disk value — similar to formatMemory but assumes KB by default.
 */
function formatDisk(value) {
    if (!value || value === '—') return '—';
    const str = String(value);
    const match = str.match(/^([\d.]+)\s*(GB|MB|KB|B)?$/i);
    if (match) {
        const num = parseFloat(match[1]);
        const unit = (match[2] || '').toUpperCase();
        if (unit === 'GB') return `${num} GB`;
        if (unit === 'MB') return `${num} MB`;
        if (unit === 'KB') return `${num} KB`;
        if (unit === 'B') return `${num} B`;
        // No unit — assume KB for disk
        return formatBytes(num, 'KB');
    }
    return str;
}

/**
 * Return the executable or shell command for display.
 * If Args is provided, appends it to the command.
 */
function formatCommand(cmd, args) {
    const name = basename(cmd || '');
    if (!name) return '—';
    if (args) return `${name} ${args}`;
    return name;
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
    const container = $('.connection-status');
    const statusDot = container ? container.querySelector('.status-dot') : null;
    const statusText = container ? container.querySelector('.status-text') : null;

    if (!container || !statusDot || !statusText) return;

    async function checkStatus() {
        try {
            const response = await fetch('/api/health');
            if (response.ok) {
                container.classList.remove('disconnected');
                container.classList.add('connected');
                statusText.textContent = 'Connected';
            } else {
                throw new Error('Not OK');
            }
        } catch (error) {
            container.classList.remove('connected');
            container.classList.add('disconnected');
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