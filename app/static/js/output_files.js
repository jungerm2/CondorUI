// Output Files Management

let currentOutputFiles = [];
let selectedFileIds = new Set();

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
    const count = selectedFileIds.size;
    $('#output-selection-count').textContent = `${count} selected`;
    $('#output-delete-btn').disabled = count === 0;

    // Update select-all checkbox
    const selectAll = $('#output-select-all');
    if (selectAll) {
        if (currentOutputFiles.length > 0) {
            const allSelected = currentOutputFiles.every(f => selectedFileIds.has(f.filename));
            selectAll.checked = allSelected;
            selectAll.indeterminate = !allSelected && currentOutputFiles.some(f => selectedFileIds.has(f.filename));
        } else {
            selectAll.checked = false;
            selectAll.indeterminate = false;
        }
    }
}

// Render output file list
function renderOutputFiles() {
    const tbody = $('#output-files-tbody');
    const empty = $('#output-files-empty');
    const table = $('#output-files-table');

    if (!tbody) return;

    tbody.innerHTML = '';

    if (currentOutputFiles.length === 0) {
        table.style.display = 'none';
        empty.style.display = 'block';
        return;
    }

    table.style.display = '';
    empty.style.display = 'none';

    currentOutputFiles.forEach(f => {
        const isChecked = selectedFileIds.has(f.filename);
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="output-row-checkbox" data-filename="${escHtml(f.filename)}" ${isChecked ? 'checked' : ''}>
            </td>
            <td class="monospace">${escHtml(f.filename)}</td>
            <td>${formatFileSize(f.size)}</td>
            <td>
                <a href="/job/${f.cluster_id}" style="color: var(--accent-cyan);">${escHtml(f.job_name || 'Job #' + f.cluster_id)}</a>
            </td>
            <td>${formatDate(f.modified_at)}</td>
            <td>
                <a href="/api/output-files/${encodeURIComponent(f.filename)}/download" class="btn btn-ghost btn-sm" style="padding: 4px 8px;">
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
                selectedFileIds.add(filename);
            } else {
                selectedFileIds.delete(filename);
            }
            updateSelectionUI();
        });
    });

    updateSelectionUI();
}

// Delete selected output files
async function handleBulkDelete() {
    if (selectedFileIds.size === 0) return;

    const count = selectedFileIds.size;
    const names = [...selectedFileIds].slice(0, 5);
    let detail = names.join(', ');
    if (count > 5) detail += `, and ${count - 5} more...`;

    if (!confirm(`Are you sure you want to delete ${count} output file(s)?\n\n${detail}`)) return;

    let successCount = 0;
    let failCount = 0;

    for (const filename of selectedFileIds) {
        try {
            await api(`/output-files/${encodeURIComponent(filename)}`, { method: 'DELETE' });
            successCount++;
        } catch (err) {
            failCount++;
            toast(`Failed to delete '${filename}': ${err.message}`, 'error');
        }
    }

    toast(`Deleted ${successCount} file(s)` + (failCount > 0 ? ` (${failCount} failed)` : ''));
    selectedFileIds.clear();
    await loadOutputFiles();
}

document.addEventListener('DOMContentLoaded', () => {
    loadOutputFiles();

    // Select-all checkbox
    $('#output-select-all').addEventListener('change', (e) => {
        const checked = e.target.checked;
        currentOutputFiles.forEach(f => {
            if (checked) {
                selectedFileIds.add(f.filename);
            } else {
                selectedFileIds.delete(f.filename);
            }
        });
        $$('.output-row-checkbox').forEach(cb => {
            cb.checked = checked;
        });
        updateSelectionUI();
    });

    // Bulk delete
    $('#output-delete-btn').addEventListener('click', handleBulkDelete);
});