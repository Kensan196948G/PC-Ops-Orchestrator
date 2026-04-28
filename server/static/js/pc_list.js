let currentPage = 1;
let searchTimer = null;

function statusBadgeEl(status) {
    const map = {
        'healthy': ['status-healthy', '正常'],
        'warning': ['status-warning', '要注意'],
        'critical': ['status-critical', '危険'],
        'unknown': ['status-unknown', '不明'],
    };
    const [cls, label] = map[status] || map['unknown'];
    const span = document.createElement('span');
    span.className = `status-badge ${cls}`;
    span.textContent = label;
    return span;
}

function formatGB(val) {
    if (val === null || val === undefined) return '-';
    return val.toFixed(1) + ' GB';
}

function formatDisk(free, total) {
    if (free === null || free === undefined || total === null || total === undefined) return '-';
    const pct = (free / total * 100).toFixed(0);
    return `${free.toFixed(1)} / ${total.toFixed(1)} GB (${pct}%)`;
}

function formatTime(iso) {
    if (!iso) return '-';
    return new Date(iso).toLocaleString('ja-JP');
}

function truncate(str, len) {
    if (!str) return '-';
    return str.length > len ? str.substring(0, len) + '...' : str;
}

function makeMessageRow(message, cols, style) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = cols;
    td.className = 'text-center';
    td.textContent = message;
    if (style) td.style.cssText = style;
    tr.appendChild(td);
    return tr;
}

async function loadPCs(page) {
    currentPage = page || currentPage;
    const search = document.getElementById('search-input').value.trim();
    const status = document.getElementById('status-filter').value;
    const tbody = document.getElementById('pc-table-body');
    tbody.replaceChildren(makeMessageRow('読み込み中...', 9, null));

    try {
        const params = new URLSearchParams();
        if (search) params.set('search', search);
        if (status) params.set('status', status);
        params.set('page', currentPage);
        params.set('per_page', '30');

        const data = await apiFetch('/pcs?' + params.toString());
        tbody.replaceChildren();

        if (data.pcs && data.pcs.length > 0) {
            data.pcs.forEach(pc => {
                const tr = document.createElement('tr');
                tr.style.cursor = 'pointer';
                tr.addEventListener('click', () => { location.href = `/pcs/${pc.id}`; });

                const td = (text) => {
                    const el = document.createElement('td');
                    el.textContent = text;
                    return el;
                };

                const nameTd = document.createElement('td');
                const strong = document.createElement('strong');
                strong.textContent = pc.pc_name;
                nameTd.appendChild(strong);

                tr.appendChild(nameTd);
                tr.appendChild(td(pc.os_version || '-'));
                tr.appendChild(td(truncate(pc.cpu_name, 30) || '-'));
                tr.appendChild(td(formatGB(pc.memory_total_gb)));
                tr.appendChild(td(formatDisk(pc.disk_free_gb, pc.disk_total_gb)));

                const statusTd = document.createElement('td');
                statusTd.appendChild(statusBadgeEl(pc.status));
                tr.appendChild(statusTd);

                tr.appendChild(td(pc.health_score ?? '-'));
                tr.appendChild(td(formatTime(pc.last_seen)));

                const dotTd = document.createElement('td');
                if (pc.last_seen) {
                    const dot = document.createElement('span');
                    dot.textContent = '●';
                    dot.style.color = Date.now() - new Date(pc.last_seen).getTime() < 300000
                        ? 'var(--success)' : 'var(--text-muted)';
                    dotTd.appendChild(dot);
                }
                tr.appendChild(dotTd);

                tbody.appendChild(tr);
            });
        } else {
            tbody.replaceChildren(makeMessageRow('PCが登録されていません', 9, null));
        }

        renderPagination(data.total, data.page, data.pages);
    } catch (e) {
        tbody.replaceChildren(makeMessageRow('読み込みに失敗しました', 9, 'color:var(--danger);'));
    }
}

function renderPagination(total, page, pages) {
    const el = document.getElementById('pagination');
    el.replaceChildren();
    if (!pages || pages <= 1) return;
    for (let i = 1; i <= pages; i++) {
        const btn = document.createElement('button');
        btn.textContent = i;
        if (i === page) btn.className = 'active';
        btn.addEventListener('click', () => loadPCs(i));
        el.appendChild(btn);
    }
}

function searchPCs() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadPCs(1), 300);
}

document.addEventListener('DOMContentLoaded', () => {
    loadPCs(1);
    setInterval(() => loadPCs(currentPage), 30000);
});
