let currentPage = 1;
let searchTimer = null;

function statusBadge(status) {
    const map = {
        'healthy': '<span class="status-badge status-healthy">正常</span>',
        'warning': '<span class="status-badge status-warning">要注意</span>',
        'critical': '<span class="status-badge status-critical">危険</span>',
        'unknown': '<span class="status-badge status-unknown">不明</span>',
    };
    return map[status] || map['unknown'];
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

async function loadPCs(page) {
    currentPage = page || currentPage;
    const search = document.getElementById('search-input').value.trim();
    const status = document.getElementById('status-filter').value;
    const tbody = document.getElementById('pc-table-body');
    tbody.innerHTML = '<tr><td colspan="9" class="text-center">読み込み中...</td></tr>';

    try {
        const params = new URLSearchParams();
        if (search) params.set('search', search);
        if (status) params.set('status', status);
        params.set('page', currentPage);
        params.set('per_page', '30');

        const data = await apiFetch('/pcs?' + params.toString());
        tbody.innerHTML = data.pcs && data.pcs.length > 0 ? data.pcs.map(pc => `
            <tr onclick="location.href='/pcs/${pc.id}'" style="cursor:pointer;">
                <td><strong>${pc.pc_name}</strong></td>
                <td>${pc.os_version || '-'}</td>
                <td>${truncate(pc.cpu_name, 30) || '-'}</td>
                <td>${formatGB(pc.memory_total_gb)}</td>
                <td>${formatDisk(pc.disk_free_gb, pc.disk_total_gb)}</td>
                <td>${statusBadge(pc.status)}</td>
                <td>${pc.health_score ?? '-'}</td>
                <td>${formatTime(pc.last_seen)}</td>
                <td>${pc.last_seen ? (Date.now() - new Date(pc.last_seen).getTime() < 300000 ? '<span style="color:var(--success)">&#9679;</span>' : '<span style="color:var(--text-muted)">&#9679;</span>') : ''}</td>
            </tr>
        `).join('') : '<tr><td colspan="9" class="text-center">PCが登録されていません</td></tr>';

        renderPagination(data.total, data.page, data.pages);
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-center" style="color:var(--danger);">読み込みに失敗しました</td></tr>';
    }
}

function renderPagination(total, page, pages) {
    const el = document.getElementById('pagination');
    if (!pages || pages <= 1) {
        el.innerHTML = '';
        return;
    }
    let html = '';
    for (let i = 1; i <= pages; i++) {
        html += `<button class="${i === page ? 'active' : ''}" onclick="loadPCs(${i})">${i}</button>`;
    }
    el.innerHTML = html;
}

function searchPCs() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadPCs(1), 300);
}

document.addEventListener('DOMContentLoaded', () => {
    loadPCs(1);
    setInterval(() => loadPCs(currentPage), 30000);
});
