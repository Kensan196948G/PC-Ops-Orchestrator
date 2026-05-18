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

function scoreBar(score) {
    const bar = document.createElement('div');
    bar.style.cssText = 'display:flex;align-items:center;gap:0.5rem;';
    const inner = document.createElement('div');
    inner.style.cssText = 'background:var(--border);border-radius:4px;height:8px;width:80px;overflow:hidden;';
    const fill = document.createElement('div');
    const pct = Math.max(0, Math.min(100, score));
    const color = score < 40 ? '#dc2626' : score < 60 ? '#f59e0b' : score < 80 ? '#3b82f6' : '#16a34a';
    fill.style.cssText = `width:${pct}%;height:100%;background:${color};`;
    inner.appendChild(fill);
    const num = document.createElement('span');
    num.style.cssText = 'font-size:0.85rem;font-weight:600;min-width:3ch;';
    num.textContent = pct.toFixed(1);
    bar.appendChild(inner);
    bar.appendChild(num);
    return bar;
}

function fmtDeductions(deductionsJson) {
    let list;
    try {
        list = typeof deductionsJson === 'string' ? JSON.parse(deductionsJson) : deductionsJson;
    } catch {
        return '-';
    }
    if (!Array.isArray(list) || list.length === 0) return '減点なし';
    return list.slice(0, 3).map(d => `${d.label || d.category || '?'} (${d.points?.toFixed(1) ?? 0})`).join(', ');
}

function fmtDate(str) {
    if (!str) return '-';
    return new Date(str).toLocaleString('ja-JP');
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

function clearBody(tbody) {
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
}

async function loadStats(days) {
    try {
        const data = await apiFetch(`/stability/scores?per_page=999&days=${days}`);
        const items = data.items || data || [];
        let critical = 0, unstable = 0, warning = 0, healthy = 0;
        for (const r of items) {
            const sc = r.latest_score ?? r.score ?? 100;
            if (sc < 40) critical++;
            else if (sc < 60) unstable++;
            else if (sc < 80) warning++;
            else healthy++;
        }
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        set('stat-total', items.length);
        set('stat-critical', critical);
        set('stat-unstable', unstable);
        set('stat-warning', warning);
        set('stat-healthy', healthy);
        return items;
    } catch (e) {
        console.error('loadStats error:', e);
        return [];
    }
}

function buildScoreRow(item) {
    const tr = document.createElement('tr');
    const score = item.latest_score ?? item.score ?? 100;

    // PC名 (link)
    const tdName = document.createElement('td');
    const a = document.createElement('a');
    a.href = `/pcs/${item.pc_id}`;
    a.textContent = item.pc_name || ('PC#' + item.pc_id);
    tdName.appendChild(a);
    tr.appendChild(tdName);

    // スコアバー
    const tdScore = document.createElement('td');
    tdScore.appendChild(scoreBar(score));
    tr.appendChild(tdScore);

    // 状態バッジ
    const tdStatus = document.createElement('td');
    tdStatus.appendChild(scoreBadge(score));
    tr.appendChild(tdStatus);

    // 減点要因
    const tdDeduct = document.createElement('td');
    tdDeduct.style.cssText = 'font-size:0.8rem;max-width:240px;';
    tdDeduct.textContent = fmtDeductions(item.deductions);
    tr.appendChild(tdDeduct);

    // 分析日数
    const tdDays = document.createElement('td');
    tdDays.textContent = item.analysis_days ?? '-';
    tr.appendChild(tdDays);

    // 計算日時
    const tdCalc = document.createElement('td');
    tdCalc.textContent = fmtDate(item.calculated_at);
    tr.appendChild(tdCalc);

    // 操作
    const tdOp = document.createElement('td');
    const btn = document.createElement('button');
    btn.className = 'btn btn-secondary role-operator-or-admin';
    btn.style.cssText = 'padding:0.2rem 0.5rem;font-size:0.75rem;';
    btn.textContent = '再計算';
    btn.addEventListener('click', () => recalculateOne(item.pc_id, item.pc_name));
    tdOp.appendChild(btn);
    tr.appendChild(tdOp);

    return tr;
}

async function loadScores(days) {
    const tbody = document.getElementById('scores-body');
    if (!tbody) return;
    clearBody(tbody);
    tbody.appendChild(emptyRow(7, '読み込み中...'));
    try {
        const data = await apiFetch(`/stability/scores?per_page=999&days=${days}`);
        const items = (data.items || data || []).sort((a, b) => {
            const sa = a.latest_score ?? a.score ?? 100;
            const sb = b.latest_score ?? b.score ?? 100;
            return sa - sb;
        });
        clearBody(tbody);
        if (items.length === 0) {
            tbody.appendChild(emptyRow(7, 'データなし'));
            return;
        }
        for (const item of items) tbody.appendChild(buildScoreRow(item));
    } catch (e) {
        clearBody(tbody);
        tbody.appendChild(emptyRow(7, '読み込み失敗'));
        console.error(e);
    }
}

async function loadRanking(days) {
    const tbody = document.getElementById('ranking-body');
    if (!tbody) return;
    clearBody(tbody);
    tbody.appendChild(emptyRow(5, '読み込み中...'));
    try {
        const data = await apiFetch(`/stability/event-ranking?days=${days}&limit=10`);
        const items = data.items || data || [];
        clearBody(tbody);
        if (items.length === 0) {
            tbody.appendChild(emptyRow(5, 'データなし'));
            return;
        }
        items.forEach((item, idx) => {
            const tr = document.createElement('tr');
            [String(idx + 1), String(item.event_id ?? '-'), item.category ?? '-',
             String(item.count ?? '-'), String(item.pc_count ?? '-')].forEach(text => {
                const td = document.createElement('td');
                td.textContent = text;
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
    } catch (e) {
        clearBody(tbody);
        tbody.appendChild(emptyRow(5, '読み込み失敗'));
        console.error(e);
    }
}

async function recalculateAll(days) {
    const btn = document.getElementById('btn-recalculate');
    if (btn) btn.disabled = true;
    try {
        await apiFetch(`/stability/calculate?days=${days}`, { method: 'POST' });
        await Promise.all([loadStats(days), loadScores(days), loadRanking(days)]);
    } catch (e) {
        console.error('recalculate error:', e);
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function recalculateOne(pcId, pcName) {
    const days = document.getElementById('days-filter')?.value || '30';
    try {
        await apiFetch(`/stability/calculate/${pcId}?days=${days}`, { method: 'POST' });
        await Promise.all([loadStats(days), loadScores(days)]);
    } catch (e) {
        console.error('recalculate ' + pcName + ' error:', e);
    }
}

function getDays() {
    return document.getElementById('days-filter')?.value || '30';
}

document.addEventListener('DOMContentLoaded', () => {
    const days = getDays();
    loadStats(days);
    loadScores(days);
    loadRanking(days);

    document.getElementById('days-filter')?.addEventListener('change', e => {
        const d = e.target.value;
        loadStats(d);
        loadScores(d);
        loadRanking(d);
    });

    document.getElementById('btn-recalculate')?.addEventListener('click', () => {
        recalculateAll(getDays());
    });
});
