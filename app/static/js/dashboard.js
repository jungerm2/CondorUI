// =============================================================================
// Unified Jobs Table — merges active (schedd) + history (DB) into one view
// =============================================================================
let currentJobs = [];
let sortField = 'QDate';
let sortAsc = false;
let countdownInterval = null;
let refreshInProgress = false;
let countdown = 30;
const REFRESH_RATE = 30; // seconds
let selectedIds = new Set(); // Set of "clusterId.procId" strings

async function loadJobs() {
    // Prevent concurrent refresh calls
    if (refreshInProgress) return;
    refreshInProgress = true;

    try {
        const limit = $('#history-limit').value;

        // Fetch both active jobs and history in parallel
        const [activeData, historyData] = await Promise.all([
            api('/jobs'),
            api(`/history?limit=${limit}`),
        ]);

        const activeJobs = (activeData.jobs || []).filter(j => !activeData.daemon_unavailable);
        const historyJobs = historyData.jobs || [];

        // Merge: active jobs take precedence by ClusterId
        const seen = new Set();
        const merged = [];

        // Active jobs first (they have real-time status)
        activeJobs.forEach(job => {
            const key = `${job.ClusterId}.${job.ProcId}`;
            seen.add(key);
            merged.push(job);
        });

        // History jobs — skip if already in active
        historyJobs.forEach(job => {
            const key = `${job.ClusterId}.${job.ProcId}`;
            if (!seen.has(key)) {
                seen.add(key);
                merged.push(job);
            }
        });

        currentJobs = merged;
        renderTable();
        renderStats(activeJobs);
    } catch (e) {
        toast('Failed to load jobs: ' + e.message, 'error');
        const tbody = $('#jobs-tbody');
        if (tbody) {
            tbody.innerHTML = `<tr class="empty-row"><td colspan="11">Unable to load jobs. ${e.message}</td></tr>`;
        }
    } finally {
        refreshInProgress = false;
    }
}

function renderStats(activeJobs) {
    const stats = { total: 0, idle: 0, running: 0, held: 0 };
    activeJobs.forEach(job => {
        stats.total++;
        const status = parseInt(job.JobStatus);
        if (status === 1) stats.idle++;
        else if (status === 2) stats.running++;
        else if (status === 5) stats.held++;
    });

    $('#stat-total').textContent = stats.total;
    $('#stat-idle').textContent = stats.idle;
    $('#stat-running').textContent = stats.running;
    $('#stat-held').textContent = stats.held;
}

function getFilteredJobs() {
    const query = $('#job-search').value.toLowerCase().trim();
    const statusFilter = $('#status-filter').value;

    return currentJobs.filter(job => {
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
    $$('#jobs-table thead th.sortable').forEach(th => {
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

    const deleteBtn = $('#delete-btn');
    const editBtn = $('#edit-btn');
    const releaseBtn = $('#release-btn');

    deleteBtn.disabled = count === 0;
    editBtn.disabled = count === 0;
    releaseBtn.disabled = count === 0;

    // Update select-all checkbox
    const selectAll = $('#select-all');
    if (selectAll) {
        const filtered = getFilteredJobs();
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

function renderTable() {
    const tbody = $('#jobs-tbody');
    tbody.innerHTML = '';

    let filtered = getFilteredJobs();
    filtered = sortJobs(filtered);

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr class="empty-row"><td colspan="11">No jobs found</td></tr>`;
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

        // Action buttons based on status
        const statusNum = parseInt(job.JobStatus);
        let actionButtons = '';
        if (statusNum === 5) {
            // Held → release button
            actionButtons = `
                <button class="btn btn-sm btn-ghost release-btn" data-id="${jobKey}" title="Release Job">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <polygon points="5,3 19,12 5,21" />
                    </svg>
                </button>
            `;
        } else if (statusNum === 1 || statusNum === 2) {
            // Idle or Running → hold button
            actionButtons = `
                <button class="btn btn-sm btn-ghost hold-btn" data-id="${jobKey}" title="Hold Job">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <rect x="6" y="4" width="4" height="16" />
                        <rect x="14" y="4" width="4" height="16" />
                    </svg>
                </button>
            `;
        }
        // For completed/removed (3,4), no action buttons

        tr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="row-checkbox" data-job-key="${escHtml(jobKey)}" ${isChecked ? 'checked' : ''}>
            </td>
            <td><div style="display: flex; gap: 4px;">${actionButtons}</div></td>
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
            if (e.target.closest('a') || e.target.closest('input[type="checkbox"]') || e.target.closest('button')) return;
            const cb = tr.querySelector('.row-checkbox');
            if (cb) {
                cb.checked = !cb.checked;
                cb.dispatchEvent(new Event('change'));
            }
        });

        tbody.appendChild(tr);
    });

    // Bind checkbox events
    tbody.querySelectorAll('.row-checkbox').forEach(cb => {
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

    // Bind action button events
    $$('.hold-btn').forEach(btn => btn.addEventListener('click', handleHold));
    $$('.release-btn').forEach(btn => btn.addEventListener('click', handleRelease));

    updateSortArrows();
    updateSelectionUI();
}

// ---------------------------------------------------------------------------
// Single-job actions (hold/release/remove from action buttons)
// ---------------------------------------------------------------------------

async function handleHold(e) {
    const jobId = e.currentTarget.dataset.id;
    try {
        await api(`/jobs/${jobId}/hold`, { method: 'POST' });
        toast(`Job ${jobId} held successfully`);
        countdown = REFRESH_RATE;
        loadJobs();
    } catch (err) {
        toast(`Failed to hold job: ${err.message}`, 'error');
    }
}

async function handleRelease(e) {
    const jobId = e.currentTarget.dataset.id;
    try {
        await api(`/jobs/${jobId}/release`, { method: 'POST' });
        toast(`Job ${jobId} released successfully`);
        countdown = REFRESH_RATE;
        loadJobs();
    } catch (err) {
        toast(`Failed to release job: ${err.message}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Batch selection actions
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
        await loadJobs();
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
        await loadJobs();
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
        onComplete: loadJobs,
        autoRelease: true,
    });
}

// ---------------------------------------------------------------------------
// Auto-refresh
// ---------------------------------------------------------------------------

function startAutoRefresh() {
    countdown = REFRESH_RATE;
    $('#refresh-countdown').textContent = countdown;

    if (countdownInterval) clearInterval(countdownInterval);
    countdownInterval = setInterval(() => {
        countdown--;
        if (countdown <= 0) {
            countdown = REFRESH_RATE;
            loadJobs();
        }
        $('#refresh-countdown').textContent = countdown;
    }, 1000);
}

// ---------------------------------------------------------------------------
// DOM event binding
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    loadJobs();
    startAutoRefresh();

    $('#refresh-btn').addEventListener('click', () => {
        loadJobs();
        startAutoRefresh();
    });

    $('#job-search').addEventListener('input', renderTable);
    $('#status-filter').addEventListener('change', renderTable);
    $('#history-limit').addEventListener('change', loadJobs);

    // Select-all checkbox
    $('#select-all').addEventListener('change', (e) => {
        const checked = e.target.checked;
        const filtered = getFilteredJobs();
        filtered.forEach(job => {
            const key = `${job.ClusterId}.${job.ProcId}`;
            if (checked) {
                selectedIds.add(key);
            } else {
                selectedIds.delete(key);
            }
        });
        $$('.row-checkbox').forEach(cb => {
            cb.checked = checked;
        });
        updateSelectionUI();
    });

    // Sortable column headers
    $$('#jobs-table thead th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const field = th.dataset.sort;
            if (field === sortField) {
                sortAsc = !sortAsc;
            } else {
                sortField = field;
                sortAsc = false;
            }
            renderTable();
        });
    });

    // Batch action buttons
    $('#delete-btn').addEventListener('click', deleteSelected);
    $('#edit-btn').addEventListener('click', editSelected);
    $('#release-btn').addEventListener('click', releaseSelected);
});