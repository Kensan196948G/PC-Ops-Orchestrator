let currentAlertsPage = 1;

const SEVERITY_CLASS = { critical: 'severity-critical', high: 'severity-high', medium: 'severity-medium', low: 'severity-low' };
const SEVERITY_TEXT = { critical: '危険', high: '高', medium: '中', low: '低' };

function makeSeverityBadge(sev) {
    const span = document.createElement('span');
    span.className = 'status-badge ' + (SEVERITY_CLASS[sev] || '');
    span.textContent = SEVERITY_TEXT[sev] || sev;
    return span;
}

function makeStatusBadge(resolved) {
    const span = document.createElement('span');
    span.className = 'status-badge ' + (resolved ? 'status-completed' : 'status-pending');
    span.textContent = resolved ? '解決済み' : '未解決';
    return span;
}

function makeBtn(label, cls, handler, roleClass) {
    const btn = document.createElement('button');
    btn.className = 'btn ' + cls + (roleClass ? ' ' + roleClass : '');
    btn.style.cssText = 'padding:0.2rem 0.5rem;font-size:0.75rem;margin-right:0.25rem;';
    btn.textContent = label;
    btn.onclick = handler;
    return btn;
}

function buildAlertRow(a) {
    const tr = document.createElement('tr');

    const tdId = document.createElement('td');
    tdId.textContent = '#' + a.id;

    const tdSev = document.createElement('td');
    tdSev.appendChild(makeSeverityBadge(a.severity));

    const tdType = document.createElement('td');
    tdType.textContent = a.alert_type || '-';

    const tdMsg = document.createElement('td');
    tdMsg.textContent = a.message || '-';

    const tdTime = document.createElement('td');
    tdTime.textContent = a.created_at ? new Date(a.created_at).toLocaleString('ja-JP') : '-';

    const tdStatus = document.createElement('td');
    tdStatus.appendChild(makeStatusBadge(a.resolved));
    if (a.acknowledged) {
        const ack = document.createElement('span');
        ack.style.cssText = 'color:var(--text-secondary);font-size:0.75rem;margin-left:4px;';
        ack.textContent = '✓ ' + (a.acknowledged_by || '');
        tdStatus.appendChild(ack);
    }

    const tdActions = document.createElement('td');
    if (!a.resolved) {
        if (!a.acknowledged) {
            tdActions.appendChild(makeBtn('確認', 'btn-secondary', () => acknowledgeAlert(a.id), 'role-operator-or-admin'));
        }
        tdActions.appendChild(makeBtn('解決', 'btn-danger', () => resolveAlert(a.id), 'role-operator-or-admin'));
    }

    [tdId, tdSev, tdType, tdMsg, tdTime, tdStatus, tdActions].forEach(td => tr.appendChild(td));
    return tr;
}

async function loadAlerts(page) {
    currentAlertsPage = page || currentAlertsPage;
    const severity = document.getElementById('severity-filter').value;
    const resolved = document.getElementById('resolved-filter').value;
    const tbody = document.getElementById('alerts-body');

    const loadingRow = document.createElement('tr');
    const loadingCell = document.createElement('td');
    loadingCell.colSpan = 7;
    loadingCell.className = 'text-center';
    loadingCell.textContent = '読み込み中...';
    loadingRow.appendChild(loadingCell);
    tbody.replaceChildren(loadingRow);

    try {
        const params = new URLSearchParams({ resolved, page: currentAlertsPage, per_page: 30 });
        if (severity) params.set('severity', severity);

        const data = await apiFetch('/alerts?' + params.toString());

        if (data.alerts && data.alerts.length > 0) {
            tbody.replaceChildren(...data.alerts.map(buildAlertRow));
        } else {
            const emptyRow = document.createElement('tr');
            const emptyCell = document.createElement('td');
            emptyCell.colSpan = 7;
            emptyCell.className = 'text-center';
            emptyCell.textContent = 'アラートはありません';
            emptyRow.appendChild(emptyCell);
            tbody.replaceChildren(emptyRow);
        }

        const pagination = document.getElementById('alerts-pagination');
        pagination.replaceChildren();
        if (data.pages && data.pages > 1) {
            for (let i = 1; i <= data.pages; i++) {
                const btn = document.createElement('button');
                btn.textContent = i;
                if (i === data.page) btn.className = 'active';
                btn.onclick = () => loadAlerts(i);
                pagination.appendChild(btn);
            }
        }
    } catch (e) {
        const errRow = document.createElement('tr');
        const errCell = document.createElement('td');
        errCell.colSpan = 7;
        errCell.className = 'text-center';
        errCell.style.color = 'var(--danger)';
        errCell.textContent = '読み込みに失敗しました';
        errRow.appendChild(errCell);
        tbody.replaceChildren(errRow);
    }
}

async function acknowledgeAlert(alertId) {
    try {
        const res = await apiFetch('/alerts/' + alertId + '/acknowledge', { method: 'POST' });
        if (res.alert) {
            showSuccess('確認済みにしました');
            loadAlerts(currentAlertsPage);
        } else {
            showError(res.error || '操作に失敗しました');
        }
    } catch (e) {
        showError('APIエラー');
    }
}

async function resolveAlert(alertId) {
    if (!confirm('アラート #' + alertId + ' を解決済みにしますか？')) return;
    try {
        const res = await apiFetch('/alerts/' + alertId + '/resolve', { method: 'POST' });
        if (res.message) {
            showSuccess(res.message);
            loadAlerts(currentAlertsPage);
        } else {
            showError(res.error || '操作に失敗しました');
        }
    } catch (e) {
        showError('APIエラー');
    }
}

async function syncAlerts() {
    try {
        const res = await apiFetch('/alerts/sync', { method: 'POST' });
        showSuccess('同期完了: 新規 ' + res.created + ' 件、解決 ' + res.resolved + ' 件');
        loadAlerts(1);
    } catch (e) {
        showError('同期に失敗しました');
    }
}

async function exportAlertsCSV() {
    const severity = document.getElementById('severity-filter')?.value || '';
    const resolved = document.getElementById('resolved-filter')?.value || 'false';
    const params = new URLSearchParams({ resolved });
    if (severity) params.set('severity', severity);
    try {
        const res = await apiFetchRaw('/alerts/export.csv?' + params.toString());
        if (!res.ok) { showError('エクスポートに失敗しました'); return; }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'alerts.csv';
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) {
        showError('エクスポートに失敗しました');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const severityFilter = document.getElementById('severity-filter');
    if (severityFilter) severityFilter.addEventListener('change', () => loadAlerts(1));

    const resolvedFilter = document.getElementById('resolved-filter');
    if (resolvedFilter) resolvedFilter.addEventListener('change', () => loadAlerts(1));

    const syncBtn = document.getElementById('btn-sync-alerts');
    if (syncBtn) syncBtn.addEventListener('click', syncAlerts);

    const csvBtn = document.getElementById('btn-export-alerts-csv');
    if (csvBtn) csvBtn.addEventListener('click', exportAlertsCSV);

    loadAlerts(1);
    setInterval(() => loadAlerts(currentAlertsPage), 30000);
});
