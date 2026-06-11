let currentHistory = [];
let sortField = 'ClusterId';
let sortAsc = false;

async function loadHistory() {
    const limit = $('#history-limit').value;
    try {
        const data = await api(`/history?limit=${limit}`);
        if (data.daemon_unavailable) {
            currentHistory = [];
            const tbody = $('#history-tbody');
            if (tbody) {
                tbody.innerHTML = `<tr class="empty-row"><td colspan="8">⚠️ HTCondor daemon is not available. This is expected on a development machine without a running condor_schedd.</td></tr>`;
            }
            return;
        }
        currentHistory = data.jobs || [];
        renderHistoryTable();
    } catch (e) {
        toast('Failed to load history: ' + e.message, 'error');
    }
}

function getFilteredHistory() {
    const query = $('#history-search').value.toLowerCase().trim();

    return currentHistory.filter(job => {
        return !query || 
            (job.ClusterId.toString().includes(query)) ||
            (job.Owner && job.Owner.toLowerCase().includes(query)) ||
            (job.Cmd && job.Cmd.toLowerCase().includes(query));
    });
}

function renderHistoryTable() {
    const tbody = $('#history-tbody');
    tbody.innerHTML = '';

    let filtered = getFilteredHistory();

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr class="empty-row"><td colspan="8">No history records found</td></tr>`;
        return;
    }

    filtered.forEach(job => {
        const tr = document.createElement('tr');
        const statusClass = getStatusClass(job.JobStatus);
        const statusName = getStatusName(job.JobStatus);
        
        const qDate = formatDate(job.QDate);
        const compDate = formatDate(job.CompletionDate);
        
        let wallTime = '—';
        if (job.RemoteWallClockTime) {
            wallTime = formatDuration(Math.round(parseFloat(job.RemoteWallClockTime)));
        } else if (job.CompletionDate && job.QDate) {
            wallTime = formatDuration(job.CompletionDate - job.QDate);
        }

        const exitCode = job.ExitCode !== undefined ? job.ExitCode : '—';

        tr.innerHTML = `
            <td><a href="/job/${job.ClusterId}/${job.ProcId}" class="job-id-link">${job.ClusterId}.${job.ProcId}</a></td>
            <td>${job.Owner || '—'}</td>
            <td class="monospace" title="${job.Cmd}">${basename(job.Cmd)}</td>
            <td><span class="status-badge ${statusClass}">${statusName}</span></td>
            <td class="monospace">${exitCode}</td>
            <td>${qDate}</td>
            <td>${compDate}</td>
            <td>${wallTime}</td>
        `;
        tbody.appendChild(tr);
    });
}

document.addEventListener('DOMContentLoaded', () => {
    loadHistory();

    // Event listeners
    $('#refresh-history-btn').addEventListener('click', loadHistory);
    $('#history-limit').addEventListener('change', loadHistory);
    $('#history-search').addEventListener('input', renderHistoryTable);
});
