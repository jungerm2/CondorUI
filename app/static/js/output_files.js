// Output Files Management

let currentOutputFiles = [];
let selectedFiles = new Map(); // filename -> {cluster_id, filename}
let outputSortField = 'filename';
let outputSortAsc = true;

// formatFileSize and formatDate are now defined in common.js
// These duplicates have been removed; use the shared versions instead.

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

    // Update select-all checkbox
    const selectAll = $('#output-select-all');
    if (selectAll) {
        if (currentOutputFiles.length > 0) {
            const allSelected = currentOutputFiles.every(f => selectedFiles.has(f.filename));
            selectAll.checked = allSelected;
            selectAll.indeterminate = !allSelected && currentOutputFiles.some(f => selectedFiles.has(f.filename));
        } else {
            selectAll.checked = false;
            selectAll.indeterminate = false;
        }
    }
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

// Render output file list
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

    // Apply sort
    filtered = sortData(filtered, outputSortField, outputSortAsc, getOutputSortValue);

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
        const isChecked = selectedFiles.has(f.filename);
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="output-row-checkbox" data-filename="${escHtml(f.filename)}" ${isChecked ? 'checked' : ''}>
            </td>
            <td class="monospace">${escHtml(f.filename)}</td>
            <td>${formatFileSize(f.size)}</td>
            <td>
                <a href="/job/${f.cluster_id}" style="color: var(--accent-cyan);">${f.cluster_id}</a>
            </td>
            <td>
                <a href="/job/${f.cluster_id}" style="color: var(--accent-cyan);">${escHtml(f.job_name || 'Job #' + f.cluster_id)}</a>
            </td>
            <td class="monospace" style="max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escHtml(f.command || '')}">${escHtml(f.command || '—')}</td>
            <td>${formatDate(f.modified_at)}</td>
            <td>
                <a href="/api/output-files/download/${f.cluster_id}/${encodeURIComponent(f.filename)}" class="btn btn-ghost btn-sm" style="padding: 4px 8px;">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                        <polyline points="7,10 12,15 17,10" />
                        <line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                    Download
                </a>
            </td>
        `;
        tbody.appendChild(tr);

        // Row click toggles checkbox
        tr.addEventListener('click', (e) => {
            if (e.target.closest('a') || e.target.closest('input[type="checkbox"]')) return;
            const cb = tr.querySelector('.output-row-checkbox');
            if (cb) {
                cb.checked = !cb.checked;
                cb.dispatchEvent(new Event('change'));
            }
        });
    });

    // Bind checkbox events
    tbody.querySelectorAll('.output-row-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
            const filename = cb.dataset.filename;
            if (cb.checked) {
                // Find the cluster_id for this filename from currentOutputFiles
                const file = currentOutputFiles.find(f => f.filename === filename);
                selectedFiles.set(filename, { cluster_id: file ? file.cluster_id : null, filename });
            } else {
                selectedFiles.delete(filename);
            }
            updateSelectionUI();
        });
    });

    updateSortArrows(table, outputSortField, outputSortAsc);
    updateSelectionUI();
}

// Delete selected output files
async function handleBulkDelete() {
    if (selectedFiles.size === 0) return;

    const count = selectedFiles.size;
    const names = [...selectedFiles.keys()].slice(0, 5);
    let detail = names.join(', ');
    if (count > 5) detail += `, and ${count - 5} more...`;

    // Show confirmation modal
    showConfirmModal(
        `Are you sure you want to delete <strong>${count}</strong> output file(s)?<br><br><code style="font-size: 0.82rem;">${escHtml(detail)}</code>`,
        {
            title: 'Delete Output Files',
            confirmText: `Delete ${count} File(s)`,
            confirmClass: 'btn-danger',
            onConfirm: async () => {
                let successCount = 0;
                let failCount = 0;

                for (const [filename, info] of selectedFiles) {
                    try {
                        await api(`/output-files/delete/${info.cluster_id}/${encodeURIComponent(filename)}`, { method: 'DELETE' });
                        successCount++;
                    } catch (err) {
                        failCount++;
                        toast(`Failed to delete '${filename}': ${err.message}`, 'error');
                    }
                }

                toast(`Deleted ${successCount} file(s)` + (failCount > 0 ? ` (${failCount} failed)` : ''));
                selectedFiles.clear();
                await loadOutputFiles();
            },
        }
    );
}

document.addEventListener('DOMContentLoaded', () => {
    loadOutputFiles();

    // Select-all checkbox
    $('#output-select-all').addEventListener('change', (e) => {
        const checked = e.target.checked;
        currentOutputFiles.forEach(f => {
            if (checked) {
                selectedFiles.set(f.filename, { cluster_id: f.cluster_id, filename: f.filename });
            } else {
                selectedFiles.delete(f.filename);
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

    // Bulk delete
    $('#output-delete-btn').addEventListener('click', handleBulkDelete);
});