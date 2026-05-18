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

function fmtDate(str) {
    if (!str) return '-';
    return new Date(str).toLocaleString('ja-JP');
}

function riskBadge(changeRatio) {
    const span = document.createElement('span');
    span.className = 'status-badge';
    if (changeRatio >= 2.0) {
        span.classList.add('severity-critical');
        span.textContent = '高リスク';
    } else if (changeRatio >= 1.5) {
        span.classList.add('severity-high');
        span.textContent = '中リスク';
    } else if (changeRatio >= 1.0) {
        span.classList.add('severity-medium');
        span.textContent = '低リスク';
    } else {
        span.classList.add('severity-low');
        span.textContent = '影響軽微';
    }
    return span;
}

function fmtChangeRatio(ratio) {
    if (ratio === null || ratio === undefined) return '-';
    const pct = ((ratio - 1) * 100).toFixed(1);
    return (ratio >= 1 ? '+' : '') + pct + '%';
}

let allItems = [];

async function loadKbImpact() {
    const days = document.getElementById('days-filter')?.value || '30';
    const tbody = document.getElementById('kb-body');
    if (!tbody) return;
    clearBody(tbody);
    tbody.appendChild(emptyRow(8, '読み込み中...'));
    try {
        const data = await apiFetch(`/stability/kb-impact?days=${days}`);
        allItems = data.items || data || [];
        renderTable();
    } catch (e) {
        clearBody(tbody);
        tbody.appendChild(emptyRow(8, '読み込み失敗'));
        console.error(e);
    }
}

function renderTable() {
    const tbody = document.getElementById('kb-body');
    if (!tbody) return;
    const search = document.getElementById('kb-search')?.value?.toLowerCase() || '';
    const filtered = allItems.filter(it =>
        !search || (it.kb_id || '').toLowerCase().includes(search)
    );

    clearBody(tbody);
    if (filtered.length === 0) {
        tbody.appendChild(emptyRow(8, 'データなし'));
        return;
    }

    filtered.forEach((item, idx) => {
        const tr = document.createElement('tr');

        // 順位
        const tdRank = document.createElement('td');
        tdRank.textContent = String(idx + 1);
        tr.appendChild(tdRank);

        // KB番号
        const tdKb = document.createElement('td');
        const a = document.createElement('a');
        a.href = '#';
        a.textContent = item.kb_id || '-';
        a.addEventListener('click', e => {
            e.preventDefault();
            loadKbDetail(item.kb_id);
        });
        tdKb.appendChild(a);
        tr.appendChild(tdKb);

        // タイトル
        const tdTitle = document.createElement('td');
        tdTitle.style.cssText = 'font-size:0.85rem;max-width:280px;';
        tdTitle.textContent = item.title || '-';
        tr.appendChild(tdTitle);

        // 影響PC数
        const tdPc = document.createElement('td');
        tdPc.textContent = String(item.pc_count ?? '-');
        tr.appendChild(tdPc);

        // インストール前エラー
        const tdBefore = document.createElement('td');
        tdBefore.textContent = (item.before_avg ?? 0).toFixed(2);
        tr.appendChild(tdBefore);

        // インストール後エラー
        const tdAfter = document.createElement('td');
        tdAfter.textContent = (item.after_avg ?? 0).toFixed(2);
        tr.appendChild(tdAfter);

        // 変化率
        const tdRatio = document.createElement('td');
        tdRatio.style.fontWeight = '600';
        const ratio = item.change_ratio ?? 1.0;
        tdRatio.textContent = fmtChangeRatio(ratio);
        tdRatio.style.color = ratio >= 1.5 ? '#dc2626' : ratio >= 1.0 ? '#f59e0b' : '#16a34a';
        tr.appendChild(tdRatio);

        // リスク
        const tdRisk = document.createElement('td');
        tdRisk.appendChild(riskBadge(ratio));
        tr.appendChild(tdRisk);

        tbody.appendChild(tr);
    });
}

async function loadKbDetail(kbId) {
    const panel = document.getElementById('kb-detail-panel');
    const title = document.getElementById('kb-detail-title');
    const tbody = document.getElementById('kb-detail-body');
    if (!panel || !tbody) return;

    panel.classList.remove('hidden');
    if (title) title.textContent = `KB 詳細: ${kbId}`;
    clearBody(tbody);
    tbody.appendChild(emptyRow(5, '読み込み中...'));

    try {
        const days = document.getElementById('days-filter')?.value || '30';
        const data = await apiFetch(`/stability/kb-impact/${kbId}?days=${days}`);
        const items = data.items || data.pcs || data || [];
        clearBody(tbody);
        if (items.length === 0) {
            tbody.appendChild(emptyRow(5, 'PCデータなし'));
            return;
        }
        for (const pc of items) {
            const tr = document.createElement('tr');

            const tdName = document.createElement('td');
            const a = document.createElement('a');
            a.href = `/pcs/${pc.pc_id}`;
            a.textContent = pc.pc_name || ('PC#' + pc.pc_id);
            tdName.appendChild(a);
            tr.appendChild(tdName);

            const tdInst = document.createElement('td');
            tdInst.textContent = fmtDate(pc.installed_at);
            tr.appendChild(tdInst);

            const tdB = document.createElement('td');
            tdB.textContent = String(pc.before_count ?? '-');
            tr.appendChild(tdB);

            const tdA = document.createElement('td');
            tdA.textContent = String(pc.after_count ?? '-');
            tr.appendChild(tdA);

            const tdDelta = document.createElement('td');
            const delta = (pc.after_count ?? 0) - (pc.before_count ?? 0);
            tdDelta.textContent = (delta >= 0 ? '+' : '') + delta;
            tdDelta.style.fontWeight = '600';
            tdDelta.style.color = delta > 0 ? '#dc2626' : delta < 0 ? '#16a34a' : 'inherit';
            tr.appendChild(tdDelta);

            tbody.appendChild(tr);
        }
    } catch (e) {
        clearBody(tbody);
        tbody.appendChild(emptyRow(5, '読み込み失敗'));
        console.error(e);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadKbImpact();

    document.getElementById('days-filter')?.addEventListener('change', loadKbImpact);
    document.getElementById('kb-search')?.addEventListener('input', renderTable);
    document.getElementById('btn-close-detail')?.addEventListener('click', () => {
        document.getElementById('kb-detail-panel')?.classList.add('hidden');
    });
});
