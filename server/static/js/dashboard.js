let healthChart = null;
let osChart = null;

function escHtml(str) {
    if (str === null || str === undefined) return '-';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function severityBadge(sev) {
    const map = {
        critical: '<span class="status-badge severity-critical">危険</span>',
        high: '<span class="status-badge severity-high">高</span>',
        medium: '<span class="status-badge severity-medium">中</span>',
        low: '<span class="status-badge severity-low">低</span>',
    };
    return map[sev] || sev;
}

async function refreshDashboard() {
    try {
        const stats = await apiFetch('/dashboard/stats');
        document.getElementById('stat-total').textContent = stats.total_pcs || 0;
        document.getElementById('stat-healthy').textContent = stats.healthy || 0;
        document.getElementById('stat-warning').textContent = stats.warning || 0;
        document.getElementById('stat-critical').textContent = stats.critical || 0;
        document.getElementById('stat-online').textContent = stats.online_count || 0;
        document.getElementById('stat-pending-tasks').textContent = stats.pending_tasks || 0;
        document.getElementById('stat-low-disk').textContent = stats.low_disk_count || 0;
        document.getElementById('stat-high-mem').textContent = stats.high_memory_count || 0;
    } catch (e) {
        showError('統計情報の取得に失敗しました');
    }

    try {
        const health = await apiFetch('/dashboard/health-distribution');
        const labels = health.distribution.map(d => d.range);
        const values = health.distribution.map(d => d.count);
        const colors = ['#ff4757', '#ff6b81', '#ffa502', '#ffd43b', '#2ed573'];

        if (healthChart) healthChart.destroy();
        healthChart = new Chart(document.getElementById('healthChart'), {
            type: 'doughnut',
            data: {
                labels: labels.map((l, i) => l + '点 (' + values[i] + '台)'),
                datasets: [{
                    data: values,
                    backgroundColor: colors,
                    borderWidth: 0,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'right', labels: { color: '#8b8fa3', font: { size: 11 } } }
                }
            }
        });
    } catch (e) {
        console.error('Health chart error:', e);
    }

    try {
        const osData = await apiFetch('/dashboard/os-breakdown');
        const labels = osData.breakdown.map(d => d.os);
        const values = osData.breakdown.map(d => d.count);

        if (osChart) osChart.destroy();
        osChart = new Chart(document.getElementById('osChart'), {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: '台数',
                    data: values,
                    backgroundColor: '#4f8cff',
                    borderRadius: 4,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    x: { ticks: { color: '#8b8fa3', stepSize: 1 }, grid: { color: '#2d3248' } },
                    y: { ticks: { color: '#8b8fa3' }, grid: { display: false } }
                }
            }
        });
    } catch (e) {
        console.error('OS chart error:', e);
    }

    try {
        const recent = await apiFetch('/dashboard/recent');
        const tbody = document.getElementById('recent-ops-body');

        if (recent.operations && recent.operations.length > 0) {
            tbody.innerHTML = recent.operations.slice(0, 20).map(op => {
                const time = op.created_at ? new Date(op.created_at).toLocaleString('ja-JP') : '-';
                return `<tr>
                    <td>${time}</td>
                    <td>${op.action || '-'}</td>
                    <td>${op.target || '-'}</td>
                    <td>${op.created_by || '-'}</td>
                </tr>`;
            }).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center">操作ログはまだありません</td></tr>';
        }
    } catch (e) {
        console.error('Recent ops error:', e);
    }

    try {
        const alertsData = await apiFetch('/alerts?per_page=5');
        const count = alertsData.unresolved_count || 0;
        const countEl = document.getElementById('dashboard-alert-count');
        if (countEl) {
            countEl.textContent = count > 0 ? `(未解決 ${count} 件)` : '(なし)';
            countEl.style.color = count > 0 ? 'var(--danger)' : 'var(--text-secondary)';
        }
        const alertsTbody = document.getElementById('dashboard-alerts-body');
        if (alertsTbody) {
            if (alertsData.alerts && alertsData.alerts.length > 0) {
                alertsTbody.innerHTML = alertsData.alerts.map(a => {
                    const time = a.created_at ? new Date(a.created_at).toLocaleString('ja-JP') : '-';
                    return `<tr>
                        <td>${severityBadge(a.severity)}</td>
                        <td>${escHtml(a.alert_type)}</td>
                        <td>${escHtml(a.message)}</td>
                        <td>${escHtml(time)}</td>
                    </tr>`;
                }).join('');
            } else {
                alertsTbody.innerHTML = '<tr><td colspan="4" class="text-center">アクティブアラートはありません</td></tr>';
            }
        }
    } catch (e) {
        console.error('Alerts fetch error:', e);
    }

    document.getElementById('last-update').textContent =
        '最終更新: ' + new Date().toLocaleString('ja-JP');
}

document.addEventListener('DOMContentLoaded', () => {
    refreshDashboard();
    setInterval(refreshDashboard, 30000);
});
