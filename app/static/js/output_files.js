// Output Files Management

let currentOutputFiles = [];
// Keyed by "cluster_id/filename" — filenames repeat across clusters
let selectedFiles = new Map(); // key -> {cluster_id, filename}
let outputSortField = 'filename';
let outputSortAsc = true;

const outputKey = (f) => `${f.cluster_id}/${f.filename}`;
const outputHref = (path) => `/api/output-files/${path}`;

// Load output files from API
async function loadOutputFiles() {
    try {
        const data = await api('/output-files');
        currentOutputFiles = data.output_files || [];
        renderOutputFiles();
    } catch (err) {
        toast(`Failed to load output files: ${err.message}`, 'error');
    }
}

// Update selection UI
function updateSelectionUI() {
    const count = selectedFiles.size;
    $('#output-selection-count').textContent = `${count} selected`;
    $('#output-delete-btn').disabled = count === 0;
    $('#output-download-btn').disabled = count === 0;

    // Update select-all checkbox
    updateSelectAllState($('#output-select-all'), currentOutputFiles, selectedFiles, outputKey);
}

// Get sortable value for an output file
function getOutputSortValue(item, field) {
    switch (field) {
        case 'filename': return (item.filename || '').toLowerCase();
        case 'size': return item.size || 0;
        case 'cluster_id': return item.cluster_id || 0;
        case 'job_name': return (item.job_name || '').toLowerCase();
        case 'command': return (item.command || '').toLowerCase();
        case 'modified_at': return item.modified_at || 0;
        default: return 0;
    }
}

// Remember collapsed job groups across re-renders (keyed by cluster id)
const collapsedJobs = new Set();

// One grouped file row: checkbox, folder-aware filename, size, date, actions
function buildOutputFileRow(f) {
    const key = outputKey(f);
    const isChecked = selectedFiles.has(key);
    const slug = `${f.cluster_id}/${f.filename.split('/').map(encodeURIComponent).join('/')}`;
    const parts = f.filename.split('/');
    const base = parts.pop() || f.filename;
    const dir = parts.join('/');

    const tr = document.createElement('tr');
    tr.innerHTML = `
        <td style="text-align: center;">
            <input type="checkbox" class="output-row-checkbox" data-key="${escHtml(key)}" ${isChecked ? 'checked' : ''}>
        </td>
        <td class="monospace" style="max-width: 340px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escHtml(f.filename)}">
            ${dir ? `<span class="file-folder" style="margin-left: ${(dir.split('/').length - 1) * 14}px;">${escHtml(dir)}/</span>` : ''}${escHtml(base)}
        </td>
        <td>${formatFileSize(f.size)}</td>
        <td>${formatDate(f.modified_at)}</td>
        <td>
            <div class="action-btns">
                <button class="btn btn-ghost btn-sm output-preview-btn" data-cluster-id="${f.cluster_id}" data-filename="${escHtml(f.filename)}" title="Preview">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                        <circle cx="12" cy="12" r="3" />
                    </svg>
                </button>
                <a href="${outputHref(`download/${slug}`)}" class="btn btn-ghost btn-sm" title="Download" download>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                        <polyline points="7,10 12,15 17,10" />
                        <line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                </a>
                <button class="btn btn-ghost btn-sm output-delete-btn" data-cluster-id="${f.cluster_id}" data-filename="${escHtml(f.filename)}" title="Delete" style="color: var(--danger-color, #f87171);">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <polyline points="3,6 5,6 21,6" />
                        <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                    </svg>
                </button>
            </div>
        </td>
    `;
    return tr;
}

// Re-bind all row and group events after each render (rows are recreated)
function bindOutputRowEvents(tbody) {
    tbody.querySelectorAll('.output-row-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
            const key = cb.dataset.key;
            if (cb.checked) {
                const file = currentOutputFiles.find(f => outputKey(f) === key);
                selectedFiles.set(key, {
                    cluster_id: file ? file.cluster_id : parseInt(key, 10),
                    filename: file ? file.filename : key.split('/').slice(1).join('/'),
                });
            } else {
                selectedFiles.delete(key);
            }
            updateSelectionUI();
        });
    });

    tbody.querySelectorAll('.output-preview-btn').forEach(btn => {
        btn.addEventListener('click', () => openOutputPreview(btn.dataset.clusterId, btn.dataset.filename));
    });
    tbody.querySelectorAll('.output-delete-btn').forEach(btn => {
        btn.addEventListener('click', () => handleSingleDelete(btn.dataset.clusterId, btn.dataset.filename));
    });

    // Group checkbox: select/deselect only this job's files
    tbody.querySelectorAll('.output-group-checkbox').forEach(gcb => {
        gcb.addEventListener('change', () => {
            const clusterId = parseInt(gcb.dataset.clusterId, 10);
            currentOutputFiles.filter(f => f.cluster_id === clusterId).forEach(f => {
                const key = outputKey(f);
                if (gcb.checked) {
                    selectedFiles.set(key, { cluster_id: f.cluster_id, filename: f.filename });
                } else {
                    selectedFiles.delete(key);
                }
            });
            renderOutputFiles();  // one re-render syncs every checkbox
        });
    });

    // Header click (except links/checkboxes) collapses or expands the job
    tbody.querySelectorAll('tr.group-header').forEach(tr => {
        tr.addEventListener('click', e => {
            if (e.target.closest('a, input, button')) return;
            const id = parseInt(tr.dataset.clusterId, 10);
            if (collapsedJobs.has(id)) collapsedJobs.delete(id); else collapsedJobs.add(id);
            renderOutputFiles();
        });
    });
}

// Render output file list grouped by job: a collapsible header row per
// cluster (job name, file count, total size), file rows beneath it with
// their folder path shown muted so nested output sticks together.
function renderOutputFiles() {
    const tbody = $('#output-files-tbody');
    const empty = $('#output-files-empty');
    const table = $('#output-files-table');

    if (!tbody) return;

    // Apply search filter
    const query = $('#output-search') ? $('#output-search').value : '';
    let filtered = filterData(currentOutputFiles, query, [
        item => item.filename,
        item => item.job_name,
        item => String(item.cluster_id || ''),
        item => item.command,
    ]);

    // Apply sort, then group in order of first appearance: groups inherit
    // the current sort (e.g. by size, jobs are ordered by their largest file)
    filtered = sortData(filtered, outputSortField, outputSortAsc, getOutputSortValue);

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

    const groups = new Map();
    filtered.forEach(f => {
        if (!groups.has(f.cluster_id)) groups.set(f.cluster_id, []);
        groups.get(f.cluster_id).push(f);
    });

    groups.forEach((files, clusterId) => {
        const name = files[0].job_name || `Job #${clusterId}`;
        const totalCount = files.length;
        const totalBytes = files.reduce((sum, f) => sum + (f.size || 0), 0);
        const allSelected = files.every(f => selectedFiles.has(outputKey(f)));
        const someSelected = files.some(f => selectedFiles.has(outputKey(f)));
        const collapsed = collapsedJobs.has(clusterId);

        const gtr = document.createElement('tr');
        gtr.className = 'group-header';
        gtr.dataset.clusterId = clusterId;
        gtr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="output-group-checkbox" data-cluster-id="${clusterId}"
                    ${allSelected ? 'checked' : ''}>
            </td>
            <td colspan="4">
                <span class="expand-chevron ${collapsed ? '' : 'expanded'}"></span>
                <a href="/job/${clusterId}" style="color: var(--accent-cyan);">${escHtml(name)}</a>
                <span class="monospace" style="color: var(--text-muted); margin-left: 6px;">#${clusterId}</span>
                <span style="color: var(--text-muted); margin-left: 10px;">${totalCount} file${totalCount === 1 ? '' : 's'} · ${formatFileSize(totalBytes)}</span>
            </td>
        `;
        const gcb = gtr.querySelector('.output-group-checkbox');
        gcb.indeterminate = someSelected && !allSelected;
        tbody.appendChild(gtr);

        if (!collapsed) {
            files.forEach(f => {
                const row = buildOutputFileRow(f);
                bindRowClickToggle(row, '.output-row-checkbox', ['a', 'button']);
                tbody.appendChild(row);
            });
        }
    });

    bindOutputRowEvents(tbody);

    updateSortArrows(table, outputSortField, outputSortAsc);
    updateSelectionUI();
}

// Delete a single output file from its row
function handleSingleDelete(clusterId, filename) {
    showConfirmModal(
        `Delete output file <strong>${escHtml(filename)}</strong> from cluster <strong>${escHtml(clusterId)}</strong>?<br><br>This cannot be undone.`,
        {
            title: 'Delete Output File',
            confirmText: 'Delete',
            confirmClass: 'btn-danger',
            onConfirm: async () => {
                try {
                    await api(`/output-files/delete/${clusterId}/${encodeURIComponent(filename)}`, { method: 'DELETE' });
                    toast(`Deleted '${filename}'`);
                    selectedFiles.delete(outputKey({ cluster_id: parseInt(clusterId, 10), filename }));
                    await loadOutputFiles();
                } catch (err) {
                    toast(`Failed to delete '${filename}': ${err.message}`, 'error');
                }
            },
        }
    );
}

// Delete selected output files in one request
async function handleBulkDelete() {
    if (selectedFiles.size === 0) return;

    const count = selectedFiles.size;
    const names = [...selectedFiles.keys()].slice(0, 5);
    let detail = names.join(', ');
    if (count > 5) detail += `, and ${count - 5} more...`;

    showConfirmModal(
        `Are you sure you want to delete <strong>${count}</strong> output file(s)?<br><br><code style="font-size: 0.82rem;">${escHtml(detail)}</code>`,
        {
            title: 'Delete Output Files',
            confirmText: `Delete ${count} File(s)`,
            confirmClass: 'btn-danger',
            onConfirm: async () => {
                const files = [...selectedFiles.values()];
                try {
                    const res = await api('/output-files/delete-bulk', {
                        method: 'DELETE',
                        body: JSON.stringify({ files }),
                    });
                    toast(res.message || `Deleted ${files.length} file(s)`);
                    const failed = res.failed || [];
                    if (failed.length > 0) {
                        toast(`${failed.length} file(s) could not be deleted`, 'warning');
                    }
                } catch (err) {
                    toast(`Failed to delete files: ${err.message}`, 'error');
                }
                selectedFiles.clear();
                await loadOutputFiles();
            },
        }
    );
}

// Download selected output files: archives download directly, the rest
// go into one zip
async function handleBulkDownload() {
    if (selectedFiles.size === 0) return;

    const btn = $('#output-download-btn');
    btn.disabled = true;
    try {
        await bulkDownloadSelection([...selectedFiles.values()], {
            singleUrl: f =>
                outputHref(`download/${f.cluster_id}/${f.filename.split('/').map(encodeURIComponent).join('/')}`),
            zipUrl: outputHref('bulk-download'),
            zipBody: files => ({ files }),
        });
    } finally {
        btn.disabled = selectedFiles.size === 0;
    }
}

// Open the shared preview modal for one output file
function openOutputPreview(clusterId, filename) {
    openFilePreview({
        name: filename,
        previewUrl: outputHref(`preview/${clusterId}/${encodeURIComponent(filename)}`),
        downloadUrl: outputHref(`download/${clusterId}/${encodeURIComponent(filename)}`),
    });
}

document.addEventListener('DOMContentLoaded', () => {
    showListLoading('output-files-empty');
    initModals();
    loadOutputFiles();

    // Select-all checkbox — key selections by outputKey(f) so the
    // tri-state updater and row checkboxes see the same keys
    $('#output-select-all').addEventListener('change', (e) => {
        const checked = e.target.checked;
        currentOutputFiles.forEach(f => {
            const key = outputKey(f);
            if (checked) {
                selectedFiles.set(key, { cluster_id: f.cluster_id, filename: f.filename });
            } else {
                selectedFiles.delete(key);
            }
        });
        $$('.output-row-checkbox').forEach(cb => {
            cb.checked = checked;
        });
        updateSelectionUI();
    });

    // Search input
    const searchInput = $('#output-search');
    if (searchInput) {
        searchInput.addEventListener('input', renderOutputFiles);
    }

    // Sortable column headers
    const table = $('#output-files-table');
    if (table) {
        table.querySelectorAll('thead th.sortable').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                if (field === outputSortField) {
                    outputSortAsc = !outputSortAsc;
                } else {
                    outputSortField = field;
                    outputSortAsc = true;
                }
                renderOutputFiles();
            });
        });
    }

    // Bulk delete and bulk download
    $('#output-delete-btn').addEventListener('click', handleBulkDelete);
    $('#output-download-btn').addEventListener('click', handleBulkDownload);
});