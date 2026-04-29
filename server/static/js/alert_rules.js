'use strict';

let currentPage = 1;

const METRIC_LABELS = { cpu: 'CPU(%)', memory: 'メモリ(%)', disk: 'ディスク(%)', offline: 'オフライン' };
const OP_LABELS = { gt: '>', gte: '>=', lt: '<', lte: '<=' };

async function loadRules(page = 1) {
    currentPage = page;
    const data = await apiFetch(`/alert-rules?page=${page}&per_page=50`);
    const tbody = document.getElementById('rules-body');
    tbody.textContent = '';

    if (!data.alert_rules || data.alert_rules.length === 0) {
        const row = tbody.insertRow();
        const cell = row.insertCell();
        cell.colSpan = 7;
        cell.className = 'text-center';
        cell.textContent = 'アラートルールがありません';
        document.getElementById('rules-pagination').textContent = '';
        return;
    }

    for (const r of data.alert_rules) {
        const row = tbody.insertRow();
        row.dataset.id = r.id;

        const tdName = row.insertCell();
        const strong = document.createElement('strong');
        strong.textContent = r.name;
        tdName.appendChild(strong);

        row.insertCell().textContent = METRIC_LABELS[r.metric] || r.metric;

        const tdCond = row.insertCell();
        if (r.metric === 'offline') {
            tdCond.textContent = '検出時';
        } else {
            tdCond.textContent = `${OP_LABELS[r.operator] || r.operator} ${r.threshold}%`;
        }

        const tdSev = row.insertCell();
        const badge = document.createElement('span');
        badge.className = r.severity === 'critical' ? 'badge badge-danger' : 'badge badge-warning';
        badge.textContent = r.severity;
        tdSev.appendChild(badge);

        const tdNotify = row.insertCell();
        const parts = [];
        if (r.notify_slack_webhook) parts.push('Slack');
        if (r.notify_teams_webhook) parts.push('Teams');
        if (r.notify_webhook_url) parts.push('Webhook');
        if (r.notify_email) parts.push('Mail');
        let notifyText = parts.length ? parts.join(', ') : '-';
        if (r.channel_type) {
            notifyText += ` (${r.channel_type})`;
        }
        tdNotify.textContent = notifyText;

        const tdState = row.insertCell();
        const toggle = document.createElement('button');
        toggle.className = (r.is_enabled ? 'btn btn-xs btn-primary' : 'btn btn-xs btn-secondary') + ' role-admin-only';
        toggle.textContent = r.is_enabled ? '有効' : '無効';
        toggle.dataset.action = 'toggle';
        toggle.dataset.id = r.id;
        tdState.appendChild(toggle);

        const tdOps = row.insertCell();
        tdOps.className = 'action-cell';
        tdOps.appendChild(makeBtn('✎', 'btn-secondary btn-xs', 'edit', r.id, '編集', 'role-admin-only'));
        tdOps.appendChild(makeBtn('⚡', 'btn-secondary btn-xs', 'test-notify', r.id, 'テスト通知', 'role-admin-only'));
        tdOps.appendChild(makeBtn('✕', 'btn-danger btn-xs', 'delete', r.id, '削除', 'role-admin-only'));
    }

    renderPagination('rules-pagination', data.page, data.pages, loadRules);
}

function makeBtn(label, classes, action, id, title, roleClass) {
    const btn = document.createElement('button');
    btn.className = `btn ${classes}` + (roleClass ? ` ${roleClass}` : '');
    btn.textContent = label;
    btn.title = title;
    btn.dataset.action = action;
    btn.dataset.id = id;
    return btn;
}

document.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const id = parseInt(btn.dataset.id, 10);
    const action = btn.dataset.action;

    if (action === 'toggle') {
        const data = await apiFetch(`/alert-rules/${id}/toggle`, { method: 'POST' });
        if (data.error) { showError(data.error); return; }
        showSuccess(data.message);
        loadRules(currentPage);
    } else if (action === 'edit') {
        await editRule(id);
    } else if (action === 'test-notify') {
        const data = await apiFetch(`/alert-rules/${id}/test-notify`, { method: 'POST' });
        if (data.error) { showError(data.error); return; }
        const res = data.results || {};
        const summary = ['slack', 'teams', 'generic_webhook', 'email']
            .map((c) => `${c}=${res[c] || '-'}`)
            .join(', ');
        showSuccess(`テスト通知: ${summary}`);
    } else if (action === 'delete') {
        const name = btn.closest('tr')?.querySelector('strong')?.textContent || '';
        if (!confirm(`「${name}」を削除しますか？`)) return;
        const data = await apiFetch(`/alert-rules/${id}`, { method: 'DELETE' });
        if (data.error) { showError(data.error); return; }
        showSuccess(data.message);
        loadRules(currentPage);
    }
});

function showCreateModal() {
    document.getElementById('rule-modal-title').textContent = 'ルールの作成';
    document.getElementById('rule-form').reset();
    document.getElementById('rule-id').value = '';
    document.getElementById('rule-enabled').checked = true;
    toggleThreshold();
    toggleChannelInputs();
    document.getElementById('rule-modal').classList.add('active');
}

function toggleChannelInputs() {
    // チャネル種別 select に応じて関連入力だけを表示する。
    // 空 ("自動") のときは全フィールド表示。
    const sel = document.getElementById('rule-channel-type');
    if (!sel) return;
    const value = sel.value;
    document.querySelectorAll('[data-channel]').forEach((el) => {
        if (!value) {
            el.style.display = '';
            return;
        }
        const ch = el.dataset.channel;
        const visible =
            (value === 'slack' && ch === 'slack') ||
            (value === 'teams' && ch === 'teams') ||
            (value === 'generic_webhook' && ch === 'generic') ||
            (value === 'email' && ch === 'email');
        el.style.display = visible ? '' : 'none';
    });
}

function closeRuleModal(e) {
    if (e.target.id === 'rule-modal') closeRuleModalDirect();
}

function closeRuleModalDirect() {
    document.getElementById('rule-modal').classList.remove('active');
}

function toggleThreshold() {
    const metric = document.getElementById('rule-metric').value;
    document.getElementById('threshold-group').style.display = metric === 'offline' ? 'none' : '';
}

async function editRule(id) {
    const data = await apiFetch(`/alert-rules/${id}`);
    const r = data.alert_rule;
    if (!r) return;
    document.getElementById('rule-modal-title').textContent = 'ルールの編集';
    document.getElementById('rule-id').value = r.id;
    document.getElementById('rule-name').value = r.name;
    document.getElementById('rule-metric').value = r.metric;
    document.getElementById('rule-operator').value = r.operator || 'gt';
    document.getElementById('rule-threshold').value = r.threshold ?? '';
    document.getElementById('rule-severity').value = r.severity || 'warning';
    document.getElementById('rule-slack').value = r.notify_slack_webhook || '';
    document.getElementById('rule-teams').value = r.notify_teams_webhook || '';
    document.getElementById('rule-generic').value = r.notify_webhook_url || '';
    document.getElementById('rule-email').value = r.notify_email || '';
    document.getElementById('rule-channel-type').value = r.channel_type || '';
    document.getElementById('rule-enabled').checked = r.is_enabled;
    toggleThreshold();
    toggleChannelInputs();
    document.getElementById('rule-modal').classList.add('active');
}

async function submitRuleForm(e) {
    e.preventDefault();
    const id = document.getElementById('rule-id').value;
    const metric = document.getElementById('rule-metric').value;
    const thresholdRaw = document.getElementById('rule-threshold').value;

    const payload = {
        name: document.getElementById('rule-name').value,
        metric,
        operator: document.getElementById('rule-operator').value,
        threshold: metric !== 'offline' ? parseFloat(thresholdRaw) : null,
        severity: document.getElementById('rule-severity').value,
        notify_slack_webhook: document.getElementById('rule-slack').value || null,
        notify_teams_webhook: document.getElementById('rule-teams').value || null,
        notify_webhook_url: document.getElementById('rule-generic').value || null,
        notify_email: document.getElementById('rule-email').value || null,
        channel_type: document.getElementById('rule-channel-type').value || null,
        is_enabled: document.getElementById('rule-enabled').checked,
    };

    const method = id ? 'PUT' : 'POST';
    const path = id ? `/alert-rules/${id}` : '/alert-rules';
    const data = await apiFetch(path, { method, body: JSON.stringify(payload) });
    if (data.error) { showError(data.error); return; }
    showSuccess(data.message);
    closeRuleModalDirect();
    loadRules(currentPage);
}

function renderPagination(containerId, page, pages, callback) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.textContent = '';
    if (pages <= 1) return;
    if (page > 1) {
        const prev = document.createElement('button');
        prev.className = 'btn btn-secondary btn-sm';
        prev.textContent = '‹ 前';
        prev.addEventListener('click', () => callback(page - 1));
        el.appendChild(prev);
        el.append(' ');
    }
    el.append(`${page} / ${pages}`);
    if (page < pages) {
        el.append(' ');
        const next = document.createElement('button');
        next.className = 'btn btn-secondary btn-sm';
        next.textContent = '次 ›';
        next.addEventListener('click', () => callback(page + 1));
        el.appendChild(next);
    }
}

document.addEventListener('DOMContentLoaded', () => loadRules(1));
