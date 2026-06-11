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
        
        let descPreview = '';
        try {
            if (tmpl.description.trim().startsWith('{')) {
                const parsed = JSON.parse(tmpl.description);
                descPreview = `Universe: ${parsed.universe || 'vanilla'}, Executable: ${basename(parsed.executable)}`;
            } else {
                descPreview = tmpl.description.split('\n').slice(0, 3).join('\n');
            }
        } catch (e) {
            descPreview = tmpl.description;
        }

        card.innerHTML = `
            <div class="card-header" style="border-bottom: none; padding-bottom: 0;">
                <h3 style="margin: 0; font-size: 1.1rem; color: var(--text-primary);">${tmpl.name}</h3>
            </div>
            <div class="card-body" style="flex-grow: 1; padding: 12px 16px;">
                <pre class="monospace" style="background: var(--bg-secondary); padding: 8px; border-radius: 4px; font-size: 0.8rem; overflow: hidden; text-overflow: ellipsis; white-space: pre-wrap; max-height: 100px;">${descPreview}</pre>
                <span style="font-size: 0.75rem; color: var(--text-muted);">Saved: ${formatDate(new Date(tmpl.created_at).getTime()/1000)}</span>
            </div>
            <div class="card-footer" style="display: flex; justify-content: flex-end; gap: 8px; border-top: 1px solid var(--border-color); padding: 12px 16px; background: var(--bg-secondary);">
                <button class="btn btn-ghost btn-sm delete-tmpl-btn" data-id="${tmpl.id}" style="color: var(--danger-color);">Delete</button>
                <button class="btn btn-primary btn-sm use-tmpl-btn" data-tmpl='${JSON.stringify(tmpl).replace(/'/g, "&apos;")}'>Use Template</button>
            </div>
        `;
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
        btn.addEventListener('click', async (e) => {
            const id = e.currentTarget.dataset.id;
            if (!confirm('Are you sure you want to delete this template?')) return;
            try {
                await api(`/templates/${id}`, { method: 'DELETE' });
                toast('Template deleted successfully');
                loadTemplates();
            } catch (err) {
                toast(`Failed to delete template: ${err.message}`, 'error');
            }
        });
    });
}

document.addEventListener('DOMContentLoaded', () => {
    loadTemplates();

    $('#save-template-btn').addEventListener('click', () => {
        if (confirm('Templates are configured and saved on the Submit Job page. Go there now?')) {
            window.location.href = '/submit';
        }
    });
});
