/* ===== Condor Web UI — SPA Application ===== */

(function () {
    "use strict";

    // ── State ──
    let currentTab = "dashboard";
    let refreshInterval = null;
    let countdown = 30;
    let countdownInterval = null;
    let allJobs = [];
    let sortField = "ClusterId";
    let sortAsc = false;
    let selectedSubmitFile = null;
    let uploadedFiles = [];

    // ── Helpers ──
    const $ = (sel, ctx = document) => ctx.querySelector(sel);
    const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

    function api(url, opts = {}) {
        return fetch(url, opts).then(r => {
            if (!r.ok) return r.json().then(d => Promise.reject(d));
            return r.json();
        });
    }

    function toast(msg, type = "info") {
        const c = $("#toast-container");
        const el = document.createElement("div");
        el.className = `toast ${type}`;
        el.textContent = msg;
        c.appendChild(el);
        setTimeout(() => { el.classList.add("removing"); setTimeout(() => el.remove(), 300); }, 4000);
    }

    function formatDate(epoch) {
        if (!epoch) return "—";
        const d = new Date(epoch * 1000);
        return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    }

    function formatDuration(seconds) {
        if (!seconds || seconds <= 0) return "—";
        seconds = Math.round(seconds);
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = seconds % 60;
        if (h > 0) return `${h}h ${m}m`;
        if (m > 0) return `${m}m ${s}s`;
        return `${s}s`;
    }

    function statusClass(name) {
        const map = { "Idle": "idle", "Running": "running", "Held": "held", "Completed": "completed", "Transferring Output": "transferring", "Removed": "removed", "Suspended": "idle" };
        return map[name] || "idle";
    }

    function basename(path) {
        if (!path) return "—";
        return String(path).split("/").pop();
    }

    // ── Navigation ──
    function navigate(tab) {
        currentTab = tab;
        $$(".nav-link").forEach(l => l.classList.toggle("active", l.dataset.tab === tab));
        $$(".tab-panel").forEach(p => p.classList.toggle("active", p.id === `panel-${tab}`));

        if (tab === "dashboard") { refreshDashboard(); startAutoRefresh(); }
        else { stopAutoRefresh(); }
        if (tab === "templates") loadTemplates();
    }

    // ── Dashboard ──
    async function refreshDashboard() {
        try {
            const [statsData, jobsData] = await Promise.all([api("/api/stats"), api("/api/jobs")]);
            updateStats(statsData);
            allJobs = jobsData.jobs || [];
            renderJobsTable();
            setConnected(true);
        } catch (e) {
            console.error("Dashboard refresh failed:", e);
            setConnected(false);
        }
    }

    function updateStats(s) {
        $("#stat-total").textContent = s.Total ?? 0;
        $("#stat-idle").textContent = s.Idle ?? 0;
        $("#stat-running").textContent = s.Running ?? 0;
        $("#stat-held").textContent = s.Held ?? 0;
    }

    function renderJobsTable() {
        const tbody = $("#jobs-tbody");
        let jobs = [...allJobs];

        // Filter by search
        const search = ($("#job-search").value || "").toLowerCase();
        if (search) {
            jobs = jobs.filter(j =>
                String(j.ClusterId).includes(search) ||
                (j.Owner || "").toLowerCase().includes(search) ||
                (j.Cmd || "").toLowerCase().includes(search) ||
                (j.JobBatchName || "").toLowerCase().includes(search)
            );
        }

        // Filter by status
        const statusFilter = $("#status-filter").value;
        if (statusFilter) jobs = jobs.filter(j => j.JobStatus == statusFilter);

        // Sort
        jobs.sort((a, b) => {
            let va = a[sortField] ?? "", vb = b[sortField] ?? "";
            if (typeof va === "number" && typeof vb === "number") return sortAsc ? va - vb : vb - va;
            va = String(va).toLowerCase(); vb = String(vb).toLowerCase();
            return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
        });

        if (jobs.length === 0) {
            tbody.innerHTML = `<tr class="empty-row"><td colspan="8">No active jobs</td></tr>`;
            return;
        }

        tbody.innerHTML = jobs.map(j => {
            const id = `${j.ClusterId}.${j.ProcId}`;
            const sc = statusClass(j.JobStatusName);
            return `<tr>
                <td><span class="job-id" data-cluster="${j.ClusterId}" data-proc="${j.ProcId}">${id}</span></td>
                <td>${j.Owner || "—"}</td>
                <td class="job-cmd" title="${j.Cmd || ""}">${basename(j.Cmd)}</td>
                <td><span class="status-badge status-${sc}">${j.JobStatusName}</span></td>
                <td class="job-host" title="${j.RemoteHost || ""}">${j.RemoteHost ? basename(j.RemoteHost) : "—"}</td>
                <td>${formatDate(j.QDate)}</td>
                <td class="job-resources">${j.RequestCpus || 1} CPU · ${j.RequestMemory || "?"} MB</td>
                <td>
                    <div class="action-btns">
                        ${j.JobStatus !== 5 ? `<button class="action-btn hold" title="Hold" data-action="hold" data-id="${id}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg></button>` : ""}
                        ${j.JobStatus === 5 ? `<button class="action-btn release" title="Release" data-action="release" data-id="${id}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5,3 19,12 5,21"/></svg></button>` : ""}
                        <button class="action-btn remove" title="Remove" data-action="remove" data-id="${id}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
                    </div>
                </td>
            </tr>`;
        }).join("");
    }

    function startAutoRefresh() {
        stopAutoRefresh();
        countdown = 30;
        countdownInterval = setInterval(() => {
            countdown--;
            const el = $("#refresh-countdown");
            if (el) el.textContent = countdown;
            if (countdown <= 0) { countdown = 30; refreshDashboard(); }
        }, 1000);
    }

    function stopAutoRefresh() {
        clearInterval(countdownInterval);
        countdownInterval = null;
    }

    function setConnected(ok) {
        const el = $("#connection-status");
        el.classList.toggle("connected", ok);
        $(".status-text", el).textContent = ok ? "Connected" : "Disconnected";
    }

    // ── Job Actions ──
    async function jobAction(action, jobId) {
        try {
            const method = action === "remove" ? "DELETE" : "POST";
            const url = action === "remove" ? `/api/jobs/${jobId}` : `/api/jobs/${jobId}/${action}`;
            await api(url, { method });
            toast(`Job ${jobId} ${action === "remove" ? "removed" : action + "ed"}`, "success");
            refreshDashboard();
        } catch (e) {
            toast(`Failed to ${action} ${jobId}: ${e.error || e.message || e}`, "error");
        }
    }

    // ── Job Detail Modal ──
    async function showJobDetail(clusterId, procId) {
        const overlay = $("#job-modal-overlay");
        const body = $("#modal-body");
        $("#modal-title").textContent = `Job ${clusterId}.${procId}`;
        body.innerHTML = "<p style='color:var(--text-muted)'>Loading...</p>";
        overlay.classList.add("active");

        try {
            const data = await api(`/api/jobs/${clusterId}`);
            const job = (data.jobs || []).find(j => j.ProcId == procId) || data.jobs[0];
            if (!job) { body.innerHTML = "<p>Job not found</p>"; return; }

            const attrs = Object.entries(job).filter(([k]) => k !== "JobStatusName").sort(([a], [b]) => a.localeCompare(b));
            let html = `<div class="detail-grid">`;
            const priority = ["ClusterId", "ProcId", "JobStatus", "JobStatusName", "Owner", "Cmd", "Args", "RemoteHost", "HoldReason"];
            const shown = new Set();

            priority.forEach(k => {
                if (job[k] !== undefined) {
                    shown.add(k);
                    const isWide = k === "HoldReason" || k === "Cmd" || k === "Args";
                    html += `<div class="detail-item${isWide ? " full-width" : ""}"><div class="detail-label">${k}</div><div class="detail-value">${k === "JobStatus" ? `${job[k]} (${job.JobStatusName})` : job[k]}</div></div>`;
                }
            });
            attrs.forEach(([k, v]) => {
                if (!shown.has(k)) html += `<div class="detail-item"><div class="detail-label">${k}</div><div class="detail-value">${v}</div></div>`;
            });
            html += `</div>`;

            // Log section
            html += `<h3 style="margin: 16px 0 8px; font-size: 0.95rem;">Job Log</h3>`;
            html += `<div class="log-output" id="job-log-output">Loading log...</div>`;
            body.innerHTML = html;

            // Load log
            try {
                const logData = await api(`/api/jobs/${clusterId}/log?proc=${procId}`);
                $("#job-log-output").textContent = logData.log || "No log content";
            } catch { $("#job-log-output").textContent = "Could not load log"; }
        } catch (e) {
            body.innerHTML = `<p style="color:var(--status-held)">Error: ${e.error || e}</p>`;
        }
    }

    // ── Submit: Form Mode ──
    function buildSubmitDict() {
        const d = {};
        const universe = $("#job-universe").value;
        d.universe = universe;
        if ((universe === "container" || universe === "docker") && $("#job-container-image").value)
            d.container_image = $("#job-container-image").value;

        const exe = $("#job-executable").value.trim();
        if (!exe) return null;
        d.executable = exe;

        const args = $("#job-arguments").value.trim();
        if (args) d.arguments = args;

        const xfer = $("#job-transfer-input").value.trim();
        // Append uploaded file paths
        const allPaths = [xfer, ...uploadedFiles.map(f => f.osdf_path || f.local_path)].filter(Boolean);
        if (allPaths.length) d.transfer_input_files = allPaths.join(", ");

        d.request_cpus = $("#job-cpus").value;
        d.request_memory = $("#job-memory").value;
        d.request_disk = $("#job-disk").value;

        const output = $("#job-output").value.trim();
        if (output) d.output = output;
        const error = $("#job-error").value.trim();
        if (error) d.error = error;
        const log = $("#job-log").value.trim();
        if (log) d.log = log;

        // Extra attributes
        $$(".attr-row", $("#extra-attrs")).forEach(row => {
            const k = row.querySelector(".attr-key").value.trim();
            const v = row.querySelector(".attr-val").value.trim();
            if (k && v) d[k] = v;
        });

        d.should_transfer_files = "YES";
        return d;
    }

    async function submitForm() {
        const submit = buildSubmitDict();
        if (!submit) return toast("Executable is required", "error");
        const count = parseInt($("#job-count").value) || 1;
        const name = $("#job-name").value.trim() || "Untitled Job";

        try {
            const data = await api("/api/submit", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, submit, count }),
            });
            toast(`Submitted cluster ${data.cluster_id} (${data.num_procs} procs)`, "success");
            navigate("dashboard");
        } catch (e) {
            toast(`Submit failed: ${e.error || e}`, "error");
        }
    }

    // ── Submit: Raw Mode ──
    async function submitRaw() {
        const content = $("#raw-submit-editor").value.trim();
        if (!content) return toast("Submit description is empty", "error");
        const name = $("#raw-job-name").value.trim() || "Untitled Job";

        const formData = new FormData();
        const blob = new Blob([content], { type: "text/plain" });
        formData.append("file", blob, "job.sub");
        formData.append("name", name);

        try {
            const data = await api("/api/submit/file", { method: "POST", body: formData });
            toast(`Submitted cluster ${data.cluster_id} (${data.num_procs} procs)`, "success");
            navigate("dashboard");
        } catch (e) {
            toast(`Submit failed: ${e.error || e}`, "error");
        }
    }

    // ── Submit: File Mode ──
    async function submitFile() {
        if (!selectedSubmitFile) return toast("No file selected", "error");
        const name = $("#file-job-name").value.trim() || selectedSubmitFile.name;

        const formData = new FormData();
        formData.append("file", selectedSubmitFile);
        formData.append("name", name);

        try {
            const data = await api("/api/submit/file", { method: "POST", body: formData });
            toast(`Submitted cluster ${data.cluster_id} (${data.num_procs} procs)`, "success");
            navigate("dashboard");
        } catch (e) {
            toast(`Submit failed: ${e.error || e}`, "error");
        }
    }

    // ── File Upload (input files for OSDF staging) ──
    async function uploadInputFiles(files) {
        const formData = new FormData();
        for (const f of files) formData.append("files", f);

        try {
            const data = await api("/api/upload", { method: "POST", body: formData });
            uploadedFiles.push(...(data.uploaded || []));
            renderUploadedFiles();
            toast(`Uploaded ${data.count} file(s)`, "success");
        } catch (e) {
            toast(`Upload failed: ${e.error || e}`, "error");
        }
    }

    function renderUploadedFiles() {
        const container = $("#uploaded-files-list");
        container.innerHTML = uploadedFiles.map((f, i) => `
            <div class="uploaded-file">
                <span class="filename">${f.filename}</span>
                <span style="color:var(--text-muted);font-size:0.8rem">${f.osdf_path || f.local_path}</span>
                <button class="action-btn remove" data-upload-idx="${i}" title="Remove"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
            </div>
        `).join("");
    }

    // ── Templates ──
    async function loadTemplates() {
        try {
            const data = await api("/api/templates");
            renderTemplates(data.templates || []);
        } catch (e) {
            toast(`Failed to load templates: ${e.error || e}`, "error");
        }
    }

    function renderTemplates(templates) {
        const grid = $("#templates-grid");
        if (templates.length === 0) {
            grid.innerHTML = `<div class="empty-state"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" width="64" height="64"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14,2 14,8 20,8"/></svg><p>No templates saved yet</p><p class="hint">Build a submit description and save it as a template for reuse</p></div>`;
            return;
        }
        grid.innerHTML = templates.map(t => `
            <div class="template-card" data-id="${t.id}">
                <h3>${t.name}</h3>
                <p>${t.description || "No description"}</p>
                <div class="template-meta">Updated ${new Date(t.updated_at).toLocaleDateString()}</div>
                <div class="template-actions">
                    <button class="btn btn-ghost btn-sm use-template" data-id="${t.id}" data-submit='${t.submit_data}'>Use Template</button>
                    <button class="btn btn-danger btn-sm delete-template" data-id="${t.id}">Delete</button>
                </div>
            </div>
        `).join("");
    }

    async function saveTemplate() {
        const submit = buildSubmitDict();
        if (!submit) return toast("Build a submit description first", "error");

        const name = prompt("Template name:");
        if (!name) return;
        const description = prompt("Description (optional):") || "";

        try {
            await api("/api/templates", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, description, submit_data: submit }),
            });
            toast(`Template "${name}" saved`, "success");
            loadTemplates();
        } catch (e) {
            toast(`Failed to save: ${e.error || e}`, "error");
        }
    }

    async function deleteTemplate(id) {
        if (!confirm("Delete this template?")) return;
        try {
            await api(`/api/templates/${id}`, { method: "DELETE" });
            toast("Template deleted", "success");
            loadTemplates();
        } catch (e) {
            toast(`Failed to delete: ${e.error || e}`, "error");
        }
    }

    function useTemplate(submitData) {
        try {
            const d = typeof submitData === "string" ? JSON.parse(submitData) : submitData;
            navigate("submit");
            // Switch to form mode
            switchSubmitMode("form");
            // Fill form
            if (d.universe) $("#job-universe").value = d.universe;
            toggleContainerImage();
            if (d.container_image) $("#job-container-image").value = d.container_image;
            if (d.executable) $("#job-executable").value = d.executable;
            if (d.arguments) $("#job-arguments").value = d.arguments;
            if (d.transfer_input_files) $("#job-transfer-input").value = d.transfer_input_files;
            if (d.request_cpus) $("#job-cpus").value = d.request_cpus;
            if (d.request_memory) $("#job-memory").value = d.request_memory;
            if (d.request_disk) $("#job-disk").value = d.request_disk;
            if (d.output) $("#job-output").value = d.output;
            if (d.error) $("#job-error").value = d.error;
            if (d.log) $("#job-log").value = d.log;
            toast("Template loaded into form", "info");
        } catch (e) {
            toast("Failed to load template", "error");
        }
    }

    // ── History ──
    async function loadHistory() {
        const limit = $("#history-limit").value;
        try {
            const data = await api(`/api/history?limit=${limit}`);
            renderHistory(data.jobs || []);
        } catch (e) {
            toast(`Failed to load history: ${e.error || e}`, "error");
            renderHistory([]);
        }
    }

    function renderHistory(jobs) {
        const tbody = $("#history-tbody");
        const search = ($("#history-search").value || "").toLowerCase();
        if (search) {
            jobs = jobs.filter(j =>
                String(j.ClusterId).includes(search) ||
                (j.Owner || "").toLowerCase().includes(search) ||
                (j.Cmd || "").toLowerCase().includes(search)
            );
        }

        if (jobs.length === 0) {
            tbody.innerHTML = `<tr class="empty-row"><td colspan="8">No history found</td></tr>`;
            return;
        }

        tbody.innerHTML = jobs.map(j => {
            const sc = statusClass(j.JobStatusName);
            return `<tr>
                <td><span class="job-id" data-cluster="${j.ClusterId}" data-proc="${j.ProcId}">${j.ClusterId}.${j.ProcId}</span></td>
                <td>${j.Owner || "—"}</td>
                <td class="job-cmd" title="${j.Cmd || ""}">${basename(j.Cmd)}</td>
                <td><span class="status-badge status-${sc}">${j.JobStatusName}</span></td>
                <td>${j.ExitCode ?? "—"}</td>
                <td>${formatDate(j.QDate)}</td>
                <td>${formatDate(j.CompletionDate)}</td>
                <td>${formatDuration(j.RemoteWallClockTime)}</td>
            </tr>`;
        }).join("");
    }

    // ── UI Helpers ──
    function switchSubmitMode(mode) {
        $$(".toggle-btn").forEach(b => b.classList.toggle("active", b.dataset.mode === mode));
        $$(".submit-mode").forEach(p => p.classList.toggle("active", p.id === `mode-${mode}`));
    }

    function toggleContainerImage() {
        const v = $("#job-universe").value;
        $("#container-image-group").style.display = (v === "container" || v === "docker") ? "block" : "none";
    }

    function addAttrRow() {
        const container = $("#extra-attrs");
        const row = document.createElement("div");
        row.className = "attr-row";
        row.innerHTML = `<input type="text" class="form-input attr-key" placeholder="Key"><input type="text" class="form-input attr-val" placeholder="Value"><button class="remove-attr" title="Remove">&times;</button>`;
        container.appendChild(row);
        row.querySelector(".remove-attr").addEventListener("click", () => row.remove());
    }

    function setupDropzone(dropzoneId, inputId, onFiles) {
        const dz = $(`#${dropzoneId}`);
        const input = $(`#${inputId}`);

        dz.addEventListener("click", () => input.click());
        dz.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("dragover"); });
        dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
        dz.addEventListener("drop", e => {
            e.preventDefault(); dz.classList.remove("dragover");
            onFiles(e.dataTransfer.files);
        });
        input.addEventListener("change", () => { if (input.files.length) onFiles(input.files); });
    }

    // ── Init ──
    function init() {
        // Navigation
        $$(".nav-link").forEach(link => {
            link.addEventListener("click", e => { e.preventDefault(); navigate(link.dataset.tab); });
        });

        // Handle hash navigation
        const hash = location.hash.replace("#", "") || "dashboard";
        navigate(hash);
        window.addEventListener("hashchange", () => navigate(location.hash.replace("#", "") || "dashboard"));

        // Dashboard controls
        $("#refresh-btn").addEventListener("click", refreshDashboard);
        $("#job-search").addEventListener("input", renderJobsTable);
        $("#status-filter").addEventListener("change", renderJobsTable);

        // Table sorting
        $$(".sortable").forEach(th => {
            th.addEventListener("click", () => {
                if (sortField === th.dataset.sort) sortAsc = !sortAsc;
                else { sortField = th.dataset.sort; sortAsc = true; }
                renderJobsTable();
            });
        });

        // Job actions (delegated)
        document.addEventListener("click", e => {
            const actionBtn = e.target.closest("[data-action]");
            if (actionBtn) {
                const action = actionBtn.dataset.action;
                const id = actionBtn.dataset.id;
                if (action === "remove" && !confirm(`Remove job ${id}?`)) return;
                jobAction(action, id);
            }

            const jobId = e.target.closest(".job-id");
            if (jobId) showJobDetail(jobId.dataset.cluster, jobId.dataset.proc);

            const useBtn = e.target.closest(".use-template");
            if (useBtn) useTemplate(useBtn.dataset.submit);

            const delBtn = e.target.closest(".delete-template");
            if (delBtn) deleteTemplate(delBtn.dataset.id);

            const uploadRemove = e.target.closest("[data-upload-idx]");
            if (uploadRemove) { uploadedFiles.splice(parseInt(uploadRemove.dataset.uploadIdx), 1); renderUploadedFiles(); }
        });

        // Modal
        $("#modal-close-btn").addEventListener("click", () => $("#job-modal-overlay").classList.remove("active"));
        $("#job-modal-overlay").addEventListener("click", e => { if (e.target === e.currentTarget) e.currentTarget.classList.remove("active"); });

        // Submit mode toggle
        $$(".toggle-btn").forEach(btn => btn.addEventListener("click", () => switchSubmitMode(btn.dataset.mode)));

        // Universe → container image
        $("#job-universe").addEventListener("change", toggleContainerImage);

        // Extra attributes
        $("#add-attr-btn").addEventListener("click", addAttrRow);

        // Submit buttons
        $("#submit-form-btn").addEventListener("click", submitForm);
        $("#submit-raw-btn").addEventListener("click", submitRaw);
        $("#submit-file-btn").addEventListener("click", submitFile);

        // Input file upload dropzone
        setupDropzone("input-file-dropzone", "input-file-upload", files => uploadInputFiles(files));

        // Submit file dropzone
        setupDropzone("submit-file-dropzone", "submit-file-input", files => {
            selectedSubmitFile = files[0];
            const reader = new FileReader();
            reader.onload = () => {
                $("#file-preview").innerHTML = `<pre>${reader.result}</pre>`;
                $("#submit-file-btn").disabled = false;
            };
            reader.readAsText(files[0]);
        });

        // Templates
        $("#save-template-btn").addEventListener("click", saveTemplate);

        // History
        $("#refresh-history-btn").addEventListener("click", loadHistory);
        $("#history-limit").addEventListener("change", loadHistory);
        $("#history-search").addEventListener("input", () => loadHistory());

        // Theme toggle
        const themeToggle = $("#theme-toggle");
        if (themeToggle) {
            themeToggle.addEventListener("click", () => {
                document.body.classList.toggle("light-theme");
                localStorage.setItem("condor-theme", document.body.classList.contains("light-theme") ? "light" : "dark");
            });
            const savedTheme = localStorage.getItem("condor-theme");
            if (savedTheme === "light" || (!savedTheme && window.matchMedia("(prefers-color-scheme: light)").matches)) {
                document.body.classList.add("light-theme");
            }
        }
    }

    document.addEventListener("DOMContentLoaded", init);
})();
