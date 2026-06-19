const clusterId = window.JOB_CLUSTER_ID;
const procId = window.JOB_PROC_ID;

let fileContents = {
    log: '',
    stdout: '',
    stderr: ''
};
let activeFileTab = 'log';
let detailsRefreshTimer = null;
let detailsRefreshInProgress = false;
let submitFileContent = '';

async function loadJobDetails() {
    // Prevent concurrent refresh calls
    if (detailsRefreshInProgress) return;
    detailsRefreshInProgress = true;

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
        $('#quick-executable').textContent = formatCommand(job.Cmd, job.Args);
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

        // Populate additional metadata with formatted resources
        $('#meta-cluster-id').textContent = `${clusterId}.${procId}`;
        $('#meta-submitted').textContent = job.QDate ? formatDate(job.QDate) : '—';
        $('#meta-completed').textContent = job.CompletionDate ? formatDate(job.CompletionDate) : '—';
        $('#meta-cpus').textContent = job.RequestCpus || '—';
        $('#meta-memory').textContent = formatMemory(job.RequestMemory);
        $('#meta-disk').textContent = formatDisk(job.RequestDisk);
        $('#meta-hold-reason').textContent = job.HoldReason || '—';
        $('#meta-exit-code').textContent = job.ExitCode !== undefined ? job.ExitCode : '—';

        // Parse logs for usage data
        parseLogsForUsage(data.log);

        // Save file contents
        fileContents.log = data.log;
        fileContents.stdout = data.stdout;
        fileContents.stderr = data.stderr;
        updateFileContentDisplay();

        // Load submit file content
        loadSubmitFileContent(data);

        // Render ClassAd Attributes Table
        renderAttributesTable(job);

        // Render action buttons
        renderActions(statusVal, data.log);

        // Update download links
        updateDownloadLinks(data.paths);

        // Start auto-refresh if job is not complete
        startDetailsAutoRefresh(statusVal);
    } catch (e) {
        toast('Failed to load job details: ' + e.message, 'error');
    } finally {
        detailsRefreshInProgress = false;
    }
}

/**
 * Parse the log content for Partitionable Resources usage.
 * Looks for lines like:
 *   Disk (KB)            :     3000  1048576   1048576
 *   Memory (MB)          :              1024      1024
 */
function parseLogsForUsage(logContent) {
    if (!logContent) return;

    const usageContainer = $('#job-usage-container');
    if (!usageContainer) return;

    // Find Partitionable Resources section
    const lines = logContent.split('\n');
    let inResourceSection = false;
    let usageLines = [];

    for (const line of lines) {
        if (line.includes('Partitionable Resources')) {
            inResourceSection = true;
            continue;
        }
        if (inResourceSection) {
            // Empty line or non-resource line ends the section
            if (line.trim() === '' || (!line.includes(':') && !line.includes('|'))) {
                if (usageLines.length > 0) break;
                inResourceSection = false;
                continue;
            }
            usageLines.push(line);
        }
    }

    if (usageLines.length === 0) {
        usageContainer.innerHTML = `<p class="usage-notes">No resource usage data found in log yet.</p>`;
        return;
    }

    // Parse resource lines
    // Format: Cpus : 1 1
    //         Disk (KB) : 3000 1048576 1048576
    //         Memory (MB) : 1024 1024
    let html = '<div class="usage-grid">';

    for (const line of usageLines) {
        const parts = line.split(':');
        if (parts.length < 2) continue;

        const resourceName = parts[0].trim();
        const values = parts.slice(1).join(':').trim().split(/\s+/).filter(v => v);

        if (values.length === 0) continue;

        // Determine which values correspond to Usage, Request, Allocated
        let usageVal = '—', requestVal = '—', allocatedVal = '—';

        if (resourceName.toLowerCase().includes('cpus') || resourceName.toLowerCase().includes('gpus')) {
            if (values.length >= 1) requestVal = values[values.length >= 2 ? values.length - 2 : 0];
            if (values.length >= 1) allocatedVal = values[values.length - 1];
            if (values.length >= 3) usageVal = values[0];
        } else if (resourceName.toLowerCase().includes('disk') || resourceName.toLowerCase().includes('memory')) {
            if (values.length >= 3) {
                usageVal = values[0];
                requestVal = values[1];
                allocatedVal = values[2];
            } else if (values.length === 2) {
                requestVal = values[0];
                allocatedVal = values[1];
            } else if (values.length === 1) {
                allocatedVal = values[0];
            }
        } else {
            if (values.length >= 3) {
                usageVal = values[0];
                requestVal = values[1];
                allocatedVal = values[2];
            } else if (values.length >= 1) {
                allocatedVal = values[values.length - 1];
            }
        }

        // Format the values based on resource type
        let usageDisplay = usageVal;
        let requestDisplay = requestVal;
        let allocatedDisplay = allocatedVal;

        if (resourceName.toLowerCase().includes('memory')) {
            // Memory values are in MB
            usageDisplay = usageVal !== '—' ? formatBytes(usageVal, 'MB') : '—';
            requestDisplay = requestVal !== '—' ? formatBytes(requestVal, 'MB') : '—';
            allocatedDisplay = allocatedVal !== '—' ? formatBytes(allocatedVal, 'MB') : '—';
        } else if (resourceName.toLowerCase().includes('disk')) {
            // Disk values are in KB
            usageDisplay = usageVal !== '—' ? formatBytes(usageVal, 'KB') : '—';
            requestDisplay = requestVal !== '—' ? formatBytes(requestVal, 'KB') : '—';
            allocatedDisplay = allocatedVal !== '—' ? formatBytes(allocatedVal, 'KB') : '—';
        }

        let usagePercent = '';
        if (usageVal !== '—' && requestVal !== '—' && parseFloat(requestVal) > 0) {
            const pct = (parseFloat(usageVal) / parseFloat(requestVal) * 100);
            if (pct > 0) {
                usagePercent = `<span class="usage-pct ${pct > 100 ? 'usage-exceeded' : pct > 90 ? 'usage-warning' : ''}">(${pct.toFixed(0)}%)</span>`;
            }
        }

        html += `
            <div class="usage-item">
                <span class="usage-label">${resourceName}</span>
                <div class="usage-values">
                    <div class="usage-value">
                        <span class="usage-value-label">Usage</span>
                        <span class="usage-value-num">${usageDisplay} ${usagePercent}</span>
                    </div>
                    <div class="usage-value">
                        <span class="usage-value-label">Requested</span>
                        <span class="usage-value-num">${requestDisplay}</span>
                    </div>
                    <div class="usage-value">
                        <span class="usage-value-label">Allocated</span>
                        <span class="usage-value-num">${allocatedDisplay}</span>
                    </div>
                </div>
            </div>
        `;
    }

    html += '</div>';
    usageContainer.innerHTML = html;
}

function updateFileContentDisplay() {
    const outputEl = $('#file-content-output');
    outputEl.textContent = fileContents[activeFileTab];
}

function updateDownloadLinks(paths) {
    // Build download URLs — use ?download=1&file=... to trigger file download from the API
    const baseUrl = `/api/jobs/${clusterId}/${procId}/files`;

    const downloadLog = $('#download-log-btn');
    const downloadStdout = $('#download-stdout-btn');
    const downloadStderr = $('#download-stderr-btn');

    if (downloadLog) {
        downloadLog.href = paths.log ? `${baseUrl}?tail=0&download=1&file=log` : '#';
        downloadLog.style.display = paths.log ? 'inline-flex' : 'none';
    }
    if (downloadStdout) {
        downloadStdout.href = paths.out ? `${baseUrl}?tail=0&download=1&file=out` : '#';
        downloadStdout.style.display = paths.out ? 'inline-flex' : 'none';
    }
    if (downloadStderr) {
        downloadStderr.href = paths.err ? `${baseUrl}?tail=0&download=1&file=err` : '#';
        downloadStderr.style.display = paths.err ? 'inline-flex' : 'none';
    }
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

function renderActions(statusVal, logContent) {
    const container = $('#job-actions-container');
    container.innerHTML = '';
    
    const status = parseInt(statusVal);
    
    // Check if job is in active queue (Idle, Running, Held, etc.)
    // Active statuses: 1 (Idle), 2 (Running), 5 (Held), 6 (Transferring)
    const isActive = [1, 2, 5, 6].includes(status);
    if (!isActive) return;

    if (status === 5) {
        // Held — show release and qedit buttons
        container.innerHTML = `
            <button class="btn btn-primary" id="action-release-btn">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" style="margin-right: 8px;">
                    <polygon points="5,3 19,12 5,21" />
                </svg>
                Release Job
            </button>
            <button class="btn btn-ghost" id="action-qedit-btn" style="border: 1px solid var(--border-color);">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" style="margin-right: 8px;">
                    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                    <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
                </svg>
                Edit Job (qedit)
            </button>
        `;

        // Check if the hold was due to exceeded resources — if so, auto-show the qedit dialog
        const isResourceExceeded = logContent && (
            logContent.includes('exceeded allocated disk') ||
            logContent.includes('exceeded allocated memory')
        );
        if (isResourceExceeded) {
            setTimeout(() => {
                const qeditBtn = $('#action-qedit-btn');
                if (qeditBtn) qeditBtn.style.border = '2px solid var(--status-held)';
            }, 100);
        }
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
        <button class="btn btn-remove" id="action-remove-btn">
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
    const qeditBtn = $('#action-qedit-btn');

    if (holdBtn) {
        holdBtn.addEventListener('click', async () => {
            try {
                await api(`/jobs/${clusterId}.${procId}/hold`, { method: 'POST' });
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
                await api(`/jobs/${clusterId}.${procId}/release`, { method: 'POST' });
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

    if (qeditBtn) {
        qeditBtn.addEventListener('click', () => {
            openQeditDialog([{ clusterId, procId }], {
                onComplete: loadJobDetails,
                autoRelease: true,
            });
        });
    }
}

/**
 * Start auto-refresh with a 30-second countdown.
 * Always runs regardless of job status.
 */
const DETAILS_REFRESH_RATE = 30; // seconds
let detailsCountdown = DETAILS_REFRESH_RATE;
let detailsCountdownInterval = null;

function startDetailsAutoRefresh(statusVal) {
    const status = parseInt(statusVal);
    // Completed (4), Removed (3) — stop refreshing but keep countdown display
    const needsRefresh = ![3, 4].includes(status);

    if (detailsCountdownInterval) {
        clearInterval(detailsCountdownInterval);
        detailsCountdownInterval = null;
    }
    if (detailsRefreshTimer) {
        clearInterval(detailsRefreshTimer);
        detailsRefreshTimer = null;
    }

    const countdownEl = $('#details-refresh-countdown');
    if (!countdownEl) return;

    // Always reset countdown and keep it running
    detailsCountdown = DETAILS_REFRESH_RATE;
    countdownEl.textContent = detailsCountdown;

    // Countdown display update — always tick, but only refresh if needed
    detailsCountdownInterval = setInterval(() => {
        detailsCountdown--;
        if (detailsCountdown <= 0) {
            detailsCountdown = DETAILS_REFRESH_RATE;
            if (needsRefresh) {
                loadJobDetails();
            }
        }
        const el = $('#details-refresh-countdown');
        if (el) el.textContent = detailsCountdown;
    }, 1000);
}

/**
 * Load the submit file content for display in the Submit File tab.
 * Fetches it from the submissions API which queries the local DB.
 */
async function loadSubmitFileContent(data) {
    const outputEl = $('#submitfile-content-output');
    if (!outputEl) return;

    try {
        // Try to get the submit description from the submission record
        const submissions = await api('/submissions?limit=500');
        const submission = (submissions.submissions || []).find(s => s.cluster_id === clusterId);
        if (submission && submission.submit_description) {
            let content = submission.submit_description;
            // If it's a JSON object (from form builder), show the raw JSON
            // (preserves comments and whitespace from the original submission)
            if (content.trim().startsWith('{')) {
                try {
                    const parsed = JSON.parse(content);
                    // Show the raw JSON string (formatted) rather than reconstructing
                    // the .sub file, which would lose comments and whitespace
                    content = JSON.stringify(parsed, null, 2);
                } catch {
                    // Not JSON, show as-is (raw submit file content)
                }
            }
            outputEl.textContent = content;
        } else {
            outputEl.textContent = 'Submit file not available for this job (submitted outside the web UI or no longer in database).';
        }
    } catch (e) {
        outputEl.textContent = 'Failed to load submit file: ' + e.message;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadJobDetails();

    // Refresh button
    $('#refresh-details-btn').addEventListener('click', () => {
        loadJobDetails();
        // Reset countdown
        detailsCountdown = DETAILS_REFRESH_RATE;
        $('#details-refresh-countdown').textContent = detailsCountdown;
    });

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