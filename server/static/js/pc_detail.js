let historyChart = null;

async function loadPCDetail() {
    try {
        const data = await apiFetch('/pcs/' + PC_ID);
        const pc = data.pc;

        document.getElementById('pc-name').textContent = pc.pc_name;
        document.getElementById('d-pc-name').textContent = pc.pc_name;
        document.getElementById('d-domain').textContent = pc.domain || '-';
        document.getElementById('d-os').textContent = pc.os_version || '-';
        document.getElementById('d-arch').textContent = pc.os_architecture || '-';
        document.getElementById('d-ip').textContent = pc.ip_address || '-';
        document.getElementById('d-mac').textContent = pc.mac_address || '-';
        document.getElementById('d-status').innerHTML = statusBadge(pc.status);
        document.getElementById('d-score').textContent = pc.health_score ?? '-';
        document.getElementById('d-last-seen').textContent = pc.last_seen ? new Date(pc.last_seen).toLocaleString('ja-JP') : '-';
        document.getElementById('d-agent-ver').textContent = pc.agent_version || '-';

        document.getElementById('d-cpu').textContent = pc.cpu_name || '-';
        document.getElementById('d-cores').textContent = pc.cpu_cores ?? '-';
        document.getElementById('d-logical').textContent = pc.cpu_logical_processors ?? '-';
        document.getElementById('d-mem-total').textContent = pc.memory_total_gb ? pc.memory_total_gb.toFixed(1) + ' GB' : '-';
        document.getElementById('d-mem-free').textContent = pc.memory_available_gb ? pc.memory_available_gb.toFixed(1) + ' GB' : '-';
        document.getElementById('d-disk-total').textContent = pc.disk_total_gb ? pc.disk_total_gb.toFixed(1) + ' GB' : '-';
        document.getElementById('d-disk-free').textContent = pc.disk_free_gb ? pc.disk_free_gb.toFixed(1) + ' GB' : '-';

        if (data.snapshots && data.snapshots.length > 0) {
            renderHistoryChart(data.snapshots);
        }

        if (data.recent_tasks) {
            const tbody = document.getElementById('recent-tasks-body');
            if (data.recent_tasks.length > 0) {
                // escapeHTML wraps every API-returned scalar to neutralize XSS
                // payloads in task_type / status / result / error_message.
                tbody.innerHTML = data.recent_tasks.map(t => `
                    <tr>
                        <td>#${escapeHTML(t.id)}</td>
                        <td>${escapeHTML(t.task_type)}</td>
                        <td><span class="status-badge status-${escapeHTML(t.status)}">${escapeHTML(t.status)}</span></td>
                        <td>${escapeHTML(t.created_at ? new Date(t.created_at).toLocaleString('ja-JP') : '-')}</td>
                        <td>${escapeHTML(t.result ? t.result.substring(0, 50) : t.error_message || '-')}</td>
                    </tr>
                `).join('');
            } else {
                tbody.innerHTML = '<tr><td colspan="5" class="text-center">タスク履歴はありません</td></tr>';
            }
        }
    } catch (e) {
        showError('PC情報の取得に失敗しました');
    }
}

function renderHistoryChart(snapshots) {
    const labels = snapshots.map(s => s.collected_at ? new Date(s.collected_at).toLocaleString('ja-JP') : '');
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

    historyChart = new Chart(document.getElementById('historyChart'), {
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

function statusBadge(status) {
    const map = {
        'healthy': '<span class="status-badge status-healthy">正常</span>',
        'warning': '<span class="status-badge status-warning">要注意</span>',
        'critical': '<span class="status-badge status-critical">危険</span>',
        'unknown': '<span class="status-badge status-unknown">不明</span>',
        'pending': '<span class="status-badge status-pending">未処理</span>',
        'running': '<span class="status-badge status-running">実行中</span>',
        'completed': '<span class="status-badge status-completed">完了</span>',
        'failed': '<span class="status-badge status-failed">失敗</span>',
    };
    return map[status] || status;
}

async function executeTask() {
    const type = document.getElementById('task-type-select').value;
    const command = document.getElementById('task-command').value.trim();
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

        if (res.task) {
            showSuccess('タスクを作成しました (ID: ' + res.task.id + ')');
            loadPCDetail();
        } else {
            showError(res.error || 'タスク作成に失敗しました');
        }
    } catch (e) {
        showError('APIエラー');
    }
}

document.getElementById('task-type-select').addEventListener('change', function() {
    const cmdInput = document.getElementById('task-command');
    cmdInput.style.display = this.value === 'custom' ? 'inline-block' : 'none';
});

const _severityBadge = {
    'Critical':  '<span class="status-badge status-critical">Critical</span>',
    'Important': '<span class="status-badge status-warning">Important</span>',
    'Moderate':  '<span class="status-badge status-pending">Moderate</span>',
    'Low':       '<span class="status-badge status-unknown">Low</span>',
};

function _upRow(cells, htmlCells) {
    const tr = document.createElement('tr');
    cells.forEach((text, i) => {
        const td = document.createElement('td');
        if (htmlCells && htmlCells[i] !== undefined) {
            td.innerHTML = htmlCells[i];
        } else {
            td.textContent = text;
        }
        tr.appendChild(td);
    });
    return tr;
}

function _swRow(cells) {
    const tr = document.createElement('tr');
    cells.forEach(text => {
        const td = document.createElement('td');
        td.textContent = text;
        tr.appendChild(td);
    });
    return tr;
}

function _upMessageRow(msg, cols) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = cols;
    td.className = 'text-center';
    td.textContent = msg;
    tr.appendChild(td);
    return tr;
}

function _swMessageRow(msg, cols, color) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = cols;
    td.className = 'text-center';
    if (color) td.style.color = color;
    td.textContent = msg;
    tr.appendChild(td);
    return tr;
}

async function loadUpdates() {
    const tbody = document.getElementById('updates-body');
    try {
        const data = await apiFetch('/pcs/' + PC_ID + '/updates');
        const list = data.updates || [];
        document.getElementById('updates-title').textContent =
            'Windows Update 一覧 (' + (data.total || 0) + '件)';
        if (list.length === 0) {
            tbody.replaceChildren(_upMessageRow('Windows Update 情報がありません', 5));
            return;
        }
        const fragment = document.createDocumentFragment();
        list.forEach(u => {
            const severityHtml = _severityBadge[u.severity] || (u.severity ? u.severity : '-');
            const installedHtml = u.installed
                ? '<span class="status-badge status-completed">インストール済</span>'
                : '<span class="status-badge status-pending">未インストール</span>';
            fragment.appendChild(_upRow(
                [u.kb_id || '-', u.title || '-', '', '', u.installed_at ? new Date(u.installed_at).toLocaleString('ja-JP') : '-'],
                { 2: severityHtml, 3: installedHtml }
            ));
        });
        tbody.replaceChildren(fragment);
    } catch (e) {
        tbody.replaceChildren(_upMessageRow('読み込みに失敗しました', 5));
    }
}

async function loadSoftware() {
    const tbody = document.getElementById('software-body');
    try {
        const data = await apiFetch('/pcs/' + PC_ID + '/software');
        const list = data.software || [];
        document.getElementById('software-title').textContent =
            'インストール済みソフトウェア (' + (data.total || 0) + '件)';
        if (list.length === 0) {
            tbody.replaceChildren(_swMessageRow('ソフトウェア情報がありません', 4, null));
            return;
        }
        const fragment = document.createDocumentFragment();
        list.forEach(sw => {
            fragment.appendChild(_swRow([
                sw.name || '-',
                sw.version || '-',
                sw.publisher || '-',
                sw.install_date ? new Date(sw.install_date).toLocaleDateString('ja-JP') : '-',
            ]));
        });
        tbody.replaceChildren(fragment);
    } catch (e) {
        tbody.replaceChildren(_swMessageRow('読み込みに失敗しました', 4, 'var(--danger)'));
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadPCDetail();
    loadUpdates();
    loadSoftware();
    setInterval(() => { loadPCDetail(); loadUpdates(); loadSoftware(); }, 30000);
});
