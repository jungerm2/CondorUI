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

// ---------------------------------------------------------------------------
// Shared QEdit Dialog — reusable across history and job_details pages
// ---------------------------------------------------------------------------

const COMMON_QEDIT_ATTRS = [
    { attr: 'request_disk', desc: 'Request Disk (KB)' },
    { attr: 'request_memory', desc: 'Request Memory (MB)' },
    { attr: 'request_cpus', desc: 'Request CPUs' },
    { attr: 'JobLeaseDuration', desc: 'Job Lease Duration (sec)' },
    { attr: 'Priority', desc: 'Priority' },
    { attr: 'hold_reason', desc: 'Hold Reason' },
    { attr: 'job_prio', desc: 'Job Priority' },
    { attr: 'nice_user', desc: 'Nice User (bool)' },
    { attr: 'PeriodicHold', desc: 'Periodic Hold (expr)' },
    { attr: 'PeriodicRelease', desc: 'Periodic Release (expr)' },
    { attr: 'PeriodicRemove', desc: 'Periodic Remove (expr)' },
];

/**
 * Open a shared qedit modal for editing ClassAd attributes on one or more jobs.
 *
 * @param {Array<{clusterId: number, procId: number}>} jobs - Jobs to edit.
 * @param {Object} options
 * @param {Function} [options.onComplete] - Called after successful edit.
 * @param {boolean} [options.autoRelease=true] - Whether to release held jobs after edit.
 */
function openQeditDialog(jobs, options = {}) {
    const { onComplete, autoRelease = true } = options;
    if (!jobs || jobs.length === 0) {
        toast('No jobs selected for editing', 'warning');
        return;
    }

    const jobLabel = jobs.length === 1
        ? `${jobs[0].clusterId}.${jobs[0].procId}`
        : `${jobs.length} jobs`;

    // Create modal
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay active';
    overlay.id = 'qedit-modal';
    overlay.innerHTML = `
        <div class="modal modal-wide">
            <div class="modal-header">
                <h2>Edit Job Attributes</h2>
                <button class="btn btn-ghost btn-sm modal-close-btn" style="padding: 4px 8px;">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
                        <line x1="18" y1="6" x2="6" y2="18" />
                        <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                </button>
            </div>
            <div class="modal-body">
                <p style="margin-bottom: 16px; color: var(--text-secondary);">
                    Edit ClassAd attributes for <strong>${escHtml(jobLabel)}</strong>.
                    Changes take effect immediately via <code>condor_qedit</code>.
                </p>
                <div id="qedit-rows-container">
                    <div class="qedit-row">
                        <select class="form-input qedit-attr-select" style="flex: 1;">
                            <option value="">— Select attribute —</option>
                            ${COMMON_QEDIT_ATTRS.map(a =>
                                `<option value="${a.attr}">${a.attr} — ${escHtml(a.desc)}</option>`
                            ).join('')}
                        </select>
                        <input type="text" class="form-input qedit-value-input" placeholder="New value" style="flex: 1;">
                        <button class="btn btn-ghost btn-sm qedit-remove-row" style="padding: 4px 8px; flex-shrink: 0;" title="Remove row">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                                <line x1="18" y1="6" x2="6" y2="18" />
                                <line x1="6" y1="6" x2="18" y2="18" />
                            </svg>
                        </button>
                    </div>
                </div>
                <button class="btn btn-ghost" id="qedit-add-row-btn" style="margin-top: 8px; border: 1px dashed var(--border-color); width: 100%;">
                    + Add another attribute
                </button>
                <p style="font-size: 0.8rem; color: var(--text-muted); margin-top: 12px;">
                    Common edits: <code>request_disk</code> (KB), <code>request_memory</code> (MB), <code>request_cpus</code>.
                </p>
                <div style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px;">
                    <button class="btn btn-ghost modal-close-btn">Cancel</button>
                    <button class="btn btn-primary" id="qedit-apply-btn">Apply Changes</button>
                </div>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    // --- Event binding ---
    const closeBtns = overlay.querySelectorAll('.modal-close-btn');
    const applyBtn = overlay.querySelector('#qedit-apply-btn');
    const addRowBtn = overlay.querySelector('#qedit-add-row-btn');
    const rowsContainer = overlay.querySelector('#qedit-rows-container');

    function closeModal() { overlay.remove(); }
    closeBtns.forEach(btn => btn.addEventListener('click', closeModal));
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(); });

    // Add a new editable row
    function addRow(attrValue = '', valueValue = '') {
        const row = document.createElement('div');
        row.className = 'qedit-row';
        row.innerHTML = `
            <select class="form-input qedit-attr-select" style="flex: 1;">
                <option value="">— Select attribute —</option>
                ${COMMON_QEDIT_ATTRS.map(a =>
                    `<option value="${a.attr}" ${a.attr === attrValue ? 'selected' : ''}>${a.attr} — ${escHtml(a.desc)}</option>`
                ).join('')}
            </select>
            <input type="text" class="form-input qedit-value-input" placeholder="New value" value="${escHtml(valueValue)}" style="flex: 1;">
            <button class="btn btn-ghost btn-sm qedit-remove-row" style="padding: 4px 8px; flex-shrink: 0;" title="Remove row">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
            </button>
        `;
        rowsContainer.appendChild(row);

        const removeBtn = row.querySelector('.qedit-remove-row');
        removeBtn.addEventListener('click', () => {
            if (rowsContainer.children.length > 1) {
                row.remove();
            } else {
                toast('At least one attribute row is required', 'warning');
            }
        });

        // Focus the value input
        const valInput = row.querySelector('.qedit-value-input');
        setTimeout(() => valInput.focus(), 50);
    }

    addRowBtn.addEventListener('click', () => addRow());

    // Remove-row handlers for initial row
    const initialRemoveBtns = overlay.querySelectorAll('.qedit-remove-row');
    initialRemoveBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const row = btn.closest('.qedit-row');
            if (rowsContainer.children.length > 1) {
                row.remove();
            } else {
                toast('At least one attribute row is required', 'warning');
            }
        });
    });

    // Apply
    applyBtn.addEventListener('click', async () => {
        const rows = overlay.querySelectorAll('.qedit-row');
        const edits = [];
        rows.forEach(row => {
            const attr = row.querySelector('.qedit-attr-select').value.trim();
            const value = row.querySelector('.qedit-value-input').value.trim();
            if (attr && value) {
                edits.push({ attr, value });
            }
        });

        if (edits.length === 0) {
            toast('Please fill in at least one attribute and value', 'warning');
            return;
        }

        applyBtn.disabled = true;
        applyBtn.textContent = 'Applying...';

        try {
            // Apply each edit to each job
            for (const job of jobs) {
                for (const edit of edits) {
                    await api('/qedit', {
                        method: 'POST',
                        body: JSON.stringify({
                            cluster_id: job.clusterId,
                            proc_id: job.procId || 0,
                            attr: edit.attr,
                            value: edit.value,
                        })
                    });
                }
                // Auto-release held jobs after edit
                if (autoRelease) {
                    try {
                        await api(`/jobs/${job.clusterId}.${job.procId || 0}/release`, { method: 'POST' });
                    } catch {
                        // Release may fail if job wasn't held; that's fine
                    }
                }
            }

            toast(`Updated ${edits.length} attribute(s) on ${jobs.length} job(s)`);
            closeModal();
            if (onComplete) onComplete();
        } catch (err) {
            toast(`Failed to edit job: ${err.message}`, 'error');
            applyBtn.disabled = false;
            applyBtn.textContent = 'Apply Changes';
        }
    });

    // Allow Enter key to submit
    overlay.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.target.closest('.qedit-row')) {
            applyBtn.click();
        }
    });
}

// Run basic initializations on DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initConnectionMonitor();
});
