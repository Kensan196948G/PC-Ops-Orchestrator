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
    tr.classList.add('row-clickable');
    tr.addEventListener('click', () => openNotifLogDrawer(log));

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
        a.addEventListener('click', e => e.stopPropagation());
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

// ── Drawer ──────────────────────────────────────────────────────────────────

function openNotifLogDrawer(log) {
    const overlay = document.getElementById('notiflog-drawer-overlay');
    const titleEl = document.getElementById('notiflog-drawer-title');
    const bodyEl = document.getElementById('notiflog-drawer-body');
    if (!overlay || !bodyEl) return;

    if (titleEl) {
        const badge = makeStatusBadge(log.status);
        titleEl.textContent = '';
        titleEl.appendChild(badge);
        titleEl.appendChild(document.createTextNode(' ' + (CHANNEL_TEXT[log.channel] || log.channel || '-') + ' #' + log.id));
    }

    bodyEl.textContent = '';

    // Key/value section
    const kvSection = document.createElement('div');
    const kvHead = document.createElement('div');
    kvHead.className = 'drawer-section-title';
    kvHead.textContent = '配信情報';
    kvSection.appendChild(kvHead);

    const dl = document.createElement('dl');
    dl.className = 'kv-grid';
    const pairs = [
        ['チャネル', CHANNEL_TEXT[log.channel] || log.channel || '-'],
        ['状態', STATUS_TEXT[log.status] || log.status || '-'],
        ['ルール', log.rule_id ? 'Rule #' + log.rule_id : '-'],
        ['送信日時', log.sent_at ? new Date(log.sent_at).toLocaleString('ja-JP') : '-'],
        ['リトライ回数', log.retry_count != null ? String(log.retry_count) : '-'],
    ];
    for (const [k, v] of pairs) {
        const dt = document.createElement('dt'); dt.textContent = k; dl.appendChild(dt);
        const dd = document.createElement('dd'); dd.textContent = v; dl.appendChild(dd);
    }
    kvSection.appendChild(dl);
    bodyEl.appendChild(kvSection);

    // Full message
    if (log.message) {
        const msgSection = document.createElement('div');
        const msgHead = document.createElement('div');
        msgHead.className = 'drawer-section-title';
        msgHead.textContent = 'メッセージ全文';
        msgSection.appendChild(msgHead);
        const pre = document.createElement('pre');
        pre.style.cssText = 'font-size:0.78rem;white-space:pre-wrap;word-break:break-word;' +
            'background:var(--bg-tertiary);border:1px solid var(--border);' +
            'border-radius:var(--radius);padding:0.75rem;color:var(--text-secondary);';
        pre.textContent = log.message;
        msgSection.appendChild(pre);
        bodyEl.appendChild(msgSection);
    }

    // Error detail
    if (log.error_message) {
        const errSection = document.createElement('div');
        const errHead = document.createElement('div');
        errHead.className = 'drawer-section-title';
        errHead.textContent = 'エラー詳細';
        errSection.appendChild(errHead);
        const pre = document.createElement('pre');
        pre.style.cssText = 'font-size:0.78rem;white-space:pre-wrap;word-break:break-word;' +
            'background:var(--danger-soft);border:1px solid var(--danger);' +
            'border-radius:var(--radius);padding:0.75rem;color:var(--danger);';
        pre.textContent = log.error_message;
        errSection.appendChild(pre);
        bodyEl.appendChild(errSection);
    }

    overlay.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

function closeNotifLogDrawer() {
    const overlay = document.getElementById('notiflog-drawer-overlay');
    if (overlay) overlay.classList.add('hidden');
    document.body.style.overflow = '';
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

    document.getElementById('btn-close-notiflog-drawer')?.addEventListener('click', closeNotifLogDrawer);
    document.getElementById('btn-close-notiflog-drawer-footer')?.addEventListener('click', closeNotifLogDrawer);
    document.getElementById('notiflog-drawer-overlay')?.addEventListener('click', e => {
        if (e.target === e.currentTarget) closeNotifLogDrawer();
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeNotifLogDrawer(); });

    loadLogs(1);
    setInterval(() => loadLogs(currentLogsPage), 60000);
});
