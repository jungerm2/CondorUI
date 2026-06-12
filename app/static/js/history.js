let currentHistory = [];
let sortField = 'ClusterId';
let sortAsc = false;
let historyLoadInProgress = false;

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
            tbody.innerHTML = `<tr class="empty-row"><td colspan="8">Unable to load history. ${e.message}</td></tr>`;
        }
    } finally {
        historyLoadInProgress = false;
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
        const cpus = job.RequestCpus || '—';
        const mem = formatMemory(job.RequestMemory);
        const disk = formatDisk(job.RequestDisk);

        tr.innerHTML = `
            <td><a href="/job/${job.ClusterId}/${job.ProcId}" class="job-id-link">${job.ClusterId}.${job.ProcId}</a></td>
            <td>${job.Owner || '—'}</td>
            <td class="monospace" title="${job.Cmd || job.Args || ''}">${formatCommand(job.Cmd, job.Args)}</td>
            <td><span class="status-badge ${statusClass}">${statusName}</span></td>
            <td class="monospace">${exitCode}</td>
            <td>${qDate}</td>
            <td>${compDate}</td>
            <td>${wallTime}</td>
            <td style="font-size: 0.85rem;">${cpus} CPU, ${mem}, ${disk}</td>
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
