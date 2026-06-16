// Local variables
let serverFiles = [];
let serverContainers = [];
let selectedFileUris = new Set();
let selectedContainerUri = null;
let pendingSubmitFile = null;

// Submission modes toggle
function initModeToggle() {
    const buttons = $$('.mode-toggle button');
    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            buttons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const mode = btn.dataset.mode;
            $$('.submit-mode').forEach(el => el.classList.remove('active'));
            $(`#mode-${mode}`).classList.add('active');
        });
    });
}

// Extra attributes management
function initExtraAttrs() {
    const container = $('#extra-attrs');
    const addBtn = $('#add-attr-btn');

    addBtn.addEventListener('click', () => {
        const row = document.createElement('div');
        row.className = 'attr-row';
        row.innerHTML = `
            <input type="text" placeholder="Attribute Name" class="form-input attr-key">
            <input type="text" placeholder="Value" class="form-input attr-value">
            <button class="btn btn-ghost remove-attr-btn" title="Remove">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
            </button>
        `;
        row.querySelector('.remove-attr-btn').addEventListener('click', () => row.remove());
        container.appendChild(row);
    });
}

// Load server-side containers and render clickable list
async function loadContainers() {
    const listEl = $('#submit-containers-list');
    if (!listEl) return;

    try {
        const data = await api('/containers');
        serverContainers = data.containers || [];
    } catch (err) {
        listEl.innerHTML = `<p class="hint" style="color: var(--text-muted); font-size: 0.85rem;">Could not load containers: ${err.message}</p>`;
        return;
    }

    if (serverContainers.length === 0) {
        listEl.innerHTML = `
            <p class="hint" style="color: var(--text-muted); font-size: 0.85rem;">
                No containers available.
                <a href="/containers" style="color: var(--accent-cyan);">Manage containers</a>
            </p>`;
        return;
    }

    listEl.innerHTML = '';
    serverContainers.forEach(c => {
        const isSelected = selectedContainerUri === c.uri;
        const item = document.createElement('div');
        item.className = `submit-file-item ${isSelected ? 'selected' : ''}`;
        item.dataset.uri = c.uri;
        item.dataset.id = c.id;

        item.innerHTML = `
            <div class="submit-file-check">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" class="check-icon">
                    <polyline points="20,6 9,17 4,12" />
                </svg>
            </div>
            <div class="submit-file-info">
                <span class="submit-file-name">${escHtml(c.name)}</span>
                <span class="submit-file-meta">${formatFileSize(c.size)}</span>
            </div>
        `;

        item.addEventListener('click', () => {
            const uri = item.dataset.uri;
            if (selectedContainerUri === uri) {
                selectedContainerUri = null;
                item.classList.remove('selected');
                $('#job-container-image').value = '';
            } else {
                // Deselect all others
                listEl.querySelectorAll('.submit-file-item').forEach(el => el.classList.remove('selected'));
                selectedContainerUri = uri;
                item.classList.add('selected');
                $('#job-container-image').value = uri;
            }
        });

        listEl.appendChild(item);
    });
}

// Load server-side files and render clickable list
async function loadServerFiles() {
    const listEl = $('#submit-files-list');
    if (!listEl) return;

    try {
        const data = await api('/files');
        serverFiles = data.files || [];
    } catch (err) {
        listEl.innerHTML = `<p class="hint" style="color: var(--text-muted); font-size: 0.85rem;">Could not load files: ${err.message}</p>`;
        return;
    }

    if (serverFiles.length === 0) {
        listEl.innerHTML = `
            <p class="hint" style="color: var(--text-muted); font-size: 0.85rem;">
                No files uploaded yet.
                <a href="/files" style="color: var(--accent-cyan);">Upload files</a>
            </p>`;
        return;
    }

    listEl.innerHTML = '';
    serverFiles.forEach(f => {
        const isSelected = selectedFileUris.has(f.uri);
        const item = document.createElement('div');
        item.className = `submit-file-item ${isSelected ? 'selected' : ''}`;
        item.dataset.uri = f.uri;
        item.dataset.id = f.id;

        const isOsdf = !!f.osdf_path;
        const locationLabel = isOsdf ? 'OSDF' : 'Local';

        item.innerHTML = `
            <div class="submit-file-check">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" class="check-icon">
                    <polyline points="20,6 9,17 4,12" />
                </svg>
            </div>
            <div class="submit-file-info">
                <span class="submit-file-name monospace">${escHtml(f.original_name)}</span>
                <span class="submit-file-meta">${formatFileSize(f.size)} · ${locationLabel}</span>
            </div>
        `;

        item.addEventListener('click', () => {
            const uri = item.dataset.uri;
            if (selectedFileUris.has(uri)) {
                selectedFileUris.delete(uri);
                item.classList.remove('selected');
            } else {
                selectedFileUris.add(uri);
                item.classList.add('selected');
            }
            // Update the transfer_input_files text field
            updateTransferInputField();
            // Update the Requirements based on staged file selection
            updateStagedRequirements();
        });

        listEl.appendChild(item);
    });
}

function formatFileSize(bytes) {
    if (!bytes && bytes !== 0) return '—';
    if (bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    let size = bytes;
    while (size >= 1024 && i < units.length - 1) {
        size /= 1024;
        i++;
    }
    return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

// Update the transfer_input_files text field with selected file URIs
function updateTransferInputField() {
    // Keep only manual entries that are NOT server-managed file URIs
    const serverUriSet = new Set(serverFiles.map(f => f.uri));
    const manualInput = ($('#job-transfer-input').value || '')
        .split(',')
        .map(x => x.trim())
        .filter(x => x && !serverUriSet.has(x));

    const allUris = [...manualInput, ...Array.from(selectedFileUris)];
    $('#job-transfer-input').value = allUris.join(', ');
}

// .sub file upload & preview
function initSubmitFileUpload() {
    const dropzone = $('#submit-file-dropzone');
    const fileInput = $('#submit-file-input');
    const previewEl = $('#file-preview');
    const submitBtn = $('#submit-file-btn');

    dropzone.addEventListener('click', () => fileInput.click());

    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));

    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            setSubmitFile(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length) {
            setSubmitFile(fileInput.files[0]);
        }
    });

    function setSubmitFile(file) {
        pendingSubmitFile = file;
        const reader = new FileReader();
        reader.onload = (e) => {
            previewEl.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <strong>${escHtml(file.name)}</strong>
                    <span class="file-size">${(file.size / 1024).toFixed(2)} KB</span>
                </div>
                <pre class="monospace" style="background: var(--bg-secondary); padding: 12px; border-radius: 6px; overflow-x: auto; max-height: 250px; border: 1px solid var(--border-color);">${escHtml(e.target.result)}</pre>
            `;
            submitBtn.removeAttribute('disabled');
        };
        reader.readAsText(file);
    }
}

// Build submit dict from form builder inputs
function buildSubmitDict() {
    const universe = $('#job-universe').value;
    const d = {
        universe: universe,
    };

    const isShell = $('#execmode-shell-btn').classList.contains('active');
    if (isShell) {
        d.shell = $('#job-shell-cmd').value.trim();
    } else {
        d.executable = $('#job-executable').value.trim();
    }

    if (universe === 'container') {
        const img = $('#job-container-image').value.trim();
        if (img) d.container_image = img;
    }

    const args = $('#job-arguments').value.trim();
    if (args) d.arguments = args;

    let transferInputs = ($('#job-transfer-input').value || '')
        .split(',')
        .map(x => x.trim())
        .filter(x => x);

    if (transferInputs.length > 0) {
        d.transfer_input_files = transferInputs.join(', ');
    }

    d.request_cpus = $('#job-cpus').value;
    d.request_memory = $('#job-memory').value;
    d.request_disk = $('#job-disk').value;

    const output = $('#job-output').value.trim();
    if (output) d.output = output;
    const error = $('#job-error').value.trim();
    if (error) d.error = error;
    const log = $('#job-log').value.trim();
    if (log) d.log = log;

    $$('.attr-row').forEach(row => {
        const key = row.querySelector('.attr-key').value.trim();
        const val = row.querySelector('.attr-value').value.trim();
        if (key) d[key] = val;
    });

    return d;
}

// Job Submission handlers
async function submitFormJob() {
    const name = $('#job-name').value.trim() || 'Untitled Job';
    const count = parseInt($('#job-count').value) || 1;
    const submit = buildSubmitDict();

    if (!submit.executable && !submit.shell) {
        const isShell = $('#execmode-shell-btn').classList.contains('active');
        toast(isShell ? 'Shell command is required' : 'Executable is required', 'warning');
        return;
    }

    toast('Submitting job...');
    try {
        const res = await api('/submit', {
            method: 'POST',
            body: JSON.stringify({ name, submit, count })
        });
        toast(`Submitted successfully! Cluster ID: ${res.cluster_id}`);
        setTimeout(() => window.location.href = '/', 1500);
    } catch (err) {
        toast(`Submission failed: ${err.message}`, 'error');
    }
}

async function submitRawJob() {
    const name = $('#raw-job-name').value.trim() || 'Raw Submit';
    const content = $('#raw-submit-editor').value.trim();

    if (!content) {
        toast('Submit description cannot be empty', 'warning');
        return;
    }

    toast('Submitting job...');
    try {
        // Use FormData (not the api() helper) to avoid JSON Content-Type header
        const formData = new FormData();
        formData.append('name', name);
        const blob = new Blob([content], { type: 'text/plain' });
        formData.append('file', blob, 'submit.sub');

        const response = await fetch('/api/submit/file', {
            method: 'POST',
            body: formData
        });
        const res = await response.json();
        if (!response.ok) throw new Error(res.error || 'Submit failed');
        toast(`Submitted successfully! Cluster ID: ${res.cluster_id}`);
        setTimeout(() => window.location.href = '/', 1500);
    } catch (err) {
        toast(`Submission failed: ${err.message}`, 'error');
    }
}

async function submitUploadedFileJob() {
    if (!pendingSubmitFile) return;

    const name = $('#file-job-name').value.trim() || pendingSubmitFile.name;
    const formData = new FormData();
    formData.append('name', name);
    formData.append('file', pendingSubmitFile);

    toast('Submitting submit file...');
    try {
        const response = await fetch('/api/submit/file', {
            method: 'POST',
            body: formData
        });
        const res = await response.json();
        if (!response.ok) throw new Error(res.error || 'Submit file execution failed');

        toast(`Submitted successfully! Cluster ID: ${res.cluster_id}`);
        setTimeout(() => window.location.href = '/', 1500);
    } catch (err) {
        toast(`Submission failed: ${err.message}`, 'error');
    }
}

// Syncing Form to Raw
function syncFormToRaw() {
    const submit = buildSubmitDict();
    let rawText = '';

    rawText += `universe = ${submit.universe || 'vanilla'}\n`;
    if (submit.container_image) {
        rawText += `container_image = ${submit.container_image}\n`;
    }
    if (submit.shell) {
        rawText += `shell = ${submit.shell}\n`;
    } else if (submit.executable) {
        rawText += `executable = ${submit.executable}\n`;
        if (submit.arguments) {
            rawText += `arguments = ${submit.arguments}\n`;
        }
    }
    if (submit.transfer_input_files) {
        rawText += `transfer_input_files = ${submit.transfer_input_files}\n`;
    }

    rawText += `\n# Resources\n`;
    rawText += `request_cpus = ${submit.request_cpus || '1'}\n`;
    rawText += `request_memory = ${submit.request_memory || '1 GB'}\n`;
    rawText += `request_disk = ${submit.request_disk || '1 GB'}\n`;

    rawText += `\n# Output & Logs\n`;
    if (submit.output) rawText += `output = ${submit.output}\n`;
    if (submit.error) rawText += `error = ${submit.error}\n`;
    if (submit.log) rawText += `log = ${submit.log}\n`;

    let hasExtras = false;
    $$('.attr-row').forEach(row => {
        const key = row.querySelector('.attr-key').value.trim();
        const val = row.querySelector('.attr-value').value.trim();
        if (key) {
            if (!hasExtras) {
                rawText += `\n# Additional ClassAds\n`;
                hasExtras = true;
            }
            rawText += `${key} = ${val}\n`;
        }
    });

    const count = parseInt($('#job-count').value) || 1;
    rawText += `\nqueue ${count}\n`;

    $('#raw-submit-editor').value = rawText;
}

// Syncing Raw to Form
function syncRawToForm() {
    const rawText = $('#raw-submit-editor').value;
    const lines = rawText.split('\n');

    const container = $('#extra-attrs');
    container.innerHTML = '';
    selectedFileUris.clear();

    lines.forEach(line => {
        line = line.split('#')[0].trim();
        if (!line || !line.includes('=')) return;

        const eqIdx = line.indexOf('=');
        const key = line.substring(0, eqIdx).trim().toLowerCase();
        const val = line.substring(eqIdx + 1).trim();

        switch (key) {
            case 'universe':
                $('#job-universe').value = val;
                $('#job-universe').dispatchEvent(new Event('change'));
                break;
            case 'container_image':
                $('#job-container-image').value = val;
                break;
            case 'executable':
                $('#execmode-exec-btn').classList.add('active');
                $('#execmode-shell-btn').classList.remove('active');
                $('#exec-field').style.display = 'block';
                $('#shell-field').style.display = 'none';
                $('#args-field').style.display = 'block';
                $('#job-executable').value = val;
                break;
            case 'shell':
                $('#execmode-shell-btn').classList.add('active');
                $('#execmode-exec-btn').classList.remove('active');
                $('#shell-field').style.display = 'block';
                $('#exec-field').style.display = 'none';
                $('#args-field').style.display = 'none';
                $('#job-shell-cmd').value = val;
                break;
            case 'arguments':
                $('#job-arguments').value = val;
                break;
            case 'transfer_input_files':
                const files = val.split(',').map(f => f.trim());
                // Try to match against server files by URI
                files.forEach(f => {
                    const matched = serverFiles.find(sf => sf.uri === f);
                    if (matched) {
                        selectedFileUris.add(matched.uri);
                    }
                });
                // Non-matched files go to manual input
                const matchedUris = new Set(serverFiles.map(sf => sf.uri));
                const nonMatched = files.filter(f => !matchedUris.has(f));
                $('#job-transfer-input').value = nonMatched.join(', ');
                break;
            case 'request_cpus':
                $('#job-cpus').value = val;
                break;
            case 'request_memory':
                $('#job-memory').value = val;
                break;
            case 'request_disk':
                $('#job-disk').value = val;
                break;
            case 'output':
                $('#job-output').value = val;
                break;
            case 'error':
                $('#job-error').value = val;
                break;
            case 'log':
                $('#job-log').value = val;
                break;
            default:
                // Handle as custom ClassAd
                if (key !== 'queue') {
                    const row = document.createElement('div');
                    row.className = 'attr-row';
                    row.innerHTML = `
                        <input type="text" value="${escHtml(line.substring(0, eqIdx).trim())}" class="form-input attr-key">
                        <input type="text" value="${escHtml(val)}" class="form-input attr-value">
                        <button class="btn btn-ghost remove-attr-btn" title="Remove">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                                <line x1="18" y1="6" x2="6" y2="18" />
                                <line x1="6" y1="6" x2="18" y2="18" />
                            </svg>
                        </button>
                    `;
                    row.querySelector('.remove-attr-btn').addEventListener('click', () => row.remove());
                    container.appendChild(row);
                }
                break;
        }

        const queueMatch = line.match(/^queue\s+(\d+)/i);
        if (queueMatch) {
            $('#job-count').value = queueMatch[1];
        }
    });

    // Refresh the file selection UI and staged requirements
    refreshFileSelectionUI();
    updateStagedRequirements();
}

// Refresh the visual state of file items based on selectedFileUris
function refreshFileSelectionUI() {
    const items = document.querySelectorAll('#submit-files-list .submit-file-item');
    items.forEach(item => {
        const uri = item.dataset.uri;
        if (selectedFileUris.has(uri)) {
            item.classList.add('selected');
        } else {
            item.classList.remove('selected');
        }
    });
}

// Check if any selected files are staged (OSDF) and auto-add Requirements = (Target.HasCHTCStaging == true)
function updateStagedRequirements() {
    const container = $('#extra-attrs');
    const attrRows = container.querySelectorAll('.attr-row');

    // Check if any of the currently selected file URIs correspond to staged files
    const hasStagedFile = Array.from(selectedFileUris).some(uri => {
        const file = serverFiles.find(f => f.uri === uri);
        return file && file.osdf_path;
    });

    // Look for existing Requirements row
    let existingReqRow = null;
    attrRows.forEach(row => {
        const key = row.querySelector('.attr-key').value.trim();
        if (key.toLowerCase() === 'requirements') {
            existingReqRow = row;
        }
    });

    if (hasStagedFile) {
        if (!existingReqRow) {
            // Add a new Requirements row
            const row = document.createElement('div');
            row.className = 'attr-row';
            row.innerHTML = `
                <input type="text" value="Requirements" class="form-input attr-key" readonly style="color: var(--text-muted);">
                <input type="text" value="(Target.HasCHTCStaging == true)" class="form-input attr-value" readonly style="color: var(--text-muted);">
                <button class="btn btn-ghost remove-attr-btn" title="Remove" style="visibility: hidden;">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <line x1="18" y1="6" x2="6" y2="18" />
                        <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                </button>
            `;
            container.appendChild(row);
        }
    } else {
        // No staged files selected — remove the Requirements row if it was auto-added
        if (existingReqRow) {
            existingReqRow.remove();
        }
    }
}

function checkSelectedTemplate() {
    const raw = localStorage.getItem('selectedTemplate');
    if (raw) {
        localStorage.removeItem('selectedTemplate');
        try {
            const tmpl = JSON.parse(raw);
            toast(`Loaded template: ${tmpl.name}`);
            $('#job-name').value = tmpl.name;

            // Use submit_data for the actual submit description, with description as fallback
            const submitStr = tmpl.submit_data || tmpl.description || '';
            if (!submitStr) return;

            if (submitStr.trim().startsWith('{')) {
                const submit = JSON.parse(submitStr);
                if (submit.shell) {
                    $('#execmode-shell-btn').classList.add('active');
                    $('#execmode-exec-btn').classList.remove('active');
                    $('#shell-field').style.display = 'block';
                    $('#exec-field').style.display = 'none';
                    $('#args-field').style.display = 'none';
                    $('#job-shell-cmd').value = submit.shell;
                }
                if (submit.universe) {
                    $('#job-universe').value = submit.universe;
                    $('#job-universe').dispatchEvent(new Event('change'));
                }
                if (submit.container_image) $('#job-container-image').value = submit.container_image;
                if (submit.executable) $('#job-executable').value = submit.executable;
                if (submit.arguments) $('#job-arguments').value = submit.arguments;
                if (submit.request_cpus) $('#job-cpus').value = submit.request_cpus;
                if (submit.request_memory) $('#job-memory').value = submit.request_memory;
                if (submit.request_disk) $('#job-disk').value = submit.request_disk;
                if (submit.output) $('#job-output').value = submit.output;
                if (submit.error) $('#job-error').value = submit.error;
                if (submit.log) $('#job-log').value = submit.log;

                if (submit.transfer_input_files) {
                    const files = submit.transfer_input_files.split(',').map(f => f.trim());
                    // Match against server files
                    files.forEach(f => {
                        const matched = serverFiles.find(sf => sf.uri === f);
                        if (matched) {
                            selectedFileUris.add(matched.uri);
                        }
                    });
                    const matchedUris = new Set(serverFiles.map(sf => sf.uri));
                    const nonMatched = files.filter(f => !matchedUris.has(f));
                    $('#job-transfer-input').value = nonMatched.join(', ');
                }

                const standardKeys = ['universe', 'container_image', 'executable', 'arguments', 'shell', 'request_cpus', 'request_memory', 'request_disk', 'output', 'error', 'log', 'transfer_input_files'];
                const container = $('#extra-attrs');
                container.innerHTML = '';
                for (const [key, val] of Object.entries(submit)) {
                    if (!standardKeys.includes(key)) {
                        const row = document.createElement('div');
                        row.className = 'attr-row';
                        row.innerHTML = `
                            <input type="text" value="${escHtml(key)}" class="form-input attr-key">
                            <input type="text" value="${escHtml(String(val))}" class="form-input attr-value">
                            <button class="btn btn-ghost remove-attr-btn" title="Remove">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                                    <line x1="18" y1="6" x2="6" y2="18" />
                                    <line x1="6" y1="6" x2="18" y2="18" />
                                </svg>
                            </button>
                        `;
                        row.querySelector('.remove-attr-btn').addEventListener('click', () => row.remove());
                        container.appendChild(row);
                    }
                }

                // Refresh file selection UI and staged requirements
                refreshFileSelectionUI();
                updateStagedRequirements();
            } else {
                // Switch to Raw mode
                const rawBtn = $('#mode-raw-btn');
                if (rawBtn) rawBtn.click();
                $('#raw-submit-editor').value = submitStr;
                $('#raw-job-name').value = tmpl.name;
            }
        } catch (e) {
            console.error('Error loading template', e);
        }
    }
}

async function saveAsTemplate(mode) {
    const name = prompt('Enter a name for this template:');
    if (!name) return;

    let submit_data = '';
    if (mode === 'form') {
        const submit = buildSubmitDict();
        if (!submit.executable && !submit.shell) {
            const isShell = $('#execmode-shell-btn').classList.contains('active');
            toast(isShell ? 'Shell command is required to save template' : 'Executable is required to save template', 'warning');
            return;
        }
        submit_data = JSON.stringify(submit);
    } else {
        submit_data = $('#raw-submit-editor').value.trim();
        if (!submit_data) {
            toast('Submit description cannot be empty', 'warning');
            return;
        }
    }

    toast('Saving template...');
    try {
        await api('/templates', {
            method: 'POST',
            body: JSON.stringify({ name, submit_data })
        });
        toast('Template saved successfully!');
    } catch (err) {
        toast(`Failed to save template: ${err.message}`, 'error');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initModeToggle();
    initExtraAttrs();
    initSubmitFileUpload();

    // Load server files and containers, then check for template
    Promise.all([
        loadServerFiles(),
        loadContainers()
    ]).then(() => {
        checkSelectedTemplate();
    });

    $('#job-universe').addEventListener('change', (e) => {
        const containerGroup = $('#container-image-group');
        const containerSelectGroup = $('#container-select-group');
        if (e.target.value === 'container') {
            containerGroup.style.display = 'block';
            containerSelectGroup.style.display = 'block';
        } else {
            containerGroup.style.display = 'none';
            containerSelectGroup.style.display = 'none';
        }
    });

    function initExecShellToggle() {
        const execBtn = $('#execmode-exec-btn');
        const shellBtn = $('#execmode-shell-btn');
        const execField = $('#exec-field');
        const shellField = $('#shell-field');
        const argsField = $('#args-field');

        execBtn.addEventListener('click', () => {
            execBtn.classList.add('active');
            shellBtn.classList.remove('active');
            execField.style.display = 'block';
            shellField.style.display = 'none';
            argsField.style.display = 'block';
        });

        shellBtn.addEventListener('click', () => {
            shellBtn.classList.add('active');
            execBtn.classList.remove('active');
            shellField.style.display = 'block';
            execField.style.display = 'none';
            argsField.style.display = 'none';
        });
    }
    initExecShellToggle();

    $('#mode-raw-btn').addEventListener('click', () => {
        $('#raw-job-name').value = $('#job-name').value.trim() || 'Untitled Job';
        syncFormToRaw();
    });
    $('#mode-form-btn').addEventListener('click', () => {
        $('#job-name').value = $('#raw-job-name').value.trim() || '';
        syncRawToForm();
    });

    $('#submit-form-btn').addEventListener('click', submitFormJob);
    $('#submit-raw-btn').addEventListener('click', submitRawJob);
    $('#submit-file-btn').addEventListener('click', submitUploadedFileJob);

    $('#save-as-tmpl-btn').addEventListener('click', () => saveAsTemplate('form'));

    const rawSaveBtn = document.createElement('button');
    rawSaveBtn.className = 'btn btn-ghost btn-lg';
    rawSaveBtn.id = 'raw-save-as-tmpl-btn';
    rawSaveBtn.type = 'button';
    rawSaveBtn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" style="margin-right: 8px;">
            <path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z" />
            <polyline points="17,21 17,13 7,13 7,21" />
            <polyline points="7,3 7,8 15,8" />
        </svg>
        Save as Template
    `;
    $('#mode-raw .submit-actions').insertBefore(rawSaveBtn, $('#submit-raw-btn'));
    rawSaveBtn.addEventListener('click', () => saveAsTemplate('raw'));
});