const clusterId = window.JOB_CLUSTER_ID;
const procId = window.JOB_PROC_ID;

let fileContents = {
    log: '',
    stdout: '',
    stderr: ''
};
let activeFileTab = 'log';

async function loadJobDetails() {
    try {
        const data = await api(`/jobs/${clusterId}/details?proc=${procId}&tail=1000`);
        
        // Populate header & subtitle
        $('#job-submission-name').textContent = data.submission_name || 'Job Subbed Outside Web UI';
        
        const job = data.job;
        const statusVal = job.JobStatus || 0;
        const statusClass = getStatusClass(statusVal);
        const statusName = getStatusName(statusVal);
        
        const badge = $('#job-status-badge');
        badge.textContent = statusName;
        badge.className = `status-badge ${statusClass}`;

        // Populate quick metrics
        $('#quick-owner').textContent = job.Owner || '—';
        $('#quick-executable').textContent = job.Cmd ? basename(job.Cmd) : '—';
        $('#quick-host').textContent = job.RemoteHost ? basename(job.RemoteHost) : (job.LastRemoteHost ? basename(job.LastRemoteHost) : '—');
        
        let wallTime = '—';
        if (job.RemoteWallClockTime) {
            wallTime = formatDuration(Math.round(parseFloat(job.RemoteWallClockTime)));
        } else if (job.CompletionDate && job.QDate) {
            wallTime = formatDuration(job.CompletionDate - job.QDate);
        } else if (job.QDate) {
            wallTime = formatDuration(Math.floor(Date.now() / 1000) - job.QDate);
        }
        $('#quick-walltime').textContent = wallTime;

        // Save file contents
        fileContents.log = data.log;
        fileContents.stdout = data.stdout;
        fileContents.stderr = data.stderr;
        updateFileContentDisplay();

        // Render ClassAd Attributes Table
        renderAttributesTable(job);

        // Render action buttons
        renderActions(statusVal);
    } catch (e) {
        toast('Failed to load job details: ' + e.message, 'error');
    }
}

function updateFileContentDisplay() {
    const outputEl = $('#file-content-output');
    outputEl.textContent = fileContents[activeFileTab];
}

function renderAttributesTable(job) {
    const tbody = $('#attributes-tbody');
    tbody.innerHTML = '';

    const keys = Object.keys(job).sort();
    if (keys.length === 0) {
        tbody.innerHTML = `<tr><td colspan="2" style="text-align: center; color: var(--text-muted);">No ClassAd attributes available</td></tr>`;
        return;
    }

    keys.forEach(key => {
        const tr = document.createElement('tr');
        let val = job[key];
        // Format if it's epoch date
        if (key.endsWith('Date') && typeof val === 'number' && val > 1000000000) {
            val = `${val} (${formatDate(val)})`;
        }
        tr.innerHTML = `
            <td class="monospace" style="font-weight: 500; font-size: 0.85rem; color: var(--text-primary);">${key}</td>
            <td class="monospace" style="font-size: 0.85rem; color: var(--text-secondary); word-break: break-all;">${val}</td>
        `;
        tbody.appendChild(tr);
    });
}

function renderActions(statusVal) {
    const container = $('#job-actions-container');
    container.innerHTML = '';
    
    const status = parseInt(statusVal);
    
    // Check if job is in active queue (Idle, Running, Held, etc.)
    // Active statuses: 1 (Idle), 2 (Running), 5 (Held), 6 (Transferring)
    const isActive = [1, 2, 5, 6].includes(status);
    if (!isActive) return;

    if (status === 5) {
        // Held
        container.innerHTML = `
            <button class="btn btn-primary" id="action-release-btn">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" style="margin-right: 8px;">
                    <polygon points="5,3 19,12 5,21" />
                </svg>
                Release Job
            </button>
        `;
    } else {
        // Running or Idle
        container.innerHTML = `
            <button class="btn btn-ghost" id="action-hold-btn" style="border: 1px solid var(--border-color);">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" style="margin-right: 8px;">
                    <rect x="6" y="4" width="4" height="16" />
                    <rect x="14" y="4" width="4" height="16" />
                </svg>
                Hold Job
            </button>
        `;
    }

    container.innerHTML += `
        <button class="btn btn-primary" id="action-remove-btn" style="background: var(--danger-color); border-color: var(--danger-color);">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" style="margin-right: 8px;">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
            Remove Job
        </button>
    `;

    // Bind events
    const holdBtn = $('#action-hold-btn');
    const releaseBtn = $('#action-release-btn');
    const removeBtn = $('#action-remove-btn');

    if (holdBtn) {
        holdBtn.addEventListener('click', async () => {
            try {
                await api(`/jobs/${clusterId}.${procId}`, { method: 'POST', body: JSON.stringify({ action: 'hold' }) });
                toast('Job held successfully');
                loadJobDetails();
            } catch (err) {
                toast(`Failed to hold job: ${err.message}`, 'error');
            }
        });
    }

    if (releaseBtn) {
        releaseBtn.addEventListener('click', async () => {
            try {
                await api(`/jobs/${clusterId}.${procId}`, { method: 'POST', body: JSON.stringify({ action: 'release' }) });
                toast('Job released successfully');
                loadJobDetails();
            } catch (err) {
                toast(`Failed to release job: ${err.message}`, 'error');
            }
        });
    }

    if (removeBtn) {
        removeBtn.addEventListener('click', async () => {
            if (!confirm(`Are you sure you want to remove job ${clusterId}.${procId}?`)) return;
            try {
                await api(`/jobs/${clusterId}.${procId}`, { method: 'DELETE' });
                toast('Job removed successfully');
                setTimeout(() => window.location.href = '/', 1500);
            } catch (err) {
                toast(`Failed to remove job: ${err.message}`, 'error');
            }
        });
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadJobDetails();

    // Main tabs toggling
    $$('.details-tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.details-tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const tab = btn.dataset.tab;
            $$('.details-tab-panel').forEach(p => p.classList.remove('active'));
            $(`#tab-panel-${tab}`).classList.add('active');
        });
    });

    // Sub tabs toggling (files)
    $$('.sub-tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.sub-tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            activeFileTab = btn.dataset.file;
            updateFileContentDisplay();
        });
    });

    // Copy file content button
    $('#copy-log-btn').addEventListener('click', () => {
        const text = $('#file-content-output').textContent;
        navigator.clipboard.writeText(text).then(() => {
            toast('Content copied to clipboard');
        }).catch(err => {
            toast('Failed to copy content: ' + err, 'error');
        });
    });
});
