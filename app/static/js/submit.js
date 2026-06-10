// Local variables
let uploadedFiles = [];
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

// OSDF Input Files Upload & Drag/Drop
function initInputFilesUpload() {
    const dropzone = $('#input-file-dropzone');
    const fileInput = $('#input-file-upload');
    const listEl = $('#uploaded-files-list');

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
            handleUploadFiles(e.dataTransfer.files);
        }
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length) {
            handleUploadFiles(fileInput.files);
        }
    });

    async function handleUploadFiles(files) {
        for (const file of files) {
            const formData = new FormData();
            formData.append('file', file);
            toast(`Uploading ${file.name}...`);
            try {
                const res = await fetch('/api/upload', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Upload failed');
                
                uploadedFiles.push(data.osdf_uri);
                renderUploadedFiles();
                toast(`${file.name} uploaded and staged to OSDF`);
            } catch (err) {
                toast(`Upload failed: ${err.message}`, 'error');
            }
        }
    }

    function renderUploadedFiles() {
        listEl.innerHTML = '';
        uploadedFiles.forEach((uri, idx) => {
            const name = basename(uri);
            const fileItem = document.createElement('div');
            fileItem.className = 'uploaded-file-item';
            fileItem.innerHTML = `
                <span class="file-name monospace">${name}</span>
                <span class="file-uri monospace">${uri}</span>
                <button class="btn btn-ghost btn-sm remove-file-btn" data-idx="${idx}" title="Remove file" style="color: var(--danger-color);">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <line x1="18" y1="6" x2="6" y2="18" />
                        <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                </button>
            `;
            fileItem.querySelector('.remove-file-btn').addEventListener('click', (e) => {
                const i = parseInt(e.currentTarget.dataset.idx);
                uploadedFiles.splice(i, 1);
                renderUploadedFiles();
            });
            listEl.appendChild(fileItem);
        });
    }
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
                    <strong>${file.name}</strong>
                    <span class="file-size">${(file.size / 1024).toFixed(2)} KB</span>
                </div>
                <pre class="monospace" style="background: var(--bg-secondary); padding: 12px; border-radius: 6px; overflow-x: auto; max-height: 250px; border: 1px solid var(--border-color);">${e.target.result}</pre>
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
        executable: $('#job-executable').value.trim()
    };

    if (universe === 'container') {
        const img = $('#job-container-image').value.trim();
        if (img) d.container_image = img;
    }

    const args = $('#job-arguments').value.trim();
    if (args) d.arguments = args;

    // Combine form input transfer file list with uploaded files list
    let transferInputs = ($('#job-transfer-input').value || '')
        .split(',')
        .map(x => x.trim())
        .filter(x => x);
    
    uploadedFiles.forEach(uri => {
        if (!transferInputs.includes(uri)) {
            transferInputs.push(uri);
        }
    });

    if (transferInputs.length > 0) {
        d.transfer_input_files = transferInputs.join(', ');
    }

    // Resources
    d.request_cpus = $('#job-cpus').value;
    d.request_memory = $('#job-memory').value;
    d.request_disk = $('#job-disk').value;

    // Output/Error/Log paths - if not empty
    const output = $('#job-output').value.trim();
    if (output) d.output = output;
    const error = $('#job-error').value.trim();
    if (error) d.error = error;
    const log = $('#job-log').value.trim();
    if (log) d.log = log;

    // Custom attrs
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

    if (!submit.executable) {
        toast('Executable is required', 'warning');
        return;
    }

    toast('Submitting job...');
    try {
        const res = await api('/submit', {
            method: 'POST',
            body: JSON.stringify({ name, submit, count })
        });
        toast(`Submitted successfully! Cluster ID: ${res.cluster_id}`);
        // Reset or navigate to dashboard
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
        const res = await api('/submit/file', {
            method: 'POST',
            // Since it's /submit/file, we must send a Form
            body: (() => {
                const fd = new FormData();
                fd.append('name', name);
                const file = new Blob([content], { type: 'text/plain' });
                fd.append('file', file, 'submit.sub');
                return fd;
            })()
        });
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
    
    // Formatting standard .sub layout
    rawText += `universe = ${submit.universe || 'vanilla'}\n`;
    if (submit.container_image) {
        rawText += `container_image = ${submit.container_image}\n`;
    }
    rawText += `executable = ${submit.executable || ''}\n`;
    if (submit.arguments) {
        rawText += `arguments = ${submit.arguments}\n`;
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
    
    // Extras
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
    
    // Reset extra attributes container
    const container = $('#extra-attrs');
    container.innerHTML = '';
    uploadedFiles = [];

    lines.forEach(line => {
        line = line.split('#')[0].trim(); // Remove comment
        if (!line || !line.includes('=')) return;

        const parts = line.split('=');
        const key = parts[0].trim().toLowerCase();
        const val = parts.slice(1).join('=').trim();

        switch (key) {
            case 'universe':
                $('#job-universe').value = val;
                $('#job-universe').dispatchEvent(new Event('change'));
                break;
            case 'container_image':
                $('#job-container-image').value = val;
                break;
            case 'executable':
                $('#job-executable').value = val;
                break;
            case 'arguments':
                $('#job-arguments').value = val;
                break;
            case 'transfer_input_files':
                // Parse out staged osdf files
                const files = val.split(',').map(f => f.trim());
                files.forEach(f => {
                    if (f.startsWith('osdf:///')) {
                        uploadedFiles.push(f);
                    }
                });
                // Find and keep only non-osdf inputs for the local text box
                const nonOsdf = files.filter(f => !f.startsWith('osdf:///'));
                $('#job-transfer-input').value = nonOsdf.join(', ');
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
                        <input type="text" value="${parts[0].trim()}" class="form-input attr-key">
                        <input type="text" value="${val}" class="form-input attr-value">
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

        // Try to match "queue <count>"
        const queueMatch = line.match(/^queue\s+(\d+)/i);
        if (queueMatch) {
            $('#job-count').value = queueMatch[1];
        }
    });

    // Refresh uploaded files list presentation
    const listEl = $('#uploaded-files-list');
    listEl.innerHTML = '';
    uploadedFiles.forEach((uri, idx) => {
        const name = basename(uri);
        const fileItem = document.createElement('div');
        fileItem.className = 'uploaded-file-item';
        fileItem.innerHTML = `
            <span class="file-name monospace">${name}</span>
            <span class="file-uri monospace">${uri}</span>
            <button class="btn btn-ghost btn-sm remove-file-btn" data-idx="${idx}" title="Remove file" style="color: var(--danger-color);">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
            </button>
        `;
        fileItem.querySelector('.remove-file-btn').addEventListener('click', (e) => {
            const i = parseInt(e.currentTarget.dataset.idx);
            uploadedFiles.splice(i, 1);
            fileItem.remove();
        });
        listEl.appendChild(fileItem);
    });
}

function checkSelectedTemplate() {
    const raw = localStorage.getItem('selectedTemplate');
    if (raw) {
        localStorage.removeItem('selectedTemplate');
        try {
            const tmpl = JSON.parse(raw);
            toast(`Loaded template: ${tmpl.name}`);
            $('#job-name').value = tmpl.name;
            
            if (tmpl.description.trim().startsWith('{')) {
                const submit = JSON.parse(tmpl.description);
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
                    uploadedFiles = files.filter(f => f.startsWith('osdf:///'));
                    const nonOsdf = files.filter(f => !f.startsWith('osdf:///'));
                    $('#job-transfer-input').value = nonOsdf.join(', ');
                }
                
                const standardKeys = ['universe', 'container_image', 'executable', 'arguments', 'request_cpus', 'request_memory', 'request_disk', 'output', 'error', 'log', 'transfer_input_files'];
                const container = $('#extra-attrs');
                container.innerHTML = '';
                for (const [key, val] of Object.entries(submit)) {
                    if (!standardKeys.includes(key)) {
                        const row = document.createElement('div');
                        row.className = 'attr-row';
                        row.innerHTML = `
                            <input type="text" value="${key}" class="form-input attr-key">
                            <input type="text" value="${val}" class="form-input attr-value">
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
            } else {
                // Switch to Raw mode
                const rawBtn = $('#mode-raw-btn');
                if (rawBtn) rawBtn.click();
                $('#raw-submit-editor').value = tmpl.description;
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

    let description = '';
    if (mode === 'form') {
        const submit = buildSubmitDict();
        if (!submit.executable) {
            toast('Executable is required to save template', 'warning');
            return;
        }
        description = JSON.stringify(submit);
    } else {
        description = $('#raw-submit-editor').value.trim();
        if (!description) {
            toast('Submit description cannot be empty', 'warning');
            return;
        }
    }

    toast('Saving template...');
    try {
        await api('/templates', {
            method: 'POST',
            body: JSON.stringify({ name, description })
        });
        toast('Template saved successfully!');
    } catch (err) {
        toast(`Failed to save template: ${err.message}`, 'error');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initModeToggle();
    initExtraAttrs();
    initInputFilesUpload();
    initSubmitFileUpload();

    // Show/hide container image input depending on universe choice
    $('#job-universe').addEventListener('change', (e) => {
        const containerGroup = $('#container-image-group');
        if (e.target.value === 'container') {
            containerGroup.style.display = 'block';
        } else {
            containerGroup.style.display = 'none';
        }
    });

    // Tab mode transition sync
    $('#mode-raw-btn').addEventListener('click', syncFormToRaw);
    $('#mode-form-btn').addEventListener('click', syncRawToForm);

    // Submission triggers
    $('#submit-form-btn').addEventListener('click', submitFormJob);
    $('#submit-raw-btn').addEventListener('click', submitRawJob);
    $('#submit-file-btn').addEventListener('click', submitUploadedFileJob);

    // Save as template triggers
    $('#save-as-tmpl-btn').addEventListener('click', () => saveAsTemplate('form'));
    
    // Inject save as template button in raw actions
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

    // Check template load
    checkSelectedTemplate();
});
