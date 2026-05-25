let lastSyncAt = null;

const SEVERITY_CLASS = {
    critical: 'status-critical',
    high: 'status-error',
    medium: 'status-warning',
    low: 'status-completed',
};

function severityBadge(sev) {
    const span = document.createElement('span');
    span.className = 'status-badge ' + (SEVERITY_CLASS[sev] || '');
    span.textContent = sev || '-';
    return span;
}

function buildRow(issue) {
    const tr = document.createElement('tr');

    const tdTitle = document.createElement('td');
    tdTitle.textContent = issue.title || '-';
    tdTitle.style.cssText = 'max-width:400px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
    if (issue.title) tdTitle.title = issue.title;

    const tdKb = document.createElement('td');
    tdKb.textContent = issue.kb_id || '-';

    const tdOs = document.createElement('td');
    tdOs.textContent = issue.affected_os || '-';

    const tdSev = document.createElement('td');
    tdSev.appendChild(severityBadge(issue.severity));

    const tdCreated = document.createElement('td');
    tdCreated.textContent = issue.created_at ? new Date(issue.created_at).toLocaleString('ja-JP') : '-';

    [tdTitle, tdKb, tdOs, tdSev, tdCreated].forEach(td => tr.appendChild(td));
    return tr;
}

async function loadIssues() {
    const tbody = document.getElementById('wrh-issues-body');
    const active = document.getElementById('wrh-active-filter').value;

    const loadingRow = document.createElement('tr');
    const loadingCell = document.createElement('td');
    loadingCell.colSpan = 5;
    loadingCell.className = 'text-center';
    loadingCell.textContent = '読み込み中...';
    loadingRow.appendChild(loadingCell);
    tbody.replaceChildren(loadingRow);

    try {
        const data = await apiFetch(`/integration/windows-release-health/issues?active=${encodeURIComponent(active)}`);
        const totalEl = document.getElementById('wrh-stat-total');
        if (totalEl && totalEl.firstChild) {
            totalEl.firstChild.nodeValue = String(data.total ?? 0);
        }
        if (!data.issues || data.issues.length === 0) {
            const emptyRow = document.createElement('tr');
            const emptyCell = document.createElement('td');
            emptyCell.colSpan = 5;
            emptyCell.className = 'text-center';
            emptyCell.textContent = '該当する Known Issue はありません';
            emptyRow.appendChild(emptyCell);
            tbody.replaceChildren(emptyRow);
            return;
        }
        tbody.replaceChildren(...data.issues.map(buildRow));
    } catch (e) {
        console.error('WRH load error:', e);
        const errRow = document.createElement('tr');
        const errCell = document.createElement('td');
        errCell.colSpan = 5;
        errCell.className = 'text-center';
        errCell.style.color = 'var(--danger)';
        errCell.textContent = '読み込みに失敗しました';
        errRow.appendChild(errCell);
        tbody.replaceChildren(errRow);
    }
}

async function syncRSS() {
    const btn = document.getElementById('btn-wrh-sync');
    if (btn) btn.disabled = true;
    try {
        const data = await apiFetch('/integration/windows-release-health/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        lastSyncAt = new Date();
        const syncEl = document.getElementById('wrh-stat-last-sync');
        if (syncEl) syncEl.textContent = lastSyncAt.toLocaleString('ja-JP');
        const inserted = data.inserted ?? 0;
        const updated = data.updated ?? 0;
        alert(`同期完了: ${inserted} 件追加 / ${updated} 件更新`);
        await loadIssues();
    } catch (e) {
        console.error('WRH sync error:', e);
        alert('RSS 同期に失敗しました');
    } finally {
        if (btn) btn.disabled = false;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const filter = document.getElementById('wrh-active-filter');
    if (filter) filter.addEventListener('change', loadIssues);

    const refreshBtn = document.getElementById('btn-wrh-refresh');
    if (refreshBtn) refreshBtn.addEventListener('click', loadIssues);

    const syncBtn = document.getElementById('btn-wrh-sync');
    if (syncBtn) syncBtn.addEventListener('click', syncRSS);

    loadIssues();
});
