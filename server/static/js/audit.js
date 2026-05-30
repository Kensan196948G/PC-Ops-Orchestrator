let _debounceTimer = null;
let _currentPage = 1;

function debounceLoad() {
    clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(() => loadLogs(1), 400);
}

function _buildParams(extra = {}) {
    const createdBy = document.getElementById('user-filter').value.trim();
    const action = document.getElementById('action-filter').value.trim();
    const fromDate = document.getElementById('from-date')?.value || '';
    const toDate = document.getElementById('to-date')?.value || '';
    const params = new URLSearchParams(extra);
    if (createdBy) params.set('created_by', createdBy);
    if (action) params.set('action', action);
    if (fromDate) params.set('from_date', fromDate);
    if (toDate) params.set('to_date', toDate);
    return params;
}

async function loadLogs(page) {
    _currentPage = page || _currentPage;
    const params = _buildParams({ page: _currentPage, per_page: 50 });

    const tbody = document.getElementById('audit-body');
    try {
        const data = await apiFetch('/audit/logs?' + params.toString());
        renderTable(data.logs || []);
        renderPagination(data.page, data.pages);
    } catch (e) {
        tbody.replaceChildren(_msgRow('読み込みに失敗しました', 7, 'var(--danger)'));
    }
}

function _msgRow(text, cols, color) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = cols;
    td.className = 'text-center';
    if (color) td.style.color = color;
    td.textContent = text;
    tr.appendChild(td);
    return tr;
}

function renderTable(logs) {
    const tbody = document.getElementById('audit-body');
    if (logs.length === 0) {
        tbody.replaceChildren(_msgRow('操作ログはありません', 7, null));
        return;
    }

    const fragment = document.createDocumentFragment();
    logs.forEach(log => {
        const tr = document.createElement('tr');
        tr.classList.add('row-clickable');
        tr.addEventListener('click', () => openAuditDrawer(log));
        [
            String(log.id),
            log.action || '-',
            log.target || '-',
            log.details ? log.details.substring(0, 80) : '-',
            log.created_by || '-',
            log.ip_address || '-',
            log.created_at ? new Date(log.created_at).toLocaleString('ja-JP') : '-',
        ].forEach(text => {
            const td = document.createElement('td');
            td.textContent = text;
            tr.appendChild(td);
        });
        fragment.appendChild(tr);
    });
    tbody.replaceChildren(fragment);
}

// ── Drawer ──────────────────────────────────────────────────────────────────

function openAuditDrawer(log) {
    const overlay = document.getElementById('audit-drawer-overlay');
    const titleEl = document.getElementById('audit-drawer-title');
    const bodyEl = document.getElementById('audit-drawer-body');
    if (!overlay || !bodyEl) return;

    if (titleEl) titleEl.textContent = (log.action || '-') + (log.target ? ' — ' + log.target : '');
    bodyEl.textContent = '';

    const kvSection = document.createElement('div');
    const kvHead = document.createElement('div');
    kvHead.className = 'drawer-section-title';
    kvHead.textContent = '操作情報';
    kvSection.appendChild(kvHead);

    const dl = document.createElement('dl');
    dl.className = 'kv-grid';
    const pairs = [
        ['ID', '#' + log.id],
        ['操作内容', log.action || '-'],
        ['対象', log.target || '-'],
        ['実行者', log.created_by || '-'],
        ['IPアドレス', log.ip_address || '-'],
        ['日時', log.created_at ? new Date(log.created_at).toLocaleString('ja-JP') : '-'],
    ];
    for (const [k, v] of pairs) {
        const dt = document.createElement('dt'); dt.textContent = k; dl.appendChild(dt);
        const dd = document.createElement('dd'); dd.textContent = v; dl.appendChild(dd);
    }
    kvSection.appendChild(dl);
    bodyEl.appendChild(kvSection);

    if (log.details) {
        const detailSection = document.createElement('div');
        const detailHead = document.createElement('div');
        detailHead.className = 'drawer-section-title';
        detailHead.textContent = '詳細';
        detailSection.appendChild(detailHead);
        const pre = document.createElement('pre');
        pre.style.cssText = 'font-size:0.78rem;white-space:pre-wrap;word-break:break-word;' +
            'background:var(--bg-tertiary);border:1px solid var(--border);' +
            'border-radius:var(--radius);padding:0.75rem;color:var(--text-secondary);';
        pre.textContent = log.details;
        detailSection.appendChild(pre);
        bodyEl.appendChild(detailSection);
    }

    overlay.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

function closeAuditDrawer() {
    const overlay = document.getElementById('audit-drawer-overlay');
    if (overlay) overlay.classList.add('hidden');
    document.body.style.overflow = '';
}

function renderPagination(current, total) {
    const container = document.getElementById('audit-pagination');
    if (total <= 1) { container.replaceChildren(); return; }

    const fragment = document.createDocumentFragment();
    const addBtn = (label, page, disabled) => {
        const btn = document.createElement('button');
        btn.className = 'page-btn' + (page === current ? ' active' : '');
        btn.textContent = label;
        btn.disabled = disabled;
        if (!disabled) btn.addEventListener('click', () => loadLogs(page));
        fragment.appendChild(btn);
    };

    addBtn('«', current - 1, current <= 1);
    const start = Math.max(1, current - 2);
    const end = Math.min(total, current + 2);
    for (let p = start; p <= end; p++) addBtn(String(p), p, false);
    addBtn('»', current + 1, current >= total);

    container.replaceChildren(fragment);
}

async function exportCsv() {
    const params = _buildParams();
    const res = await apiFetchRaw('/audit/export.csv?' + params.toString());
    if (!res.ok) { showError('CSV エクスポートに失敗しました'); return; }
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'audit_logs.csv';
    a.click();
    URL.revokeObjectURL(a.href);
}

document.addEventListener('DOMContentLoaded', () => {
    const userFilter = document.getElementById('user-filter');
    if (userFilter) userFilter.addEventListener('input', debounceLoad);

    const actionFilter = document.getElementById('action-filter');
    if (actionFilter) actionFilter.addEventListener('input', debounceLoad);

    const fromDate = document.getElementById('from-date');
    if (fromDate) fromDate.addEventListener('change', debounceLoad);

    const toDate = document.getElementById('to-date');
    if (toDate) toDate.addEventListener('change', debounceLoad);

    const refreshBtn = document.getElementById('btn-refresh-audit');
    if (refreshBtn) refreshBtn.addEventListener('click', () => loadLogs(1));

    const csvBtn = document.getElementById('btn-export-audit-csv');
    if (csvBtn) csvBtn.addEventListener('click', exportCsv);

    loadLogs(1);
    setInterval(() => loadLogs(_currentPage), 30000);

    document.getElementById('btn-close-audit-drawer')?.addEventListener('click', closeAuditDrawer);
    document.getElementById('btn-close-audit-drawer-footer')?.addEventListener('click', closeAuditDrawer);
    document.getElementById('audit-drawer-overlay')?.addEventListener('click', e => {
        if (e.target === e.currentTarget) closeAuditDrawer();
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeAuditDrawer(); });
});
