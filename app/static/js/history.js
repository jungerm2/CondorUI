let currentHistory = [];
let sortField = 'QDate';
let sortAsc = false;
let historyLoadInProgress = false;
let selectedIds = new Set(); // Set of "clusterId.procId" strings

// Frontend cache for history data — persists across page navigations via sessionStorage
const HISTORY_CACHE_KEY = 'condor_history_cache';
const HISTORY_CACHE_TTL_MS = 120_000; // 2 minutes

function getCachedHistory() {
    try {
        const raw = sessionStorage.getItem(HISTORY_CACHE_KEY);
        if (!raw) return null;
        const cached = JSON.parse(raw);
        if (Date.now() - cached.timestamp > HISTORY_CACHE_TTL_MS) {
            sessionStorage.removeItem(HISTORY_CACHE_KEY);
            return null;
        }
        return cached.data;
    } catch {
        return null;
    }
}

function setCachedHistory(data) {
    try {
        sessionStorage.setItem(HISTORY_CACHE_KEY, JSON.stringify({
            timestamp: Date.now(),
            data: data,
        }));
    } catch {
        // sessionStorage may be full; ignore
    }
}

async function loadHistory() {
    // Prevent concurrent duplicate loads
    if (historyLoadInProgress) return;
    historyLoadInProgress = true;

    const limit = $('#history-limit').value;

    try {
        const data = await api(`/history?limit=${limit}`);
        const jobs = data.jobs || [];
        currentHistory = jobs;
        setCachedHistory(jobs);
        renderHistoryTable();
    } catch (e) {
        toast('Failed to load history: ' + e.message, 'error');
        const tbody = $('#history-tbody');
        if (tbody) {
            tbody.innerHTML = `<tr class="empty-row"><td colspan="10">Unable to load history. ${e.message}</td></tr>`;
        }
    } finally {
        historyLoadInProgress = false;
    }
}

function getFilteredHistory() {
    const query = $('#history-search').value.toLowerCase().trim();
    const statusFilter = $('#history-status-filter').value;

    return currentHistory.filter(job => {
        // Status filter
        if (statusFilter && String(job.JobStatus) !== statusFilter) {
            return false;
        }

        // Text search
        if (!query) return true;

        return (
            String(job.ClusterId).includes(query) ||
            (job.Owner && job.Owner.toLowerCase().includes(query)) ||
            (job.Cmd && job.Cmd.toLowerCase().includes(query)) ||
            (job.Args && job.Args.toLowerCase().includes(query)) ||
            (job.JobBatchName && job.JobBatchName.toLowerCase().includes(query)) ||
            (getStatusName(job.JobStatus) && getStatusName(job.JobStatus).toLowerCase().includes(query))
        );
    });
}

function getSortValue(job, field) {
    switch (field) {
        case 'ClusterId': return job.ClusterId || 0;
        case 'Owner': return (job.Owner || '').toLowerCase();
        case 'Cmd': return (job.Cmd || '').toLowerCase();
        case 'JobStatus': return job.JobStatus || 0;
        case 'ExitCode': return job.ExitCode !== undefined ? job.ExitCode : -1;
        case 'QDate': return job.QDate || 0;
        case 'CompletionDate': return job.CompletionDate || 0;
        case 'RemoteWallClockTime': return parseFloat(job.RemoteWallClockTime) || 0;
        case 'Resources': {
            // Composite sort: CPUs first, then memory, then disk
            const cpus = parseInt(job.RequestCpus) || 0;
            const mem = parseInt(job.RequestMemory) || 0;
            const disk = parseInt(job.RequestDisk) || 0;
            return cpus * 1000000 + mem * 1000 + disk;
        }
        default: return 0;
    }
}

function sortJobs(jobs) {
    const sorted = [...jobs];
    sorted.sort((a, b) => {
        const va = getSortValue(a, sortField);
        const vb = getSortValue(b, sortField);
        if (va < vb) return sortAsc ? -1 : 1;
        if (va > vb) return sortAsc ? 1 : -1;
        return 0;
    });
    return sorted;
}

function updateSortArrows() {
    $$('#history-table thead th.sortable').forEach(th => {
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

function updateSelectionUI() {
    const count = selectedIds.size;
    $('#selection-count').textContent = `${count} selected`;

    const deleteBtn = $('#history-delete-btn');
    const editBtn = $('#history-edit-btn');
    const releaseBtn = $('#history-release-btn');

    deleteBtn.disabled = count === 0;
    editBtn.disabled = count === 0;
    releaseBtn.disabled = count === 0;

    // Update select-all checkbox
    const selectAll = $('#history-select-all');
    if (selectAll) {
        const filtered = getFilteredHistory();
        if (filtered.length > 0) {
            const allSelected = filtered.every(j => selectedIds.has(`${j.ClusterId}.${j.ProcId}`));
            selectAll.checked = allSelected;
            selectAll.indeterminate = !allSelected && filtered.some(j => selectedIds.has(`${j.ClusterId}.${j.ProcId}`));
        } else {
            selectAll.checked = false;
            selectAll.indeterminate = false;
        }
    }
}

function renderHistoryTable() {
    const tbody = $('#history-tbody');
    tbody.innerHTML = '';

    let filtered = getFilteredHistory();
    filtered = sortJobs(filtered);

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr class="empty-row"><td colspan="10">No history records found</td></tr>`;
        updateSelectionUI();
        return;
    }

    filtered.forEach(job => {
        const tr = document.createElement('tr');
        const statusClass = getStatusClass(job.JobStatus);
        const statusName = getStatusName(job.JobStatus);
        const jobKey = `${job.ClusterId}.${job.ProcId}`;

        const qDate = formatDate(job.QDate);
        const compDate = formatDate(job.CompletionDate);

        let wallTime = '—';
        if (job.RemoteWallClockTime) {
            wallTime = formatDuration(Math.round(parseFloat(job.RemoteWallClockTime)));
        } else if (job.CompletionDate && job.QDate) {
            wallTime = formatDuration(job.CompletionDate - job.QDate);
        }

        const exitCode = job.ExitCode !== undefined ? job.ExitCode : '—';
        const cpus = job.RequestCpus || '—';
        const mem = formatMemory(job.RequestMemory);
        const disk = formatDisk(job.RequestDisk);

        const isChecked = selectedIds.has(jobKey);

        tr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="history-row-checkbox" data-job-key="${escHtml(jobKey)}" ${isChecked ? 'checked' : ''}>
            </td>
            <td><a href="/job/${job.ClusterId}/${job.ProcId}" class="job-id-link">${job.ClusterId}.${job.ProcId}</a></td>
            <td>${escHtml(job.Owner || '—')}</td>
            <td class="monospace" title="${escHtml(job.Cmd || job.Args || '')}">${formatCommand(job.Cmd, job.Args)}</td>
            <td><span class="status-badge ${statusClass}">${statusName}</span></td>
            <td class="monospace">${exitCode}</td>
            <td>${qDate}</td>
            <td>${compDate}</td>
            <td>${wallTime}</td>
            <td style="font-size: 0.85rem;">${cpus} CPU, ${mem}, ${disk}</td>
        `;

        // Row click toggles checkbox
        tr.addEventListener('click', (e) => {
            // Don't toggle if clicking a link or the checkbox itself
            if (e.target.closest('a') || e.target.closest('input[type="checkbox"]')) return;
            const cb = tr.querySelector('.history-row-checkbox');
            if (cb) {
                cb.checked = !cb.checked;
                cb.dispatchEvent(new Event('change'));
            }
        });

        tbody.appendChild(tr);
    });

    // Bind checkbox events
    tbody.querySelectorAll('.history-row-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
            const key = cb.dataset.jobKey;
            if (cb.checked) {
                selectedIds.add(key);
            } else {
                selectedIds.delete(key);
            }
            updateSelectionUI();
        });
    });

    updateSortArrows();
    updateSelectionUI();
}

// ---------------------------------------------------------------------------
// Selection actions
// ---------------------------------------------------------------------------

async function deleteSelected() {
    if (selectedIds.size === 0) return;

    const count = selectedIds.size;
    if (!confirm(`Are you sure you want to delete ${count} job(s)? This will remove them from the schedd, database, and logs.`)) return;

    const clusterIds = [...selectedIds].map(key => parseInt(key.split('.')[0]));

    try {
        const result = await api('/history/delete', {
            method: 'POST',
            body: JSON.stringify({ cluster_ids: clusterIds }),
        });
        toast(`Deleted ${result.count} job(s) successfully`);
        selectedIds.clear();
        await loadHistory();
    } catch (err) {
        toast(`Failed to delete: ${err.message}`, 'error');
    }
}

async function releaseSelected() {
    if (selectedIds.size === 0) return;

    const clusterIds = [...selectedIds].map(key => parseInt(key.split('.')[0]));

    try {
        const result = await api('/history/release', {
            method: 'POST',
            body: JSON.stringify({ cluster_ids: clusterIds }),
        });
        const successCount = result.results.filter(r => r.success).length;
        toast(`Released ${successCount} job(s)`);
        await loadHistory();
    } catch (err) {
        toast(`Failed to release: ${err.message}`, 'error');
    }
}

function editSelected() {
    if (selectedIds.size === 0) return;

    const jobs = [...selectedIds].map(key => {
        const [clusterId, procId] = key.split('.');
        return { clusterId: parseInt(clusterId), procId: parseInt(procId || '0') };
    });

    openQeditDialog(jobs, {
        onComplete: loadHistory,
        autoRelease: true,
    });
}

// ---------------------------------------------------------------------------
// DOM event binding
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    loadHistory();

    // Refresh
    $('#refresh-history-btn').addEventListener('click', loadHistory);

    // Limit
    $('#history-limit').addEventListener('change', loadHistory);

    // Search / filter
    $('#history-search').addEventListener('input', renderHistoryTable);
    $('#history-status-filter').addEventListener('change', renderHistoryTable);

    // Select-all checkbox
    $('#history-select-all').addEventListener('change', (e) => {
        const checked = e.target.checked;
        const filtered = getFilteredHistory();
        filtered.forEach(job => {
            const key = `${job.ClusterId}.${job.ProcId}`;
            if (checked) {
                selectedIds.add(key);
            } else {
                selectedIds.delete(key);
            }
        });
        // Update all visible checkboxes
        $$('.history-row-checkbox').forEach(cb => {
            cb.checked = checked;
        });
        updateSelectionUI();
    });

    // Sortable column headers
    $$('#history-table thead th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const field = th.dataset.sort;
            if (field === sortField) {
                sortAsc = !sortAsc;
            } else {
                sortField = field;
                sortAsc = false;
            }
            renderHistoryTable();
        });
    });

    // Action buttons
    $('#history-delete-btn').addEventListener('click', deleteSelected);
    $('#history-edit-btn').addEventListener('click', editSelected);
    $('#history-release-btn').addEventListener('click', releaseSelected);
});