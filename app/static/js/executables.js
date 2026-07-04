// Executables Management
// Mirrors the patterns from files.js but simpler: no UUID paths, no OSDF staging, no rename.

let currentExecs = [];
let deleteTargetFilename = null;
let selectedExecFilenames = new Set();
let uploadAbortControllers = []; // Track active uploads for cancel
let execSortField = 'filename';
let execSortAsc = true;

// Modal helpers (same as files.js)
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

// Load executables from API
async function loadExecutables() {
    try {
        const data = await api('/executables');
        currentExecs = data.executables || [];
        renderExecutables();
    } catch (err) {
        toast(`Failed to load executables: ${err.message}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Selection UI
// ---------------------------------------------------------------------------

function updateSelectionUI() {
    const count = selectedExecFilenames.size;
    $('#exec-selection-count').textContent = `${count} selected`;

    const deleteBtn = $('#exec-delete-btn');
    deleteBtn.disabled = count === 0;

    // Update select-all checkbox
    const selectAll = $('#exec-select-all');
    if (selectAll) {
        if (currentExecs.length > 0) {
            const allSelected = currentExecs.every(f => selectedExecFilenames.has(f.filename));
            selectAll.checked = allSelected;
            selectAll.indeterminate = !allSelected && currentExecs.some(f => selectedExecFilenames.has(f.filename));
        } else {
            selectAll.checked = false;
            selectAll.indeterminate = false;
        }
    }
}

// Get sortable value for an executable
function getExecSortValue(item, field) {
    switch (field) {
        case 'filename': return (item.filename || '').toLowerCase();
        case 'size': return item.size || 0;
        case 'uploaded_at': return item.uploaded_at || 0;
        default: return 0;
    }
}

// Render executable list
function renderExecutables() {
    const tbody = $('#exec-tbody');
    const empty = $('#exec-empty');
    const table = $('#exec-table');

    if (!tbody) return;

    // Apply search filter
    const query = $('#exec-search') ? $('#exec-search').value : '';
    let filtered = filterData(currentExecs, query, [
        item => item.filename,
    ]);

    // Apply sort
    filtered = sortData(filtered, execSortField, execSortAsc, getExecSortValue);

    tbody.innerHTML = '';

    if (filtered.length === 0) {
        table.style.display = 'none';
        empty.style.display = 'block';
        updateSelectionUI();
        return;
    }

    table.style.display = '';
    empty.style.display = 'none';

    filtered.forEach(f => {
        const isChecked = selectedExecFilenames.has(f.filename);

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="exec-row-checkbox" data-exec-filename="${f.filename}" ${isChecked ? 'checked' : ''}>
            </td>
            <td class="monospace">${escHtml(f.filename)}</td>
            <td>${formatFileSize(f.size)}</td>
            <td>${formatDate(f.uploaded_at)}</td>
        `;
        tbody.appendChild(tr);

        // Row click toggles checkbox
        tr.addEventListener('click', (e) => {
            if (e.target.closest('input[type="checkbox"]')) return;
            const cb = tr.querySelector('.exec-row-checkbox');
            if (cb) {
                cb.checked = !cb.checked;
                cb.dispatchEvent(new Event('change'));
            }
        });
    });

    // Bind checkbox events
    tbody.querySelectorAll('.exec-row-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
            const filename = cb.dataset.execFilename;
            if (cb.checked) {
                selectedExecFilenames.add(filename);
            } else {
                selectedExecFilenames.delete(filename);
            }
            updateSelectionUI();
        });
    });

    updateSortArrows(table, execSortField, execSortAsc);
    updateSelectionUI();
}

// ---------------------------------------------------------------------------
// Upload with per-file progress bars and cancel (same pattern as files.js)
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

// Upload files — each file sent as raw request body
async function handleUpload(files) {
    const fileList = Array.from(files);
    if (fileList.length === 0) return;

    const dropzone = $('#exec-dropzone');
    const progressList = $('#exec-upload-progress-list');

    // Clear any previous selection when starting a new upload
    selectedExecFilenames.clear();

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

        const { promise, abort } = uploadFileRaw(file, '/api/executables', {
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
        await loadExecutables();
    } else if (failCount > 0) {
        toast(`All ${failCount} upload(s) failed`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Delete
// ---------------------------------------------------------------------------

async function handleDelete() {
    if (deleteTargetFilename === null) return;

    try {
        await api(`/executables/${encodeURIComponent(deleteTargetFilename)}`, { method: 'DELETE' });
        toast('Executable deleted');
        closeModal('exec-delete-modal');
        deleteTargetFilename = null;
        await loadExecutables();
    } catch (err) {
        toast(`Delete failed: ${err.message}`, 'error');
    }
}

async function handleBulkDelete() {
    if (selectedExecFilenames.size === 0) return;

    const count = selectedExecFilenames.size;
    const names = currentExecs
        .filter(f => selectedExecFilenames.has(f.filename))
        .map(f => f.filename)
        .slice(0, 5);
    let detail = names.join(', ');
    if (count > 5) detail += `, and ${count - 5} more...`;

    showConfirmModal(
        `Are you sure you want to delete <strong>${count}</strong> executable(s)? This will permanently remove them from disk.<br><br><code style="font-size: 0.82rem;">${escHtml(detail)}</code>`,
        {
            title: 'Delete Executables',
            confirmText: `Delete ${count} Executable(s)`,
            confirmClass: 'btn-danger',
            onConfirm: async () => {
                const filenames = [...selectedExecFilenames];
                let successCount = 0;
                let failCount = 0;

                for (const filename of filenames) {
                    try {
                        await api(`/executables/${encodeURIComponent(filename)}`, { method: 'DELETE' });
                        successCount++;
                    } catch (err) {
                        failCount++;
                        toast(`Failed to delete '${filename}': ${err.message}`, 'error');
                    }
                }

                toast(`Deleted ${successCount} executable(s)` + (failCount > 0 ? ` (${failCount} failed)` : ''));
                selectedExecFilenames.clear();
                await loadExecutables();
            },
        }
    );
}

// ---------------------------------------------------------------------------
// Init upload dropzone
// ---------------------------------------------------------------------------

function initUploadDropzone() {
    const dropzone = $('#exec-dropzone');
    const fileInput = $('#exec-upload-input');
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

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    initModals();
    initUploadDropzone();
    loadExecutables();

    // Select-all checkbox
    const selectAll = $('#exec-select-all');
    if (selectAll) {
        selectAll.addEventListener('change', (e) => {
            const checked = e.target.checked;
            currentExecs.forEach(f => {
                if (checked) {
                    selectedExecFilenames.add(f.filename);
                } else {
                    selectedExecFilenames.delete(f.filename);
                }
            });
            $$('.exec-row-checkbox').forEach(cb => {
                cb.checked = checked;
            });
            updateSelectionUI();
        });
    }

    // Search input
    const searchInput = $('#exec-search');
    if (searchInput) {
        searchInput.addEventListener('input', renderExecutables);
    }

    // Sortable column headers
    const table = $('#exec-table');
    if (table) {
        table.querySelectorAll('thead th.sortable').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                if (field === execSortField) {
                    execSortAsc = !execSortAsc;
                } else {
                    execSortField = field;
                    execSortAsc = true;
                }
                renderExecutables();
            });
        });
    }

    // Bulk action buttons
    $('#exec-delete-btn').addEventListener('click', handleBulkDelete);

    // Delete confirm
    $('#exec-delete-confirm-btn').addEventListener('click', handleDelete);
});