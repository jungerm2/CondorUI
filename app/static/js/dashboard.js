let currentJobs = [];
let sortField = 'ClusterId';
let sortAsc = false;
let refreshTimer = null;
let countdownInterval = null;
const REFRESH_RATE = 30; // seconds

async function loadJobs() {
    try {
        const data = await api('/jobs');
        if (data.daemon_unavailable) {
            currentJobs = [];
            const tbody = $('#jobs-tbody');
            if (tbody) {
                tbody.innerHTML = `<tr class="empty-row"><td colspan="8">⚠️ HTCondor daemon is not available. This is expected on a development machine without a running condor_schedd.</td></tr>`;
            }
            renderStats();
            return;
        }
        currentJobs = data.jobs || [];
        renderJobsTable();
        renderStats();
    } catch (e) {
        toast('Failed to load active jobs: ' + e.message, 'error');
        // Show empty state instead of leaving stale "Loading..." in the table
        const tbody = $('#jobs-tbody');
        if (tbody) {
            tbody.innerHTML = `<tr class="empty-row"><td colspan="8">Unable to connect to HTCondor. ${e.message}</td></tr>`;
        }
    }
}

function renderStats() {
    const stats = { total: 0, idle: 0, running: 0, held: 0 };
    currentJobs.forEach(job => {
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
    const statusVal = $('#status-filter').value;

    return currentJobs.filter(job => {
        // Text filter
        const matchesText = !query ||
            (job.ClusterId.toString().includes(query)) ||
            (job.Owner && job.Owner.toLowerCase().includes(query)) ||
            (job.Cmd && job.Cmd.toLowerCase().includes(query));

        // Status filter
        const matchesStatus = !statusVal || job.JobStatus.toString() === statusVal;

        return matchesText && matchesStatus;
    });
}

function renderJobsTable() {
    const tbody = $('#jobs-tbody');
    tbody.innerHTML = '';

    let filtered = getFilteredJobs();

    // Sort
    filtered.sort((a, b) => {
        let valA = a[sortField];
        let valB = b[sortField];

        // Handle numeric conversion where appropriate
        if (sortField === 'ClusterId' || sortField === 'JobStatus' || sortField === 'QDate') {
            valA = parseFloat(valA) || 0;
            valB = parseFloat(valB) || 0;
        } else {
            valA = (valA || '').toString().toLowerCase();
            valB = (valB || '').toString().toLowerCase();
        }

        if (valA < valB) return sortAsc ? -1 : 1;
        if (valA > valB) return sortAsc ? 1 : -1;
        return 0;
    });

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr class="empty-row"><td colspan="8">No active jobs found</td></tr>`;
        return;
    }

    filtered.forEach(job => {
        const tr = document.createElement('tr');
        const statusClass = getStatusClass(job.JobStatus);
        const statusName = getStatusName(job.JobStatus);
        const subDate = formatDate(job.QDate);

        // CPU / Mem request info
        const cpus = job.RequestCpus || '1';
        const mem = job.RequestMemory || '—';
        const resStr = `${cpus} CPU, ${mem}`;

        // Buttons based on status
        let actionButtons = '';
        if (parseInt(job.JobStatus) === 5) {
            // Held
            actionButtons = `
                <button class="btn btn-sm btn-ghost release-btn" data-id="${job.ClusterId}.${job.ProcId}" title="Release Job">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <polygon points="5,3 19,12 5,21" />
                    </svg>
                </button>
            `;
        } else if (parseInt(job.JobStatus) === 1 || parseInt(job.JobStatus) === 2) {
            // Idle or Running
            actionButtons = `
                <button class="btn btn-sm btn-ghost hold-btn" data-id="${job.ClusterId}.${job.ProcId}" title="Hold Job">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <rect x="6" y="4" width="4" height="16" />
                        <rect x="14" y="4" width="4" height="16" />
                    </svg>
                </button>
            `;
        }

        actionButtons += `
            <button class="btn btn-sm btn-ghost remove-btn" data-id="${job.ClusterId}.${job.ProcId}" title="Remove Job" style="color: var(--danger-color);">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
            </button>
        `;

        tr.innerHTML = `
            <td><a href="/job/${job.ClusterId}/${job.ProcId}" class="job-id-link">${job.ClusterId}.${job.ProcId}</a></td>
            <td>${job.Owner || '—'}</td>
            <td class="monospace" title="${job.Cmd}">${basename(job.Cmd)}</td>
            <td><span class="status-badge ${statusClass}">${statusName}</span></td>
            <td class="monospace" style="font-size: 0.8rem;">${job.RemoteHost ? basename(job.RemoteHost) : '—'}</td>
            <td>${subDate}</td>
            <td style="font-size: 0.85rem;">${resStr}</td>
            <td><div style="display: flex; gap: 4px;">${actionButtons}</div></td>
        `;
        tbody.appendChild(tr);
    });

    // Add listeners to actions
    $$('.hold-btn').forEach(btn => btn.addEventListener('click', handleHold));
    $$('.release-btn').forEach(btn => btn.addEventListener('click', handleRelease));
    $$('.remove-btn').forEach(btn => btn.addEventListener('click', handleRemove));
}

async function handleHold(e) {
    const jobId = e.currentTarget.dataset.id;
    try {
        await api(`/jobs/${jobId}`, { method: 'POST', body: JSON.stringify({ action: 'hold' }) });
        toast(`Job ${jobId} held successfully`);
        loadJobs();
    } catch (err) {
        toast(`Failed to hold job: ${err.message}`, 'error');
    }
}

async function handleRelease(e) {
    const jobId = e.currentTarget.dataset.id;
    try {
        await api(`/jobs/${jobId}`, { method: 'POST', body: JSON.stringify({ action: 'release' }) });
        toast(`Job ${jobId} released successfully`);
        loadJobs();
    } catch (err) {
        toast(`Failed to release job: ${err.message}`, 'error');
    }
}

async function handleRemove(e) {
    const jobId = e.currentTarget.dataset.id;
    if (!confirm(`Are you sure you want to remove job ${jobId}?`)) return;
    try {
        await api(`/jobs/${jobId}`, { method: 'DELETE' });
        toast(`Job ${jobId} removed successfully`);
        loadJobs();
    } catch (err) {
        toast(`Failed to remove job: ${err.message}`, 'error');
    }
}

function startAutoRefresh() {
    let countdown = REFRESH_RATE;
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

document.addEventListener('DOMContentLoaded', () => {
    loadJobs();
    startAutoRefresh();

    // Event listeners
    $('#refresh-btn').addEventListener('click', () => {
        loadJobs();
        startAutoRefresh();
    });

    $('#job-search').addEventListener('input', renderJobsTable);
    $('#status-filter').addEventListener('change', renderJobsTable);

    // Sorting headers
    $$('#jobs-table th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const field = th.dataset.sort;
            if (sortField === field) {
                sortAsc = !sortAsc;
            } else {
                sortField = field;
                sortAsc = true;
            }
            renderJobsTable();
        });
    });
});
