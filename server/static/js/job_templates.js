let currentExecPage = 1;

const CATEGORY_LABELS = {
    general: '一般', maintenance: 'メンテナンス', security: 'セキュリティ',
    diagnostics: '診断', update: '更新',
};
const RISK_LABELS = { low: '低', medium: '中', high: '高' };
const RISK_CLASSES = { low: 'status-completed', medium: 'status-pending', high: 'status-failed' };

function statusBadge(status) {
    const map = {
        pending_approval: '<span class="status-badge status-pending">承認待ち</span>',
        pending: '<span class="status-badge status-pending">待機中</span>',
        running: '<span class="status-badge status-running">実行中</span>',
        completed: '<span class="status-badge status-completed">完了</span>',
        failed: '<span class="status-badge status-failed">失敗</span>',
        cancelled: '<span class="status-badge status-unknown">キャンセル</span>',
    };
    return map[status] || escapeHTML(status);
}

function riskBadge(level) {
    const cls = RISK_CLASSES[level] || '';
    return `<span class="status-badge ${cls}">${escapeHTML(RISK_LABELS[level] || level)}</span>`;
}

function formatTime(iso) {
    if (!iso) return '-';
    return new Date(iso).toLocaleString('ja-JP');
}

// ---------------------------------------------------------------------------
// Template list
// ---------------------------------------------------------------------------

async function loadTemplates() {
    const category = document.getElementById('template-category-filter').value;
    const risk = document.getElementById('template-risk-filter').value;
    const showDisabled = document.getElementById('template-show-disabled').checked;
    const tbody = document.getElementById('templates-body');
    tbody.innerHTML = '<tr><td colspan="7" class="text-center">読み込み中...</td></tr>';

    try {
        const params = new URLSearchParams();
        if (category) params.set('category', category);
        if (risk) params.set('risk_level', risk);
        if (showDisabled) params.set('enabled_only', 'false');

        const data = await apiFetch('/api/job-templates?' + params.toString());
        if (!data.templates || data.templates.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center">テンプレートがありません</td></tr>';
            return;
        }

        tbody.innerHTML = data.templates.map(t => `
            <tr>
                <td><strong>${escapeHTML(t.name)}</strong>
                    ${t.description ? `<br><small class="text-muted">${escapeHTML(t.description)}</small>` : ''}
                </td>
                <td>${escapeHTML(CATEGORY_LABELS[t.category] || t.category)}</td>
                <td>${riskBadge(t.risk_level)}</td>
                <td>${t.requires_approval ? '&#10003;' : '-'}</td>
                <td>${t.is_enabled
                    ? '<span class="status-badge status-completed">有効</span>'
                    : '<span class="status-badge status-unknown">無効</span>'}</td>
                <td>${escapeHTML(t.created_by || '-')}</td>
                <td>
                    <button class="btn role-operator-or-admin"
                        style="padding:0.2rem 0.5rem;font-size:0.75rem;"
                        onclick="openExecuteModal(${Number(t.id)}, ${JSON.stringify(t.name).replace(/"/g, '&quot;')}, ${JSON.stringify(t.description || '').replace(/"/g, '&quot;')}, ${t.is_enabled})"
                        ${t.is_enabled ? '' : 'disabled title="無効化されています"'}>
                        &#9654; 実行
                    </button>
                    <button class="btn btn-secondary role-admin-only"
                        style="padding:0.2rem 0.5rem;font-size:0.75rem;"
                        onclick="openEditModal(${Number(t.id)})">
                        編集
                    </button>
                    <button class="btn btn-danger role-admin-only"
                        style="padding:0.2rem 0.5rem;font-size:0.75rem;"
                        onclick="deleteTemplate(${Number(t.id)}, ${JSON.stringify(t.name).replace(/"/g, '&quot;')})">
                        削除
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center" style="color:var(--danger);">読み込みに失敗しました</td></tr>';
    }
}

// ---------------------------------------------------------------------------
// Execution history
// ---------------------------------------------------------------------------

async function loadExecutions(page) {
    currentExecPage = page || currentExecPage;
    const status = document.getElementById('exec-status-filter').value;
    const tbody = document.getElementById('executions-body');
    tbody.innerHTML = '<tr><td colspan="9" class="text-center">読み込み中...</td></tr>';

    try {
        const params = new URLSearchParams();
        if (status) params.set('status', status);
        params.set('page', currentExecPage);
        params.set('per_page', '20');

        const data = await apiFetch('/api/job-executions?' + params.toString());
        if (!data.executions || data.executions.length === 0) {
            tbody.innerHTML = '<tr><td colspan="9" class="text-center">実行履歴がありません</td></tr>';
        } else {
            tbody.innerHTML = data.executions.map(e => {
                let actionBtns = '';
                if (e.status === 'pending_approval') {
                    actionBtns = `
                        <button class="btn btn-primary role-admin-only"
                            style="padding:0.2rem 0.5rem;font-size:0.75rem;"
                            onclick="event.stopPropagation();approveExecution(${Number(e.id)})">
                            承認
                        </button>
                        <button class="btn btn-danger role-admin-only"
                            style="padding:0.2rem 0.5rem;font-size:0.75rem;"
                            onclick="event.stopPropagation();openRejectModal(${Number(e.id)})">
                            却下
                        </button>`;
                } else if (e.status === 'pending') {
                    actionBtns = `
                        <button class="btn btn-danger role-operator-or-admin"
                            style="padding:0.2rem 0.5rem;font-size:0.75rem;"
                            onclick="event.stopPropagation();cancelExecution(${Number(e.id)})">
                            キャンセル
                        </button>`;
                }
                return `
                <tr style="cursor:pointer;" onclick="showExecDetail(${Number(e.id)})">
                    <td>#${escapeHTML(e.id)}</td>
                    <td>${escapeHTML(e.template_name || e.template_id)}</td>
                    <td>${escapeHTML(e.pc_name || e.pc_id)}</td>
                    <td>${statusBadge(e.status)}</td>
                    <td>${escapeHTML(e.requested_by || '-')}</td>
                    <td>${escapeHTML(e.approved_by || '-')}</td>
                    <td>${escapeHTML(formatTime(e.created_at))}</td>
                    <td>${escapeHTML(formatTime(e.completed_at))}</td>
                    <td>${actionBtns}</td>
                </tr>`;
            }).join('');
        }

        const pagination = document.getElementById('exec-pagination');
        if (data.pages && data.pages > 1) {
            let html = '';
            for (let i = 1; i <= data.pages; i++) {
                html += `<button class="${i === data.page ? 'active' : ''}" onclick="loadExecutions(${i})">${i}</button>`;
            }
            pagination.innerHTML = html;
        } else {
            pagination.innerHTML = '';
        }
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-center" style="color:var(--danger);">読み込みに失敗しました</td></tr>';
    }
}

// ---------------------------------------------------------------------------
// Template Create / Edit Modal
// ---------------------------------------------------------------------------

function openCreateModal() {
    document.getElementById('template-modal-title').textContent = 'テンプレート作成';
    document.getElementById('template-edit-id').value = '';
    document.getElementById('template-name').value = '';
    document.getElementById('template-description').value = '';
    document.getElementById('template-category').value = 'general';
    document.getElementById('template-risk-level').value = 'low';
    document.getElementById('template-script-body').value = '';
    document.getElementById('template-requires-approval').value = 'false';
    document.getElementById('template-is-enabled').value = 'true';
    openModal('template-modal');
}

async function openEditModal(templateId) {
    try {
        const data = await apiFetch(`/api/job-templates/${templateId}`);
        const t = data.template;
        document.getElementById('template-modal-title').textContent = 'テンプレート編集';
        document.getElementById('template-edit-id').value = t.id;
        document.getElementById('template-name').value = t.name || '';
        document.getElementById('template-description').value = t.description || '';
        document.getElementById('template-category').value = t.category || 'general';
        document.getElementById('template-risk-level').value = t.risk_level || 'low';
        document.getElementById('template-script-body').value = t.script_body || '';
        document.getElementById('template-requires-approval').value = t.requires_approval ? 'true' : 'false';
        document.getElementById('template-is-enabled').value = t.is_enabled ? 'true' : 'false';
        openModal('template-modal');
    } catch (e) {
        alert('テンプレートの取得に失敗しました: ' + (e.message || e));
    }
}

async function saveTemplate() {
    const editId = document.getElementById('template-edit-id').value;
    const payload = {
        name: document.getElementById('template-name').value.trim(),
        description: document.getElementById('template-description').value,
        category: document.getElementById('template-category').value,
        risk_level: document.getElementById('template-risk-level').value,
        script_body: document.getElementById('template-script-body').value,
        requires_approval: document.getElementById('template-requires-approval').value === 'true',
        is_enabled: document.getElementById('template-is-enabled').value === 'true',
    };

    if (!payload.name) { alert('テンプレート名は必須です'); return; }

    try {
        if (editId) {
            await apiFetch(`/api/job-templates/${editId}`, { method: 'PUT', body: JSON.stringify(payload) });
        } else {
            await apiFetch('/api/job-templates', { method: 'POST', body: JSON.stringify(payload) });
        }
        closeModal('template-modal');
        loadTemplates();
    } catch (e) {
        alert('保存に失敗しました: ' + (e.message || e));
    }
}

async function deleteTemplate(templateId, name) {
    if (!confirm('テンプレート「' + name + '」を削除しますか？実行履歴がある場合は削除できません。')) return;
    try {
        await apiFetch(`/api/job-templates/${templateId}`, { method: 'DELETE' });
        loadTemplates();
    } catch (e) {
        alert('削除に失敗しました: ' + (e.message || e));
    }
}

// ---------------------------------------------------------------------------
// Execute Template Modal
// ---------------------------------------------------------------------------

async function openExecuteModal(templateId, name, description, isEnabled) {
    if (!isEnabled) return;
    document.getElementById('execute-template-id').value = templateId;
    document.getElementById('execute-template-desc').textContent = name + ' — ' + (description || '説明なし');

    const pcSelect = document.getElementById('execute-pc-id');
    pcSelect.innerHTML = '<option value="">読み込み中...</option>';
    openModal('execute-modal');

    try {
        const data = await apiFetch('/api/pcs?per_page=500');
        const pcs = data.pcs || [];
        pcSelect.innerHTML = '<option value="">PCを選択...</option>' +
            pcs.map(p => `<option value="${Number(p.id)}">${escapeHTML(p.pc_name)}</option>`).join('');
    } catch (e) {
        pcSelect.innerHTML = '<option value="">PC読み込み失敗</option>';
    }
}

async function runExecute() {
    const templateId = document.getElementById('execute-template-id').value;
    const pcId = document.getElementById('execute-pc-id').value;
    if (!pcId) { alert('PCを選択してください'); return; }

    try {
        await apiFetch(`/api/job-templates/${templateId}/execute`, {
            method: 'POST',
            body: JSON.stringify({ pc_id: Number(pcId) }),
        });
        closeModal('execute-modal');
        loadExecutions(1);
    } catch (e) {
        alert('実行リクエストに失敗しました: ' + (e.message || e));
    }
}

// ---------------------------------------------------------------------------
// Execution Detail Modal
// ---------------------------------------------------------------------------

async function showExecDetail(execId) {
    openModal('exec-detail-modal');
    const body = document.getElementById('exec-detail-body');
    body.innerHTML = '<p class="text-center">読み込み中...</p>';
    try {
        const data = await apiFetch(`/api/job-executions/${execId}`);
        const e = data.execution;
        const rows = [
            ['ID', '#' + escapeHTML(e.id)],
            ['テンプレート ID', escapeHTML(e.template_id)],
            ['PC ID', escapeHTML(e.pc_id)],
            ['状態', statusBadge(e.status)],
            ['要求者', escapeHTML(e.requested_by)],
            ['作成日時', escapeHTML(formatTime(e.created_at))],
            ['実行開始', escapeHTML(formatTime(e.executed_at))],
            ['完了日時', escapeHTML(formatTime(e.completed_at))],
            ['終了コード', e.result_exit_code !== null ? escapeHTML(e.result_exit_code) : '-'],
        ];
        const tableRows = rows.map(([k, v]) => `<tr><th>${escapeHTML(k)}</th><td>${v}</td></tr>`).join('');
        const outputSection = e.result_output
            ? `<h4>出力</h4><pre style="background:var(--bg-secondary);padding:0.75rem;border-radius:4px;overflow:auto;max-height:300px;">${escapeHTML(e.result_output)}</pre>`
            : '';
        body.innerHTML = `<table class="table">${tableRows}</table>${outputSection}`;
    } catch (err) {
        body.innerHTML = '<p style="color:var(--danger);">読み込みに失敗しました</p>';
    }
}

async function cancelExecution(execId) {
    if (!confirm('実行 #' + execId + ' をキャンセルしますか？')) return;
    try {
        await apiFetch(`/api/job-executions/${execId}/cancel`, { method: 'POST' });
        loadExecutions(currentExecPage);
    } catch (e) {
        alert('キャンセルに失敗しました: ' + (e.message || e));
    }
}

async function approveExecution(execId) {
    if (!confirm('実行 #' + execId + ' を承認しますか？')) return;
    try {
        await apiFetch(`/api/job-executions/${execId}/approve`, { method: 'POST' });
        loadExecutions(currentExecPage);
    } catch (e) {
        alert('承認に失敗しました: ' + (e.message || e));
    }
}

function openRejectModal(execId) {
    document.getElementById('reject-execution-id').value = execId;
    document.getElementById('reject-reason').value = '';
    openModal('reject-modal');
}

async function submitReject() {
    const execId = Number(document.getElementById('reject-execution-id').value);
    const reason = document.getElementById('reject-reason').value.trim();
    if (!reason) { alert('却下理由を入力してください'); return; }
    try {
        await apiFetch(`/api/job-executions/${execId}/reject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reason }),
        });
        closeModal('reject-modal');
        loadExecutions(currentExecPage);
    } catch (e) {
        alert('却下に失敗しました: ' + (e.message || e));
    }
}

// ---------------------------------------------------------------------------
// Modal helpers
// ---------------------------------------------------------------------------

function openModal(id) {
    document.getElementById(id).classList.add('open');
    document.addEventListener('keydown', handleModalKey);
}

function closeModal(id) {
    document.getElementById(id).classList.remove('open');
}

function handleModalKey(e) {
    if (e.key === 'Escape') {
        ['template-modal', 'execute-modal', 'reject-modal', 'exec-detail-modal'].forEach(id => closeModal(id));
        document.removeEventListener('keydown', handleModalKey);
    }
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    loadTemplates();
    loadExecutions(1);

    document.getElementById('btn-show-create-template').addEventListener('click', openCreateModal);
    document.getElementById('btn-save-template').addEventListener('click', saveTemplate);
    document.getElementById('btn-cancel-template').addEventListener('click', () => closeModal('template-modal'));
    document.getElementById('btn-close-template-modal').addEventListener('click', () => closeModal('template-modal'));

    document.getElementById('btn-run-execute').addEventListener('click', runExecute);
    document.getElementById('btn-cancel-execute').addEventListener('click', () => closeModal('execute-modal'));
    document.getElementById('btn-close-execute-modal').addEventListener('click', () => closeModal('execute-modal'));

    document.getElementById('btn-close-exec-detail').addEventListener('click', () => closeModal('exec-detail-modal'));

    document.getElementById('btn-submit-reject').addEventListener('click', submitReject);
    document.getElementById('btn-cancel-reject').addEventListener('click', () => closeModal('reject-modal'));
    document.getElementById('btn-close-reject-modal').addEventListener('click', () => closeModal('reject-modal'));

    document.getElementById('template-category-filter').addEventListener('change', loadTemplates);
    document.getElementById('template-risk-filter').addEventListener('change', loadTemplates);
    document.getElementById('template-show-disabled').addEventListener('change', loadTemplates);
    document.getElementById('exec-status-filter').addEventListener('change', () => loadExecutions(1));
});
