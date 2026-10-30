// Renders page — thin client-side wrapper. Picks files/executables/containers
// from existing endpoints, composes the full submit payload client-side, and
// loops POST /api/submit for batch mode. No results UI: clusters are linked to
// the dashboard history (/job/<cluster_id>).

const FRAME_LIMIT = 1048574; // Blender's hard frame-number limit (matches render.py)
const WARNING_COLOR = 'var(--status-warning-color)';

// Single source of truth for every page default. Change values here and the
// form, the payload and the macros all follow.
const DEFAULTS = {
    jobName: 'Visionsim Render',
    frames: { start: 1, end: 250 },
    jobs: 6,
    grid: { rows: 2, cols: 3, spacing: 0 },
    config: {
        width: '',   // blank = use the .blend file's own resolution
        height: '',
        resolutionPercentage: '', // blank = visionsim default (100)
        maxSamples: '',           // blank = visionsim default (256)
        deviceType: 'cpu',
        keyframeMultiplier: '',   // blank = visionsim default (1.0)
    },
    passes: {
        composites: false, frames: true, depths: false, normals: false,
        flows: false, segmentations: false, materials: false,
        diffuse: false, specular: false, points: false,
    },
    playblast: { video: true },
    output: {
        directory: '$(OutputsDir)/$INT(ClusterId,%08d)', // shown as editable text
        directoryMacro: '$(OutputsDir)/$INT(ClusterId,%08d)',
        researchdrive: 'pelican://chtc.wisc.edu/researchdrive/mgupta37/CHTC',
        subdir: '',
        remap: false,
    },
    resources: {
        cpus: 8, memory: '4 GB', disk: '8 GB',
    },
    // Seeded into the Additional ClassAds card; they are the source of truth
    // for these attributes, so removing a row removes the attribute.
    classAds: {
        Requirements: '(Target.HasCHTCStaging == true)',
        max_retries: '3',
        stream_output: 'True',
        stream_error: 'True',
        retry_request_memory: 'RequestMemory * 2',
        retry_request_disk: 'RequestDisk * 2',
    },
};

let rendersMode = 'single';
let renderBlendFiles = []; // /api/files entries ending in .blend
let renderContainers = [];
let renderExecutables = [];
// Everything selected, in any mode. More than one file means one cluster each.
let selectedBlendUris = new Set();

function fileIsStaged(f) {
    return !!f.osdf_path || (f.uri || '').startsWith('osdf://');
}

function blendFolder(displayName) {
    const parts = (displayName || '').split('/');
    return parts.length > 1 ? parts.slice(0, -1).join(' / ') : '(root)';
}

function blendBaseName(displayName) {
    const parts = (displayName || '').split('/');
    return parts[parts.length - 1];
}

// Batching is inferred: more than one selected file = one cluster per file.
function isMultiSelectMode() {
    return selectedBlendUris.size > 1;
}

function selectedBlendEntries() {
    return renderBlendFiles.filter(f => selectedBlendUris.has(f.uri));
}

// Folder checkboxes show all / none / partial selection.
function syncFolderToggle(details, files) {
    const toggle = details.querySelector('[data-folder-toggle]');
    if (!toggle) return;
    const selected = files.filter(f => selectedBlendUris.has(f.uri)).length;
    toggle.checked = files.length > 0 && selected === files.length;
    toggle.indeterminate = selected > 0 && selected < files.length;
}

// ----- Data loading -----

function loadServerData() {
    return Promise.all([
        api('/files').then(data => {
            renderBlendFiles = (data.files || []).filter(f =>
                /\.blend$/i.test(f.display_name || f.original_name || ''));
        }),
        api('/executables').then(data => {
            renderExecutables = data.executables || [];
        }),
        api('/containers').then(data => {
            renderContainers = data.containers || [];
        }),
    ]);
}

// ----- Pickers -----

function renderBlendList() {
    const listEl = $('#renders-blend-list');
    const query = ($('#renders-blend-search').value || '').toLowerCase().trim();
    const visible = query
        ? renderBlendFiles.filter(f =>
            (f.display_name || '').toLowerCase().includes(query) ||
            (f.original_name || '').toLowerCase().includes(query))
        : renderBlendFiles;
    const folders = new Map();
    visible.forEach(f => {
        const folder = blendFolder(f.display_name);
        if (!folders.has(folder)) folders.set(folder, []);
        folders.get(folder).push(f);
    });
    if (renderBlendFiles.length === 0) {
        listEl.innerHTML = `<p class="hint" style="color: var(--text-muted); font-size: 0.85rem;">
            No .blend files uploaded yet. <a href="/files" style="color: var(--accent-cyan);">Upload files</a></p>`;
        return;
    }
    if (visible.length === 0) {
        listEl.innerHTML = `<p class="hint" style="color: var(--text-muted); font-size: 0.85rem;">No .blend files match "${escHtml(query)}"</p>`;
        return;
    }
    listEl.innerHTML = '';
    // Collapsible folder groups, same details/summary pattern as the rest of
    // the codebase (details.card): summary row acts as the heading.
    folders.forEach((files, folder) => {
        const details = document.createElement('details');
        details.className = 'renders-folder';
        details.open = true;
        const summary = document.createElement('summary');
        // The folder checkbox selects/deselects everything inside it.
        const selCount = files.filter(f => selectedBlendUris.has(f.uri)).length;
        const allSelected = selCount === files.length;
        summary.innerHTML = `<input type="checkbox" data-folder-toggle aria-label="Select all in ${escHtml(folder)}" ${allSelected ? 'checked' : ''}>
            <span class="renders-folder-name">${escHtml(folder)}</span>
            <span class="renders-folder-count">${files.length}</span>`;
        details.appendChild(summary);
        const toggle = summary.querySelector('[data-folder-toggle]');
        toggle.indeterminate = selCount > 0 && !allSelected;
        toggle.addEventListener('click', (e) => {
            e.preventDefault(); // don't open/close the <details>
            if (toggle.checked) {
                files.forEach(f => selectedBlendUris.add(f.uri));
            } else {
                files.forEach(f => selectedBlendUris.delete(f.uri));
            }
            details.querySelectorAll('.submit-file-item').forEach(el => {
                const on = selectedBlendUris.has(el.dataset.uri);
                el.classList.toggle('selected', on);
                el.setAttribute('aria-checked', String(on));
            });
            syncFolderToggle(details, files);
            updateFilesDependentUI();
        });
        const body = document.createElement('div');
        body.className = 'renders-folder-body';
        details.appendChild(body);
        listEl.appendChild(details);
        files.forEach(f => {
            const selected = selectedBlendUris.has(f.uri);
            const item = document.createElement('div');
            item.dataset.uri = f.uri;
            item.className = `submit-file-item ${selected ? 'selected' : ''}`;
            item.tabIndex = 0;
            item.setAttribute('role', 'checkbox');
            item.setAttribute('aria-checked', String(selected));
            item.innerHTML = `
                <div class="submit-file-check">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" class="check-icon">
                        <polyline points="20,6 9,17 4,12" />
                    </svg>
                </div>
                <div class="submit-file-info">
                    <span class="submit-file-name monospace">${escHtml(blendBaseName(f.display_name))}</span>
                    <span class="submit-file-meta">${formatFileSize(f.size)} · ${fileIsStaged(f) ? 'OSDF' : 'Local'}</span>
                </div>`;
            item.addEventListener('click', () => {
                if (selectedBlendUris.has(f.uri)) {
                    selectedBlendUris.delete(f.uri);
                    item.classList.remove('selected');
                } else {
                    selectedBlendUris.add(f.uri);
                    item.classList.add('selected');
                }
                item.setAttribute('aria-checked', String(selectedBlendUris.has(f.uri)));
                syncFolderToggle(details, files);
                updateFilesDependentUI();
            });
            item.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    item.click();
                }
            });
            body.appendChild(item);
        });
    });
}

function resolveExecName() {
    // The mode determines the executable; the dropdown was removed — tabs are
    // the single source of truth so "executable" can't contradict the mode.
    const wanted = rendersMode === 'multi' ? 'render_multicam.py' : 'render.py';
    const match = renderExecutables.find(ex => ex.filename === wanted)
        || renderExecutables.find(ex => /^render(_multicam)?\.py$/.test(ex.filename));
    return match ? 'executables/' + match.filename : '';
}

function updateExecHint() {
    const exec = resolveExecName();
    $('#renders-exec-auto').textContent = exec
        ? `Executable: ${exec.replace('executables/', '')} — set by the mode`
        : 'No staged render executables';
}

function renderContainerSelect() {
    const sel = $('#renders-container');
    sel.innerHTML = '<option value="">— Select a container —</option>';
    renderContainers.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.uri;
        opt.textContent = `${c.name} (${c.filename})`;
        sel.appendChild(opt);
    });
}

// ----- Split calculator + validation (mirrors render.py / render_multicam.py) -----

function scaledRange() {
    const fs = parseInt($('#renders-frame-start').value);
    const fe = parseInt($('#renders-frame-end').value);
    const k = parseFloat($('#renders-kfm').value) || 1;
    const hasRange = Number.isFinite(fs) && Number.isFinite(fe);
    return {
        fs, fe, k, hasRange,
        fs2: hasRange ? Math.round(fs * k) : null,
        fe2: hasRange ? Math.round((fe + 1) * k) - 1 : null,
    };
}

function validateSplit() {
    const warnings = [];
    const isPlayblast = rendersMode === 'playblast';
    const jobs = parseInt($('#renders-jobs').value) || 0;
    if (!isPlayblast && jobs < 2) warnings.push('jobs must be at least 2 (one dry-run proc + at least one renderer)');

    const { fs, fe, fs2, fe2, k, hasRange } = scaledRange();
    if (k <= 0) warnings.push('keyframe_multiplier must be positive');
    if (!hasRange) {
        if (k !== 1) warnings.push('keyframe multiplier needs an explicit frame range');
        // Playblasts fall back to the .blend's own range; renders need one to split.
        if (!isPlayblast) warnings.push('frame start and end are required');
    } else {
        if (fe < fs) warnings.push(`frame end (${fe}) is before frame start (${fs})`);
        if (fe2 >= FRAME_LIMIT) {
            warnings.push(`scaled frame end ${fe2} reaches Blender's ${FRAME_LIMIT} frame limit`);
        }
    }

    let info;
    if (isPlayblast) {
        info = hasRange
            ? `Playblast frames [${fs2}, ${fe2}] (${fe2 - fs2 + 1} frame(s), k=${k})`
            : "Playblast over the .blend file's own frame range";
        info += ' · one job per selected file — no dry-run proc, no ground truth';
    } else if (!hasRange) {
        info = 'Set a frame start and end to see the proc split.';
    } else {
        const scaledLen = fe2 - fs2 + 1;
        info = `Scaled range: [${fs2}, ${fe2}] (${scaledLen} frame(s), k=${k})`;
        if (jobs >= 2) {
            // render.py split_ranges over the jobs-1 renderer procs; remainder
            // goes to the first procs. Proc 0 is the metadata dry-run.
            const workers = jobs - 1;
            const size = Math.max(0, Math.floor(scaledLen / workers));
            const rem = scaledLen % workers;
            info += ' · 1 job reserved for metadata (dry-run, proc 0, renders no frames)';
            info += rem === 0
                ? ` · ${workers} render proc(s) × ${size} frame(s)`
                : ` · render procs 1..${rem} render ${size + 1} frame(s), rest ${workers - rem} × ${size}`;
            if (size < 1) warnings.push(`scaled range too short for ${workers} renderer procs`);
        }
    }
    if (rendersMode === 'multi') {
        const rows = parseInt($('#renders-rows').value) || 0;
        const cols = parseInt($('#renders-cols').value) || 0;
        const total = rows * cols;
        if (total < 1) warnings.push('rows and cols must be at least 1');
        if (jobs >= 1 && total >= 1) {
            if (jobs % total !== 0) warnings.push(`jobs (${jobs}) is not a multiple of rows*cols (${total})`);
            if (jobs < 2 * total) warnings.push(`jobs (${jobs}) must be at least 2×rows*cols (${2 * total})`);
        }
    }
    const infoEl = $('#renders-split-info');
    infoEl.textContent = info + (warnings.length ? ` — ${warnings.join('; ')}` : '');
    infoEl.style.color = warnings.length ? WARNING_COLOR : '';
    updateBatchEstimate();
    return warnings;
}

// ----- Defaults -----

function applyDefaults() {
    const set = (id, value) => {
        const el = $(id);
        if (el && el.value === '') el.value = value;
    };
    set('#renders-job-name', DEFAULTS.jobName);
    set('#renders-frame-start', DEFAULTS.frames.start);
    set('#renders-frame-end', DEFAULTS.frames.end);
    set('#renders-jobs', DEFAULTS.jobs);
    set('#renders-rows', DEFAULTS.grid.rows);
    set('#renders-cols', DEFAULTS.grid.cols);
    set('#renders-spacing', DEFAULTS.grid.spacing);
    set('#renders-width', DEFAULTS.config.width);
    set('#renders-height', DEFAULTS.config.height);
    set('#renders-res-perc', DEFAULTS.config.resolutionPercentage);
    set('#renders-max-samples', DEFAULTS.config.maxSamples);
    set('#renders-kfm', DEFAULTS.config.keyframeMultiplier);
    $('#renders-device-type').value = DEFAULTS.config.deviceType;
    Object.entries(DEFAULTS.passes).forEach(([name, on]) => {
        const el = $(`#renders-pass-${name}`);
        if (el) el.checked = on;
    });
    set('#renders-output-dir', DEFAULTS.output.directory);
    set('#renders-researchdrive', DEFAULTS.output.researchdrive);
    set('#renders-rd-subdir', DEFAULTS.output.subdir);
    $('#renders-rd-remap').checked = DEFAULTS.output.remap;
    $('#renders-playblast-video').checked = DEFAULTS.playblast.video;
    set('#renders-cpus', DEFAULTS.resources.cpus);
    set('#renders-memory', DEFAULTS.resources.memory);
    set('#renders-disk', DEFAULTS.resources.disk);
}

// ----- Payload composition -----

function extraClassAds() {
    const attrs = {};
    $$('#renders-extra-attrs .attr-row').forEach(row => {
        const key = row.querySelector('.attr-key').value.trim();
        const val = row.querySelector('.attr-value').value.trim();
        if (key) attrs[key] = val;
    });
    return attrs;
}

function addAttrRow(key = '', value = '') {
    const row = document.createElement('div');
    row.className = 'attr-row';
    row.innerHTML = `
        <input type="text" placeholder="Attribute Name" class="form-input attr-key">
        <input type="text" placeholder="Value" class="form-input attr-value">
        <button class="btn btn-ghost remove-attr-btn" title="Remove" type="button">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
        </button>`;
    row.querySelector('.attr-key').value = key;
    row.querySelector('.attr-value').value = value;
    const container = $('#renders-extra-attrs');
    row.querySelector('.remove-attr-btn').addEventListener('click', () => {
        row.remove();
        onFormChange();
    });
    container.appendChild(row);
}

function initExtraAttrs() {
    $('#renders-add-attr-btn').addEventListener('click', () => addAttrRow());
    $('#renders-extra-attrs').addEventListener('input', onFormChange);
    // Attributes the page passes by default — visible and editable here.
    Object.entries(DEFAULTS.classAds).forEach(([key, value]) => addAttrRow(key, value));
}

function addConfigArg(args, key, value) {
    // tyro's CLI is dash-case: --config.device-type; underscores are rejected
    const fullKey = key.startsWith('config.') ? key : 'config.' + key;
    args.push(`--${fullKey.replace(/_/g, '-')}=${value}`);
}

// tyro booleans are bare flags: --config.include-frames (never =True)
function addConfigFlag(args, key) {
    const fullKey = key.startsWith('config.') ? key : 'config.' + key;
    args.push(`--${fullKey.replace(/_/g, '-')}`);
}

function buildConfigArgs() {
    const args = [];
    const firstNonEmpty = (id) => {
        const v = $(id).value;
        return v === '' || v === null ? null : v;
    };
    const width = firstNonEmpty('#renders-width');
    if (width) addConfigArg(args, 'width', width);
    const height = firstNonEmpty('#renders-height');
    if (height) addConfigArg(args, 'height', height);
    const perc = firstNonEmpty('#renders-res-perc');
    if (perc) addConfigArg(args, 'resolution_percentage', perc);
    const samples = firstNonEmpty('#renders-max-samples');
    if (samples) addConfigArg(args, 'max_samples', samples);
    addConfigArg(args, 'device_type', $('#renders-device-type').value);
    const kfm = firstNonEmpty('#renders-kfm');
    if (kfm) addConfigArg(args, 'keyframe_multiplier', kfm);
    const passToFlag = {
        '#renders-pass-composites': 'include_composites',
        '#renders-pass-frames': 'include_frames',
        '#renders-pass-depths': 'include_depths',
        '#renders-pass-normals': 'include_normals',
        '#renders-pass-flows': 'include_flows',
        '#renders-pass-segmentations': 'include_segmentations',
        '#renders-pass-materials': 'include_materials',
        '#renders-pass-diffuse': 'include_diffuse_pass',
        '#renders-pass-specular': 'include_specular_pass',
        '#renders-pass-points': 'include_points',
    };
    for (const [id, key] of Object.entries(passToFlag)) {
        if ($(id).checked) addConfigFlag(args, key);
    }
    // Advanced passthrough: one key = value per line
    $('#renders-passthrough').value.split('\n').map(l => l.trim())
        .filter(l => l && l.includes('=')).forEach(line => {
            const eq = line.indexOf('=');
            addConfigArg(args, line.slice(0, eq).trim(), line.slice(eq + 1).trim());
        });
    return args;
}

// One entry per cluster submission: { name, submit, count }
// HTCondor tokenizes `arguments` on whitespace, so any token carrying spaces
// (camera offsets, debug paths, blend filenames) must be quoted.
function quoteArg(token) {
    return /\s/.test(token) ? `"${token.replace(/"/g, '\\"')}"` : token;
}

function buildPayloads() {
    const exec = resolveExecName();
    const container = $('#renders-container').value;
    const jobs = parseInt($('#renders-jobs').value) || 0;
    const cpus = parseInt($('#renders-cpus').value) || DEFAULTS.resources.cpus;
    const memory = $('#renders-memory').value || DEFAULTS.resources.memory;
    const disk = $('#renders-disk').value || DEFAULTS.resources.disk;
    const debugOut = $('#renders-debug-output').value.trim();
    const nameBase = $('#renders-job-name').value.trim() || DEFAULTS.jobName;
    const outputDir = $('#renders-output-dir').value.trim() || DEFAULTS.output.directoryMacro;
    const researchdrive = $('#renders-researchdrive').value.trim();
    const rdSubdir = $('#renders-rd-subdir').value.trim().replace(/^\/+|\/+$/g, '');
    const rdRemap = $('#renders-rd-remap').checked && researchdrive;
    const tarball = 'renders_$INT(ProcId,%05d).tar.gz';
    const frameStart = $('#renders-frame-start').value.trim();
    const frameEnd = $('#renders-frame-end').value.trim();
    const isPlayblast = rendersMode === 'playblast';
    const playblastVideo = $('#renders-playblast-video').checked;

    const makeSubmit = (entry, cliArgs) => {
        const submit = {
            universe: 'container',
            executable: exec,
            transfer_executable: 'True',
            arguments: [quoteArg(blendBaseName(entry.display_name)), '--procid=$(ProcId)', `--jobs=${isPlayblast ? 1 : jobs}`, ...cliArgs.map(quoteArg)].join(' '),
            // htcondor.Submit requires every value to be a string
            transfer_input_files: entry.uri,
            request_cpus: String(cpus),
            request_memory: memory,
            request_disk: disk,
            output: '$(LogsDir)/$INT(ClusterId,%08d)/$INT(ProcId,%05d).out',
            error: '$(LogsDir)/$INT(ClusterId,%08d)/$INT(ProcId,%05d).err',
            log: '$(LogsDir)/$INT(ClusterId,%08d)/$INT(ProcId,%05d).log',
            transfer_output_files: tarball,
            output_directory: outputDir,
        };
        submit.SceneName = blendBaseName(entry.display_name).replace(/\.[^.]+$/, '');
        if (container) submit.container_image = container;
        if (researchdrive) submit.ResearchDrive = researchdrive;
        if (rdRemap) {
            // Include the cluster id: proc ids repeat across clusters, so a
            // batch would otherwise overwrite each other's tarballs.
            const dest = rdSubdir ? `${rdSubdir}/` : '';
            submit.transfer_output_remaps =
                `${tarball} = $(ResearchDrive)/${dest}$INT(ClusterId,%08d)/${tarball}`;
        }
        // Additional ClassAds override anything above, same as the submit page.
        Object.assign(submit, extraClassAds());
        return submit;
    };

    return selectedBlendEntries().map((entry) => {
        const cliArgs = buildConfigArgs();
        if (frameStart !== '') cliArgs.push(`--frame-start=${frameStart}`);
        if (frameEnd !== '') cliArgs.push(`--frame-end=${frameEnd}`);
        if (isPlayblast) {
            cliArgs.unshift('--playblast');
            if (!playblastVideo) cliArgs.push('--no-video');
        } else if (rendersMode === 'multi') {
            cliArgs.unshift(`--rows=${$('#renders-rows').value}`, `--cols=${$('#renders-cols').value}`,
                `--spacing=${$('#renders-spacing').value || '0.0'}`);
        }
        if (debugOut) cliArgs.push(`--output-file=${debugOut}`);
        const name = isMultiSelectMode()
            ? `${nameBase} — ${blendBaseName(entry.display_name)}` : nameBase;
        return { name, submit: makeSubmit(entry, cliArgs), count: isPlayblast ? 1 : jobs };
    });
}

// ----- Validation before submit -----

function validateForm() {
    const errors = [...new Set(validateSplit())];

    if (!resolveExecName()) errors.push('No staged render executable (upload render.py / render_multicam.py on the Executables page)');
    if (!$('#renders-container').value) errors.push('No container image selected');
    if ($('#renders-rd-remap').checked && !$('#renders-researchdrive').value.trim()) {
        errors.push('ResearchDrive base is required when redirecting tarballs');
    }

    const entries = selectedBlendEntries();
    if (entries.length === 0) errors.push('Select a blend file');
    // HTCondor writes every transfer_input_files entry under its sandbox base
    // name; two selected files with the same basename would overwrite each
    // other and render the wrong file.
    const byBase = new Map();
    for (const f of entries) {
        const base = blendBaseName(f.display_name);
        if (byBase.has(base)) byBase.get(base).push(f);
        else byBase.set(base, [f]);
    }
    const dupes = [...byBase.entries()].filter(([, fs2]) => fs2.length > 1);
    if (dupes.length > 0) {
        errors.push(`Duplicate file name(s) selected — they would overwrite each other in the job sandbox: ${dupes.map(([b]) => b).join(', ')}`);
    }
    const allErrors = [...new Set(errors)];
    const errEl = $('#renders-batch-errors');
    if (errEl) {
        errEl.style.display = allErrors.length ? '' : 'none';
        errEl.innerHTML = allErrors.map(e =>
            `<p class="hint" style="color: ${WARNING_COLOR};">${escHtml(e)}</p>`).join('');
    }
    return allErrors;
}

// ----- Page chrome -----

function updateBatchEstimate() {
    const el = $('#renders-batch-estimate');
    if (!el) return;
    const n = selectedBlendEntries().length;
    if (n < 2) {
        el.textContent = '';
        return;
    }
    const procs = rendersMode === 'playblast' ? 1 : (parseInt($('#renders-jobs').value) || 0);
    el.textContent = `${n} cluster(s) · ${n * procs} proc(s)`;
}

function updateFilesDependentUI() {
    const multi = rendersMode === 'multi';
    const isPlayblast = rendersMode === 'playblast';
    $('#renders-grid-card').style.display = multi ? '' : 'none';
    // Playblast ignores resolution/passes/device (viewport settings come from
    // the .blend), so the whole Render Config card is meaningless there.
    $('#renders-config-card').style.display = isPlayblast ? 'none' : '';
    $('#renders-playblast-opts').style.display = isPlayblast ? '' : 'none';
    // Playblast always runs one job per file; the proc count is not used.
    $('#renders-jobs-group').style.display = isPlayblast ? 'none' : '';
    updateExecHint();
    validateSplit();
    refreshRaw();
}

function refreshRaw() {
    $('#renders-raw-editor').value = JSON.stringify(buildPayloads(), null, 2);
}

function initModeToggle() {
    $$('.mode-toggle button').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.mode-toggle button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            rendersMode = btn.dataset.mode;
            renderBlendList(); // folder toggles only exist while batching
            updateFilesDependentUI();
        });
    });
}

// Persist last-submitted resource values for the next visit
function saveLastValues() {
    try {
        localStorage.setItem('renders-last', JSON.stringify({
            cpus: $('#renders-cpus').value,
            memory: $('#renders-memory').value,
            disk: $('#renders-disk').value,
            container: $('#renders-container').value,
        }));
    } catch { /* localStorage unavailable */ }
}

function applyLastValues() {
    try {
        const last = JSON.parse(localStorage.getItem('renders-last') || 'null');
        if (!last) return;
        if (last.cpus) $('#renders-cpus').value = last.cpus;
        if (last.memory) $('#renders-memory').value = last.memory;
        if (last.disk) $('#renders-disk').value = last.disk;
        if (last.container) $('#renders-container').value = last.container;
    } catch { /* ignore */ }
}

async function submitRenders() {
    // The editable JSON panel is the source of truth for what gets submitted.
    let payloads;
    try {
        payloads = JSON.parse($('#renders-raw-editor').value);
    } catch (err) {
        toast(`Invalid JSON in payload panel: ${err.message}`, 'error');
        return;
    }
    if (!Array.isArray(payloads)) payloads = [payloads];
    payloads = payloads.filter(p => p && p.submit);
    if (payloads.length === 0) {
        toast('Nothing to submit', 'warning');
        return;
    }
    const errors = validateForm();
    if (errors.length > 0) {
        toast(errors[0], 'error');
        return;
    }

    const btn = $('#renders-submit-btn');
    if (btn.disabled) return;
    btn.disabled = true;
    try {
        await submitPayloads(payloads);
    } finally {
        btn.disabled = false;
    }
}

function showSubmitStatus(payloads) {
    const panel = $('#renders-submit-status');
    panel.style.display = '';
    panel.innerHTML = `
        <div class="submit-card-header"><h3 id="renders-status-title">Submitting…</h3></div>
        <div class="submit-card-body" id="renders-status-list">
            ${payloads.map((p, i) => `
                <p class="hint" data-status-row="${i}">
                    <span class="monospace">${escHtml(p.name)}</span> — queued
                </p>`).join('')}
        </div>`;
    panel.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function setStatusRow(i, html) {
    const row = $(`[data-status-row="${i}"]`);
    if (row) row.innerHTML = html;
}

async function submitPayloads(payloads) {
    saveLastValues();
    showSubmitStatus(payloads);
    let failed = 0;
    for (const [i, p] of payloads.entries()) {
        setStatusRow(i, `<span class="monospace">${escHtml(p.name)}</span> — submitting…`);
        try {
            const res = await api('/submit', {
                method: 'POST',
                body: JSON.stringify({ name: p.name, submit: p.submit, count: p.count }),
            });
            setStatusRow(i, `Submitted <a href="/job/${res.cluster_id}"
                style="color: var(--accent-cyan);">cluster ${res.cluster_id}</a>
                (${res.num_procs} proc(s)) — <span class="monospace">${escHtml(p.name)}</span>`);
        } catch (err) {
            failed++;
            setStatusRow(i, `<span style="color: ${WARNING_COLOR};">Failed — ${escHtml(p.name)}: ${escHtml(err.message)}</span>`);
        }
    }
    const title = $('#renders-status-title');
    if (failed === 0) {
        title.textContent = `Submitted ${payloads.length} cluster(s)`;
        $('#renders-status-list').insertAdjacentHTML('beforeend',
            '<p class="hint">Opening the dashboard…</p>');
        setTimeout(() => { window.location.href = '/'; }, 1500);
    } else {
        title.textContent = `Submitted with ${failed} failure(s)`;
        $('#renders-status-list').insertAdjacentHTML('beforeend',
            '<p class="hint">Fix the failures above and submit again — successful clusters are already queued.</p>');
        toast(`Submitted with ${failed} failure(s)`, 'warning');
    }
}

// ----- Init -----

// Fields that own their own change behavior and must not auto-refresh the
// payload: the search box filters, the JSON editor is the submit source of
// truth, and the pass checkboxes coordinate with the master toggle.
const NO_AUTO_REFRESH = new Set(['renders-blend-search', 'renders-raw-editor', 'renders-pass-all']);

function onFormChange() {
    validateSplit(); // also refreshes the batch estimate
    refreshRaw();
}

function bindFormInputs() {
    $$('#panel-renders .submit-card-body input[id], #panel-renders .submit-card-body select[id], #panel-renders .submit-card-body textarea[id]')
        .forEach(el => {
            if (!el.id.startsWith('renders-')) return;
            if (NO_AUTO_REFRESH.has(el.id) || el.id.startsWith('renders-pass-')) return;
            el.addEventListener('input', onFormChange);
        });
}

document.addEventListener('DOMContentLoaded', () => {
    initModeToggle();
    applyDefaults();
    initExtraAttrs();

    loadServerData().then(() => {
        renderContainerSelect();
        renderBlendList();
        applyLastValues();
        updateFilesDependentUI();
    });

    $('#renders-blend-search').addEventListener('input', renderBlendList);
    bindFormInputs();
    // Master "Include-All" toggle: drives every pass checkbox in one go
    $('#renders-pass-all').addEventListener('change', (e) => {
        $$('[id^="renders-pass-"]:not(#renders-pass-all)').forEach(cb => cb.checked = e.target.checked);
        refreshRaw();
        validateSplit();
    });
    $$('[id^="renders-pass-"]:not(#renders-pass-all)').forEach(cb => {
        cb.addEventListener('change', () => {
            // reflect partial selection on the master (checked only when all pass boxes are)
            const all = [...$$('[id^="renders-pass-"]:not(#renders-pass-all)')];
            $('#renders-pass-all').checked = all.every(c => c.checked);
            refreshRaw();
            validateSplit();
        });
    });

    $('#renders-submit-btn').addEventListener('click', submitRenders);
});
