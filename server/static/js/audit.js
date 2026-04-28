let _debounceTimer = null;
let _currentPage = 1;

function debounceLoad() {
    clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(() => loadLogs(1), 400);
}

async function loadLogs(page) {
    _currentPage = page || _currentPage;
    const createdBy = document.getElementById('user-filter').value.trim();
    const action = document.getElementById('action-filter').value.trim();

    const params = new URLSearchParams({ page: _currentPage, per_page: 50 });
    if (createdBy) params.set('created_by', createdBy);
    if (action) params.set('action', action);

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

document.addEventListener('DOMContentLoaded', () => {
    loadLogs(1);
    setInterval(() => loadLogs(_currentPage), 30000);
});
