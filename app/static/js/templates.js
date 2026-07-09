async function loadTemplates() {
    try {
        const data = await api('/templates');
        renderTemplatesGrid(data.templates || []);
    } catch (e) {
        toast('Failed to load templates: ' + e.message, 'error');
    }
}

function renderTemplatesGrid(templates) {
    const grid = $('#templates-grid');
    grid.innerHTML = '';

    if (templates.length === 0) {
        grid.innerHTML = `
            <div class="empty-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" width="64" height="64">
                    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                    <polyline points="14,2 14,8 20,8" />
                </svg>
                <p>No templates saved yet</p>
                <p class="hint">Build a submit description on the Submit page and save it as a template</p>
            </div>
        `;
        return;
    }

    templates.forEach(tmpl => {
        const card = document.createElement('div');
        card.className = 'card template-card';
        card.style.display = 'flex';
        card.style.flexDirection = 'column';
        card.style.justifyContent = 'space-between';

        // Build description preview from submit_data
        const submitStr = tmpl.submit_data || '';
        let descPreview = '';
        try {
            if (submitStr.trim().startsWith('{')) {
                const parsed = JSON.parse(submitStr);
                descPreview = `Universe: ${parsed.universe || 'vanilla'}, Executable: ${escHtml(basename(parsed.executable))}`;
            } else {
                descPreview = submitStr.split('\n').slice(0, 3).join('\n');
            }
        } catch (e) {
            descPreview = submitStr;
        }

        const name = escHtml(tmpl.name);
        const descLines = descPreview.split('\n').slice(0, 3).join('\n');

        card.innerHTML = `
            <div class="card-header" style="border-bottom: none; padding-bottom: 0; display: flex; justify-content: space-between; align-items: flex-start;">
                <h3 style="margin: 0; font-size: 1.1rem; color: var(--text-primary);">${name}</h3>
                <button class="btn btn-ghost btn-sm download-tmpl-btn" data-name="${escHtml(tmpl.name)}" title="Download .sub file" style="flex-shrink: 0;">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
                        <polyline points="7,10 12,15 17,10"/>
                        <line x1="12" y1="15" x2="12" y2="3"/>
                    </svg>
                    Download
                </button>
            </div>
            <div class="card-body" style="flex-grow: 1; padding: 12px 16px;">
                <pre class="monospace" style="background: var(--bg-secondary); padding: 8px; border-radius: 4px; font-size: 0.8rem; overflow: hidden; text-overflow: ellipsis; white-space: pre-wrap; max-height: 100px;">${escHtml(descLines)}</pre>
                <span style="font-size: 0.75rem; color: var(--text-muted);">Modified: ${tmpl.updated_at ? formatDateIso(tmpl.updated_at) : '—'}</span>
            </div>
            <div class="card-footer" style="display: flex; justify-content: flex-end; gap: 8px; border-top: 1px solid var(--border-color); padding: 12px 16px; background: var(--bg-secondary);">
                <button class="btn btn-ghost btn-sm rename-tmpl-btn" data-name="${escHtml(tmpl.name)}" title="Rename template">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <path d="M17 3a2.828 2.828 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>
                    </svg>
                    Rename
                </button>
                <button class="btn btn-danger btn-sm delete-tmpl-btn" data-name="${escHtml(tmpl.name)}">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <polyline points="3,6 5,6 21,6"></polyline>
                        <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"></path>
                    </svg>
                    Delete
                </button>
                <button class="btn btn-primary btn-sm use-tmpl-btn" style="cursor: pointer;">Use Template</button>
            </div>
        `;

        // Set the template data via dataset to avoid XSS through HTML attribute injection
        const useBtn = card.querySelector('.use-tmpl-btn');
        useBtn.dataset.tmpl = JSON.stringify(tmpl);

        grid.appendChild(card);
    });

    // Add event listeners
    $$('.use-tmpl-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const tmpl = JSON.parse(e.currentTarget.dataset.tmpl);
            localStorage.setItem('selectedTemplate', JSON.stringify(tmpl));
            window.location.href = '/submit';
        });
    });

    $$('.delete-tmpl-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const name = e.currentTarget.dataset.name;
            $('#delete-template-name').value = name;
            $('#delete-template-name-display').textContent = name;
            openModal('delete-template-modal');
        });
    });

    $$('.rename-tmpl-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const name = e.currentTarget.dataset.name;
            $('#rename-template-name').value = name;
            $('#rename-template-old-name').value = name;
            openModal('rename-template-modal');
            $('#rename-template-name').focus();
            $('#rename-template-name').select();
        });
    });

    $$('.download-tmpl-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const name = e.currentTarget.dataset.name;
            const url = `/api/templates/${encodeURIComponent(name)}/download`;
            window.location.href = url;
        });
    });
}

async function confirmDeleteTemplate() {
    const name = $('#delete-template-name').value.trim();
    if (!name) return;
    try {
        await api(`/templates/${encodeURIComponent(name)}`, { method: 'DELETE' });
        toast('Template deleted successfully');
        closeModal('delete-template-modal');
        loadTemplates();
    } catch (err) {
        toast(`Failed to delete template: ${err.message}`, 'error');
    }
}

async function confirmRenameTemplate() {
    const oldName = $('#rename-template-old-name').value.trim();
    const newName = $('#rename-template-name').value.trim();
    if (!newName) {
        toast('Please enter a template name', 'warning');
        return;
    }
    if (oldName === newName) {
        closeModal('rename-template-modal');
        return;
    }
    try {
        await api(`/templates/${encodeURIComponent(oldName)}`, {
            method: 'PUT',
            body: JSON.stringify({ name: newName })
        });
        toast('Template renamed successfully');
        closeModal('rename-template-modal');
        loadTemplates();
    } catch (err) {
        toast(`Failed to rename template: ${err.message}`, 'error');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadTemplates();

    $('#save-template-btn').addEventListener('click', () => {
        if (confirm('Templates are configured and saved on the Submit job page. Go there now?')) {
            window.location.href = '/submit';
        }
    });

    // Delete template modal
    const deleteConfirmBtn = $('#delete-template-confirm-btn');
    if (deleteConfirmBtn) {
        deleteConfirmBtn.addEventListener('click', confirmDeleteTemplate);
    }

    // Rename template modal
    const renameConfirmBtn = $('#rename-template-confirm-btn');
    if (renameConfirmBtn) {
        renameConfirmBtn.addEventListener('click', confirmRenameTemplate);
    }
    const renameInput = $('#rename-template-name');
    if (renameInput) {
        renameInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                confirmRenameTemplate();
            }
        });
    }
});
