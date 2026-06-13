// Container Management

let currentContainers = [];
let renameTargetId = null;
let deleteTargetId = null;
let osdfConfigured = false;

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

// Render container list
function renderContainers() {
    const tbody = $('#containers-tbody');
    const empty = $('#containers-empty');
    const table = $('#containers-table');

    if (!tbody) return;

    tbody.innerHTML = '';

    if (currentContainers.length === 0) {
        table.style.display = 'none';
        empty.style.display = 'block';
        return;
    }

    table.style.display = '';
    empty.style.display = 'none';

    currentContainers.forEach(c => {
        const tr = document.createElement('tr');
        const sourceLabel = c.source && c.source.startsWith('uploaded:')
            ? `Uploaded: ${c.source.replace('uploaded:', '')}`
            : (c.source || '—');

        tr.innerHTML = `
            <td class="monospace" style="font-weight: 500;">${escHtml(c.name)}</td>
            <td class="monospace" style="font-size: 0.82rem; max-width: 200px; overflow: hidden; text-overflow: ellipsis;" title="${escHtml(c.source || '')}">${escHtml(sourceLabel)}</td>
            <td>${formatFileSize(c.size)}</td>
            <td>${formatDate(c.created_at)}</td>
            <td class="monospace" style="font-size: 0.8rem; max-width: 250px; overflow: hidden; text-overflow: ellipsis;" title="${escHtml(c.uri)}">${escHtml(c.uri)}</td>
            <td>
                <div class="action-btns">
                    <button class="btn btn-ghost btn-sm rename-container-btn" data-id="${c.id}" title="Rename">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                            <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
                        </svg>
                        Rename
                    </button>
                    <button class="btn btn-ghost btn-sm delete-container-btn" data-id="${c.id}" data-name="${escHtml(c.name)}" title="Delete" style="color: var(--danger-color, #f87171);">
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
        btn.addEventListener('click', () => openRenameModal(parseInt(btn.dataset.id)));
    });
    tbody.querySelectorAll('.delete-container-btn').forEach(btn => {
        btn.addEventListener('click', () => openDeleteModal(parseInt(btn.dataset.id), btn.dataset.name));
    });
}

// Pull container
async function handlePull() {
    const imageRef = $('#pull-image-ref').value.trim();
    const name = $('#pull-image-name').value.trim() || '';

    if (!imageRef) {
        toast('Docker image reference is required', 'warning');
        return;
    }

    const pullBtn = $('#pull-container-btn');
    pullBtn.disabled = true;
    pullBtn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" style="animation: spin 1s linear infinite;">
            <circle cx="12" cy="12" r="10" stroke-dasharray="32" stroke-dashoffset="32" />
        </svg>
        Pulling...
    `;

    toast('Pulling container image... This may take a while.');

    try {
        const result = await api('/containers/pull', {
            method: 'POST',
            body: JSON.stringify({ image: imageRef, name })
        });
        toast(`Container '${result.name}' pulled successfully!`);
        $('#pull-image-ref').value = '';
        $('#pull-image-name').value = '';
        await loadContainers();
    } catch (err) {
        toast(`Pull failed: ${err.message}`, 'error');
    } finally {
        pullBtn.disabled = false;
        pullBtn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                <polyline points="7,10 12,15 17,10" />
                <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            Pull
        `;
    }
}

// Upload .sif with progress bar
function handleSifUpload(file) {
    const name = $('#upload-sif-name').value.trim() || '';

    const formData = new FormData();
    formData.append('file', file);
    if (name) formData.append('name', name);

    // Show progress bar
    const progressContainer = $('#sif-upload-progress');
    const progressFill = $('#sif-upload-progress-fill');
    const progressText = $('#sif-upload-progress-text');
    const dropzone = $('#sif-dropzone');

    dropzone.style.display = 'none';
    progressContainer.style.display = 'block';
    progressFill.style.width = '0%';
    progressText.textContent = 'Uploading...';

    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable) {
            const pct = Math.round((e.loaded / e.total) * 100);
            progressFill.style.width = pct + '%';
            const uploadedMb = (e.loaded / (1024 * 1024)).toFixed(1);
            const totalMb = (e.total / (1024 * 1024)).toFixed(1);
            progressText.textContent = `${uploadedMb} MB / ${totalMb} MB (${pct}%)`;
        }
    });

    xhr.addEventListener('load', async () => {
        if (xhr.status >= 200 && xhr.status < 300) {
            try {
                const data = JSON.parse(xhr.responseText);
                toast(`Container '${data.name}' uploaded successfully!`);
                $('#upload-sif-name').value = '';
                progressFill.style.width = '100%';
                progressText.textContent = 'Complete!';
                setTimeout(() => {
                    progressContainer.style.display = 'none';
                    dropzone.style.display = '';
                }, 1500);
                await loadContainers();
            } catch (e) {
                toast('Upload succeeded but failed to parse response', 'error');
                resetUploadUI();
            }
        } else {
            let msg = 'Upload failed';
            try {
                const data = JSON.parse(xhr.responseText);
                msg = data.error || msg;
            } catch (e) { /* ignore */ }
            toast(msg, 'error');
            resetUploadUI();
        }
    });

    xhr.addEventListener('error', () => {
        toast('Upload failed due to a network error', 'error');
        resetUploadUI();
    });

    xhr.addEventListener('abort', () => {
        toast('Upload cancelled', 'warning');
        resetUploadUI();
    });

    xhr.open('POST', '/api/containers/upload');
    xhr.send(formData);
}

function resetUploadUI() {
    const progressContainer = $('#sif-upload-progress');
    const dropzone = $('#sif-dropzone');
    if (progressContainer) progressContainer.style.display = 'none';
    if (dropzone) dropzone.style.display = '';
}

// Rename
function openRenameModal(containerId) {
    const container = currentContainers.find(c => c.id === containerId);
    if (!container) return;
    renameTargetId = containerId;
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
    if (renameTargetId === null) return;

    try {
        await api(`/containers/${renameTargetId}`, {
            method: 'PUT',
            body: JSON.stringify({ name: newName })
        });
        toast('Container renamed');
        closeModal('rename-modal');
        renameTargetId = null;
        await loadContainers();
    } catch (err) {
        toast(`Rename failed: ${err.message}`, 'error');
    }
}

// Delete
function openDeleteModal(containerId, containerName) {
    deleteTargetId = containerId;
    $('#delete-container-name-display').textContent = containerName;
    openModal('delete-modal');
}

async function handleDelete() {
    if (deleteTargetId === null) return;

    try {
        await api(`/containers/${deleteTargetId}`, { method: 'DELETE' });
        toast('Container deleted');
        closeModal('delete-modal');
        deleteTargetId = null;
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

    // Rename confirm
    $('#rename-confirm-btn').addEventListener('click', handleRename);
    $('#rename-container-name').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleRename();
    });

    // Delete confirm
    $('#delete-confirm-btn').addEventListener('click', handleDelete);
});