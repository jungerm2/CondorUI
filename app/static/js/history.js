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

    // Show cached data immediately (non-blocking)
    const cached = getCachedHistory();
    if (cached) {
        currentHistory = cached;
        renderHistoryTable();
    }

    try {
        const data = await api(`/history?limit=${limit}`);
        if (data.daemon_unavailable) {
            currentHistory = [];
            setCachedHistory([]);
            const tbody = $('#history-tbody');
            if (tbody) {
                tbody.innerHTML = `<tr class="empty-row"><td colspan="8">⚠️ HTCondor daemon is not available. This is expected on a development machine without a running condor_schedd.</td></tr>`;
            }
            return;
        }
        const jobs = data.jobs || [];
        currentHistory = jobs;
        setCachedHistory(jobs);
        renderHistoryTable();
    } catch (e) {
        const msg = e.message || '';
        // If we already have cached data displayed, just show a toast — don't replace the table
        if (cached && cached.length > 0) {
            toast('Could not refresh history (using cached data). ' + msg, 'warning');
            return;
        }
        // Detect timeout errors and show a more helpful message
        if (msg.includes('timed out') || msg.includes('timeout') || msg.includes('NetworkError') || msg.includes('Failed to fetch')) {
            toast('History query timed out. The HTCondor schedd may be slow or unresponsive. Try again later.', 'error');
            const tbody = $('#history-tbody');
            if (tbody) {
                tbody.innerHTML = `<tr class="empty-row"><td colspan="8">⚠️ History query timed out. The HTCondor schedd may be slow or unresponsive. <button class="btn btn-sm" onclick="loadHistory()">Retry</button></td></tr>`;
            }
        } else {
            toast('Failed to load history: ' + msg, 'error');
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
