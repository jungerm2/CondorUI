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
let groupByCluster = true; // Group by ClusterId toggle (default on)
let clusterFilter = null; // Cluster ID filter from URL (?cluster_id=X), null if not set

let lastActiveJobs = []; // Track last active jobs for stats

async function loadJobs() {
    // Prevent concurrent refresh calls
    if (refreshInProgress) return;
    refreshInProgress = true;

    try {
        const limit = $('#history-limit').value;

        // Build active jobs URL with optional cluster filter
        let activeUrl = '/jobs';
        if (clusterFilter) {
            activeUrl += `?cluster_id=${clusterFilter}`;
        }

        // Fetch both active jobs and history in parallel
        const [activeData, historyData] = await Promise.all([
            api(activeUrl),
            api(`/history?limit=${limit}`),
        ]);

        const activeJobs = (activeData.jobs || []).filter(j => !activeData.daemon_unavailable);
        let historyJobs = historyData.jobs || [];

        // If cluster filter is active, also filter history client-side
        if (clusterFilter) {
            historyJobs = historyJobs.filter(j => String(j.ClusterId) === String(clusterFilter));
        }

        lastActiveJobs = activeJobs;

        // Merge: active jobs take precedence by ClusterId.ProcId
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
            tbody.innerHTML = `<tr class="empty-row"><td colspan="12">Unable to load jobs. ${e.message}</td></tr>`;
        }
    } finally {
        refreshInProgress = false;
    }
}

function renderStats(activeJobs) {
    const stats = { total: 0, idle: 0, running: 0, completed: 0, held: 0 };

    // Total = all merged jobs (active + completed history)
    stats.total = currentJobs.length;

    // Idle, Running, Held = from active schedd jobs only
    activeJobs.forEach(job => {
        const status = parseInt(job.JobStatus);
        if (status === 1) stats.idle++;
        else if (status === 2) stats.running++;
        else if (status === 5) stats.held++;
    });

    // Completed = count of status 4 across ALL merged jobs
    currentJobs.forEach(job => {
        if (parseInt(job.JobStatus) === 4) stats.completed++;
    });

    $('#stat-total').textContent = stats.total;
    $('#stat-idle').textContent = stats.idle;
    $('#stat-running').textContent = stats.running;
    $('#stat-completed').textContent = stats.completed;
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
            const gpus = parseInt(job.RequestGPUs) || 0;
            return cpus * 1000000 + mem * 1000 + disk * 10 + gpus;
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

// ---------------------------------------------------------------------------
// Status Bar Helper — builds a stacked bar showing status distribution
// ---------------------------------------------------------------------------

function renderStatusBar(jobs) {
    // Count jobs by status
    const counts = {};
    jobs.forEach(job => {
        const status = parseInt(job.JobStatus);
        counts[status] = (counts[status] || 0) + 1;
    });

    const total = jobs.length;
    if (total === 0) return '<span class="status-badge status-completed">—</span>';

    // Define status order and labels
    const statusOrder = [4, 2, 6, 1, 5, 3]; // Completed, Running, Transferring, Idle, Held, Removed
    const statusLabels = {
        1: 'Idle', 2: 'Running', 3: 'Removed', 4: 'Completed', 5: 'Held', 6: 'Transferring'
    };
    const statusClasses = {
        1: 'status-idle', 2: 'status-running', 3: 'status-removed',
        4: 'status-completed', 5: 'status-held', 6: 'status-transferring'
    };

    // Build segments
    let segments = '';
    statusOrder.forEach(status => {
        const count = counts[status] || 0;
        if (count === 0) return;
        const pct = (count / total) * 100;
        const label = statusLabels[status] || 'Unknown';
        const cls = statusClasses[status] || 'status-unknown';
        segments += `<div class="status-bar-segment ${cls}" style="width: ${pct}%" title="${count} ${label} (${Math.round(pct)}%)"></div>`;
    });

    // If no segments match known statuses, show a fallback
    if (!segments) {
        const otherCount = total;
        segments = `<div class="status-bar-segment status-completed" style="width: 100%" title="${otherCount} jobs"></div>`;
    }

    return `<div class="status-bar">${segments}</div>`;
}

// ---------------------------------------------------------------------------
// Filter Badge — shows when a cluster filter is active
// ---------------------------------------------------------------------------

function renderFilterBadge() {
    const container = $('#filter-badge-container');
    if (!container) return;

    if (!clusterFilter) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = `
        <span class="filter-badge">
            🔍 Cluster: ${clusterFilter}
            <button class="filter-badge-clear" id="clear-filter-btn" title="Clear filter">✕</button>
        </span>
    `;

    $('#clear-filter-btn').addEventListener('click', () => {
        clusterFilter = null;
        // Update URL without reloading
        const url = new URL(window.location);
        url.searchParams.delete('cluster_id');
        window.history.replaceState({}, '', url);
        // Re-enable group toggle
        $('#group-toggle').disabled = false;
        renderFilterBadge();
        loadJobs();
    });
}

// ---------------------------------------------------------------------------
// Update table header column labels based on current view mode
// ---------------------------------------------------------------------------

function updateTableHeaders() {
    const isGrouped = groupByCluster && !clusterFilter;
    const headers = $$('#jobs-table thead th.sortable');
    // Headers in order: 0=ClusterId, 1=JobBatchName, 2=Owner, 3=Cmd, 4=JobStatus, 5=ExitCode, 6=Procs, 7=QDate, 8=CompletionDate, 9=RemoteWallClockTime, 10=Resources
    if (headers.length >= 11) {
        // Exit code column: hide in grouped view
        const exitCodeTh = headers[5];
        if (exitCodeTh) {
            exitCodeTh.style.display = isGrouped ? 'none' : '';
        }

        // Procs column: show in grouped view, hide in flat view
        const procsTh = headers[6];
        if (procsTh) {
            procsTh.style.display = isGrouped ? '' : 'none';
        }

        // Completed column: hide in grouped view
        const completedTh = headers[8];
        if (completedTh) {
            completedTh.style.display = isGrouped ? 'none' : '';
        }

        // Wall Time -> Time Since Submitted in grouped view
        const wallTimeTh = headers[9];
        if (wallTimeTh) {
            const text = wallTimeTh.childNodes[0];
            if (text) {
                text.textContent = isGrouped ? 'Time Since Submitted' : 'Wall Time';
            }
        }

        // Resources -> Total Resources in grouped view
        const resourcesTh = headers[10];
        if (resourcesTh) {
            const text = resourcesTh.childNodes[0];
            if (text) {
                text.textContent = isGrouped ? 'Total Resources' : 'Resources';
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Grouped Table Rendering
// ---------------------------------------------------------------------------

function getGroupSortValue(group, field) {
    // For sorting groups, use aggregated values
    const first = group.jobs[0];
    switch (field) {
        case 'ClusterId': return group.clusterId || 0;
        case 'JobBatchName': return (group.name || '').toLowerCase();
        case 'Owner': return (group.owner || '').toLowerCase();
        case 'Cmd': return (group.cmd || '').toLowerCase();
        case 'JobStatus': {
            // Sort by the dominant status (most common)
            const counts = {};
            group.jobs.forEach(j => {
                const s = parseInt(j.JobStatus) || 0;
                counts[s] = (counts[s] || 0) + 1;
            });
            let maxCount = 0;
            let dominantStatus = 0;
            for (const [s, c] of Object.entries(counts)) {
                if (c > maxCount) { maxCount = c; dominantStatus = parseInt(s); }
            }
            return dominantStatus;
        }
        case 'ExitCode': return group.exitCode !== undefined ? group.exitCode : -1;
        case 'QDate': return group.qDate || 0;
        case 'CompletionDate': return group.completionDate || 0;
        case 'RemoteWallClockTime': return group.wallTime || 0;
        case 'Resources': {
            const cpus = group.totalCpus || 0;
            const mem = group.maxMemory || 0;
            const disk = group.maxDisk || 0;
            const gpus = group.totalGpus || 0;
            return cpus * 1000000 + mem * 1000 + disk * 10 + gpus;
        }
        default: return 0;
    }
}

function groupJobs(jobs) {
    const groups = {};
    jobs.forEach(job => {
        const cid = job.ClusterId;
        if (!groups[cid]) {
            groups[cid] = {
                clusterId: cid,
                jobs: [],
                name: '—',
                owner: job.Owner || '—',
                cmd: job.Cmd || '',
                args: job.Args || '',
                qDate: job.QDate || 0,
                completionDate: job.CompletionDate || 0,
                wallTime: parseFloat(job.RemoteWallClockTime) || 0,
                exitCode: job.ExitCode !== undefined ? job.ExitCode : -1,
                totalCpus: 0,
                maxMemory: 0,
                maxDisk: 0,
                totalGpus: 0,
            };
        }
        const g = groups[cid];
        g.jobs.push(job);
        // Use first non-empty name
        if (g.name === '—' && job.JobBatchName) {
            g.name = job.JobBatchName;
        }
        // Aggregate resources
        g.totalCpus += parseInt(job.RequestCpus) || 0;
        g.maxMemory = Math.max(g.maxMemory, parseInt(job.RequestMemory) || 0);
        g.maxDisk = Math.max(g.maxDisk, parseInt(job.RequestDisk) || 0);
        g.totalGpus += parseInt(job.RequestGPUs) || 0;
        // Use earliest QDate
        if (job.QDate && job.QDate < g.qDate) g.qDate = job.QDate;
        // Use latest completion date
        if (job.CompletionDate && job.CompletionDate > g.completionDate) g.completionDate = job.CompletionDate;
        // Use max wall time
        const wt = parseFloat(job.RemoteWallClockTime) || 0;
        if (wt > g.wallTime) g.wallTime = wt;
        // Use first non-negative exit code
        if (job.ExitCode !== undefined && job.ExitCode >= 0 && (g.exitCode < 0 || g.exitCode === undefined)) {
            g.exitCode = job.ExitCode;
        }
    });
    return Object.values(groups);
}

// Pre-compute per-cluster resource totals from ALL currentJobs (unfiltered)
// so the Resources column stays constant regardless of status/search filter.
let clusterResources = {}; // { clusterId: { totalCpus, maxMemory, maxDisk, totalGpus } }

function buildClusterResources() {
    const map = {};
    currentJobs.forEach(job => {
        const cid = job.ClusterId;
        if (!map[cid]) {
            map[cid] = { totalCpus: 0, maxMemory: 0, maxDisk: 0, totalGpus: 0, hasAny: false };
        }
        const r = map[cid];
        const cpus = parseInt(job.RequestCpus);
        const mem = parseInt(job.RequestMemory);
        const disk = parseInt(job.RequestDisk);
        const gpus = parseInt(job.RequestGPUs);
        if (!isNaN(cpus)) { r.totalCpus += cpus; r.hasAny = true; }
        if (!isNaN(mem)) { r.maxMemory = Math.max(r.maxMemory, mem); r.hasAny = true; }
        if (!isNaN(disk)) { r.maxDisk = Math.max(r.maxDisk, disk); r.hasAny = true; }
        if (!isNaN(gpus)) { r.totalGpus += gpus; r.hasAny = true; }
    });
    clusterResources = map;
}

function renderGroupedTable() {
    const tbody = $('#jobs-tbody');
    tbody.innerHTML = '';

    // Update column headers for grouped mode
    updateTableHeaders();

    // Rebuild cluster resources from unfiltered data
    buildClusterResources();

    let filtered = getFilteredJobs();
    let groups = groupJobs(filtered);

    // Sort groups
    groups.sort((a, b) => {
        const va = getGroupSortValue(a, sortField);
        const vb = getGroupSortValue(b, sortField);
        if (va < vb) return sortAsc ? -1 : 1;
        if (va > vb) return sortAsc ? 1 : -1;
        return 0;
    });

    if (groups.length === 0) {
        tbody.innerHTML = `<tr class="empty-row"><td colspan="12">No jobs found</td></tr>`;
        updateSelectionUI();
        return;
    }

    groups.forEach(group => {
        const cid = group.clusterId;
        const name = group.name;
        const owner = group.owner;
        const cmd = group.cmd;
        const args = group.args;
        const qDate = formatDate(group.qDate);
        // Time since submitted = now - earliest QDate in the cluster
        let timeSinceSubmitted = '—';
        if (group.qDate) {
            timeSinceSubmitted = formatDuration(Math.max(0, Math.floor(Date.now() / 1000) - group.qDate));
        }
        // Use unfiltered cluster resources for constant display
        const cr = clusterResources[cid] || {};
        const hasRes = cr.hasAny;
        const cpus = hasRes ? cr.totalCpus : '—';
        const mem = hasRes ? formatMemory(cr.maxMemory) : '—';
        const disk = hasRes ? formatDisk(cr.maxDisk) : '—';
        const gpus = hasRes ? cr.totalGpus : '—';
        const statusBarHtml = renderStatusBar(group.jobs);

        // Check if all jobs in this group are selected
        const allSelected = group.jobs.every(j => selectedIds.has(`${j.ClusterId}.${j.ProcId}`));
        const someSelected = group.jobs.some(j => selectedIds.has(`${j.ClusterId}.${j.ProcId}`));

        // Group header row — clicking navigates to filtered view
        const headerTr = document.createElement('tr');
        headerTr.className = 'group-header';
        headerTr.dataset.clusterId = cid;
        headerTr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="group-checkbox" data-cluster-id="${cid}" ${allSelected ? 'checked' : ''}>
            </td>
            <td><a href="/?cluster_id=${cid}" class="job-id-link">${cid}</a></td>
            <td style="max-width: 120px; overflow: hidden; text-overflow: ellipsis;" title="${escHtml(name)}">${escHtml(name)}</td>
            <td>${escHtml(owner)}</td>
            <td class="monospace cmd-cell" title="${escHtml(cmd || args || '')}">${formatCommand(cmd, args)}</td>
            <td>${statusBarHtml}</td>
            <td class="monospace" style="display: none;">—</td>
            <td style="text-align: center; font-weight: 500;">${group.jobs.length}</td>
            <td>${qDate}</td>
            <td style="display: none;">—</td>
            <td>${timeSinceSubmitted}</td>
            <td style="font-size: 0.85rem;">${cpus} CPU, ${mem}, ${disk}${gpus !== '—' ? `, ${gpus} GPU` : ''}</td>
        `;

        // Click on the row (but not on the link or checkbox) navigates to filtered view
        headerTr.addEventListener('click', (e) => {
            if (e.target.closest('a') || e.target.closest('input[type="checkbox"]')) return;
            window.location.href = `/?cluster_id=${cid}`;
        });

        tbody.appendChild(headerTr);

        // Group checkbox: select/deselect all jobs in group
        const groupCheckbox = headerTr.querySelector('.group-checkbox');
        groupCheckbox.addEventListener('change', () => {
            const checked = groupCheckbox.checked;
            group.jobs.forEach(job => {
                const key = `${job.ClusterId}.${job.ProcId}`;
                if (checked) {
                    selectedIds.add(key);
                } else {
                    selectedIds.delete(key);
                }
            });
            updateSelectionUI();
        });

        // Also update the group checkbox state when individual selections change
        // (e.g. from select-all)
        // This is handled by the proxy observer below
    });

    // Proxy for group checkbox state: after rendering, sync group checkboxes
    // with current selection state
    $$('.group-checkbox').forEach(cb => {
        const cid = parseInt(cb.dataset.clusterId);
        const group = groups.find(g => g.clusterId === cid);
        if (!group) return;
        const allSel = group.jobs.every(j => selectedIds.has(`${j.ClusterId}.${j.ProcId}`));
        const someSel = group.jobs.some(j => selectedIds.has(`${j.ClusterId}.${j.ProcId}`));
        cb.checked = allSel;
        cb.indeterminate = !allSel && someSel;
    });

    updateSortArrows();
    updateSelectionUI();
}

// ---------------------------------------------------------------------------
// Standard (non-grouped) Table Rendering
// ---------------------------------------------------------------------------

function renderTable() {
    // Show/hide filter badge
    renderFilterBadge();

    // Update column headers for current mode
    updateTableHeaders();

    // If cluster filter is active, always render flat (non-grouped) table
    if (clusterFilter) {
        renderFlatTable();
        return;
    }

    if (groupByCluster) {
        renderGroupedTable();
        return;
    }

    renderFlatTable();
}

function renderFlatTable() {
    const tbody = $('#jobs-tbody');
    tbody.innerHTML = '';

    // Ensure exit code column is visible in flat mode
    const exitCodeHeaders = $$('#jobs-table thead th.sortable[data-sort="ExitCode"]');
    exitCodeHeaders.forEach(th => {
        th.style.display = '';
    });

    // Reset column header text
    const headers = $$('#jobs-table thead th.sortable');
    if (headers.length >= 10) {
        const wallTimeTh = headers[8];
        if (wallTimeTh) {
            const text = wallTimeTh.childNodes[0];
            if (text) text.textContent = 'Wall Time';
        }
        const resourcesTh = headers[9];
        if (resourcesTh) {
            const text = resourcesTh.childNodes[0];
            if (text) text.textContent = 'Resources';
        }
    }

    let filtered = getFilteredJobs();
    filtered = sortJobs(filtered);

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr class="empty-row"><td colspan="12">No jobs found</td></tr>`;
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

        // Wall Time = LastRemoteWallClockTime - CumulativeSuspensionTime, only for completed jobs
        let wallTime = '—';
        if (parseInt(job.JobStatus) === 4) {
            const lastRemote = parseFloat(job.LastRemoteWallClockTime);
            const suspension = parseFloat(job.CumulativeSuspensionTime);
            if (lastRemote > 0) {
                wallTime = formatDuration(Math.round(lastRemote - (suspension || 0)));
            }
        }

        const exitCode = job.ExitCode !== undefined ? job.ExitCode : '—';
        const cpus = job.RequestCpus || '—';
        const mem = formatMemory(job.RequestMemory);
        const disk = formatDisk(job.RequestDisk);
        const gpus = job.RequestGPUs || '—';
        const name = job.JobBatchName || '—';

        const isChecked = selectedIds.has(jobKey);

        tr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="row-checkbox" data-job-key="${escHtml(jobKey)}" ${isChecked ? 'checked' : ''}>
            </td>
            <td><a href="/job/${job.ClusterId}/${job.ProcId}" class="job-id-link">${job.ClusterId}.${job.ProcId}</a></td>
            <td style="max-width: 120px; overflow: hidden; text-overflow: ellipsis;" title="${escHtml(name)}">${escHtml(name)}</td>
            <td>${escHtml(job.Owner || '—')}</td>
            <td class="monospace cmd-cell" title="${escHtml(job.Cmd || job.Args || '')}">${formatCommand(job.Cmd, job.Args)}</td>
            <td><span class="status-badge ${statusClass}">${statusName}</span></td>
            <td class="monospace">${exitCode}</td>
            <td>${qDate}</td>
            <td>${compDate}</td>
            <td>${wallTime}</td>
            <td style="font-size: 0.85rem;">${cpus} CPU, ${mem}, ${disk}${gpus !== '—' ? `, ${gpus} GPU` : ''}</td>
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
    const clusterIds = [...new Set([...selectedIds].map(key => parseInt(key.split('.')[0])))];

    const names = clusterIds.slice(0, 5).map(cid => `#${cid}`);
    let detail = names.join(', ');
    if (clusterIds.length > 5) detail += `, and ${clusterIds.length - 5} more...`;

    showConfirmModal(
        `Are you sure you want to delete <strong>${count}</strong> job(s)? This will remove them from the schedd, database, and logs.<br><br><code style="font-size: 0.82rem;">${escHtml(detail)}</code>` +
        `<br><br><label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 0.85rem; color: var(--text-secondary);">` +
        `<input type="checkbox" id="delete-outputs-checkbox" style="width: 16px; height: 16px; cursor: pointer;">` +
        `<span>Also delete output files</span></label>`,
        {
            title: 'Delete Jobs',
            confirmText: `Delete ${count} Job(s)`,
            confirmClass: 'btn-danger',
            onConfirm: async () => {
                const deleteOutputs = $('#delete-outputs-checkbox')?.checked || false;
                await executeDelete(clusterIds, deleteOutputs);
            },
        }
    );
}

/**
 * Execute deletion with progress tracking, cancel support, and navigation guard.
 *
 * @param {number[]} clusterIds - Array of cluster IDs to delete.
 * @param {boolean} deleteOutputs - Whether to also delete output files.
 */
async function executeDelete(clusterIds, deleteOutputs) {
    const total = clusterIds.length;
    let completed = 0;
    let succeeded = 0;
    let failed = 0;
    let cancelled = false;
    const errors = [];

    // --- Stop auto-refresh while deletion is in progress ---
    if (countdownInterval) {
        clearInterval(countdownInterval);
        countdownInterval = null;
    }

    // --- Add navigation guard ---
    const beforeUnloadHandler = (e) => {
        e.preventDefault();
        e.returnValue = 'Job deletion is in progress. Are you sure you want to leave?';
    };
    window.addEventListener('beforeunload', beforeUnloadHandler);

    // --- Create progress modal (non-dismissable) ---
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay active';
    overlay.id = 'delete-progress-modal';
    overlay.style.zIndex = '10000';
    overlay.innerHTML = `
        <div class="modal" style="max-width: 480px;">
            <div class="modal-header">
                <h2>Deleting Jobs</h2>
            </div>
            <div class="modal-body">
                <div id="delete-progress-text" style="margin-bottom: 16px; color: var(--text-secondary);">
                    Deleting 0 of ${total} jobs...
                </div>
                <div class="progress-bar-container" style="height: 24px;">
                    <div class="progress-bar-fill" id="delete-progress-fill" style="width: 0%; height: 100%; background: var(--status-running); border-radius: 4px; transition: width 0.2s ease;"></div>
                </div>
                <div id="delete-progress-detail" style="margin-top: 8px; font-size: 0.8rem; color: var(--text-muted);"></div>
                <div id="delete-progress-errors" style="margin-top: 8px; font-size: 0.8rem; color: var(--status-held); max-height: 120px; overflow-y: auto; display: none;"></div>
                <div style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px;">
                    <button class="btn btn-ghost" id="delete-cancel-btn">Cancel</button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);

    const progressText = overlay.querySelector('#delete-progress-text');
    const progressFill = overlay.querySelector('#delete-progress-fill');
    const progressDetail = overlay.querySelector('#delete-progress-detail');
    const progressErrors = overlay.querySelector('#delete-progress-errors');
    const cancelBtn = overlay.querySelector('#delete-cancel-btn');

    // --- Create AbortController for cancellation ---
    const abortController = new AbortController();

    cancelBtn.addEventListener('click', () => {
        cancelled = true;
        abortController.abort();
        cancelBtn.disabled = true;
        cancelBtn.textContent = 'Cancelling...';
    });

    // --- Sequential deletion with progress ---
    for (let i = 0; i < total; i++) {
        if (cancelled) break;

        const cid = clusterIds[i];
        const current = i + 1;
        const pct = Math.round((current / total) * 100);

        progressText.textContent = `Deleting job ${current} of ${total} (Cluster #${cid})...`;
        progressFill.style.width = pct + '%';
        progressDetail.textContent = `${succeeded} succeeded, ${failed} failed`;

        try {
            const result = await api('/history/delete', {
                method: 'POST',
                body: JSON.stringify({ cluster_ids: [cid], delete_outputs: deleteOutputs }),
                signal: abortController.signal,
            });
            if (result.results && result.results[0] && result.results[0].success) {
                succeeded++;
            } else {
                failed++;
                const errMsg = result.results?.[0]?.error || 'Unknown error';
                errors.push(`Cluster #${cid}: ${errMsg}`);
            }
        } catch (err) {
            if (err.name === 'AbortError') {
                // Cancelled by user
                break;
            }
            failed++;
            errors.push(`Cluster #${cid}: ${err.message}`);
        }
        completed++;
    }

    // --- Cleanup ---
    window.removeEventListener('beforeunload', beforeUnloadHandler);

    // --- Update modal to show final result ---
    cancelBtn.remove(); // Remove cancel button

    if (cancelled) {
        progressText.textContent = `Deletion cancelled. ${succeeded} jobs deleted, ${failed} failed.`;
        progressFill.style.width = Math.round((completed / total) * 100) + '%';
        progressFill.style.background = 'var(--text-muted)';
    } else {
        progressText.textContent = `Deleted ${succeeded} of ${total} jobs successfully.`;
        progressFill.style.width = '100%';
        if (failed > 0) {
            progressFill.style.background = 'var(--status-held)';
        } else {
            progressFill.style.background = 'var(--status-running)';
        }
    }

    progressDetail.textContent = `${succeeded} succeeded, ${failed} failed`;

    if (errors.length > 0) {
        progressErrors.style.display = 'block';
        progressErrors.innerHTML = errors.map(e => `<div>${escHtml(e)}</div>`).join('');
    }

    // Add close button
    const closeBtn = document.createElement('button');
    closeBtn.className = 'btn btn-primary';
    closeBtn.textContent = 'Close';
    closeBtn.addEventListener('click', () => {
        overlay.remove();
    });
    overlay.querySelector('.modal-body').appendChild(closeBtn);

    // --- Clear selection and reload ---
    selectedIds.clear();
    await loadJobs();

    // --- Restart auto-refresh ---
    startAutoRefresh();

    // Show summary toast
    if (failed > 0) {
        toast(`Deleted ${succeeded}/${total} jobs — ${failed} failed`, 'error');
    } else {
        toast(`Deleted ${succeeded} job(s) successfully`);
    }
}

async function holdSelected() {
    if (selectedIds.size === 0) return;

    // Deduplicate: get unique cluster IDs from selected procs
    const clusterIds = [...new Set([...selectedIds].map(key => parseInt(key.split('.')[0])))];

    try {
        const result = await api('/clusters/hold', {
            method: 'POST',
            body: JSON.stringify({ cluster_ids: clusterIds }),
        });
        const successCount = result.results.filter(r => r.success).length;
        toast(`Held ${successCount} cluster(s)`);
        await loadJobs();
    } catch (err) {
        toast(`Failed to hold: ${err.message}`, 'error');
    }
}

async function releaseSelected() {
    if (selectedIds.size === 0) return;

    // Deduplicate: get unique cluster IDs from selected procs
    const clusterIds = [...new Set([...selectedIds].map(key => parseInt(key.split('.')[0])))];

    try {
        const result = await api('/clusters/release', {
            method: 'POST',
            body: JSON.stringify({ cluster_ids: clusterIds }),
        });
        const successCount = result.results.filter(r => r.success).length;
        toast(`Released ${successCount} cluster(s)`);
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
    // Parse cluster filter from URL
    const params = new URLSearchParams(window.location.search);
    const cid = params.get('cluster_id');
    if (cid && cid.match(/^\d+$/)) {
        clusterFilter = cid;
        // Disable group toggle when filtered
        $('#group-toggle').disabled = true;
        $('#group-toggle-label').style.opacity = '0.5';
    }

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

    // Group by ClusterID toggle
    $('#group-toggle').addEventListener('change', (e) => {
        groupByCluster = e.target.checked;
        renderTable();
    });

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
        // Also update group checkboxes
        $$('.group-checkbox').forEach(cb => {
            cb.checked = checked;
            cb.indeterminate = false;
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