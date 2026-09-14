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

    // Remove after 5 seconds
    setTimeout(() => {
        toastEl.classList.remove('visible');
        setTimeout(() => toastEl.remove(), 300);
    }, 5000);
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

// Modal helpers (shared across pages)
function openModal(id) {
    document.getElementById(id).classList.add('active');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('active');
}

// ---------------------------------------------------------------------------
// Shared Sort & Search Utilities (DRY for table-based pages)
// ---------------------------------------------------------------------------

/**
 * Sort a copy of the data array by the given field, using a getter function.
 *
 * @param {Array} data - The data to sort.
 * @param {string} field - The field name (used by getValueFn).
 * @param {boolean} asc - Whether to sort ascending.
 * @param {Function} getValueFn - Function(item, field) => sortable value.
 * @returns {Array} A new sorted array.
 */
function sortData(data, field, asc, getValueFn) {
    const sorted = [...data];
    sorted.sort((a, b) => {
        const va = getValueFn(a, field);
        const vb = getValueFn(b, field);
        if (va < vb) return asc ? -1 : 1;
        if (va > vb) return asc ? 1 : -1;
        return 0;
    });
    return sorted;
}

/**
 * Filter data array by a text query, checking against an array of getter functions.
 *
 * @param {Array} data - The data to filter.
 * @param {string} query - The user's search query.
 * @param {Array<Function>} getterFns - Array of (item) => string getters to search across.
 * @returns {Array} Filtered array.
 */
function filterData(data, query, getterFns) {
    if (!query || !query.trim()) return data;
    const q = query.toLowerCase().trim();
    return data.filter(item => {
        return getterFns.some(fn => {
            const val = fn(item);
            return val != null && String(val).toLowerCase().includes(q);
        });
    });
}

/**
 * Update sort arrow indicators (▲/▼) on sortable table headers.
 *
 * @param {HTMLElement} table - The <table> element.
 * @param {string} sortField - The currently active sort field.
 * @param {boolean} sortAsc - Whether currently sorting ascending.
 */
function updateSortArrows(table, sortField, sortAsc) {
    if (!table) return;
    table.querySelectorAll('thead th.sortable').forEach(th => {
        const arrow = th.querySelector('.sort-arrow');
        if (!arrow) return;
        const field = th.dataset.sort;
        if (field === sortField) {
            arrow.textContent = sortAsc ? ' ▲' : ' ▼';
        } else {
            arrow.textContent = '';
        }
    });
}

// Common Formatting Helpers
function formatDate(timestamp) {
    if (!timestamp) return '—';
    const date = new Date(timestamp * 1000);
    return date.toLocaleString();
}

/**
 * Format a date from an ISO string (e.g., from the API).
 * Falls back to formatDate(timestamp) if not an ISO string.
 */
function formatDateIso(isoStr) {
    if (!isoStr) return '—';
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleString();
}

/**
 * Format a file size in bytes to a human-readable string.
 * Alias for formatBytes() that takes the value directly.
 */
function formatFileSize(bytes) {
    if (!bytes && bytes !== 0) return '—';
    if (bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    let size = bytes;
    while (size >= 1024 && i < units.length - 1) {
        size /= 1024;
        i++;
    }
    return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatDuration(seconds) {
    if (!seconds && seconds !== 0) return '—';
    if (seconds <= 0) return '—';
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
 * Shows the full command path with arguments.
 * If Args is provided, appends it to the command.
 */
function formatCommand(cmd, args) {
    if (!cmd) return '—';
    const fullCmd = cmd.trim();
    if (args) return `${fullCmd} ${args}`;
    return fullCmd;
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

// Extended list of ClassAd attributes that are commonly editable via
// `condor_qedit`. Used purely as autocomplete suggestions in advanced mode —
// the backend accepts any attribute name.
const ADVANCED_QEDIT_ATTRS = [
    { attr: 'Cmd', desc: 'Executable path' },
    { attr: 'Args', desc: 'Command arguments' },
    { attr: 'BatchName', desc: 'Batch name' },
    { attr: 'Rank', desc: 'Preference expression' },
    { attr: 'Requirements', desc: 'Match expression' },
    { attr: 'ConcurrencyLimits', desc: 'Concurrency limits' },
    { attr: 'JobPrio', desc: 'Job priority' },
    { attr: 'MaxJobRetirementTime', desc: 'Max retirement time (sec)' },
    { attr: 'JobMaxVacateTime', desc: 'Max vacate time (sec)' },
    { attr: 'JobLeaseDuration', desc: 'Job lease duration (sec)' },
    { attr: 'PeriodicHold', desc: 'Periodic hold (expr)' },
    { attr: 'PeriodicRelease', desc: 'Periodic release (expr)' },
    { attr: 'PeriodicRemove', desc: 'Periodic remove (expr)' },
    { attr: 'PeriodicRemoveReason', desc: 'Periodic remove reason' },
    { attr: 'RequestCpus', desc: 'Request CPUs' },
    { attr: 'RequestMemory', desc: 'Request memory (MB)' },
    { attr: 'RequestDisk', desc: 'Request disk (KB)' },
    { attr: 'RequestGpus', desc: 'Request GPUs' },
    { attr: 'RunAsOwner', desc: 'Run as owner (bool)' },
    { attr: 'NiceUser', desc: 'Nice user (bool)' },
    { attr: 'AcctGroup', desc: 'Accounting group' },
    { attr: 'AcctGroupUser', desc: 'Accounting group user' },
    { attr: 'ImageSize', desc: 'Image size (KB)' },
    { attr: 'DiskUsage', desc: 'Disk usage (KB)' },
    { attr: 'WantHold', desc: 'Want hold (bool)' },
    { attr: 'UserLog', desc: 'User log path' },
    { attr: 'HoldReason', desc: 'Hold reason' },
];

/**
 * Open a shared qedit modal for editing ClassAd attributes on one or more jobs.
 *
 * Basic mode presents a curated dropdown of common attributes. Advanced mode
 * lets the user type any ClassAd attribute name, with autocomplete suggestions
 * drawn from the job's live ClassAd (when supplied) plus a list of known
 * edit-able attributes.
 *
 * @param {Array<{clusterId: number, procId: number}>} jobs - Jobs to edit.
 * @param {Object} options
 * @param {Function} [options.onComplete] - Called after successful edit.
 * @param {boolean} [options.autoRelease=true] - Whether to release held jobs after edit.
 * @param {Object} [options.classad] - Live ClassAd of a job, used to seed advanced
 *   suggestions and show current values.
 * @param {boolean} [options.advancedDefault=false] - Start with advanced mode enabled.
 */
function openQeditDialog(jobs, options = {}) {
    const {
        onComplete,
        autoRelease = true,
        classad = null,
        advancedDefault = false,
    } = options;
    if (!jobs || jobs.length === 0) {
        toast('No jobs selected for editing', 'warning');
        return;
    }

    const jobLabel = jobs.length === 1
        ? `${jobs[0].clusterId}.${jobs[0].procId}`
        : `${jobs.length} jobs`;

    // Advanced-mode autocomplete: live ClassAd fields first, then known-editable
    // attribute names, deduplicated and sorted.
    const classadKeys = (classad && typeof classad === 'object') ? Object.keys(classad) : [];
    const suggestionNames = [...new Set([
        ...classadKeys,
        ...ADVANCED_QEDIT_ATTRS.map(a => a.attr),
    ])].sort();

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
                <p style="margin-bottom: 12px; color: var(--text-secondary);">
                    Edit ClassAd attributes for <strong>${escHtml(jobLabel)}</strong>.
                    Changes take effect immediately via <code>condor_qedit</code>.
                </p>
                <label class="toggle-label" id="qedit-advanced-label" style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 0.8rem; color: var(--text-secondary); user-select: none; margin-bottom: 16px;">
                    <input type="checkbox" class="toggle-input" id="qedit-advanced-toggle">
                    <span class="toggle-switch"></span>
                    Advanced mode — edit any ClassAd attribute
                </label>
                <div id="qedit-advanced-note" style="display: none; margin-bottom: 16px; padding: 10px 12px; border: 1px solid var(--border-color); border-radius: var(--radius-sm); font-size: 0.78rem; color: var(--text-muted);">
                    Advanced attributes are sent to <code>condor_qedit</code> as-is and are not
                    validated against the common list. Use with care — changes apply immediately.
                </div>
                <datalist id="qedit-attr-datalist"></datalist>
                <div id="qedit-rows-container"></div>
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
    const advancedToggle = overlay.querySelector('#qedit-advanced-toggle');
    const advancedNote = overlay.querySelector('#qedit-advanced-note');
    const datalist = overlay.querySelector('#qedit-attr-datalist');

    let advancedMode = advancedDefault;

    // Populate the advanced-mode autocomplete suggestions (rendered as DOM
    // options so ClassAd field names never need HTML escaping).
    suggestionNames.forEach(name => {
        const opt = document.createElement('option');
        opt.value = name;
        datalist.appendChild(opt);
    });

    function closeModal() { overlay.remove(); }
    closeBtns.forEach(btn => btn.addEventListener('click', closeModal));
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(); });

    // Build the attribute field for the current mode: a curated dropdown in
    // basic mode, or a free-text input (backed by the datalist) in advanced mode.
    function buildAttrField(selectedAttr = '') {
        if (advancedMode) {
            const input = document.createElement('input');
            input.type = 'text';
            input.className = 'form-input qedit-attr-input';
            input.setAttribute('list', 'qedit-attr-datalist');
            input.placeholder = 'Attribute name (e.g. HoldReason)';
            input.style.flex = '1';
            input.spellcheck = false;
            input.autocomplete = 'off';
            input.value = selectedAttr;
            return input;
        }

        const select = document.createElement('select');
        select.className = 'form-input qedit-attr-select';
        select.style.flex = '1';
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = '— Select attribute —';
        select.appendChild(placeholder);
        COMMON_QEDIT_ATTRS.forEach(a => {
            const opt = document.createElement('option');
            opt.value = a.attr;
            opt.textContent = `${a.attr} — ${a.desc}`;
            if (a.attr === selectedAttr) opt.selected = true;
            select.appendChild(opt);
        });
        return select;
    }

    // Return the job's current value for a ClassAd attribute, when known.
    function currentValueFor(attr) {
        if (!classad || !attr || !Object.prototype.hasOwnProperty.call(classad, attr)) {
            return undefined;
        }
        const value = classad[attr];
        if (value === null || value === undefined) return undefined;
        return typeof value === 'object' ? JSON.stringify(value) : value;
    }

    // Show the current value (when known) as the value input's placeholder.
    function updateValueHint(row) {
        const attrField = row.querySelector('.qedit-attr-input, .qedit-attr-select');
        const valueInput = row.querySelector('.qedit-value-input');
        if (!attrField || !valueInput) return;
        const attr = (attrField.value || '').trim();
        const current = currentValueFor(attr);
        valueInput.placeholder = current !== undefined
            ? `Current: ${current}`
            : 'New value';
    }

    // Re-render all attribute fields in place when the mode changes, preserving
    // any attribute names the user already entered.
    function applyMode() {
        advancedToggle.checked = advancedMode;
        advancedNote.style.display = advancedMode ? 'block' : 'none';

        overlay.querySelectorAll('.qedit-row').forEach(row => {
            const oldField = row.querySelector('.qedit-attr-input, .qedit-attr-select');
            const currentAttr = oldField ? (oldField.value || '').trim() : '';
            const newField = buildAttrField(currentAttr);

            if (oldField) {
                oldField.replaceWith(newField);
            } else {
                row.insertBefore(newField, row.firstChild);
            }

            newField.addEventListener('input', () => updateValueHint(row));
            newField.addEventListener('change', () => updateValueHint(row));
            updateValueHint(row);
        });
    }

    // Add a new editable row
    function addRow(attrValue = '', valueValue = '') {
        const row = document.createElement('div');
        row.className = 'qedit-row';

        const attrField = buildAttrField(attrValue);

        const valueInput = document.createElement('input');
        valueInput.type = 'text';
        valueInput.className = 'form-input qedit-value-input';
        valueInput.placeholder = 'New value';
        valueInput.style.flex = '1';
        valueInput.value = valueValue;

        const removeBtn = document.createElement('button');
        removeBtn.className = 'btn btn-ghost btn-sm qedit-remove-row';
        removeBtn.style.padding = '4px 8px';
        removeBtn.style.flexShrink = '0';
        removeBtn.title = 'Remove row';
        removeBtn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
        `;

        row.appendChild(attrField);
        row.appendChild(valueInput);
        row.appendChild(removeBtn);
        rowsContainer.appendChild(row);

        removeBtn.addEventListener('click', () => {
            if (rowsContainer.children.length > 1) {
                row.remove();
            } else {
                toast('At least one attribute row is required', 'warning');
            }
        });

        attrField.addEventListener('input', () => updateValueHint(row));
        attrField.addEventListener('change', () => updateValueHint(row));
        updateValueHint(row);

        // Focus the value input
        setTimeout(() => valueInput.focus(), 50);
        return row;
    }

    addRowBtn.addEventListener('click', () => addRow());
    advancedToggle.addEventListener('change', () => {
        advancedMode = advancedToggle.checked;
        applyMode();
    });

    // Initial state + first row
    advancedToggle.checked = advancedMode;
    advancedNote.style.display = advancedMode ? 'block' : 'none';
    addRow();

    // Apply
    applyBtn.addEventListener('click', async () => {
        const rows = overlay.querySelectorAll('.qedit-row');
        const edits = [];
        rows.forEach(row => {
            const attrField = row.querySelector('.qedit-attr-input, .qedit-attr-select');
            const attr = attrField ? attrField.value.trim() : '';
            const value = row.querySelector('.qedit-value-input').value.trim();
            if (attr && value) {
                edits.push({ attr, value });
            }
        });

        if (edits.length === 0) {
            toast('Please fill in at least one attribute and value', 'warning');
            return;
        }

        // ClassAd attribute names cannot contain whitespace
        const invalidEdit = edits.find(edit => /\s/.test(edit.attr));
        if (invalidEdit) {
            toast(`Invalid attribute name: "${invalidEdit.attr}"`, 'warning');
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

    // Allow Enter key to submit from the value input. Scoped to the value input
    // so it doesn't interfere with accepting a datalist suggestion in advanced mode.
    overlay.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.target.classList.contains('qedit-value-input')) {
            applyBtn.click();
        }
    });
}

/**
 * Show a stylish confirmation modal instead of the browser's built-in confirm().
 *
 * @param {string} message - The confirmation message to display.
 * @param {Object} [options]
 * @param {string} [options.title] - Modal title (default: "Confirm").
 * @param {string} [options.confirmText] - Confirm button text (default: "Confirm").
 * @param {string} [options.confirmClass] - CSS class for confirm button (default: "btn-danger").
 * @param {Function} [options.onConfirm] - Called when user confirms.
 * @param {Function} [options.onCancel] - Called when user cancels.
 */
function showConfirmModal(message, options = {}) {
    const {
        title = 'Confirm',
        confirmText = 'Confirm',
        confirmClass = 'btn-danger',
        onConfirm = null,
        onCancel = null,
    } = options;

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay active';
    overlay.id = 'confirm-modal';
    overlay.innerHTML = `
        <div class="modal" style="max-width: 480px;">
            <div class="modal-header">
                <h2>${escHtml(title)}</h2>
                <button class="btn btn-ghost btn-sm modal-close-btn" style="padding: 4px 8px;">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
                        <line x1="18" y1="6" x2="6" y2="18" />
                        <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                </button>
            </div>
            <div class="modal-body">
                <div style="margin-bottom: 20px; color: var(--text-secondary); line-height: 1.5;" id="confirm-message-text"></div>
                <div style="display: flex; gap: 8px; justify-content: flex-end;">
                    <button class="btn btn-ghost modal-close-btn">Cancel</button>
                    <button class="btn ${confirmClass}" id="confirm-modal-btn">${escHtml(confirmText)}</button>
                </div>
            </div>
        </div>
    `;

    // Set message content as innerHTML (not escaped) to allow HTML formatting
    const msgContainer = overlay.querySelector('#confirm-message-text');
    msgContainer.innerHTML = message;

    document.body.appendChild(overlay);

    function closeConfirm() {
        overlay.remove();
        if (onCancel) onCancel();
    }

    // Close buttons
    overlay.querySelectorAll('.modal-close-btn').forEach(btn => {
        btn.addEventListener('click', closeConfirm);
    });
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeConfirm();
    });

    // Confirm button
    overlay.querySelector('#confirm-modal-btn').addEventListener('click', () => {
        overlay.remove();
        if (onConfirm) onConfirm();
    });
}

/**
 * Create a progress tracker callback for uploadFileRaw.
 *
 * Returns an onProgress function that updates a progress bar element
 * and a text element with percentage, speed, and ETA.
 *
 * Usage:
 *   const tracker = createProgressTracker(progressFill, progressText);
 *   uploadFileRaw(file, url, { onProgress: tracker, ... });
 *
 * @param {HTMLElement} progressFill - The progress bar fill element (width is set as %).
 * @param {HTMLElement} progressText - The text element to show status.
 * @param {Object} [options]
 * @param {string} [options.prefix] - Optional text prefix (e.g., "Uploading file 2 of 5").
 * @returns {Function} onProgress callback for uploadFileRaw.
 */
function createProgressTracker(progressFill, progressText, options = {}) {
    const { prefix = '' } = options;
    let lastUpdateTime = Date.now();
    let lastLoadedBytes = 0;
    const speedSamples = [];
    const MAX_SPEED_SAMPLES = 10;

    return (e) => {
        const now = Date.now();
        const elapsed = (now - lastUpdateTime) / 1000;

        const pct = e.percent.toFixed(1);
        progressFill.style.width = pct + '%';

        const uploadedMb = (e.loaded / (1024 * 1024)).toFixed(1);
        const totalMb = (e.total / (1024 * 1024)).toFixed(1);

        // Calculate instantaneous speed
        if (elapsed > 0) {
            const instantSpeed = (e.loaded - lastLoadedBytes) / elapsed;
            if (instantSpeed > 0) {
                speedSamples.push(instantSpeed);
                if (speedSamples.length > MAX_SPEED_SAMPLES) {
                    speedSamples.shift();
                }
            }
        }

        let text = '';
        if (prefix) text = prefix + ' — ';

        // ETA from average speed
        if (speedSamples.length > 0) {
            const avgSpeed = speedSamples.reduce((a, b) => a + b, 0) / speedSamples.length;
            const remainingBytes = e.total - e.loaded;
            const etaSeconds = remainingBytes / avgSpeed;

            let etaStr = '';
            if (etaSeconds < 60) {
                etaStr = `${Math.round(etaSeconds)}s`;
            } else if (etaSeconds < 3600) {
                const mins = Math.floor(etaSeconds / 60);
                const secs = Math.round(etaSeconds % 60);
                etaStr = `${mins}m ${secs}s`;
            } else {
                const hrs = Math.floor(etaSeconds / 3600);
                const mins = Math.floor((etaSeconds % 3600) / 60);
                etaStr = `${hrs}h ${mins}m`;
            }

            let speedStr = '';
            if (avgSpeed >= 1024 * 1024) {
                speedStr = `${(avgSpeed / (1024 * 1024)).toFixed(1)} MB/s`;
            } else if (avgSpeed >= 1024) {
                speedStr = `${(avgSpeed / 1024).toFixed(1)} KB/s`;
            } else {
                speedStr = `${Math.round(avgSpeed)} B/s`;
            }

            text += `${uploadedMb} MB / ${totalMb} MB (${pct}%) — ${speedStr}, ETA: ${etaStr}`;
        } else {
            text += `${uploadedMb} MB / ${totalMb} MB (${pct}%)`;
        }

        progressText.textContent = text;
        lastUpdateTime = now;
        lastLoadedBytes = e.loaded;
    };
}

/**
 * Upload a file as raw request body (no multipart/form-data).
 *
 * This avoids Werkzeug's multipart parser buffering to temp files,
 * which can hit disk quotas with large files.
 *
 * @param {File} file - The file to upload.
 * @param {string} url - The API endpoint URL.
 * @param {Object} [options]
 * @param {string} [options.name] - Optional display name (sent as X-Container-Name or similar).
 * @param {string} [options.filenameHeader] - Header for the original filename (default: 'X-Upload-Filename').
 * @param {string} [options.nameHeader] - Header for the display name (default: 'X-Container-Name').
 * @param {Function} [options.onProgress] - Callback with { loaded, total, percent }.
 * @param {AbortSignal} [options.signal] - Optional AbortSignal to cancel the upload.
 * @returns {{ promise: Promise<Object>, abort: Function }} Parsed JSON response promise and abort function.
 */
function uploadFileRaw(file, url, options = {}) {
    const xhr = new XMLHttpRequest();
    const {
        name = '',
        filenameHeader = 'X-Upload-Filename',
        nameHeader = 'X-Container-Name',
        onProgress = null,
        signal = null,
        extraHeaders = {},  // Optional extra HTTP headers, e.g. { 'X-Overwrite': 'true' }
    } = options;

    xhr.open('POST', url);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.setRequestHeader(filenameHeader, file.name);
    if (name) {
        xhr.setRequestHeader(nameHeader, name);
    }
    // Set any extra headers
    for (const [key, value] of Object.entries(extraHeaders)) {
        xhr.setRequestHeader(key, value);
    }

    if (signal) {
        signal.addEventListener('abort', () => xhr.abort());
    }

    xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable && onProgress) {
            onProgress({
                loaded: e.loaded,
                total: e.total,
                percent: (e.loaded / e.total) * 100,
            });
        }
    });

    const promise = new Promise((resolve, reject) => {
        xhr.addEventListener('load', () => {
            try {
                const data = JSON.parse(xhr.responseText);
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve(data);
                } else {
                    reject(new Error(data.error || `Upload failed with status ${xhr.status}`));
                }
            } catch (e) {
                reject(new Error('Failed to parse server response'));
            }
        });

        xhr.addEventListener('error', () => {
            reject(new Error('Upload failed due to a network error'));
        });

        xhr.addEventListener('abort', () => {
            reject(new DOMException('Upload aborted', 'AbortError'));
        });
    });

    xhr.send(file);

    return { promise, abort: () => xhr.abort() };
}

// ---------------------------------------------------------------------------
// Sidebar Collapse / Expand
// ---------------------------------------------------------------------------

function initSidebar() {
    const collapseBtn = $('#sidebar-collapse-btn');
    if (!collapseBtn) return;

    // Toggle sidebar collapsed state
    collapseBtn.addEventListener('click', () => {
        const isCollapsed = document.documentElement.classList.toggle('sidebar-collapsed');
        localStorage.setItem('sidebarCollapsed', isCollapsed);
    });

    // Initialize nav section collapse/expand
    initNavSections();
}

function initNavSections() {
    const sections = document.querySelectorAll('.nav-section');
    if (!sections.length) return;

    sections.forEach(section => {
        const header = section.querySelector('.nav-section-header');
        const content = section.querySelector('.nav-section-content');
        if (!header || !content) return;

        // Set initial max-height so the collapse animation works
        const sectionId = section.id;
        const isCollapsed = localStorage.getItem(`navSection_${sectionId}`) === 'collapsed';

        if (isCollapsed) {
            section.classList.add('collapsed');
        } else {
            // Expand: set max-height to scrollHeight
            content.style.maxHeight = content.scrollHeight + 'px';
        }

        header.addEventListener('click', () => {
            const wasCollapsed = section.classList.contains('collapsed');

            if (wasCollapsed) {
                // Expand
                section.classList.remove('collapsed');
                content.style.maxHeight = content.scrollHeight + 'px';
                localStorage.setItem(`navSection_${sectionId}`, 'expanded');
            } else {
                // Collapse
                section.classList.add('collapsed');
                content.style.maxHeight = '0';
                localStorage.setItem(`navSection_${sectionId}`, 'collapsed');
            }
        });
    });
}

// Run basic initializations on DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initConnectionMonitor();
    initSidebar();
});