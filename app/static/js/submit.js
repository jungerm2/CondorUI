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

// Load server-side containers and populate the select dropdown
async function loadContainers() {
    const selectEl = $('#job-container-select');
    if (!selectEl) return;

    try {
        const data = await api('/containers');
        serverContainers = data.containers || [];

        // Clear existing options (keep the default)
        selectEl.innerHTML = '<option value="">— Select a container —</option>';

        serverContainers.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.uri;
            opt.textContent = `${c.name} (${c.filename})`;
            selectEl.appendChild(opt);
        });

        // If there's a pre-selected container, set it
        if (selectedContainerUri) {
            selectEl.value = selectedContainerUri;
        }
    } catch (err) {
        selectEl.innerHTML = `<option value="">— Failed to load containers: ${err.message} —</option>`;
    }
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

// formatFileSize is now defined in common.js
// This duplicate has been removed; use the shared version instead.

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
        // Transfer executable checkbox
        if ($('#job-transfer-executable').checked) {
            d.transfer_executable = true;
        }
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

    // GPU / CUDA fields
    const gpus = parseInt($('#job-gpus').value) || 0;
    if (gpus > 0) {
        d.request_gpus = gpus;
    }
    const gpuMinCap = $('#job-gpu-min-capability').value.trim();
    if (gpuMinCap) d.gpus_minimum_capability = gpuMinCap;
    const gpuMinMem = $('#job-gpu-min-memory').value.trim();
    if (gpuMinMem) d.gpus_minimum_memory = gpuMinMem;
    const gpuMinRuntime = $('#job-gpu-min-runtime').value.trim();
    if (gpuMinRuntime) d.gpus_minimum_runtime = gpuMinRuntime;
    const cudaVer = $('#job-cuda-version').value.trim();
    if (cudaVer) d.cuda_version = cudaVer;

    const output = $('#job-output').value.trim();
    if (output) d.output = output;
    const error = $('#job-error').value.trim();
    if (error) d.error = error;
    const log = $('#job-log').value.trim();
    if (log) d.log = log;

    // Output file transfer fields
    const transferOutput = $('#job-transfer-output').value.trim();
    if (transferOutput) {
        d.transfer_output_files = transferOutput;
    }

    const outputDirectory = $('#job-output-directory').value.trim();
    if (outputDirectory) {
        d.output_directory = outputDirectory;
    }

    const outputRemaps = $('#job-output-remaps').value.trim();
    if (outputRemaps) {
        // Parse remaps: each line is "filename = destination"
        const remapLines = outputRemaps.split('\n').map(l => l.trim()).filter(l => l);
        if (remapLines.length > 0) {
            // Build a semicolon-separated remap string
            const remapEntries = [];
            for (const line of remapLines) {
                const eqIdx = line.indexOf('=');
                if (eqIdx > 0) {
                    const key = line.substring(0, eqIdx).trim();
                    const val = line.substring(eqIdx + 1).trim();
                    if (key && val) {
                        remapEntries.push(`${key} = ${val}`);
                    }
                }
            }
            if (remapEntries.length > 0) {
                d.transfer_output_remaps = remapEntries.join('; ');
            }
        }
    }

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
    const content = $('#raw-submit-editor').value;

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
    if (submit.request_gpus) {
        rawText += `request_gpus = ${submit.request_gpus}\n`;
    }
    if (submit.gpus_minimum_capability) {
        rawText += `gpus_minimum_capability = ${submit.gpus_minimum_capability}\n`;
    }
    if (submit.gpus_minimum_memory) {
        rawText += `gpus_minimum_memory = ${submit.gpus_minimum_memory}\n`;
    }
    if (submit.gpus_minimum_runtime) {
        rawText += `gpus_minimum_runtime = ${submit.gpus_minimum_runtime}\n`;
    }
    if (submit.cuda_version) {
        rawText += `cuda_version = ${submit.cuda_version}\n`;
    }

    rawText += `\n# Output & Logs\n`;
    if (submit.output) rawText += `output = ${submit.output}\n`;
    if (submit.error) rawText += `error = ${submit.error}\n`;
    if (submit.log) rawText += `log = ${submit.log}\n`;
    if (submit.transfer_output_files) {
        rawText += `transfer_output_files = ${submit.transfer_output_files}\n`;
    }
    if (submit.output_directory) {
        rawText += `output_directory = ${submit.output_directory}\n`;
    }
    if (submit.transfer_output_remaps) {
        rawText += `transfer_output_remaps = ${submit.transfer_output_remaps}\n`;
    }

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
        const trimmedLine = line.split('#')[0].trim();
        if (!trimmedLine) return;

        // Handle queue directive separately (e.g., "queue 5")
        const queueMatch = trimmedLine.match(/^queue\s+(\d+)$/i);
        if (queueMatch) {
            $('#job-count').value = queueMatch[1];
            return;
        }

        if (!trimmedLine.includes('=')) return;

        const eqIdx = trimmedLine.indexOf('=');
        const key = trimmedLine.substring(0, eqIdx).trim().toLowerCase();
        const val = trimmedLine.substring(eqIdx + 1).trim();

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
            case 'request_gpus':
                $('#job-gpus').value = val;
                break;
            case 'gpus_minimum_capability':
                $('#job-gpu-min-capability').value = val;
                break;
            case 'gpus_minimum_memory':
                $('#job-gpu-min-memory').value = val;
                break;
            case 'gpus_minimum_runtime':
                $('#job-gpu-min-runtime').value = val;
                break;
            case 'cuda_version':
                $('#job-cuda-version').value = val;
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
            case 'transfer_output_files':
                $('#job-transfer-output').value = val;
                break;
            case 'output_directory':
                $('#job-output-directory').value = val;
                break;
            case 'transfer_output_remaps':
                // Remaps are stored as semicolon-separated "key = val; key2 = val2"
                // Convert to newline-separated for the textarea
                const remapLines = val.split(';').map(s => s.trim()).filter(s => s);
                $('#job-output-remaps').value = remapLines.join('\n');
                break;
            default:
                // Handle as custom ClassAd
                if (key !== 'queue') {
                    const row = document.createElement('div');
                    row.className = 'attr-row';
                    row.innerHTML = `
                        <input type="text" value="${escHtml(trimmedLine.substring(0, eqIdx).trim())}" class="form-input attr-key">
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
        // No staged files selected — remove the Requirements row only if it was auto-added (readonly)
        if (existingReqRow) {
            const keyInput = existingReqRow.querySelector('.attr-key');
            if (keyInput && keyInput.hasAttribute('readonly')) {
                existingReqRow.remove();
            }
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
                if (submit.container_image) {
                    $('#job-container-image').value = submit.container_image;
                    // Sync container dropdown
                    if (serverContainers.length > 0) {
                        const matched = serverContainers.find(c => c.uri === submit.container_image);
                        if (matched) {
                            $('#job-container-select').value = matched.uri;
                        }
                    }
                }
                if (submit.executable) {
                    $('#job-executable').value = submit.executable;
                    // Sync executable picker
                    const execName = submit.executable.replace(/^executables\//, '');
                    const matched = serverExecutables.find(ex => ex.filename === execName);
                    if (matched) {
                        selectedExecutableName = matched.filename;
                    }
                    renderExecPicker();
                }
                if (submit.arguments) $('#job-arguments').value = submit.arguments;
                if (submit.request_cpus) $('#job-cpus').value = submit.request_cpus;
                if (submit.request_memory) $('#job-memory').value = submit.request_memory;
                if (submit.request_disk) $('#job-disk').value = submit.request_disk;
                if (submit.output) $('#job-output').value = submit.output;
                if (submit.error) $('#job-error').value = submit.error;
                if (submit.log) $('#job-log').value = submit.log;
                if (submit.transfer_output_files) $('#job-transfer-output').value = submit.transfer_output_files;
                if (submit.output_directory) $('#job-output-directory').value = submit.output_directory;
                if (submit.transfer_output_remaps) {
                    // Convert semicolon-separated to newline-separated for the textarea
                    const remapLines = submit.transfer_output_remaps.split(';').map(s => s.trim()).filter(s => s);
                    $('#job-output-remaps').value = remapLines.join('\n');
                }
                if (submit.request_gpus) $('#job-gpus').value = submit.request_gpus;
                if (submit.gpus_minimum_capability) $('#job-gpu-min-capability').value = submit.gpus_minimum_capability;
                if (submit.gpus_minimum_memory) $('#job-gpu-min-memory').value = submit.gpus_minimum_memory;
                if (submit.gpus_minimum_runtime) $('#job-gpu-min-runtime').value = submit.gpus_minimum_runtime;
                if (submit.cuda_version) $('#job-cuda-version').value = submit.cuda_version;
                if (submit.transfer_executable) $('#job-transfer-executable').checked = true;
                if (submit.queue) $('#job-count').value = submit.queue;

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
                    // Update the text field to include both manual entries and selected file URIs
                    updateTransferInputField();
                }

                const standardKeys = [
                    'universe', 'container_image', 'executable', 'arguments', 'shell',
                    'request_cpus', 'request_memory', 'request_disk',
                    'output', 'error', 'log',
                    'transfer_input_files',
                    'transfer_output_files', 'output_directory', 'transfer_output_remaps',
                    'request_gpus', 'gpus_minimum_capability', 'gpus_minimum_memory',
                    'gpus_minimum_runtime', 'cuda_version', 'transfer_executable',
                    'requirements', 'queue',
                ];
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
    // Pre-fill the template name with the job name
    const jobNameInput = mode === 'form' ? $('#job-name') : $('#raw-job-name');
    const defaultName = jobNameInput ? jobNameInput.value.trim() || 'My Template' : 'My Template';
    $('#save-template-name').value = defaultName;

    // Open the modal
    openModal('save-template-modal');
    $('#save-template-name').focus();
    $('#save-template-name').select();

    // Store the mode for the confirm handler
    window._saveTemplateMode = mode;
}

async function confirmSaveTemplate() {
    const name = $('#save-template-name').value.trim();
    if (!name) {
        toast('Please enter a template name', 'warning');
        return;
    }

    const mode = window._saveTemplateMode;
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
        closeModal('save-template-modal');
    } catch (err) {
        toast(`Failed to save template: ${err.message}`, 'error');
    }
}
// ---------------------------------------------------------------------------
// Executables card — always visible, single-select with toggle, like input files
// ---------------------------------------------------------------------------

let serverExecutables = [];
let selectedExecutableName = null;

async function loadExecutablesForPicker() {
    try {
        const data = await api('/executables');
        serverExecutables = data.executables || [];
    } catch (err) {
        serverExecutables = [];
    }
}

function renderExecPicker() {
    const listEl = $('#exec-picker-list');
    if (!listEl) return;

    if (serverExecutables.length === 0) {
        listEl.innerHTML = `
            <p class="hint" style="color: var(--text-muted); font-size: 0.85rem;">
                No executables uploaded yet.
                <a href="/executables" style="color: var(--accent-cyan);">Upload executables</a>
            </p>`;
        return;
    }

    listEl.innerHTML = '';
    serverExecutables.forEach(ex => {
        const isSelected = selectedExecutableName === ex.filename;
        const item = document.createElement('div');
        item.className = `submit-file-item ${isSelected ? 'selected' : ''}`;
        item.style.cursor = 'pointer';
        item.innerHTML = `
            <div class="submit-file-check">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" class="check-icon">
                    <polyline points="20,6 9,17 4,12" />
                </svg>
            </div>
            <div class="submit-file-info">
                <span class="submit-file-name monospace">${escHtml(ex.filename)}</span>
                <span class="submit-file-meta">${formatFileSize(ex.size)}</span>
            </div>
        `;
        item.addEventListener('click', () => {
            // Toggle selection: if already selected, un-select; otherwise select
            if (selectedExecutableName === ex.filename) {
                // Un-select
                selectedExecutableName = null;
                $('#job-executable').value = '';
                item.classList.remove('selected');
            } else {
                // Select this one
                selectedExecutableName = ex.filename;
                // Use the full path (EXECUTABLES_DIR + filename) for the input field
                $('#job-executable').value = 'executables/' + ex.filename;
                $('#job-transfer-executable').checked = true;
                // Refresh visual state — deselect all others
                listEl.querySelectorAll('.submit-file-item').forEach(el => el.classList.remove('selected'));
                item.classList.add('selected');
            }
        });
        listEl.appendChild(item);
    });
}

// Show/hide the executables card based on exec/shell mode
function updateExecutablesCardVisibility() {
    const card = $('#executables-card');
    if (!card) return;
    const isShell = $('#execmode-shell-btn').classList.contains('active');
    card.style.display = isShell ? 'none' : '';
}

document.addEventListener('DOMContentLoaded', () => {
    initModeToggle();
    initExtraAttrs();
    initSubmitFileUpload();

    // Load server files, containers, and executables, then check for template
    Promise.all([
        loadServerFiles(),
        loadContainers(),
        loadExecutablesForPicker()
    ]).then(() => {
        checkSelectedTemplate();
        // Render executables card after data is loaded
        renderExecPicker();
    });

    $('#job-universe').addEventListener('change', (e) => {
        const containerGroup = $('#container-image-group');
        const containerSelectGroup = $('#container-select-group');
        if (e.target.value === 'container' || e.target.value === 'docker') {
            containerGroup.style.display = 'block';
            if (containerSelectGroup) containerSelectGroup.style.display = 'block';
        } else {
            containerGroup.style.display = 'none';
            if (containerSelectGroup) containerSelectGroup.style.display = 'none';
        }
    });

    // When a container is selected from the dropdown, set the container image path
    $('#job-container-select').addEventListener('change', (e) => {
        const selectedUri = e.target.value;
        $('#job-container-image').value = selectedUri;
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
            updateExecutablesCardVisibility();
        });

        shellBtn.addEventListener('click', () => {
            shellBtn.classList.add('active');
            execBtn.classList.remove('active');
            shellField.style.display = 'block';
            execField.style.display = 'none';
            argsField.style.display = 'none';
            updateExecutablesCardVisibility();
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
    $('#raw-save-as-tmpl-btn').addEventListener('click', () => saveAsTemplate('raw'));

    // Save template modal confirm button (defined in common.js openModal/closeModal)
    const saveConfirmBtn = $('#save-template-confirm-btn');
    if (saveConfirmBtn) {
        saveConfirmBtn.addEventListener('click', confirmSaveTemplate);
    }

    // Also allow Enter key to confirm in the save template modal
    const saveNameInput = $('#save-template-name');
    if (saveNameInput) {
        saveNameInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                confirmSaveTemplate();
            }
        });
    }
});