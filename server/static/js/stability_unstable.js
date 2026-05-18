const SCORE_STATUS = [
    { max: 40, cls: 'severity-critical', label: '危険' },
    { max: 60, cls: 'severity-high',     label: '不安定' },
    { max: 80, cls: 'severity-medium',   label: '要注意' },
    { max: 101, cls: 'severity-low',     label: '正常' },
];

function scoreStatus(score) {
    return SCORE_STATUS.find(s => score < s.max) || SCORE_STATUS[SCORE_STATUS.length - 1];
}

function scoreBadge(score) {
    const st = scoreStatus(score);
    const span = document.createElement('span');
    span.className = 'status-badge ' + st.cls;
    span.textContent = st.label;
    return span;
}

function fmtDeductions(raw) {
    let list;
    try { list = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch { return '-'; }
    if (!Array.isArray(list) || list.length === 0) return '減点なし';
    return list.slice(0, 3).map(d => `${d.label || d.category || '?'} (${d.points?.toFixed(1) ?? 0})`).join(', ');
}

function fmtDate(str) {
    if (!str) return '-';
    return new Date(str).toLocaleString('ja-JP');
}

function clearBody(tbody) {
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
}

function emptyRow(cols, msg) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = cols;
    td.className = 'text-center';
    td.textContent = msg;
    tr.appendChild(td);
    return tr;
}

let allItems = [];
let currentPage = 1;
const PER_PAGE = 30;

async function loadUnstable() {
    const threshold = document.getElementById('threshold-filter')?.value || '60';
    const days = document.getElementById('days-filter')?.value || '30';
    const tbody = document.getElementById('unstable-body');
    if (!tbody) return;
    clearBody(tbody);
    tbody.appendChild(emptyRow(7, '読み込み中...'));
    try {
        const data = await apiFetch(`/stability/unstable-pcs?threshold=${threshold}&days=${days}`);
        allItems = (data.items || data || []).sort((a, b) => {
            const sa = a.latest_score ?? a.score ?? 100;
            const sb = b.latest_score ?? b.score ?? 100;
            return sa - sb;
        });
        currentPage = 1;
        renderPage();
    } catch (e) {
        clearBody(tbody);
        tbody.appendChild(emptyRow(7, '読み込み失敗'));
        console.error(e);
    }
}

function renderPage() {
    const tbody = document.getElementById('unstable-body');
    const paginationEl = document.getElementById('unstable-pagination');
    if (!tbody) return;

    const searchVal = document.getElementById('pc-search')?.value?.toLowerCase() || '';
    const filtered = allItems.filter(item =>
        !searchVal || (item.pc_name || '').toLowerCase().includes(searchVal)
    );

    clearBody(tbody);
    if (filtered.length === 0) {
        tbody.appendChild(emptyRow(7, 'データなし'));
        if (paginationEl) paginationEl.textContent = '';
        return;
    }

    const start = (currentPage - 1) * PER_PAGE;
    const page = filtered.slice(start, start + PER_PAGE);

    for (const item of page) {
        const tr = document.createElement('tr');
        const score = item.latest_score ?? item.score ?? 100;

        // PC名
        const tdName = document.createElement('td');
        const a = document.createElement('a');
        a.href = `/pcs/${item.pc_id}`;
        a.textContent = item.pc_name || ('PC#' + item.pc_id);
        tdName.appendChild(a);
        tr.appendChild(tdName);

        // IP
        const tdIp = document.createElement('td');
        tdIp.textContent = item.ip_address || '-';
        tr.appendChild(tdIp);

        // スコア
        const tdScore = document.createElement('td');
        tdScore.style.fontWeight = '600';
        tdScore.textContent = score.toFixed(1);
        tr.appendChild(tdScore);

        // 状態
        const tdStatus = document.createElement('td');
        tdStatus.appendChild(scoreBadge(score));
        tr.appendChild(tdStatus);

        // 減点要因
        const tdDeduct = document.createElement('td');
        tdDeduct.style.cssText = 'font-size:0.8rem;max-width:220px;';
        tdDeduct.textContent = fmtDeductions(item.deductions);
        tr.appendChild(tdDeduct);

        // 計算日時
        const tdCalc = document.createElement('td');
        tdCalc.textContent = fmtDate(item.calculated_at);
        tr.appendChild(tdCalc);

        // 操作
        const tdOp = document.createElement('td');
        const btn = document.createElement('a');
        btn.href = `/pcs/${item.pc_id}`;
        btn.className = 'btn btn-secondary';
        btn.style.cssText = 'padding:0.2rem 0.5rem;font-size:0.75rem;';
        btn.textContent = '詳細';
        tdOp.appendChild(btn);
        tr.appendChild(tdOp);

        tbody.appendChild(tr);
    }

    if (paginationEl) {
        paginationEl.textContent = '';
        const totalPages = Math.ceil(filtered.length / PER_PAGE);
        if (totalPages > 1) {
            for (let p = 1; p <= totalPages; p++) {
                const btn = document.createElement('button');
                btn.className = 'btn ' + (p === currentPage ? 'btn-primary' : 'btn-secondary');
                btn.style.cssText = 'margin:0.1rem;padding:0.2rem 0.6rem;';
                btn.textContent = String(p);
                btn.addEventListener('click', () => { currentPage = p; renderPage(); });
                paginationEl.appendChild(btn);
            }
        }
    }
}

function exportCsv() {
    const rows = [['PC名', 'IP', 'スコア', '状態', '計算日時']];
    for (const item of allItems) {
        const score = item.latest_score ?? item.score ?? 100;
        const st = SCORE_STATUS.find(s => score < s.max) || SCORE_STATUS[SCORE_STATUS.length - 1];
        rows.push([item.pc_name || '', item.ip_address || '', score.toFixed(1), st.label, item.calculated_at || '']);
    }
    const csv = rows.map(r => r.map(v => '"' + String(v).replace(/"/g, '""') + '"').join(',')).join('\n');
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'unstable_pcs.csv';
    a.click();
    URL.revokeObjectURL(url);
}

document.addEventListener('DOMContentLoaded', () => {
    loadUnstable();

    document.getElementById('threshold-filter')?.addEventListener('change', loadUnstable);
    document.getElementById('days-filter')?.addEventListener('change', loadUnstable);
    document.getElementById('pc-search')?.addEventListener('input', () => { currentPage = 1; renderPage(); });
    document.getElementById('btn-export-csv')?.addEventListener('click', exportCsv);
});
