let historyChart = null;
let _snapshotsCache = [];
let _historyRendered = false;

const STATUS_MAP = {
    healthy:   ['status-healthy',   '正常'],
    warning:   ['status-warning',   '要注意'],
    critical:  ['status-critical',  '危険'],
    unknown:   ['status-unknown',   '不明'],
    pending:   ['status-pending',   '未処理'],
    running:   ['status-running',   '実行中'],
    completed: ['status-completed', '完了'],
    failed:    ['status-failed',    '失敗'],
};

const SEVERITY_MAP = {
    Critical:  ['status-critical', 'Critical'],
    Important: ['status-warning',  'Important'],
    Moderate:  ['status-pending',  'Moderate'],
    Low:       ['status-unknown',  'Low'],
};

const CONNECTION_MAP = {
    online:   ['status-healthy',  'オンライン'],
    offline:  ['status-critical', 'オフライン'],
    vpn:      ['status-pending',  'VPN'],
    unknown:  ['status-unknown',  '不明'],
};

function makeBadge(cls, label) {
    const span = document.createElement('span');
    span.className = 'status-badge ' + cls;
    span.textContent = label;
    return span;
}

function statusBadgeNode(status) {
    const entry = STATUS_MAP[status];
    if (entry) return makeBadge(entry[0], entry[1]);
    return makeBadge('status-unknown', status || '-');
}

function severityBadgeNode(severity) {
    if (!severity) return document.createTextNode('-');
    const entry = SEVERITY_MAP[severity];
    if (entry) return makeBadge(entry[0], entry[1]);
    return document.createTextNode(severity);
}

function installedBadgeNode(installed) {
    return installed
        ? makeBadge('status-completed', 'インストール済')
        : makeBadge('status-pending',   '未インストール');
}

function connectionBadgeNode(type) {
    const entry = CONNECTION_MAP[type] || CONNECTION_MAP.unknown;
    return makeBadge(entry[0], entry[1]);
}

function makeSubStateChip(cls, label, title) {
    const span = document.createElement('span');
    span.className = 'badge ' + cls + ' ml-xs';
    if (title) span.title = title;
    span.textContent = label;
    return span;
}

function subStatesNode(pc) {
    const states = Array.isArray(pc && pc.sub_states) ? pc.sub_states : [];
    if (states.length === 0) return document.createTextNode('—');
    const frag = document.createDocumentFragment();
    if (states.includes('vpn_required')) {
        frag.appendChild(makeSubStateChip('badge-info', '🔒 VPN', 'SSL-VPN 経由で接続中'));
    }
    if (states.includes('pending_sync')) {
        const cnt = pc.offline_pending_count ?? 0;
        frag.appendChild(makeSubStateChip('badge-warning', `📦 同期待ち ${cnt}`, 'オフラインキャッシュ件数'));
    }
    if (states.includes('pending_job')) {
        const cnt = pc.pending_job_count ?? 0;
        frag.appendChild(makeSubStateChip('badge-primary', `🔧 ジョブ待ち ${cnt}`, 'サーバ側で実行待ちのジョブ件数'));
    }
    return frag;
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value == null || value === '' ? '-' : value;
}

function setNode(id, node) {
    const el = document.getElementById(id);
    if (el) el.replaceChildren(node);
}

function fmtGB(v) {
    return (v == null) ? '-' : v.toFixed(1) + ' GB';
}

function fmtDateTime(v) {
    if (!v) return '-';
    return new Date(v).toLocaleString('ja-JP');
}

function fmtDate(v) {
    if (!v) return '-';
    return new Date(v).toLocaleDateString('ja-JP');
}

function makeCell(value) {
    const td = document.createElement('td');
    td.textContent = (value == null || value === '') ? '-' : value;
    return td;
}

function makeCellNode(node) {
    const td = document.createElement('td');
    td.appendChild(node);
    return td;
}

function makeMessageRow(msg, cols, color) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = cols;
    td.className = 'text-center';
    if (color) td.style.color = color;
    td.textContent = msg;
    tr.appendChild(td);
    return tr;
}

function activateTab(name) {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        const active = btn.dataset.tab === name;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    document.querySelectorAll('.tab-panel').forEach(panel => {
        panel.classList.toggle('hidden', panel.id !== 'tab-' + name);
    });
    if (history && history.replaceState) {
        history.replaceState(null, '', '#' + name);
    }
    if (name === 'history' && !_historyRendered && _snapshotsCache.length > 0) {
        renderHistoryChart(_snapshotsCache);
        _historyRendered = true;
    }
}

function renderPCInfo(pc) {
    document.getElementById('pc-name').textContent = 'PC: ' + (pc.pc_name || '-');
    setText('d-pc-name', pc.pc_name);
    setText('d-domain', pc.domain);
    setText('d-os', pc.os_version);
    setText('d-os-build', pc.os_build);
    setText('d-arch', pc.os_architecture);
    setText('d-ip', pc.ip_address);
    setText('d-mac', pc.mac_address);
    setNode('d-status', statusBadgeNode(pc.status));
    setText('d-score', pc.health_score);
    setNode('d-connection', connectionBadgeNode(pc.connection_type || 'unknown'));
    setNode('d-sub-states', subStatesNode(pc));
    setText('d-last-seen', fmtDateTime(pc.last_seen));
    setText('d-agent-ver', pc.agent_version);

    setText('d-cpu', pc.cpu_name);
    setText('d-cores', pc.cpu_cores);
    setText('d-logical', pc.cpu_logical_processors);
    setText('d-mem-total', fmtGB(pc.memory_total_gb));
    setText('d-mem-free', fmtGB(pc.memory_available_gb));
    setText('d-disk-total', fmtGB(pc.disk_total_gb));
    setText('d-disk-free', fmtGB(pc.disk_free_gb));
}

function renderRecentTasks(tasks) {
    const tbody = document.getElementById('recent-tasks-body');
    if (!tbody) return;
    if (!tasks || tasks.length === 0) {
        tbody.replaceChildren(makeMessageRow('タスク履歴はありません', 5));
        return;
    }
    const frag = document.createDocumentFragment();
    tasks.forEach(t => {
        const tr = document.createElement('tr');
        tr.appendChild(makeCell('#' + t.id));
        tr.appendChild(makeCell(t.task_type));
        tr.appendChild(makeCellNode(statusBadgeNode(t.status)));
        tr.appendChild(makeCell(fmtDateTime(t.created_at)));
        const resultText = t.result
            ? (t.result.length > 50 ? t.result.substring(0, 50) + '...' : t.result)
            : (t.error_message || '-');
        tr.appendChild(makeCell(resultText));
        frag.appendChild(tr);
    });
    tbody.replaceChildren(frag);
}

function renderSoftware(list) {
    const tbody = document.getElementById('software-body');
    if (!tbody) return;
    const total = list ? list.length : 0;
    const title = document.getElementById('software-title');
    if (title) title.textContent = 'インストール済みソフトウェア (' + total + '件)';
    const counter = document.getElementById('cnt-software');
    if (counter) counter.textContent = total;
    if (total === 0) {
        tbody.replaceChildren(makeMessageRow('ソフトウェア情報がありません', 4));
        return;
    }
    const frag = document.createDocumentFragment();
    list.forEach(sw => {
        const tr = document.createElement('tr');
        tr.appendChild(makeCell(sw.name));
        tr.appendChild(makeCell(sw.version));
        tr.appendChild(makeCell(sw.publisher));
        tr.appendChild(makeCell(fmtDate(sw.install_date)));
        frag.appendChild(tr);
    });
    tbody.replaceChildren(frag);
}

function renderUpdates(list) {
    const tbody = document.getElementById('updates-body');
    if (!tbody) return;
    const total = list ? list.length : 0;
    const title = document.getElementById('updates-title');
    if (title) title.textContent = 'Windows Update 一覧 (' + total + '件)';
    const counter = document.getElementById('cnt-updates');
    if (counter) counter.textContent = total;
    if (total === 0) {
        tbody.replaceChildren(makeMessageRow('Windows Update 情報がありません', 5));
        return;
    }
    const frag = document.createDocumentFragment();
    list.forEach(u => {
        const tr = document.createElement('tr');
        tr.appendChild(makeCell(u.kb_id));
        tr.appendChild(makeCell(u.title));
        tr.appendChild(makeCellNode(severityBadgeNode(u.severity)));
        tr.appendChild(makeCellNode(installedBadgeNode(u.installed)));
        tr.appendChild(makeCell(fmtDateTime(u.installed_at)));
        frag.appendChild(tr);
    });
    tbody.replaceChildren(frag);
}

function renderNetwork(list) {
    const tbody = document.getElementById('network-body');
    if (!tbody) return;
    const total = list ? list.length : 0;
    const title = document.getElementById('network-title');
    if (title) title.textContent = 'ネットワークインターフェース (' + total + '件)';
    const counter = document.getElementById('cnt-network');
    if (counter) counter.textContent = total;
    if (total === 0) {
        tbody.replaceChildren(makeMessageRow('ネットワーク情報がありません', 8));
        return;
    }
    const frag = document.createDocumentFragment();
    list.forEach(n => {
        const tr = document.createElement('tr');
        tr.appendChild(makeCell(n.interface_name));
        tr.appendChild(makeCell(n.ip_address));
        tr.appendChild(makeCell(n.subnet_mask));
        tr.appendChild(makeCell(n.gateway));
        tr.appendChild(makeCell(n.mac_address));
        tr.appendChild(makeCell(n.dns_servers));
        tr.appendChild(makeCell(n.link_speed_mbps != null ? n.link_speed_mbps + ' Mbps' : '-'));
        tr.appendChild(makeCellNode(
            n.is_active
                ? makeBadge('status-healthy',  '有効')
                : makeBadge('status-critical', '無効')
        ));
        frag.appendChild(tr);
    });
    tbody.replaceChildren(frag);
}

function renderHistoryChart(snapshots) {
    const canvas = document.getElementById('historyChart');
    if (!canvas || typeof Chart === 'undefined') return;

    const labels = snapshots.map(s => fmtDateTime(s.collected_at));
    const cpuData = snapshots.map(s => s.cpu_usage ?? null);
    const memAvail = snapshots.map(s => s.memory_available_gb ?? null);
    const diskFree = snapshots.map(s => s.disk_free_gb ?? null);

    if (historyChart) historyChart.destroy();

    const datasets = [];
    if (cpuData.some(v => v !== null)) {
        datasets.push({
            label: 'CPU使用率 (%)',
            data: cpuData,
            borderColor: '#ff6b6b',
            backgroundColor: 'rgba(255,107,107,0.08)',
            fill: true,
            tension: 0.3,
            pointRadius: 2,
            yAxisID: 'yPercent',
        });
    }
    if (memAvail.some(v => v !== null)) {
        datasets.push({
            label: 'メモリ空き (GB)',
            data: memAvail,
            borderColor: '#4f8cff',
            backgroundColor: 'rgba(79,140,255,0.08)',
            fill: true,
            tension: 0.3,
            pointRadius: 2,
            yAxisID: 'yGB',
        });
    }
    if (diskFree.some(v => v !== null)) {
        datasets.push({
            label: 'ディスク空き (GB)',
            data: diskFree,
            borderColor: '#2ed573',
            backgroundColor: 'rgba(46,213,115,0.08)',
            fill: true,
            tension: 0.3,
            pointRadius: 2,
            yAxisID: 'yGB',
        });
    }

    if (datasets.length === 0) return;

    historyChart = new Chart(canvas, {
        type: 'line',
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            plugins: {
                legend: {
                    position: 'top',
                    labels: { color: '#8b8fa3', font: { size: 11 } }
                }
            },
            scales: {
                x: {
                    ticks: { color: '#8b8fa3', maxTicksLimit: 10, font: { size: 10 } },
                    grid: { color: '#2d3248' }
                },
                yPercent: {
                    beginAtZero: true,
                    max: 100,
                    title: { display: true, text: '%', color: '#8b8fa3', font: { size: 10 } },
                    ticks: { color: '#ff6b6b', font: { size: 10 } },
                    grid: { color: '#2d3248' }
                },
                yGB: {
                    position: 'right',
                    beginAtZero: true,
                    title: { display: true, text: 'GB', color: '#8b8fa3', font: { size: 10 } },
                    ticks: { color: '#8b8fa3', font: { size: 10 } },
                    grid: { display: false }
                }
            }
        }
    });
}

async function loadPCDetails() {
    try {
        const data = await apiFetch('/pcs/' + PC_ID + '/details');
        renderPCInfo(data.pc || {});
        renderSoftware(data.software || []);
        renderUpdates(data.windows_updates || []);
        renderNetwork(data.network_interfaces || []);
        renderRecentTasks(data.recent_tasks || []);
        _snapshotsCache = data.snapshots || [];
        // Reset chart cache so the next history-tab activation re-renders
        // with the freshest snapshots from the consolidated endpoint.
        _historyRendered = false;
        const activeHistory = document.querySelector('.tab-btn.active');
        if (activeHistory && activeHistory.dataset.tab === 'history' && _snapshotsCache.length > 0) {
            renderHistoryChart(_snapshotsCache);
            _historyRendered = true;
        }
    } catch (e) {
        if (typeof showError === 'function') showError('PC情報の取得に失敗しました');
    }
}

async function executeTask() {
    const type = document.getElementById('task-type-select').value;
    const cmdEl = document.getElementById('task-command');
    const command = cmdEl ? cmdEl.value.trim() : '';
    const params = {};

    if (type === 'custom' && !command) {
        showError('カスタムタスクのコマンドを入力してください');
        return;
    }
    if (type === 'custom') {
        params.command = command;
    }

    try {
        const res = await apiFetch('/tasks', {
            method: 'POST',
            body: JSON.stringify({
                task_type: type,
                pc_name: document.getElementById('d-pc-name').textContent,
                parameters: params,
                priority: 1,
            }),
        });

        if (res && res.task) {
            showSuccess('タスクを作成しました (ID: ' + res.task.id + ')');
            loadPCDetails();
        } else {
            showError((res && res.error) || 'タスク作成に失敗しました');
        }
    } catch (e) {
        showError('APIエラー');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => activateTab(btn.dataset.tab));
    });

    const typeSelect = document.getElementById('task-type-select');
    if (typeSelect) {
        typeSelect.addEventListener('change', () => {
            const cmdInput = document.getElementById('task-command');
            if (!cmdInput) return;
            if (typeSelect.value === 'custom') {
                cmdInput.classList.remove('hidden');
            } else {
                cmdInput.classList.add('hidden');
            }
        });
    }

    const executeBtn = document.getElementById('btn-execute-task');
    if (executeBtn) executeBtn.addEventListener('click', executeTask);

    const initial = (window.location.hash || '').replace(/^#/, '');
    if (initial && document.querySelector('.tab-btn[data-tab="' + CSS.escape(initial) + '"]')) {
        activateTab(initial);
    }

    loadPCDetails();
    setInterval(loadPCDetails, 30000);
});
