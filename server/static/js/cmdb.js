'use strict';

const SOURCE_LABELS = {
    ledger: '台帳のみ',
    agent: 'エージェント',
    winrm: 'WinRM',
};
const SOURCE_BADGE = {
    ledger: 'severity-medium',
    agent: 'severity-low',
    winrm: 'severity-info',
};

let currentPage = 1;
let allTotal = 0;
const PER_PAGE = 50;

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

function sourceBadge(src) {
    const span = document.createElement('span');
    span.className = 'status-badge ' + (SOURCE_BADGE[src] || '');
    span.textContent = SOURCE_LABELS[src] || src || '-';
    return span;
}

async function loadCmdb(page) {
    currentPage = page || currentPage;
    const q = document.getElementById('cmdb-search')?.value?.trim() || '';
    const src = document.getElementById('cmdb-source-filter')?.value || '';
    const tbody = document.getElementById('cmdb-body');
    if (!tbody) return;
    clearBody(tbody);
    tbody.appendChild(emptyRow(10, '読み込み中...'));

    const params = new URLSearchParams({ page: currentPage, per_page: PER_PAGE });
    if (q) params.set('q', q);
    if (src) params.set('asset_source', src);

    try {
        const data = await apiFetch('/cmdb/list?' + params.toString());
        allTotal = data.total || 0;

        clearBody(tbody);
        if (!data.items || data.items.length === 0) {
            tbody.appendChild(emptyRow(10, 'データなし'));
            renderPaginationEl(0, 0);
            return;
        }

        for (const item of data.items) {
            const tr = document.createElement('tr');
            tr.classList.add('row-clickable');
            tr.addEventListener('click', () => openCmdbDrawer(item));

            const tdAsset = document.createElement('td');
            tdAsset.style.fontFamily = 'var(--font-mono)';
            tdAsset.textContent = item.asset_number || '-';
            tr.appendChild(tdAsset);

            const tdPc = document.createElement('td');
            if (item.pc_name && item.asset_source !== 'ledger') {
                const a = document.createElement('a');
                a.href = '/pcs/' + item.id;
                a.textContent = item.pc_name;
                a.addEventListener('click', e => e.stopPropagation());
                tdPc.appendChild(a);
            } else {
                tdPc.textContent = item.pc_name || '-';
            }
            tr.appendChild(tdPc);

            const tdOwner = document.createElement('td');
            tdOwner.textContent = item.owner_name || '-';
            tr.appendChild(tdOwner);

            const tdEmp = document.createElement('td');
            tdEmp.textContent = item.employee_id || '-';
            tr.appendChild(tdEmp);

            const tdYear = document.createElement('td');
            tdYear.textContent = item.deploy_year || '-';
            tr.appendChild(tdYear);

            const tdOs = document.createElement('td');
            tdOs.style.cssText = 'font-size:0.8rem;max-width:160px;';
            tdOs.textContent = item.os_version || '-';
            tr.appendChild(tdOs);

            const tdIp = document.createElement('td');
            tdIp.style.fontFamily = 'var(--font-mono)';
            tdIp.textContent = item.ip_lan || item.ip_address || '-';
            tr.appendChild(tdIp);

            const tdSrc = document.createElement('td');
            tdSrc.appendChild(sourceBadge(item.asset_source));
            tr.appendChild(tdSrc);

            const tdSeen = document.createElement('td');
            tdSeen.style.fontSize = '0.8rem';
            tdSeen.textContent = fmtDate(item.last_seen);
            tr.appendChild(tdSeen);

            // Chevron
            const tdChev = document.createElement('td');
            tdChev.className = 'row-chevron';
            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.setAttribute('width', '14');
            svg.setAttribute('height', '14');
            svg.setAttribute('viewBox', '0 0 24 24');
            svg.setAttribute('fill', 'none');
            svg.setAttribute('stroke', 'currentColor');
            svg.setAttribute('stroke-width', '2.5');
            svg.setAttribute('stroke-linecap', 'round');
            svg.setAttribute('stroke-linejoin', 'round');
            const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
            poly.setAttribute('points', '9 18 15 12 9 6');
            svg.appendChild(poly);
            tdChev.appendChild(svg);
            tr.appendChild(tdChev);

            tbody.appendChild(tr);
        }

        renderPaginationEl(data.page, data.pages);
    } catch (e) {
        clearBody(tbody);
        tbody.appendChild(emptyRow(10, '読み込み失敗'));
        console.error(e);
    }
}

function renderPaginationEl(current, total) {
    const paginationEl = document.getElementById('cmdb-pagination');
    if (!paginationEl) return;
    paginationEl.textContent = '';
    if (total <= 1) return;
    for (let p = 1; p <= total; p++) {
        const btn = document.createElement('button');
        btn.className = 'btn ' + (p === current ? 'btn-primary' : 'btn-secondary');
        btn.style.cssText = 'margin:0.1rem;padding:0.2rem 0.6rem;';
        btn.textContent = String(p);
        btn.addEventListener('click', () => { currentPage = p; loadCmdb(p); });
        paginationEl.appendChild(btn);
    }
}

async function loadStats() {
    try {
        const data = await apiFetch('/cmdb/status');
        const sources = data.sources || {};
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        set('cmdb-stat-total', data.ledger_pc_count ?? '-');
        set('cmdb-stat-ledger', sources.ledger ?? 0);
        set('cmdb-stat-agent', sources.agent ?? 0);
        set('cmdb-stat-winrm', sources.winrm ?? 0);
    } catch (e) {
        console.error('CMDB stats load failed:', e);
    }
}

// ── Drawer ──────────────────────────────────────────────────────────────────

function openCmdbDrawer(item) {
    const overlay = document.getElementById('cmdb-drawer-overlay');
    const titleEl = document.getElementById('cmdb-drawer-title');
    const bodyEl = document.getElementById('cmdb-drawer-body');
    const pcLink = document.getElementById('cmdb-drawer-pc-link');
    if (!overlay || !bodyEl) return;

    if (titleEl) {
        const badge = sourceBadge(item.asset_source);
        titleEl.textContent = '';
        titleEl.appendChild(badge);
        titleEl.appendChild(document.createTextNode(' ' + (item.asset_number || item.pc_name || '-')));
    }

    if (pcLink) {
        if (item.id && item.asset_source !== 'ledger') {
            pcLink.href = '/pcs/' + item.id;
            pcLink.classList.remove('hidden');
        } else {
            pcLink.classList.add('hidden');
        }
    }

    bodyEl.textContent = '';

    const basicSection = document.createElement('div');
    const basicHead = document.createElement('div');
    basicHead.className = 'drawer-section-title';
    basicHead.textContent = '資産情報';
    basicSection.appendChild(basicHead);

    const dl = document.createElement('dl');
    dl.className = 'kv-grid';
    const pairs = [
        ['管理番号', item.asset_number || '-'],
        ['PC名', item.pc_name || '-'],
        ['貸与者', item.owner_name || '-'],
        ['社員番号', item.employee_id || '-'],
        ['導入年', item.deploy_year ? String(item.deploy_year) + ' 年' : '-'],
        ['OS', item.os_version || '-'],
        ['収集元', SOURCE_LABELS[item.asset_source] || item.asset_source || '-'],
        ['最終確認', fmtDate(item.last_seen)],
        ['台帳同期', fmtDate(item.ledger_synced_at)],
    ];
    for (const [k, v] of pairs) {
        const dt = document.createElement('dt'); dt.textContent = k; dl.appendChild(dt);
        const dd = document.createElement('dd'); dd.textContent = v; dl.appendChild(dd);
    }
    basicSection.appendChild(dl);
    bodyEl.appendChild(basicSection);

    // Network info
    const netSection = document.createElement('div');
    const netHead = document.createElement('div');
    netHead.className = 'drawer-section-title';
    netHead.textContent = 'ネットワーク情報';
    netSection.appendChild(netHead);

    const dl2 = document.createElement('dl');
    dl2.className = 'kv-grid';
    const netPairs = [
        ['IP (LAN)', item.ip_lan || item.ip_address || '-'],
        ['IP (WiFi)', item.ip_wifi || '-'],
        ['MAC (有線)', item.mac_wired || '-'],
        ['MAC (無線)', item.mac_wireless || '-'],
    ];
    for (const [k, v] of netPairs) {
        const dt = document.createElement('dt'); dt.textContent = k; dl2.appendChild(dt);
        const dd = document.createElement('dd');
        dd.textContent = v;
        dd.style.fontFamily = v !== '-' ? 'var(--font-mono)' : '';
        dl2.appendChild(dd);
    }
    netSection.appendChild(dl2);
    bodyEl.appendChild(netSection);

    // AD info
    if (item.ad_cn || item.ad_sam) {
        const adSection = document.createElement('div');
        const adHead = document.createElement('div');
        adHead.className = 'drawer-section-title';
        adHead.textContent = 'Active Directory';
        adSection.appendChild(adHead);

        const dl3 = document.createElement('dl');
        dl3.className = 'kv-grid';
        const adPairs = [
            ['CN', item.ad_cn || '-'],
            ['SAM', item.ad_sam || '-'],
        ];
        for (const [k, v] of adPairs) {
            const dt = document.createElement('dt'); dt.textContent = k; dl3.appendChild(dt);
            const dd = document.createElement('dd'); dd.textContent = v; dl3.appendChild(dd);
        }
        adSection.appendChild(dl3);
        bodyEl.appendChild(adSection);
    }

    overlay.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

function closeCmdbDrawer() {
    const overlay = document.getElementById('cmdb-drawer-overlay');
    if (overlay) overlay.classList.add('hidden');
    document.body.style.overflow = '';
}

// ── CSV Import ──────────────────────────────────────────────────────────────

async function importCsv(file) {
    const formData = new FormData();
    formData.append('file', file);
    try {
        const res = await fetch('/api/cmdb/import', {
            method: 'POST',
            headers: { Authorization: 'Bearer ' + (localStorage.getItem('token') || '') },
            body: formData,
        });
        const data = await res.json();
        if (!res.ok) {
            showError('インポート失敗: ' + (data.error || res.status));
            return;
        }
        showSuccess(`インポート完了: 新規 ${data.created ?? 0} / 更新 ${data.updated ?? 0} / スキップ ${data.skipped ?? 0}`);
        loadCmdb(1);
        loadStats();
    } catch (e) {
        showError('インポートに失敗しました');
        console.error(e);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadCmdb(1);
    loadStats();

    let searchTimer;
    document.getElementById('cmdb-search')?.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => { currentPage = 1; loadCmdb(1); }, 400);
    });
    document.getElementById('cmdb-source-filter')?.addEventListener('change', () => {
        currentPage = 1;
        loadCmdb(1);
    });
    document.getElementById('btn-reload-cmdb')?.addEventListener('click', () => {
        loadCmdb(currentPage);
        loadStats();
    });
    document.getElementById('cmdb-csv-upload')?.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) importCsv(file);
        e.target.value = '';
    });

    document.getElementById('btn-close-cmdb-drawer')?.addEventListener('click', closeCmdbDrawer);
    document.getElementById('btn-close-cmdb-drawer-footer')?.addEventListener('click', closeCmdbDrawer);
    document.getElementById('cmdb-drawer-overlay')?.addEventListener('click', e => {
        if (e.target === e.currentTarget) closeCmdbDrawer();
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeCmdbDrawer(); });
});
