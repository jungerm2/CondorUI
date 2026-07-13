// Container Management

let currentContainers = [];
let renameTargetFilename = null;
let deleteTargetFilename = null;
let osdfConfigured = false;
let containerSortField = 'name';
let containerSortAsc = true;

// Modal helpers
function openModal(id) {
    document.getElementById(id).classList.add('active');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('active');
}

function initModals() {
    document.querySelectorAll('.modal-close-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const modalId = btn.dataset.modal;
            if (modalId) closeModal(modalId);
        });
    });
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                overlay.classList.remove('active');
            }
        });
    });
}

// formatFileSize and formatDateIso are now defined in common.js
// These duplicates have been removed; use the shared versions instead.

// Check if OSDF is configured
async function checkOsdfConfig() {
    try {
        const data = await api('/containers');
        osdfConfigured = true;
        return true;
    } catch (err) {
        // If we get a 400 with "OSDF root path is not configured", show warning
        if (err.message && err.message.includes('OSDF root path')) {
            osdfConfigured = false;
            return false;
        }
        // Otherwise the endpoint works but returned an error
        osdfConfigured = true;
        return true;
    }
}

// Load containers from API
async function loadContainers() {
    try {
        const data = await api('/containers');
        currentContainers = data.containers || [];
        osdfConfigured = true;
        renderContainers();
    } catch (err) {
        if (err.message && err.message.includes('OSDF root path')) {
            osdfConfigured = false;
            showOsdfWarning();
        } else {
            toast(`Failed to load containers: ${err.message}`, 'error');
        }
    }
}

function showOsdfWarning() {
    const warning = $('#osdf-warning');
    if (warning) warning.style.display = 'flex';

    // Disable pull button
    const pullBtn = $('#pull-container-btn');
    if (pullBtn) pullBtn.disabled = true;

    // Disable dropzone
    const dropzone = $('#sif-dropzone');
    if (dropzone) {
        dropzone.style.pointerEvents = 'none';
        dropzone.style.opacity = '0.5';
    }

    // Show empty state with warning
    const tbody = $('#containers-tbody');
    const empty = $('#containers-empty');
    const table = $('#containers-table');
    if (tbody) tbody.innerHTML = '';
    if (table) table.style.display = 'none';
    if (empty) {
        empty.style.display = 'block';
        empty.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="48" height="48">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <p>OSDF Root Path Not Configured</p>
            <p class="hint">Set the <code>OSDF_ROOT_PATH</code> environment variable to use containers.</p>
        `;
    }
}

// Get sortable value for a container
function getContainerSortValue(item, field) {
    switch (field) {
        case 'name': return (item.name || '').toLowerCase();
        case 'source': return (item.source || '').toLowerCase();
        case 'size': return item.size || 0;
        case 'created_at': return item.created_at || '';
        default: return 0;
    }
}

// Render container list
function renderContainers() {
    const tbody = $('#containers-tbody');
    const empty = $('#containers-empty');
    const table = $('#containers-table');

    if (!tbody) return;

    // Apply search filter
    const query = $('#container-search') ? $('#container-search').value : '';
    let filtered = filterData(currentContainers, query, [
        item => item.name,
        item => item.source,
    ]);

    // Apply sort
    filtered = sortData(filtered, containerSortField, containerSortAsc, getContainerSortValue);

    tbody.innerHTML = '';

    if (filtered.length === 0) {
        table.style.display = 'none';
        empty.style.display = 'block';
        return;
    }

    table.style.display = '';
    empty.style.display = 'none';

    filtered.forEach(c => {
        const tr = document.createElement('tr');
        const sourceLabel = c.source && c.source.startsWith('uploaded:')
            ? `Uploaded: ${c.source.replace('uploaded:', '')}`
            : (c.source || '—');

        tr.innerHTML = `
            <td class="monospace" style="font-weight: 500;">${escHtml(c.name)}</td>
            <td class="monospace" style="font-size: 0.82rem; max-width: 200px; overflow: hidden; text-overflow: ellipsis;" title="${escHtml(c.source || '')}">${escHtml(sourceLabel)}</td>
            <td>${formatFileSize(c.size)}</td>
            <td>${formatDateIso(c.created_at)}</td>
            <td class="monospace" style="font-size: 0.8rem; max-width: 250px; overflow: hidden; text-overflow: ellipsis;" title="${escHtml(c.uri)}">${escHtml(c.uri)}</td>
            <td>
                <div class="action-btns">
                    <button class="btn btn-ghost btn-sm rename-container-btn" data-filename="${c.filename}" title="Rename">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                            <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
                        </svg>
                        Rename
                    </button>
                    <button class="btn btn-ghost btn-sm delete-container-btn" data-filename="${c.filename}" data-name="${escHtml(c.name)}" title="Delete" style="color: var(--danger-color, #f87171);">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <polyline points="3,6 5,6 21,6" />
                            <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                        </svg>
                        Delete
                    </button>
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });

    // Bind action buttons
    tbody.querySelectorAll('.rename-container-btn').forEach(btn => {
        btn.addEventListener('click', () => openRenameModal(btn.dataset.filename));
    });
    tbody.querySelectorAll('.delete-container-btn').forEach(btn => {
        btn.addEventListener('click', () => openDeleteModal(btn.dataset.filename, btn.dataset.name));
    });

    updateSortArrows(table, containerSortField, containerSortAsc);
}

// ---------------------------------------------------------------------------
// SSE pull — streams apptainer output live with progress bar support
// ---------------------------------------------------------------------------
let pullEventSource = null;

async function handlePull() {
    const imageRef = $('#pull-image-ref').value.trim();
    const name = $('#pull-image-name').value.trim() || '';

    if (!imageRef) {
        toast('Docker image reference is required', 'warning');
        return;
    }

    // Check for conflicts with existing containers (by display name)
    const displayName = name || 'Image from ' + imageRef;
    const conflict = currentContainers.find(c => c.name.toLowerCase() === displayName.toLowerCase());
    if (conflict) {
        const replace = await new Promise((resolve) => {
            showConfirmModal(
                `Container <strong>${escHtml(displayName)}</strong> already exists.<br><br>Replace it?`,
                {
                    title: 'Replace Container',
                    confirmText: 'Replace',
                    confirmClass: 'btn-primary',
                    onConfirm: () => resolve(true),
                    onCancel: () => resolve(false),
                }
            );
        });
        if (!replace) return;
    }

    // Hide pull form, show log container
    const pullFormRow = document.querySelector('#pull-container-btn').closest('.form-row');
    const logContainer = $('#pull-log-container');
    const logOutput = $('#pull-log-output');
    const pullBtn = $('#pull-container-btn');
    const stopBtn = $('#pull-stop-btn');

    pullFormRow.style.display = 'none';
    logContainer.style.display = 'block';
    logOutput.textContent = '';
    pullBtn.disabled = true;
    stopBtn.disabled = false;

    // Show spinner in the log header
    const spinner = $('#pull-spinner');
    if (spinner) spinner.style.display = 'inline-block';

    const params = new URLSearchParams({ image: imageRef });
    if (name) params.set('name', name);
    if (conflict) params.set('overwrite', 'true');

    pullEventSource = new EventSource(`/api/containers/pull/stream?${params}`);

    pullEventSource.addEventListener('start', (e) => {
        try {
            const data = JSON.parse(e.data);
            logOutput.textContent += `→ Command: ${data.command}\n`;
            logOutput.textContent += `→ Output file: ${data.filename}\n`;
        } catch {
            logOutput.textContent += `→ Output file: ${e.data}\n`;
        }
        logOutput.scrollTop = logOutput.scrollHeight;
    });

    pullEventSource.addEventListener('message', (e) => {
        // Handle \r carriage returns (used by progress bars to overwrite lines)
        const raw = e.data;
        if (raw.includes('\r')) {
            // Split on \r, take the last "segment" (most recent progress update)
            const parts = raw.split('\r');
            for (const part of parts) {
                if (part) {
                    // Replace the last line with the progress update
                    appendOrReplaceLastLine(logOutput, '  ' + part);
                }
            }
        } else {
            logOutput.textContent += raw + '\n';
        }
        logOutput.scrollTop = logOutput.scrollHeight;
    });

    pullEventSource.addEventListener('complete', (e) => {
        pullEventSource.close();
        pullEventSource = null;
        // Hide spinner
        const spinner = $('#pull-spinner');
        if (spinner) spinner.style.display = 'none';
        try {
            const container = JSON.parse(e.data);
            toast(`Container '${container.name}' pulled successfully!`);
            $('#pull-image-ref').value = '';
            $('#pull-image-name').value = '';
            setTimeout(() => {
                logContainer.style.display = 'none';
                pullFormRow.style.display = '';
                pullBtn.disabled = false;
            }, 4000);
            loadContainers();
        } catch (err) {
            toast('Pull succeeded but failed to parse response', 'error');
            resetPullUI();
        }
    });

    pullEventSource.addEventListener('error', (e) => {
        // If we already handled complete/error, EventSource may fire error too
        if (!pullEventSource) return;

        // Hide spinner
        const spinner = $('#pull-spinner');
        if (spinner) spinner.style.display = 'none';

        // Check if the event has data (from our custom error event)
        if (e.data) {
            logOutput.textContent += `\n✗ ERROR: ${e.data}\n`;
        } else {
            logOutput.textContent += '\n✗ ERROR: Connection to server lost.\n';
        }
        logOutput.scrollTop = logOutput.scrollHeight;
        toast(`Pull failed: ${e.data || 'Connection lost'}`, 'error');
        pullEventSource.close();
        pullEventSource = null;
        // Do NOT call resetPullUI() — keep the log visible so user can see the error
        // Just re-enable the pull button and stop button
        const pullBtn = $('#pull-container-btn');
        const stopBtn = $('#pull-stop-btn');
        if (pullBtn) pullBtn.disabled = false;
        if (stopBtn) stopBtn.disabled = true;
    });
}

/**
 * Append text to the log, or replace the last line if the text starts
 * with a \r (carriage return) indicator.
 *
 * This is needed because apptainer uses \r to update progress bars
 * in-place rather than printing new lines.
 */
function appendOrReplaceLastLine(logElement, text) {
    const content = logElement.textContent;
    const lastNewline = content.lastIndexOf('\n');

    if (lastNewline >= 0) {
        // Replace the content after the last newline
        logElement.textContent = content.substring(0, lastNewline + 1) + text;
    } else {
        // No newlines yet — replace the entire content
        logElement.textContent = text;
    }
}

function resetPullUI() {
    const logContainer = $('#pull-log-container');
    const pullFormRow = document.querySelector('#pull-container-btn').closest('.form-row');
    const pullBtn = $('#pull-container-btn');
    const stopBtn = $('#pull-stop-btn');
    const spinner = $('#pull-spinner');
    if (logContainer) logContainer.style.display = 'none';
    if (pullFormRow) pullFormRow.style.display = '';
    if (pullBtn) pullBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = true;
    if (spinner) spinner.style.display = 'none';
}

// Stop pull
function stopPull() {
    if (pullEventSource) {
        pullEventSource.close();
        pullEventSource = null;
        $('#pull-log-output').textContent += '\n— Pull cancelled by user —\n';
        toast('Pull cancelled', 'warning');
        resetPullUI();
    }
}

// Upload .sif as raw request body with progress bar, ETA, and sub-1% granularity
async function handleSifUpload(file) {
    const name = $('#upload-sif-name').value.trim() || '';

    // Check for conflicts with existing containers (by display name)
    const conflict = currentContainers.find(c => c.name.toLowerCase() === name.toLowerCase());
    if (conflict) {
        const replace = await new Promise((resolve) => {
            showConfirmModal(
                `Container <strong>${escHtml(name)}</strong> already exists.<br><br>Replace it?`,
                {
                    title: 'Replace Container',
                    confirmText: 'Replace',
                    confirmClass: 'btn-primary',
                    onConfirm: () => resolve(true),
                    onCancel: () => resolve(false),
                }
            );
        });
        if (!replace) return;
    }

    // Show progress bar
    const progressContainer = $('#sif-upload-progress');
    const progressFill = $('#sif-upload-progress-fill');
    const progressText = $('#sif-upload-progress-text');
    const dropzone = $('#sif-dropzone');

    dropzone.style.display = 'none';
    progressContainer.style.display = 'block';
    progressFill.style.width = '0%';
    progressText.textContent = 'Starting upload...';

    const onProgress = createProgressTracker(progressFill, progressText);

    const { promise } = uploadFileRaw(file, '/api/containers/upload', {
        name: name,
        filenameHeader: 'X-Container-Filename',
        nameHeader: 'X-Container-Name',
        onProgress,
        extraHeaders: conflict ? { 'X-Overwrite': 'true' } : {},
    });
    promise.then(async (data) => {
        toast(`Container '${data.name}' uploaded successfully!`);
        $('#upload-sif-name').value = '';
        progressFill.style.width = '100%';
        progressText.textContent = 'Complete!';
        setTimeout(() => {
            progressContainer.style.display = 'none';
            dropzone.style.display = '';
        }, 4000);
        await loadContainers();
    }).catch((err) => {
        let msg = err.message || 'Upload failed';
        progressText.textContent = `✗ ${msg}`;
        toast(msg, 'error');
    });
}

function resetUploadUI() {
    const progressContainer = $('#sif-upload-progress');
    const dropzone = $('#sif-dropzone');
    if (progressContainer) progressContainer.style.display = 'none';
    if (dropzone) dropzone.style.display = '';
}

// Rename
function openRenameModal(filename) {
    const container = currentContainers.find(c => c.filename === filename);
    if (!container) return;
    renameTargetFilename = filename;
    $('#rename-container-name').value = container.name;
    openModal('rename-modal');
    setTimeout(() => $('#rename-container-name').focus(), 100);
}


async function handleRename() {
    const newName = $('#rename-container-name').value.trim();
    if (!newName) {
        toast('Name cannot be empty', 'warning');
        return;
    }
    if (renameTargetFilename === null) return;

    try {
        await api(`/containers/${encodeURIComponent(renameTargetFilename)}`, {
            method: 'PUT',
            body: JSON.stringify({ name: newName })
        });
        toast('Container renamed');
        closeModal('rename-modal');
        renameTargetFilename = null;
        await loadContainers();
    } catch (err) {
        toast(`Rename failed: ${err.message}`, 'error');
    }
}

// Delete
function openDeleteModal(filename, containerName) {
    deleteTargetFilename = filename;
    $('#delete-container-name-display').textContent = containerName;
    openModal('delete-modal');
}


async function handleDelete() {
    if (deleteTargetFilename === null) return;

    try {
        await api(`/containers/${encodeURIComponent(deleteTargetFilename)}`, { method: 'DELETE' });
        toast('Container deleted');
        closeModal('delete-modal');
        deleteTargetFilename = null;
        await loadContainers();
    } catch (err) {
        toast(`Delete failed: ${err.message}`, 'error');
    }
}

// Init pull form
function initPullForm() {
    const imageRef = $('#pull-image-ref');
    const nameInput = $('#pull-image-name');
    const pullBtn = $('#pull-container-btn');

    function updatePullBtn() {
        pullBtn.disabled = !imageRef.value.trim();
    }

    imageRef.addEventListener('input', updatePullBtn);
    pullBtn.addEventListener('click', handlePull);

    // Enter key in either field triggers pull
    imageRef.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && imageRef.value.trim()) handlePull();
    });
    nameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && imageRef.value.trim()) handlePull();
    });
}

// Init SIF upload dropzone
function initSifUpload() {
    const dropzone = $('#sif-dropzone');
    const fileInput = $('#sif-file-input');
    if (!dropzone || !fileInput) return;

    dropzone.addEventListener('click', () => fileInput.click());

    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));

    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            const file = e.dataTransfer.files[0];
            if (file.name.toLowerCase().endsWith('.sif')) {
                handleSifUpload(file);
            } else {
                toast('Only .sif files are accepted', 'warning');
            }
        }
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length) {
            const file = fileInput.files[0];
            if (file.name.toLowerCase().endsWith('.sif')) {
                handleSifUpload(file);
            } else {
                toast('Only .sif files are accepted', 'warning');
            }
            fileInput.value = '';
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    initModals();
    initPullForm();
    initSifUpload();
    loadContainers();

    // Search input
    const searchInput = $('#container-search');
    if (searchInput) {
        searchInput.addEventListener('input', renderContainers);
    }

    // Sortable column headers
    const table = $('#containers-table');
    if (table) {
        table.querySelectorAll('thead th.sortable').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                if (field === containerSortField) {
                    containerSortAsc = !containerSortAsc;
                } else {
                    containerSortField = field;
                    containerSortAsc = true;
                }
                renderContainers();
            });
        });
    }

    // Rename confirm
    $('#rename-confirm-btn').addEventListener('click', handleRename);
    $('#rename-container-name').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleRename();
    });

    // Delete confirm
    $('#delete-confirm-btn').addEventListener('click', handleDelete);

    // Stop pull
    const stopBtn = $('#pull-stop-btn');
    if (stopBtn) stopBtn.addEventListener('click', stopPull);
});