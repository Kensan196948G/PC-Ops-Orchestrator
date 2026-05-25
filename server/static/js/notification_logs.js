let currentLogsPage = 1;

const STATUS_CLASS = { sent: 'status-completed', failed: 'status-error', skipped: 'status-warning' };
const STATUS_TEXT = { sent: '送信済み', failed: '失敗', skipped: 'スキップ' };
const CHANNEL_TEXT = {
    slack: 'Slack',
    teams: 'Teams',
    email: 'Email',
    generic_webhook: 'Webhook',
};

function makeStatusBadge(status) {
    const span = document.createElement('span');
    span.className = 'status-badge ' + (STATUS_CLASS[status] || '');
    span.textContent = STATUS_TEXT[status] || status;
    return span;
}

function buildLogRow(log) {
    const tr = document.createElement('tr');

    const tdId = document.createElement('td');
    tdId.textContent = '#' + log.id;

    const tdChannel = document.createElement('td');
    tdChannel.textContent = CHANNEL_TEXT[log.channel] || log.channel || '-';

    const tdStatus = document.createElement('td');
    tdStatus.appendChild(makeStatusBadge(log.status));

    const tdRule = document.createElement('td');
    if (log.rule_id) {
        const a = document.createElement('a');
        a.href = '/alert-rules';
        a.textContent = 'Rule #' + log.rule_id;
        a.style.cssText = 'color:var(--primary);text-decoration:none;';
        tdRule.appendChild(a);
    } else {
        tdRule.textContent = '-';
    }

    const tdMsg = document.createElement('td');
    tdMsg.textContent = log.message ? log.message.slice(0, 80) + (log.message.length > 80 ? '…' : '') : '-';
    tdMsg.style.cssText = 'max-width:300px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';

    const tdTime = document.createElement('td');
    tdTime.textContent = log.sent_at ? new Date(log.sent_at).toLocaleString('ja-JP') : '-';

    [tdId, tdChannel, tdStatus, tdRule, tdMsg, tdTime].forEach(td => tr.appendChild(td));
    return tr;
}

async function loadLogs(page) {
    currentLogsPage = page || currentLogsPage;
    const status = document.getElementById('status-filter').value;
    const channel = document.getElementById('channel-filter').value;
    const tbody = document.getElementById('notif-logs-body');

    const loadingRow = document.createElement('tr');
    const loadingCell = document.createElement('td');
    loadingCell.colSpan = 6;
    loadingCell.className = 'text-center';
    loadingCell.textContent = '読み込み中...';
    loadingRow.appendChild(loadingCell);
    tbody.replaceChildren(loadingRow);

    try {
        const params = new URLSearchParams({ page: currentLogsPage, per_page: 30 });
        if (status) params.set('status', status);
        if (channel) params.set('channel', channel);

        const data = await apiFetch('/notification-logs?' + params.toString());

        if (data.notification_logs && data.notification_logs.length > 0) {
            tbody.replaceChildren(...data.notification_logs.map(buildLogRow));
        } else {
            const emptyRow = document.createElement('tr');
            const emptyCell = document.createElement('td');
            emptyCell.colSpan = 6;
            emptyCell.className = 'text-center';
            emptyCell.textContent = '通知履歴はありません';
            emptyRow.appendChild(emptyCell);
            tbody.replaceChildren(emptyRow);
        }

        const pagination = document.getElementById('notif-logs-pagination');
        pagination.replaceChildren();
        if (data.pages && data.pages > 1) {
            for (let i = 1; i <= data.pages; i++) {
                const btn = document.createElement('button');
                btn.textContent = i;
                if (i === data.page) btn.className = 'active';
                btn.onclick = () => loadLogs(i);
                pagination.appendChild(btn);
            }
        }
    } catch (e) {
        const errRow = document.createElement('tr');
        const errCell = document.createElement('td');
        errCell.colSpan = 6;
        errCell.className = 'text-center';
        errCell.style.color = 'var(--danger)';
        errCell.textContent = '読み込みに失敗しました';
        errRow.appendChild(errCell);
        tbody.replaceChildren(errRow);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const statusFilter = document.getElementById('status-filter');
    if (statusFilter) statusFilter.addEventListener('change', () => loadLogs(1));

    const channelFilter = document.getElementById('channel-filter');
    if (channelFilter) channelFilter.addEventListener('change', () => loadLogs(1));

    const refreshBtn = document.getElementById('btn-refresh-logs');
    if (refreshBtn) refreshBtn.addEventListener('click', () => loadLogs(currentLogsPage));

    loadLogs(1);
    setInterval(() => loadLogs(currentLogsPage), 60000);
});
