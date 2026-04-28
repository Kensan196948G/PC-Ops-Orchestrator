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
                tbody.innerHTML = data.recent_tasks.map(t => `
                    <tr>
                        <td>#${t.id}</td>
                        <td>${t.task_type}</td>
                        <td><span class="status-badge status-${t.status}">${t.status}</span></td>
                        <td>${t.created_at ? new Date(t.created_at).toLocaleString('ja-JP') : '-'}</td>
                        <td>${t.result ? t.result.substring(0, 50) : t.error_message || '-'}</td>
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

document.addEventListener('DOMContentLoaded', loadPCDetail);
