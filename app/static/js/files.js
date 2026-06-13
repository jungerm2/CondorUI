// Input Files Management

let currentFiles = [];
let renameTargetId = null;
let deleteTargetId = null;

// Modal helpers
function openModal(id) {
    document.getElementById(id).classList.add('active');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('active');
}

function initModals() {
    // Close buttons
    document.querySelectorAll('.modal-close-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const modalId = btn.dataset.modal;
            if (modalId) closeModal(modalId);
        });
    });
    // Close on overlay click
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

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="monospace">${escHtml(f.filename)}</td>
            <td class="monospace">${escHtml(f.original_name)}</td>
            <td>${formatFileSize(f.size)}</td>
            <td>${formatDate(f.uploaded_at)}</td>
            <td><span class="badge ${locationClass}">${locationLabel}</span></td>
            <td>
                <div class="action-btns">
                    ${!isOsdf ? `<button class="btn btn-ghost btn-sm stage-file-btn" data-id="${f.id}" title="Stage to OSDF">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                            <polyline points="17,8 12,3 7,8" />
                            <line x1="12" y1="3" x2="12" y2="15" />
                        </svg>
                        Stage
                    </button>` : ''}
                    <button class="btn btn-ghost btn-sm rename-file-btn" data-id="${f.id}" title="Rename">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                            <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
                        </svg>
                        Rename
                    </button>
                    <button class="btn btn-ghost btn-sm delete-file-btn" data-id="${f.id}" data-name="${escHtml(f.filename)}" title="Delete" style="color: var(--danger-color, #f87171);">
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
    tbody.querySelectorAll('.stage-file-btn').forEach(btn => {
        btn.addEventListener('click', () => handleStage(parseInt(btn.dataset.id)));
    });
    tbody.querySelectorAll('.rename-file-btn').forEach(btn => {
        btn.addEventListener('click', () => openRenameModal(parseInt(btn.dataset.id)));
    });
    tbody.querySelectorAll('.delete-file-btn').forEach(btn => {
        btn.addEventListener('click', () => openDeleteModal(parseInt(btn.dataset.id), btn.dataset.name));
    });
}

// Upload files
async function handleUpload(files) {
    const formData = new FormData();
    for (const file of files) {
        formData.append('files', file);
    }

    toast('Uploading files...');
    try {
        const res = await fetch('/api/files', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Upload failed');

        toast(`Uploaded ${data.count} file(s)`);
        await loadFiles();
    } catch (err) {
        toast(`Upload failed: ${err.message}`, 'error');
    }
}

// Stage to OSDF
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
function openRenameModal(fileId) {
    const file = currentFiles.find(f => f.id === fileId);
    if (!file) return;
    renameTargetId = fileId;
    $('#rename-filename').value = file.filename;
    openModal('rename-modal');
    setTimeout(() => $('#rename-filename').focus(), 100);
}

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
        await loadFiles();
    } catch (err) {
        toast(`Rename failed: ${err.message}`, 'error');
    }
}

// Delete
function openDeleteModal(fileId, fileName) {
    deleteTargetId = fileId;
    $('#delete-filename-display').textContent = fileName;
    openModal('delete-modal');
}

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

    // Rename confirm
    $('#rename-confirm-btn').addEventListener('click', handleRename);
    $('#rename-filename').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleRename();
    });

    // Delete confirm
    $('#delete-confirm-btn').addEventListener('click', handleDelete);
});