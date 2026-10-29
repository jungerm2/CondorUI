// Input Files Management

let currentFiles = [];
let renameTargetFilename = null;
let deleteTargetFilename = null;
let selectedFileFilenames = new Set();
let uploadAbortControllers = []; // Track active uploads for cancel
let fileSortField = 'original_name';
let fileSortAsc = true;
let stagedRefreshTimer = null;

// formatFileSize and formatDateIso are now defined in common.js
// These duplicates have been removed; use the shared versions instead.

// Load files from API. Local files render immediately; a slow staged-directory
// scan reports `staged_pending` and we poll until its background scan finishes.
async function loadFiles() {
    try {
        const data = await api('/files');
        currentFiles = data.files || [];
        renderFiles();

        if (data.staged_pending) {
            if (currentFiles.length === 0) {
                const empty = $('#files-empty');
                const p = empty ? empty.querySelector('p') : null;
                if (p) p.textContent = 'Loading staged files…';
            }
            if (!stagedRefreshTimer) {
                stagedRefreshTimer = setTimeout(() => {
                    stagedRefreshTimer = null;
                    loadFiles();
                }, 2000);
            }
        } else if (stagedRefreshTimer) {
            clearTimeout(stagedRefreshTimer);
            stagedRefreshTimer = null;
        }
    } catch (err) {
        toast(`Failed to load files: ${err.message}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Selection UI (modeled after dashboard pattern)
// ---------------------------------------------------------------------------

function updateSelectionUI() {
    const count = selectedFileFilenames.size;
    $('#file-selection-count').textContent = `${count} selected`;

    const stageBtn = $('#file-stage-btn');
    const unstageBtn = $('#file-unstage-btn');
    const deleteBtn = $('#file-delete-btn');
    const renameBtn = $('#file-rename-btn');
    const downloadBtn = $('#file-download-btn');

    stageBtn.disabled = count === 0;
    unstageBtn.disabled = count === 0;
    deleteBtn.disabled = count === 0;
    downloadBtn.disabled = count === 0;
    renameBtn.disabled = count !== 1; // Rename only works on a single file

    // Enable unstage only if all selected files are staged
    if (count > 0) {
        const allStaged = currentFiles.filter(f => selectedFileFilenames.has(f.filename)).every(f => !!f.osdf_path);
        unstageBtn.disabled = !allStaged;
    }

    // Update select-all checkbox
    updateSelectAllState($('#file-select-all'), currentFiles, selectedFileFilenames, f => f.filename);
    syncGroupCheckboxes();
}

// Get sortable value for a file
function getFileSortValue(item, field) {
    switch (field) {
        case 'original_name': return (item.display_name || item.original_name || '').toLowerCase();
        case 'size': return item.size || 0;
        case 'uploaded_at': return item.uploaded_at || 0;
        case 'location': return item.osdf_path ? 'osdf' : 'local';
        default: return 0;
    }
}

const collapsedFileGroups = new Set();

function fileDisplayName(f) {
    return f.display_name || f.original_name || f.filename;
}

// Folder uploads group by their top-level folder; loose files share "Files".
function fileGroup(f) {
    const display = fileDisplayName(f);
    const cut = display.indexOf('/');
    if (cut === -1) return { key: '__files__', name: 'Files', inner: display };
    return { key: display.slice(0, cut), name: display.slice(0, cut), inner: display.slice(cut + 1) };
}

function groupFiles(files) {
    const groups = new Map();
    files.forEach(f => {
        const { key, name, inner } = fileGroup(f);
        if (!groups.has(key)) groups.set(key, { key, name, files: [], totalBytes: 0 });
        const group = groups.get(key);
        group.files.push({ ...f, _inner: inner });
        group.totalBytes += f.size || 0;
    });
    return [...groups.values()].sort((a, b) => {
        if (a.key === '__files__') return 1;
        if (b.key === '__files__') return -1;
        return a.name.localeCompare(b.name);
    });
}

function syncGroupCheckboxes() {
    const groups = groupFiles(currentFiles);
    document.querySelectorAll('.file-group-checkbox').forEach(cb => {
        const group = groups.find(g => g.key === cb.dataset.groupKey);
        if (!group) return;
        const selected = group.files.filter(f => selectedFileFilenames.has(f.filename)).length;
        cb.checked = selected === group.files.length;
        cb.indeterminate = selected > 0 && selected < group.files.length;
    });
}

function buildFileRow(f) {
    const isOsdf = !!f.osdf_path;
    const locationLabel = isOsdf ? 'OSDF' : 'Local';
    const locationClass = isOsdf ? 'badge-osdf' : 'badge-local';
    const isChecked = selectedFileFilenames.has(f.filename);
    const inner = f._inner || fileDisplayName(f);
    const parts = inner.split('/');
    const base = parts.pop() || inner;
    const dir = parts.join('/');

    const tr = document.createElement('tr');
    tr.innerHTML = `
        <td style="text-align: center;">
            <input type="checkbox" class="file-row-checkbox" data-file-filename="${escHtml(f.filename)}" ${isChecked ? 'checked' : ''}>
        </td>
        <td class="monospace" title="${escHtml(fileDisplayName(f))}">
            ${dir ? `<span class="file-folder" style="margin-left: ${(parts.length - 1) * 14}px;">${escHtml(dir)}/</span>` : ''}${escHtml(base)}
        </td>
        <td>${formatFileSize(f.size)}</td>
        <td>${formatDate(f.uploaded_at)}</td>
        <td><span class="badge ${locationClass}">${locationLabel}</span></td>
        <td>
            <div class="action-btns">
                <button class="btn btn-ghost btn-sm file-preview-btn" data-filename="${escHtml(f.filename)}" title="Preview">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                        <circle cx="12" cy="12" r="3" />
                    </svg>
                </button>
                <a href="/api/files/${escHtml(f.filename.split('/').map(encodeURIComponent).join('/'))}/download" class="btn btn-ghost btn-sm" title="Download" download>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                        <polyline points="7,10 12,15 17,10" />
                        <line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                </a>
            </div>
        </td>
    `;
    return tr;
}

// Render file list
function renderFiles() {
    const tbody = $('#files-tbody');
    const empty = $('#files-empty');
    const table = $('#files-table');

    if (!tbody) return;

    // Apply search filter
    const query = $('#file-search') ? $('#file-search').value : '';
    let filtered = filterData(currentFiles, query, [
        item => item.display_name || item.original_name,
        item => item.osdf_path ? 'OSDF' : 'Local',
    ]);

    // Apply sort
    filtered = sortData(filtered, fileSortField, fileSortAsc, getFileSortValue);

    tbody.innerHTML = '';

    if (filtered.length === 0) {
        table.style.display = 'none';
        empty.style.display = 'block';
        const p = empty.querySelector('p');
        if (p && p.dataset.emptyText) p.textContent = p.dataset.emptyText;
        updateSelectionUI();
        return;
    }

    table.style.display = '';
    empty.style.display = 'none';

    const groups = groupFiles(filtered);
    const grouped = groups.some(group => group.key !== '__files__');

    if (grouped) {
        groups.forEach(group => {
            const collapsed = collapsedFileGroups.has(group.key);
            const selected = group.files.filter(f => selectedFileFilenames.has(f.filename)).length;
            const gtr = document.createElement('tr');
            gtr.className = 'group-header';
            gtr.dataset.groupKey = group.key;
            gtr.innerHTML = `
                <td style="text-align: center;">
                    <input type="checkbox" class="file-group-checkbox" data-group-key="${escHtml(group.key)}">
                </td>
                <td colspan="5">
                    <div class="output-group-header">
                        <span class="output-group-name">
                            <span class="output-group-label">${escHtml(group.name)}${group.key === '__files__' ? '' : '/'}</span>
                        </span>
                        <span class="output-group-meta">${group.files.length} file${group.files.length === 1 ? '' : 's'} · ${formatFileSize(group.totalBytes)}</span>
                        <span class="expand-chevron ${collapsed ? '' : 'expanded'}" aria-hidden="true">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="9 6 15 12 9 18" />
                            </svg>
                        </span>
                    </div>
                </td>
            `;
            const gcb = gtr.querySelector('.file-group-checkbox');
            gcb.checked = selected === group.files.length;
            gcb.indeterminate = selected > 0 && selected < group.files.length;
            gcb.addEventListener('change', () => {
                group.files.forEach(f => {
                    if (gcb.checked) selectedFileFilenames.add(f.filename);
                    else selectedFileFilenames.delete(f.filename);
                });
                tbody.querySelectorAll('.file-row-checkbox').forEach(row => {
                    row.checked = selectedFileFilenames.has(row.dataset.fileFilename);
                });
                updateSelectionUI();
            });
            tbody.appendChild(gtr);

            if (!collapsed) {
                group.files.forEach(f => {
                    const tr = buildFileRow(f);
                    tbody.appendChild(tr);
                    bindRowClickToggle(tr, '.file-row-checkbox', ['a', 'button']);
                });
            }
        });
    } else {
        filtered.forEach(f => {
            const tr = buildFileRow(f);
            tbody.appendChild(tr);
            bindRowClickToggle(tr, '.file-row-checkbox', ['a', 'button']);
        });
    }

    // Bind checkbox events
    tbody.querySelectorAll('.file-row-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
            const filename = cb.dataset.fileFilename;
            if (cb.checked) {
                selectedFileFilenames.add(filename);
            } else {
                selectedFileFilenames.delete(filename);
            }
            updateSelectionUI();
        });
    });

    tbody.querySelectorAll('tr.group-header').forEach(tr => {
        tr.addEventListener('click', (e) => {
            if (e.target.closest('input')) return;
            const key = tr.dataset.groupKey;
            if (collapsedFileGroups.has(key)) collapsedFileGroups.delete(key);
            else collapsedFileGroups.add(key);
            renderFiles();
        });
    });

    // Row actions
    tbody.querySelectorAll('.file-preview-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const f = currentFiles.find(item => item.filename === btn.dataset.filename);
            const name = f ? (f.display_name || f.original_name) : btn.dataset.filename;
            openFilePreview({
                name,
                previewUrl: `/api/files/${btn.dataset.filename.split('/').map(encodeURIComponent).join('/')}/preview`,
                downloadUrl: `/api/files/${btn.dataset.filename.split('/').map(encodeURIComponent).join('/')}/download`,
            });
        });
    });

    updateSortArrows(table, fileSortField, fileSortAsc);
    updateSelectionUI();
}

// Standard bulk download: stored archives/containers download directly,
// plain files are bundled into one zip
async function handleBulkDownload() {
    if (selectedFileFilenames.size === 0) return;

    const items = currentFiles.filter(f => selectedFileFilenames.has(f.filename));
    const btn = $('#file-download-btn');
    btn.disabled = true;
    try {
        await bulkDownloadSelection(items, {
            singleUrl: f => `/api/files/${f.filename.split('/').map(encodeURIComponent).join('/')}/download`,
            zipUrl: '/api/files/bulk-download',
            zipBody: names => ({ files: names.map(f => f.filename) }),
        });
    } finally {
        btn.disabled = selectedFileFilenames.size === 0;
    }
}

// ---------------------------------------------------------------------------
// Upload with per-file progress bars and cancel
// ---------------------------------------------------------------------------

function createProgressItem(file, displayName = file.name) {
    const container = document.createElement('div');
    container.className = 'upload-progress-item';
    container.id = `upload-progress-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;

    container.innerHTML = `
        <div class="upload-progress-header">
            <span class="upload-progress-filename" title="${escHtml(displayName)}">${escHtml(displayName)}</span>
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

// Check if any of the given files conflict with existing input files.
// Returns an array of conflicting original filenames.
function getFileConflicts(files) {
    const existingNames = new Set(currentFiles.map(f => f.original_name));
    return Array.from(files).filter(f => existingNames.has(f.name)).map(f => f.name);
}

// Upload files — each file sent as raw request body, each with its own progress bar
async function handleUpload(files, { folder = false } = {}) {
    const fileList = Array.from(files);
    if (fileList.length === 0) return;

    const firstFolderPath = folder ? (fileList[0].webkitRelativePath || fileList[0].name) : '';
    const folderRoot = folder
        ? (firstFolderPath.includes('/') ? firstFolderPath.split('/')[0] : 'folder-upload')
        : null;

    // Folder uploads replace files at the same relative path.
    const conflicts = folder ? [] : getFileConflicts(fileList);
    if (conflicts.length > 0) {
        const detail = conflicts.slice(0, 5).join(', ');
        const suffix = conflicts.length > 5 ? `, and ${conflicts.length - 5} more...` : '';
        const replace = await new Promise((resolve) => {
            showConfirmModal(
                `<strong>${conflicts.length}</strong> file(s) already exist: <code style="font-size: 0.82rem;">${escHtml(detail)}${escHtml(suffix)}</code><br><br>Replace existing file(s)?`,
                {
                    title: 'Replace Files',
                    confirmText: 'Replace',
                    confirmClass: 'btn-primary',
                    onConfirm: () => resolve(true),
                    onCancel: () => resolve(false),
                }
            );
        });
        if (!replace) return;
    }

    const dropzone = $('#file-dropzone');
    const progressList = $('#file-upload-progress-list');

    // Clear any previous selection when starting a new upload
    selectedFileFilenames.clear();

    dropzone.style.display = 'none';
    const folderRow = $('#file-folder-row');
    if (folderRow) folderRow.style.display = 'none';
    progressList.style.display = 'block';
    progressList.innerHTML = '';

    uploadAbortControllers = [];

    // Determine if we need to use overwrite mode
    const overwrite = folder || conflicts.length > 0;

    // Create a progress item for each file
    const uploadItems = fileList.map(file => {
        const relativePath = folder ? (file.webkitRelativePath || file.name) : file.name;
        const uploadPath = folder && relativePath.startsWith(`${folderRoot}/`)
            ? relativePath.slice(folderRoot.length + 1)
            : (folder ? file.name : relativePath);
        return { file, relativePath, uploadPath };
    });
    const progressItems = uploadItems.map(({ file, relativePath, uploadPath }) => {
        const item = createProgressItem(file, relativePath);
        progressList.appendChild(item);
        return { file, relativePath, uploadPath, item, aborted: false };
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

    beginNavigationGuard('File upload is still in progress. Are you sure you want to leave?');

    // Upload each file in parallel
    const uploadPromises = progressItems.map(({ file, relativePath, uploadPath, item }) => {
        const progressFill = item.querySelector('.progress-bar-fill');
        const progressText = item.querySelector('.progress-text');
        const cancelBtn = item.querySelector('.upload-cancel-btn');

        const onProgress = createProgressTracker(progressFill, progressText);
        const headers = {
            ...(overwrite ? { 'X-Overwrite': 'true' } : {}),
            ...(folderRoot ? {
                'X-Upload-Folder': encodeURIComponent(folderRoot),
                'X-Upload-Relative-Path': encodeURIComponent(uploadPath),
            } : {}),
        };

        const { promise, abort } = uploadFileRaw(file, '/api/files', {
            filenameHeader: 'X-Upload-Filename',
            onProgress,
            extraHeaders: headers,
        });

        // Store abort for cancel-all
        uploadAbortControllers.push(abort);

        // Wire cancel button
        cancelBtn.addEventListener('click', () => {
            abort();
            item.classList.add('upload-cancelled');
            progressText.textContent = 'Cancelled';
            progressText.classList.add('progress-error');
            cancelBtn.disabled = true;
        });

        return promise.then(() => {
            successCount++;
            progressFill.style.width = '100%';
            progressText.textContent = 'Complete';
            progressText.classList.add('progress-success');
            cancelBtn.disabled = true;
        }).catch((err) => {
            if (err.name === 'AbortError') {
                // Already handled by cancel button
                return;
            }
            failCount++;
            progressText.textContent = `Failed: ${err.message}`;
            progressText.classList.add('progress-error');
            cancelBtn.disabled = true;
            toast(`Failed to upload '${relativePath}': ${err.message}`, 'error');
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
    try {
        await Promise.all(uploadPromises);
    } finally {
        endNavigationGuard();
    }

    uploadAbortControllers = [];

    const totalFiles = fileList.length;
    if (successCount > 0) {
        const msg = `Uploaded ${successCount} file(s)` + (failCount > 0 ? ` (${failCount} failed)` : '');
        toast(msg);
        setTimeout(() => {
            progressList.style.display = 'none';
            dropzone.style.display = '';
            if (folderRow) folderRow.style.display = 'flex';
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
    if (selectedFileFilenames.size === 0) return;

    const toStage = currentFiles.filter(f => selectedFileFilenames.has(f.filename) && !f.osdf_path);
    if (toStage.length === 0) {
        toast('No selected files are eligible for staging (already in OSDF)', 'warning');
        return;
    }

    toast(`Staging ${toStage.length} file(s) to OSDF...`);
    let successCount = 0;
    let failCount = 0;

    for (const file of toStage) {
        try {
            await api(`/files/${encodeURIComponent(file.filename)}/stage`, { method: 'POST' });
            successCount++;
        } catch (err) {
            failCount++;
            toast(`Failed to stage '${file.filename}': ${err.message}`, 'error');
        }
    }

    toast(`Staged ${successCount} file(s)` + (failCount > 0 ? ` (${failCount} failed)` : ''));
    selectedFileFilenames.clear();
    try {
        await loadFiles();
    } finally {
        updateSelectionUI();
    }
}

// Delete selected files
async function handleBulkDelete() {
    if (selectedFileFilenames.size === 0) return;

    const count = selectedFileFilenames.size;
    const names = currentFiles
        .filter(f => selectedFileFilenames.has(f.filename))
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
                const filenames = [...selectedFileFilenames];
                let successCount = 0;
                let failCount = 0;

                for (const filename of filenames) {
                    try {
                        await api(`/files/${encodeURIComponent(filename)}`, { method: 'DELETE' });
                        successCount++;
                    } catch (err) {
                        failCount++;
                        toast(`Failed to delete file '${filename}': ${err.message}`, 'error');
                    }
                }

                toast(`Deleted ${successCount} file(s)` + (failCount > 0 ? ` (${failCount} failed)` : ''));
                selectedFileFilenames.clear();
                await loadFiles();
            },
        }
    );
}

// Rename single selected file
async function handleBulkRename() {
    if (selectedFileFilenames.size !== 1) {
        toast('Select exactly one file to rename', 'warning');
        return;
    }

    const fileFilename = [...selectedFileFilenames][0];
    const file = currentFiles.find(f => f.filename === fileFilename);
    if (!file) return;

    renameTargetFilename = fileFilename;
    $('#rename-filename').value = file.original_name;
    openModal('rename-modal');
    setTimeout(() => $('#rename-filename').focus(), 100);
}

// Unstage selected files (move back from OSDF to local)
async function handleBulkUnstage() {
    if (selectedFileFilenames.size === 0) return;

    const toUnstage = currentFiles.filter(f => selectedFileFilenames.has(f.filename) && f.osdf_path);
    if (toUnstage.length === 0) {
        toast('No selected files are eligible for unstage (not in OSDF)', 'warning');
        return;
    }

    toast(`Unstaging ${toUnstage.length} file(s) from OSDF...`);
    let successCount = 0;
    let failCount = 0;

    for (const file of toUnstage) {
        try {
            await api(`/files/${encodeURIComponent(file.filename)}/unstage`, { method: 'POST' });
            successCount++;
        } catch (err) {
            failCount++;
            toast(`Failed to unstage '${file.filename}': ${err.message}`, 'error');
        }
    }

    toast(`Unstaged ${successCount} file(s)` + (failCount > 0 ? ` (${failCount} failed)` : ''));
    selectedFileFilenames.clear();
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
    if (renameTargetFilename === null) return;

    try {
        await api(`/files/${encodeURIComponent(renameTargetFilename)}`, {
            method: 'PUT',
            body: JSON.stringify({ filename: newName })
        });
        toast('File renamed');
        closeModal('rename-modal');
        renameTargetFilename = null;
        selectedFileFilenames.clear();
        await loadFiles();
    } catch (err) {
        toast(`Rename failed: ${err.message}`, 'error');
    }
}

// Delete
async function handleDelete() {
    if (deleteTargetFilename === null) return;

    try {
        await api(`/files/${encodeURIComponent(deleteTargetFilename)}`, { method: 'DELETE' });
        toast('File deleted');
        closeModal('delete-modal');
        deleteTargetFilename = null;
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

    const folderInput = $('#file-folder-input');
    const folderBtn = $('#file-folder-btn');
    if (folderInput && folderBtn) {
        folderBtn.addEventListener('click', () => folderInput.click());
        folderInput.addEventListener('change', () => {
            if (folderInput.files.length) {
                handleUpload(folderInput.files, { folder: true });
                folderInput.value = '';
            }
        });
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initModals();
    initUploadDropzone();
    showListLoading('files-empty');
    loadFiles();

    // Select-all checkbox
    $('#file-select-all').addEventListener('change', (e) => {
        const checked = e.target.checked;
        currentFiles.forEach(f => {
            if (checked) {
                selectedFileFilenames.add(f.filename);
            } else {
                selectedFileFilenames.delete(f.filename);
            }
        });
        $$('.file-row-checkbox').forEach(cb => {
            cb.checked = checked;
        });
        updateSelectionUI();
    });

    // Search input
    const searchInput = $('#file-search');
    if (searchInput) {
        searchInput.addEventListener('input', renderFiles);
    }

    // Sortable column headers
    const table = $('#files-table');
    if (table) {
        table.querySelectorAll('thead th.sortable').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                if (field === fileSortField) {
                    fileSortAsc = !fileSortAsc;
                } else {
                    fileSortField = field;
                    fileSortAsc = true;
                }
                renderFiles();
            });
        });
    }

    // Bulk action buttons
    $('#file-stage-btn').addEventListener('click', handleBulkStage);
    $('#file-unstage-btn').addEventListener('click', handleBulkUnstage);
    $('#file-delete-btn').addEventListener('click', handleBulkDelete);
    $('#file-rename-btn').addEventListener('click', handleBulkRename);
    $('#file-download-btn').addEventListener('click', handleBulkDownload);

    // Rename confirm
    $('#rename-confirm-btn').addEventListener('click', handleRename);
    $('#rename-filename').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleRename();
    });

    // Delete confirm
    $('#delete-confirm-btn').addEventListener('click', handleDelete);
});