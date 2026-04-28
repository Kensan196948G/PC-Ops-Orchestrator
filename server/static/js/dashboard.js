let healthChart = null;
let osChart = null;

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

    document.getElementById('last-update').textContent =
        '最終更新: ' + new Date().toLocaleString('ja-JP');
}

document.addEventListener('DOMContentLoaded', () => {
    refreshDashboard();
    setInterval(refreshDashboard, 30000);
});
