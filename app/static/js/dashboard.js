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
let expandedClusters = new Set(); // Set of clusterIds that are expanded in grouped view

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
            return cpus * 1000000 + mem * 1000 + disk;
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
                name: job.JobBatchName || '—',
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
            };
        }
        const g = groups[cid];
        g.jobs.push(job);
        // Aggregate resources
        g.totalCpus += parseInt(job.RequestCpus) || 0;
        g.maxMemory = Math.max(g.maxMemory, parseInt(job.RequestMemory) || 0);
        g.maxDisk = Math.max(g.maxDisk, parseInt(job.RequestDisk) || 0);
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

function renderGroupedTable() {
    const tbody = $('#jobs-tbody');
    tbody.innerHTML = '';

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
        tbody.innerHTML = `<tr class="empty-row"><td colspan="11">No jobs found</td></tr>`;
        updateSelectionUI();
        return;
    }

    groups.forEach(group => {
        const cid = group.clusterId;
        const firstJob = group.jobs[0];
        const name = group.name;
        const owner = group.owner;
        const cmd = group.cmd;
        const args = group.args;
        const qDate = formatDate(group.qDate);
        const compDate = formatDate(group.completionDate);
        let wallTime = '—';
        if (group.wallTime) {
            wallTime = formatDuration(Math.round(group.wallTime));
        } else if (group.completionDate && group.qDate) {
            wallTime = formatDuration(group.completionDate - group.qDate);
        }
        // Use the same formatting as individual jobs for consistency.
        // Take the display values from the first job's formatted output.
        const firstCpus = firstJob.RequestCpus || '—';
        const firstMem = formatMemory(firstJob.RequestMemory);
        const firstDisk = formatDisk(firstJob.RequestDisk);
        // For CPU, show total across all jobs; for memory/disk, show max with unit from first job
        const cpus = group.totalCpus || '—';
        const mem = firstMem;
        const disk = firstDisk;
        const statusBarHtml = renderStatusBar(group.jobs);

        // Check if all jobs in this group are selected
        const allSelected = group.jobs.every(j => selectedIds.has(`${j.ClusterId}.${j.ProcId}`));
        const someSelected = group.jobs.some(j => selectedIds.has(`${j.ClusterId}.${j.ProcId}`));

        // Group header row
        const headerTr = document.createElement('tr');
        headerTr.className = 'group-header';
        headerTr.dataset.clusterId = cid;
        headerTr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="group-checkbox" data-cluster-id="${cid}" ${allSelected ? 'checked' : ''}>
            </td>
            <td>
                <span class="expand-chevron">▶</span>
                <a href="/job/${cid}/${firstJob.ProcId || 0}" class="job-id-link">${cid}.0..${group.jobs.length - 1}</a>
            </td>
            <td style="max-width: 120px; overflow: hidden; text-overflow: ellipsis;" title="${escHtml(name)}">${escHtml(name)}</td>
            <td>${escHtml(owner)}</td>
            <td class="monospace cmd-cell" title="${escHtml(cmd || args || '')}">${formatCommand(cmd, args)}</td>
            <td>${statusBarHtml}</td>
            <td class="monospace">${group.exitCode >= 0 ? group.exitCode : '—'}</td>
            <td>${qDate}</td>
            <td>${compDate}</td>
            <td>${wallTime}</td>
            <td style="font-size: 0.85rem;">${cpus} CPU, ${mem}, ${disk}</td>
        `;

        // Sort sub-jobs by ProcId
        const sortedJobs = [...group.jobs].sort((a, b) => (a.ProcId || 0) - (b.ProcId || 0));

        // Create sub-rows as direct <tr> elements in the main tbody (not nested table)
        // so columns align with the parent table
        const subRows = [];

        sortedJobs.forEach(job => {
            const statusClass = getStatusClass(job.JobStatus);
            const statusName = getStatusName(job.JobStatus);
            const jobKey = `${job.ClusterId}.${job.ProcId}`;

            const subQDate = formatDate(job.QDate);
            const subCompDate = formatDate(job.CompletionDate);

            let subWallTime = '—';
            if (job.RemoteWallClockTime) {
                subWallTime = formatDuration(Math.round(parseFloat(job.RemoteWallClockTime)));
            } else if (job.CompletionDate && job.QDate) {
                subWallTime = formatDuration(job.CompletionDate - job.QDate);
            }

            const subExitCode = job.ExitCode !== undefined ? job.ExitCode : '—';
            const subCpus = job.RequestCpus || '—';
            const subMem = formatMemory(job.RequestMemory);
            const subDisk = formatDisk(job.RequestDisk);
            const subName = job.JobBatchName || '—';

            const isChecked = selectedIds.has(jobKey);

            const subRow = document.createElement('tr');
            subRow.className = 'group-subrow';
            subRow.dataset.clusterId = cid;
            subRow.style.display = 'none';
            subRow.innerHTML = `
                <td style="text-align: center;">
                    <input type="checkbox" class="row-checkbox" data-job-key="${escHtml(jobKey)}" ${isChecked ? 'checked' : ''}>
                </td>
                <td><a href="/job/${job.ClusterId}/${job.ProcId}" class="job-id-link">${job.ClusterId}.${job.ProcId}</a></td>
                <td style="max-width: 120px; overflow: hidden; text-overflow: ellipsis;" title="${escHtml(subName)}">${escHtml(subName)}</td>
                <td>${escHtml(job.Owner || '—')}</td>
                <td class="monospace cmd-cell" title="${escHtml(job.Cmd || job.Args || '')}">${formatCommand(job.Cmd, job.Args)}</td>
                <td><span class="status-badge ${statusClass}">${statusName}</span></td>
                <td class="monospace">${subExitCode}</td>
                <td>${subQDate}</td>
                <td>${subCompDate}</td>
                <td>${subWallTime}</td>
                <td style="font-size: 0.85rem;">${subCpus} CPU, ${subMem}, ${subDisk}</td>
            `;

            // Row click toggles checkbox
            subRow.addEventListener('click', (e) => {
                if (e.target.closest('a') || e.target.closest('input[type="checkbox"]')) return;
                const cb = subRow.querySelector('.row-checkbox');
                if (cb) {
                    cb.checked = !cb.checked;
                    cb.dispatchEvent(new Event('change'));
                }
            });

            subRows.push(subRow);
        });

        tbody.appendChild(headerTr);
        subRows.forEach(tr => tbody.appendChild(tr));

        // --- Event handlers ---

        // Restore expanded state from previous render
        const wasExpanded = expandedClusters.has(cid);
        if (wasExpanded) {
            subRows.forEach(tr => { tr.style.display = ''; });
            headerTr.querySelector('.expand-chevron').classList.add('expanded');
        }

        // Group header click: expand/collapse
        headerTr.addEventListener('click', (e) => {
            if (e.target.closest('a') || e.target.closest('input[type="checkbox"]')) return;
            const chevron = headerTr.querySelector('.expand-chevron');
            const isExpanded = chevron.classList.contains('expanded');
            if (isExpanded) {
                subRows.forEach(tr => { tr.style.display = 'none'; });
                chevron.classList.remove('expanded');
                expandedClusters.delete(cid);
            } else {
                subRows.forEach(tr => { tr.style.display = ''; });
                chevron.classList.add('expanded');
                expandedClusters.add(cid);
            }
        });

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
            // Update sub-row checkboxes
            subRows.forEach(tr => {
                const cb = tr.querySelector('.row-checkbox');
                if (cb) cb.checked = checked;
            });
            updateSelectionUI();
        });

        // Sub-row checkbox: update group checkbox state
        subRows.forEach(tr => {
            const cb = tr.querySelector('.row-checkbox');
            cb.addEventListener('change', () => {
                const key = cb.dataset.jobKey;
                if (cb.checked) {
                    selectedIds.add(key);
                } else {
                    selectedIds.delete(key);
                }
                // Update group checkbox
                const allSel = group.jobs.every(j => selectedIds.has(`${j.ClusterId}.${j.ProcId}`));
                const someSel = group.jobs.some(j => selectedIds.has(`${j.ClusterId}.${j.ProcId}`));
                groupCheckbox.checked = allSel;
                groupCheckbox.indeterminate = !allSel && someSel;
                updateSelectionUI();
            });
        });
    });

    updateSortArrows();
    updateSelectionUI();
}

// ---------------------------------------------------------------------------
// Standard (non-grouped) Table Rendering
// ---------------------------------------------------------------------------

function renderTable() {
    if (groupByCluster) {
        renderGroupedTable();
        return;
    }

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
            <td class="monospace cmd-cell" title="${escHtml(job.Cmd || job.Args || '')}">${formatCommand(job.Cmd, job.Args)}</td>
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
                try {
                    const result = await api('/history/delete', {
                        method: 'POST',
                        body: JSON.stringify({ cluster_ids: clusterIds, delete_outputs: deleteOutputs }),
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