async function loadAgents() {
    const tbody = document.getElementById('agents-body');
    if (!tbody) return;
    try {
        const data = await apiFetch('/agents');
        tbody.replaceChildren();
        const agents = data.agents || [];

        if (agents.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 8;
            td.className = 'text-center';
            td.textContent = 'エージェントが登録されていません';
            tr.appendChild(td);
            tbody.appendChild(tr);
        } else {
            agents.forEach(a => {
                const tr = document.createElement('tr');
                const td = (text) => {
                    const el = document.createElement('td');
                    el.textContent = text ?? '—';
                    return el;
                };
                tr.appendChild(td(a.pc_name));
                tr.appendChild(td(a.os_version));
                tr.appendChild(td(a.cpu_usage != null ? a.cpu_usage.toFixed(1) + '%' : '—'));
                tr.appendChild(td(a.memory_usage != null ? a.memory_usage.toFixed(1) + '%' : '—'));
                tr.appendChild(td(a.agent_version));
                tr.appendChild(td(a.last_seen ? new Date(a.last_seen).toLocaleString('ja-JP') : '—'));

                const statusTd = document.createElement('td');
                const badge = document.createElement('span');
                if (a.status === 'pending') {
                    badge.className = 'badge badge-info';
                    badge.textContent = '未承認';
                } else if (a.online) {
                    badge.className = 'badge badge-success';
                    badge.textContent = 'オンライン';
                } else {
                    badge.className = 'badge badge-secondary';
                    badge.textContent = 'オフライン';
                }
                statusTd.appendChild(badge);
                tr.appendChild(statusTd);

                const actionTd = document.createElement('td');
                actionTd.className = 'd-flex-gap';
                const detailBtn = document.createElement('a');
                detailBtn.className = 'btn btn-secondary text-xs';
                detailBtn.href = `/pcs/${a.id}`;
                detailBtn.textContent = '詳細';
                actionTd.appendChild(detailBtn);
                tr.appendChild(actionTd);

                tbody.appendChild(tr);
            });
        }

        // Update stat cards
        const onlineCount = agents.filter(a => a.online && a.status !== 'pending').length;
        const offlineCount = agents.filter(a => !a.online && a.status !== 'pending').length;
        const pendingCount = agents.filter(a => a.status === 'pending').length;

        const statOnline = document.getElementById('agent-stat-online');
        if (statOnline) statOnline.textContent = onlineCount;

        const statOffline = document.getElementById('agent-stat-offline');
        if (statOffline) statOffline.textContent = offlineCount;

        const statPending = document.getElementById('agent-stat-pending');
        if (statPending) statPending.textContent = pendingCount;

        const statTotal = document.getElementById('agent-stat-total');
        if (statTotal) statTotal.textContent = data.total ?? agents.length;

    } catch (e) {
        if (tbody) {
            tbody.replaceChildren();
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 8;
            td.className = 'text-center text-danger';
            td.textContent = '読み込みに失敗しました';
            tr.appendChild(td);
            tbody.appendChild(tr);
        }
    }
}

async function loadApiKeys() {
    const tbody = document.getElementById('apikeys-body');
    if (!tbody) return;
    try {
        const data = await apiFetch('/api-keys');
        tbody.replaceChildren();
        const keys = data.api_keys || [];
        if (keys.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 6; td.className = 'text-center';
            td.textContent = 'API キーが登録されていません。+ 新規 API キー作成から追加してください。';
            tr.appendChild(td); tbody.appendChild(tr);
            return;
        }
        keys.forEach(k => {
            const tr = document.createElement('tr');
            const td = t => { const el = document.createElement('td'); el.textContent = t ?? '—'; return el; };
            tr.appendChild(td(k.name));
            tr.appendChild(td(k.key_prefix ? k.key_prefix + '…' : '—'));
            tr.appendChild(td(k.created_at ? new Date(k.created_at).toLocaleDateString('ja-JP') : '—'));
            tr.appendChild(td(k.last_used_at ? new Date(k.last_used_at).toLocaleString('ja-JP') : '—'));
            const statusTd = document.createElement('td');
            const badge = document.createElement('span');
            badge.className = 'badge ' + (k.is_active ? 'badge-success' : 'badge-secondary');
            badge.textContent = k.is_active ? '有効' : '無効';
            statusTd.appendChild(badge); tr.appendChild(statusTd);
            const actionTd = document.createElement('td');
            actionTd.className = 'd-flex-gap';
            const rotateBtn = document.createElement('button');
            rotateBtn.className = 'btn btn-warning text-xs role-admin-only';
            rotateBtn.textContent = 'ローテート';
            rotateBtn.addEventListener('click', () => rotateApiKey(k.id, k.name));
            actionTd.appendChild(rotateBtn);
            const delBtn = document.createElement('button');
            delBtn.className = 'btn btn-danger text-xs role-admin-only';
            delBtn.textContent = '削除';
            delBtn.addEventListener('click', () => deleteApiKey(k.id, k.name));
            actionTd.appendChild(delBtn);
            tr.appendChild(actionTd);
            tbody.appendChild(tr);
        });
    } catch (e) {
        if (tbody) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 6; td.className = 'text-center text-danger';
            td.textContent = '読み込みに失敗しました';
            tr.appendChild(td); tbody.appendChild(tr);
        }
    }
}

async function rotateApiKey(id, name) {
    if (!confirm(`「${name}」の API キーをローテートしますか？現在のキーは無効になります。`)) return;
    try {
        const data = await apiFetch(`/api-keys/${id}/rotate`, { method: 'POST' });
        showApiKeyResult(data.api_key.key_value);
        loadApiKeys();
    } catch (e) { showError('ローテートに失敗しました'); }
}

async function deleteApiKey(id, name) {
    if (!confirm(`「${name}」を削除しますか？`)) return;
    try {
        await apiFetch(`/api-keys/${id}`, { method: 'DELETE' });
        showSuccess('削除しました');
        loadApiKeys();
    } catch (e) { showError('削除に失敗しました'); }
}

function showApiKeyResult(raw) {
    document.getElementById('apikey-result-value').value = raw;
    document.getElementById('apikey-result-modal').classList.add('open');
}

function closeApikeyResultModal() {
    document.getElementById('apikey-result-modal').classList.remove('open');
    loadApiKeys();
}

async function submitApiKey(e) {
    e.preventDefault();
    const name = document.getElementById('apikey-name').value.trim();
    if (!name) { showError('名前は必須です'); return; }
    try {
        const data = await apiFetch('/api-keys', { method: 'POST', body: JSON.stringify({ name }) });
        document.getElementById('apikey-modal').classList.remove('open');
        showApiKeyResult(data.api_key.key_value);
    } catch (e) { showError('作成に失敗しました'); }
}

document.addEventListener('DOMContentLoaded', () => {
    loadAgents();
    loadApiKeys();

    const addApikeyBtn = document.getElementById('btn-add-apikey');
    if (addApikeyBtn) addApikeyBtn.addEventListener('click', () => {
        document.getElementById('apikey-name').value = '';
        document.getElementById('apikey-modal').classList.add('open');
    });
    ['btn-close-apikey-modal', 'btn-close-apikey-modal-foot'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('click', () => document.getElementById('apikey-modal').classList.remove('open'));
    });
    const apikeyForm = document.getElementById('apikey-form');
    if (apikeyForm) apikeyForm.addEventListener('submit', submitApiKey);

    const copyBtn = document.getElementById('btn-copy-apikey');
    if (copyBtn) copyBtn.addEventListener('click', () => {
        const val = document.getElementById('apikey-result-value').value;
        navigator.clipboard?.writeText(val).then(() => showSuccess('コピーしました')).catch(() => showError('コピーに失敗しました'));
    });
    ['btn-close-apikey-result', 'btn-close-apikey-result-foot'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('click', closeApikeyResultModal);
    });

    document.getElementById('btn-csv-agents')?.addEventListener('click', async () => {
        try {
            const res = await apiFetchRaw('/agents/export.csv');
            if (!res.ok) { showError('CSVダウンロードに失敗しました'); return; }
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = 'agents.csv'; a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            showError('CSVダウンロードに失敗しました');
        }
    });
});
