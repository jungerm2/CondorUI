// Input Files Management

let currentFiles = [];
let renameTargetId = null;
let deleteTargetId = null;
let selectedFileIds = new Set();
let uploadAbortControllers = []; // Track active uploads for cancel

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

// Format file size
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

// Format date
function formatDate(isoStr) {
    if (!isoStr) return '—';
    const d = new Date(isoStr);
    return d.toLocaleString();
}

// Load files from API
async function loadFiles() {
    try {
        const data = await api('/files');
        currentFiles = data.files || [];
        renderFiles();
    } catch (err) {
        toast(`Failed to load files: ${err.message}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Selection UI (modeled after dashboard pattern)
// ---------------------------------------------------------------------------

function updateSelectionUI() {
    const count = selectedFileIds.size;
    $('#file-selection-count').textContent = `${count} selected`;

    const stageBtn = $('#file-stage-btn');
    const unstageBtn = $('#file-unstage-btn');
    const deleteBtn = $('#file-delete-btn');
    const renameBtn = $('#file-rename-btn');

    stageBtn.disabled = count === 0;
    unstageBtn.disabled = count === 0;
    deleteBtn.disabled = count === 0;
    renameBtn.disabled = count !== 1; // Rename only works on a single file

    // Enable unstage only if all selected files are staged
    if (count > 0) {
        const allStaged = currentFiles.filter(f => selectedFileIds.has(f.id)).every(f => !!f.osdf_path);
        unstageBtn.disabled = !allStaged;
    }

    // Update select-all checkbox
    const selectAll = $('#file-select-all');
    if (selectAll) {
        if (currentFiles.length > 0) {
            const allSelected = currentFiles.every(f => selectedFileIds.has(f.id));
            selectAll.checked = allSelected;
            selectAll.indeterminate = !allSelected && currentFiles.some(f => selectedFileIds.has(f.id));
        } else {
            selectAll.checked = false;
            selectAll.indeterminate = false;
        }
    }
}

// Render file list
function renderFiles() {
    const tbody = $('#files-tbody');
    const empty = $('#files-empty');
    const table = $('#files-table');

    if (!tbody) return;

    tbody.innerHTML = '';

    if (currentFiles.length === 0) {
        table.style.display = 'none';
        empty.style.display = 'block';
        return;
    }

    table.style.display = '';
    empty.style.display = 'none';

    currentFiles.forEach(f => {
        const isOsdf = !!f.osdf_path;
        const locationLabel = isOsdf ? 'OSDF' : 'Local';
        const locationClass = isOsdf ? 'badge-osdf' : 'badge-local';
        const isChecked = selectedFileIds.has(f.id);

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="file-row-checkbox" data-file-id="${f.id}" ${isChecked ? 'checked' : ''}>
            </td>
            <td class="monospace">${escHtml(f.filename)}</td>
            <td class="monospace">${escHtml(f.original_name)}</td>
            <td>${formatFileSize(f.size)}</td>
            <td>${formatDate(f.uploaded_at)}</td>
            <td><span class="badge ${locationClass}">${locationLabel}</span></td>
        `;
        tbody.appendChild(tr);

        // Row click toggles checkbox
        tr.addEventListener('click', (e) => {
            if (e.target.closest('input[type="checkbox"]')) return;
            const cb = tr.querySelector('.file-row-checkbox');
            if (cb) {
                cb.checked = !cb.checked;
                cb.dispatchEvent(new Event('change'));
            }
        });
    });

    // Bind checkbox events
    tbody.querySelectorAll('.file-row-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
            const id = parseInt(cb.dataset.fileId);
            if (cb.checked) {
                selectedFileIds.add(id);
            } else {
                selectedFileIds.delete(id);
            }
            updateSelectionUI();
        });
    });

    updateSelectionUI();
}

// ---------------------------------------------------------------------------
// Upload with per-file progress bars and cancel
// ---------------------------------------------------------------------------

function createProgressItem(file) {
    const container = document.createElement('div');
    container.className = 'upload-progress-item';
    container.id = `upload-progress-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;

    container.innerHTML = `
        <div class="upload-progress-header">
            <span class="upload-progress-filename" title="${escHtml(file.name)}">${escHtml(file.name)}</span>
            <button class="btn btn-ghost btn-sm upload-cancel-btn" title="Cancel upload" style="padding: 2px 6px; flex-shrink: 0;">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
            </button>
        </div>
        <div class="progress-bar-container">
            <div class="progress-bar-fill" style="width: 0%;"></div>
        </div>
        <span class="progress-text">Starting...</span>
    `;

    return container;
}

// Upload files — each file sent as raw request body, each with its own progress bar
async function handleUpload(files) {
    const fileList = Array.from(files);
    if (fileList.length === 0) return;

    const dropzone = $('#file-dropzone');
    const progressList = $('#file-upload-progress-list');

    // Clear any previous selection when starting a new upload
    selectedFileIds.clear();

    dropzone.style.display = 'none';
    progressList.style.display = 'block';
    progressList.innerHTML = '';

    uploadAbortControllers = [];

    // Create a progress item for each file
    const progressItems = fileList.map(file => {
        const item = createProgressItem(file);
        progressList.appendChild(item);
        return { file, item, aborted: false };
    });

    // Add a cancel-all button if multiple files
    if (fileList.length > 1) {
        const cancelAllRow = document.createElement('div');
        cancelAllRow.className = 'upload-progress-cancel-all';
        cancelAllRow.innerHTML = `<button class="btn btn-ghost btn-sm" id="cancel-all-uploads-btn">Cancel All</button>`;
        progressList.appendChild(cancelAllRow);
    }

    let successCount = 0;
    let failCount = 0;

    // Upload each file in parallel
    const uploadPromises = progressItems.map(({ file, item }) => {
        const progressFill = item.querySelector('.progress-bar-fill');
        const progressText = item.querySelector('.progress-text');
        const cancelBtn = item.querySelector('.upload-cancel-btn');

        const onProgress = createProgressTracker(progressFill, progressText);

        const { promise, abort } = uploadFileRaw(file, '/api/files', {
            filenameHeader: 'X-Upload-Filename',
            onProgress,
        });

        // Store abort for cancel-all
        uploadAbortControllers.push(abort);

        // Wire cancel button
        cancelBtn.addEventListener('click', () => {
            abort();
            item.classList.add('upload-cancelled');
            progressText.textContent = '✗ Cancelled';
            cancelBtn.disabled = true;
        });

        return promise.then(() => {
            successCount++;
            progressFill.style.width = '100%';
            progressText.textContent = '✓ Complete';
            cancelBtn.disabled = true;
        }).catch((err) => {
            if (err.name === 'AbortError') {
                // Already handled by cancel button
                return;
            }
            failCount++;
            progressText.textContent = `✗ ${err.message}`;
            cancelBtn.disabled = true;
            toast(`Failed to upload '${file.name}': ${err.message}`, 'error');
        });
    });

    // Cancel-all handler
    const cancelAllBtn = $('#cancel-all-uploads-btn');
    if (cancelAllBtn) {
        cancelAllBtn.addEventListener('click', () => {
            uploadAbortControllers.forEach(abort => abort());
            uploadAbortControllers = [];
            cancelAllBtn.disabled = true;
            cancelAllBtn.textContent = 'Cancelling...';
        });
    }

    // Wait for all uploads to finish
    await Promise.all(uploadPromises);

    uploadAbortControllers = [];

    const totalFiles = fileList.length;
    if (successCount > 0) {
        const msg = `Uploaded ${successCount} file(s)` + (failCount > 0 ? ` (${failCount} failed)` : '');
        toast(msg);
        setTimeout(() => {
            progressList.style.display = 'none';
            dropzone.style.display = '';
        }, 4000);
        await loadFiles();
    } else if (failCount > 0) {
        toast(`All ${failCount} upload(s) failed`, 'error');
    }
    // If all were cancelled, just leave the UI showing cancelled state
}

// ---------------------------------------------------------------------------
// Bulk actions
// ---------------------------------------------------------------------------

// Stage selected files to OSDF
async function handleBulkStage() {
    if (selectedFileIds.size === 0) return;

    const toStage = currentFiles.filter(f => selectedFileIds.has(f.id) && !f.osdf_path);
    if (toStage.length === 0) {
        toast('No selected files are eligible for staging (already in OSDF)', 'warning');
        return;
    }

    toast(`Staging ${toStage.length} file(s) to OSDF...`);
    let successCount = 0;
    let failCount = 0;

    for (const file of toStage) {
        try {
            await api(`/files/${file.id}/stage`, { method: 'POST' });
            successCount++;
        } catch (err) {
            failCount++;
            toast(`Failed to stage '${file.filename}': ${err.message}`, 'error');
        }
    }

    toast(`Staged ${successCount} file(s)` + (failCount > 0 ? ` (${failCount} failed)` : ''));
    selectedFileIds.clear();
    try {
        await loadFiles();
    } finally {
        updateSelectionUI();
    }
}

// Delete selected files
async function handleBulkDelete() {
    if (selectedFileIds.size === 0) return;

    const count = selectedFileIds.size;
    const names = currentFiles
        .filter(f => selectedFileIds.has(f.id))
        .map(f => f.filename)
        .slice(0, 5);
    let detail = names.join(', ');
    if (count > 5) detail += `, and ${count - 5} more...`;

    showConfirmModal(
        `Are you sure you want to delete <strong>${count}</strong> file(s)? This will permanently remove them from disk.<br><br><code style="font-size: 0.82rem;">${escHtml(detail)}</code>`,
        {
            title: 'Delete Files',
            confirmText: `Delete ${count} File(s)`,
            confirmClass: 'btn-danger',
            onConfirm: async () => {
                const ids = [...selectedFileIds];
                let successCount = 0;
                let failCount = 0;

                for (const id of ids) {
                    try {
                        await api(`/files/${id}`, { method: 'DELETE' });
                        successCount++;
                    } catch (err) {
                        failCount++;
                        toast(`Failed to delete file #${id}: ${err.message}`, 'error');
                    }
                }

                toast(`Deleted ${successCount} file(s)` + (failCount > 0 ? ` (${failCount} failed)` : ''));
                selectedFileIds.clear();
                await loadFiles();
            },
        }
    );
}

// Rename single selected file
async function handleBulkRename() {
    if (selectedFileIds.size !== 1) {
        toast('Select exactly one file to rename', 'warning');
        return;
    }

    const fileId = [...selectedFileIds][0];
    const file = currentFiles.find(f => f.id === fileId);
    if (!file) return;

    renameTargetId = fileId;
    $('#rename-filename').value = file.filename;
    openModal('rename-modal');
    setTimeout(() => $('#rename-filename').focus(), 100);
}

// Unstage selected files (move back from OSDF to local)
async function handleBulkUnstage() {
    if (selectedFileIds.size === 0) return;

    const toUnstage = currentFiles.filter(f => selectedFileIds.has(f.id) && f.osdf_path);
    if (toUnstage.length === 0) {
        toast('No selected files are eligible for unstage (not in OSDF)', 'warning');
        return;
    }

    toast(`Unstaging ${toUnstage.length} file(s) from OSDF...`);
    let successCount = 0;
    let failCount = 0;

    for (const file of toUnstage) {
        try {
            await api(`/files/${file.id}/unstage`, { method: 'POST' });
            successCount++;
        } catch (err) {
            failCount++;
            toast(`Failed to unstage '${file.filename}': ${err.message}`, 'error');
        }
    }

    toast(`Unstaged ${successCount} file(s)` + (failCount > 0 ? ` (${failCount} failed)` : ''));
    selectedFileIds.clear();
    try {
        await loadFiles();
    } finally {
        updateSelectionUI();
    }
}

// Single-file stage (used by bulk action loop)
async function handleStage(fileId) {
    toast('Staging to OSDF...');
    try {
        await api(`/files/${fileId}/stage`, { method: 'POST' });
        toast('File staged to OSDF');
        await loadFiles();
    } catch (err) {
        toast(`Stage failed: ${err.message}`, 'error');
    }
}

// Rename
async function handleRename() {
    const newName = $('#rename-filename').value.trim();
    if (!newName) {
        toast('Filename cannot be empty', 'warning');
        return;
    }
    if (renameTargetId === null) return;

    try {
        await api(`/files/${renameTargetId}`, {
            method: 'PUT',
            body: JSON.stringify({ filename: newName })
        });
        toast('File renamed');
        closeModal('rename-modal');
        renameTargetId = null;
        selectedFileIds.clear();
        await loadFiles();
    } catch (err) {
        toast(`Rename failed: ${err.message}`, 'error');
    }
}

// Delete
async function handleDelete() {
    if (deleteTargetId === null) return;

    try {
        await api(`/files/${deleteTargetId}`, { method: 'DELETE' });
        toast('File deleted');
        closeModal('delete-modal');
        deleteTargetId = null;
        await loadFiles();
    } catch (err) {
        toast(`Delete failed: ${err.message}`, 'error');
    }
}

// Init upload dropzone
function initUploadDropzone() {
    const dropzone = $('#file-dropzone');
    const fileInput = $('#file-upload-input');
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
            handleUpload(e.dataTransfer.files);
        }
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length) {
            handleUpload(fileInput.files);
            fileInput.value = '';
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    initModals();
    initUploadDropzone();
    loadFiles();

    // Select-all checkbox
    $('#file-select-all').addEventListener('change', (e) => {
        const checked = e.target.checked;
        currentFiles.forEach(f => {
            if (checked) {
                selectedFileIds.add(f.id);
            } else {
                selectedFileIds.delete(f.id);
            }
        });
        $$('.file-row-checkbox').forEach(cb => {
            cb.checked = checked;
        });
        updateSelectionUI();
    });

    // Bulk action buttons
    $('#file-stage-btn').addEventListener('click', handleBulkStage);
    $('#file-unstage-btn').addEventListener('click', handleBulkUnstage);
    $('#file-delete-btn').addEventListener('click', handleBulkDelete);
    $('#file-rename-btn').addEventListener('click', handleBulkRename);

    // Rename confirm
    $('#rename-confirm-btn').addEventListener('click', handleRename);
    $('#rename-filename').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleRename();
    });

    // Delete confirm
    $('#delete-confirm-btn').addEventListener('click', handleDelete);
});