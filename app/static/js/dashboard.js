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
        case 'JobBatchName': return (job.JobBatchName || '').toLowerCase();
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
    const holdBtn = $('#hold-btn');
    const releaseBtn = $('#release-btn');

    deleteBtn.disabled = count === 0;
    editBtn.disabled = count === 0;
    holdBtn.disabled = count === 0;
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
        const name = job.JobBatchName || '—';

        const isChecked = selectedIds.has(jobKey);

        tr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="row-checkbox" data-job-key="${escHtml(jobKey)}" ${isChecked ? 'checked' : ''}>
            </td>
            <td><a href="/job/${job.ClusterId}/${job.ProcId}" class="job-id-link">${job.ClusterId}.${job.ProcId}</a></td>
            <td style="max-width: 120px; overflow: hidden; text-overflow: ellipsis;" title="${escHtml(name)}">${escHtml(name)}</td>
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
            if (e.target.closest('a') || e.target.closest('input[type="checkbox"]')) return;
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

    updateSortArrows();
    updateSelectionUI();
}

// ---------------------------------------------------------------------------
// Batch selection actions
// ---------------------------------------------------------------------------

async function deleteSelected() {
    if (selectedIds.size === 0) return;

    const count = selectedIds.size;
    const clusterIds = [...selectedIds].map(key => parseInt(key.split('.')[0]));

    const names = clusterIds.slice(0, 5).map(cid => `#${cid}`);
    let detail = names.join(', ');
    if (clusterIds.length > 5) detail += `, and ${clusterIds.length - 5} more...`;

    showConfirmModal(
        `Are you sure you want to delete <strong>${count}</strong> job(s)? This will remove them from the schedd, database, and logs.<br><br><code style="font-size: 0.82rem;">${escHtml(detail)}</code>`,
        {
            title: 'Delete Jobs',
            confirmText: `Delete ${count} Job(s)`,
            confirmClass: 'btn-danger',
            onConfirm: async () => {
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
            },
        }
    );
}

async function holdSelected() {
    if (selectedIds.size === 0) return;

    const clusterIds = [...selectedIds].map(key => parseInt(key.split('.')[0]));

    let heldCount = 0;
    for (const cid of clusterIds) {
        try {
            await api(`/jobs/${cid}.0/hold`, { method: 'POST' });
            heldCount++;
        } catch {
            // Job may already be held or not in schedd; skip
        }
    }
    toast(`Held ${heldCount} job(s)`);
    await loadJobs();
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
// Disk Quota Widgets — one card per quota
// ---------------------------------------------------------------------------

async function loadQuotas() {
    const container = $('#quota-cards-container');
    if (!container) return;

    try {
        const data = await api('/quotas');
        if (!data.quotas || data.quotas.length === 0) {
            container.innerHTML = '';
            return;
        }

        // Build one card per quota
        container.innerHTML = data.quotas.map(quota => {
            const usedGb = quota.disk_used_gb || 0;
            const limitGb = quota.disk_limit_gb || 0;
            const filesUsed = quota.files_used != null ? quota.files_used : null;
            const fileLimit = quota.file_limit != null ? quota.file_limit : null;
            const path = quota.path || '';

            // Determine usage percentage for bar styling
            let pct = 0;
            let barClass = '';
            if (limitGb > 0) {
                pct = Math.min((usedGb / limitGb) * 100, 100);
                if (pct >= 90) barClass = 'quota-bar-danger';
                else if (pct >= 75) barClass = 'quota-bar-warning';
            }

            // Format numbers
            const usedStr = usedGb.toFixed(2);
            const limitStr = limitGb.toFixed(2);

            return `<div class="stat-card quota-card">
                <div class="stat-icon" style="background: rgba(52, 211, 153, 0.1); color: var(--status-running);">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                        <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
                    </svg>
                </div>
                <div class="stat-info quota-info">
                    <span class="quota-path" title="${escHtml(path)}">${escHtml(path || '/')}</span>
                    <span class="quota-usage">${usedStr} GB ${limitGb > 0 ? `/ ${limitStr} GB` : ''}</span>
                    ${limitGb > 0 ? `<div class="quota-bar-container"><div class="quota-bar-fill ${barClass}" style="width: ${pct}%"></div></div>` : ''}
                    <span class="quota-detail">${filesUsed != null ? `${filesUsed.toLocaleString()} files` : ''}${filesUsed != null && fileLimit != null ? ` / ${fileLimit.toLocaleString()}` : ''}</span>
                </div>
            </div>`;
        }).join('');
    } catch (err) {
        // Quota command may not be available; hide the container
        container.innerHTML = '';
    }
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
    loadQuotas();
    startAutoRefresh();

    $('#refresh-btn').addEventListener('click', () => {
        loadJobs();
        loadQuotas();
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
    $('#hold-btn').addEventListener('click', holdSelected);
    $('#release-btn').addEventListener('click', releaseSelected);
});