let healthChart = null;

const OS_COLORS = ['#4f8cff', '#6ba5ff', '#a78bfa', '#18dcff', '#2ed573', '#ffa502', '#ff6b81', '#ff4757'];

function escHtml(str) {
    if (str === null || str === undefined) return '—';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function severityBadge(sev) {
    const map = {
        critical: '<span class="severity critical">Critical</span>',
        high:     '<span class="severity high">High</span>',
        medium:   '<span class="severity medium">Medium</span>',
        low:      '<span class="severity low">Low</span>',
    };
    return map[sev] || `<span class="severity low">${escHtml(sev)}</span>`;
}

function taskStatusBadge(status) {
    const cls = { pending:'pending', running:'running', completed:'completed', failed:'failed', cancelled:'cancelled' }[status] || 'pending';
    const lbl = { pending:'待機中', running:'実行中', completed:'完了', failed:'失敗', cancelled:'中止' }[status] || escHtml(status);
    return `<span class="badge-dot ${cls}"><span class="dot"></span>${lbl}</span>`;
}

function auditActionColor(action) {
    if (!action) return '#8b91a8';
    const a = action.toLowerCase();
    if (a.includes('delete')) return '#dc2626';
    if (a.includes('create') || a.includes('add')) return '#16a34a';
    if (a.includes('update') || a.includes('edit')) return '#2563eb';
    if (a.includes('login')) return '#7c3aed';
    return '#8b91a8';
}

async function refreshDashboard() {
    // Stats
    try {
        const stats = await apiFetch('/dashboard/stats');
        const total   = stats.total_pcs       || 0;
        const healthy = stats.healthy         || 0;
        const warning = stats.warning         || 0;
        const critical= stats.critical        || 0;
        const pending = stats.pending_tasks   || 0;
        const lowDisk = stats.low_disk_count  || 0;
        const alerts  = stats.unresolved_alerts || 0;
        const done    = stats.completed_tasks_today || 0;

        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        set('stat-total',          total);
        set('stat-healthy',        healthy);
        set('stat-warning',        warning);
        set('stat-critical',       critical);
        set('stat-pending-tasks',  pending);
        set('stat-low-disk',       lowDisk);
        set('stat-alerts',         alerts);
        set('stat-completed-tasks',done);
        set('healthy-pct', total > 0 ? Math.round((healthy / total) * 100) : 0);
        set('kpi-total-delta', `${total}台管理中`);

        const ad = document.getElementById('kpi-alerts-delta');
        if (ad) ad.textContent = alerts > 0 ? `${alerts}件未対応` : 'アラートなし';

        const td = document.getElementById('kpi-tasks-delta');
        if (td) td.textContent = pending > 0 ? `${pending}件処理待ち` : 'すべて処理済み';

        const lu = document.getElementById('last-update');
        if (lu) lu.textContent = `${total}台を監視中 · 最終更新 ${new Date().toLocaleTimeString('ja-JP')}`;
    } catch (e) {
        console.error('Stats error:', e);
    }

    // Health ring
    try {
        const stats2 = await apiFetch('/dashboard/stats');
        const h = stats2.healthy  || 0;
        const w = stats2.warning  || 0;
        const c = stats2.critical || 0;
        const t = stats2.total_pcs || 0;
        const o = Math.max(0, t - h - w - c);

        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        set('ring-healthy',  h);
        set('ring-warning',  w);
        set('ring-critical', c);
        set('ring-offline',  o);
        const pc = document.getElementById('health-pc-count');
        if (pc) pc.textContent = `${t}台`;

        const canvas = document.getElementById('healthChart');
        if (canvas && window.Chart) {
            if (healthChart) healthChart.destroy();
            healthChart = new Chart(canvas, {
                type: 'doughnut',
                data: {
                    labels: ['正常', '要注意', '危険', 'オフライン'],
                    datasets: [{ data: [h, w, c, o],
                        backgroundColor: ['#2ed573', '#ffa502', '#ff4757', '#8b91a8'],
                        borderWidth: 3, borderColor: 'var(--bg-card)', hoverOffset: 4 }],
                },
                options: {
                    responsive: false, cutout: '72%',
                    plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => ` ${ctx.label}: ${ctx.raw}台` }}},
                },
            });
        }
    } catch (e) {
        console.error('Health ring error:', e);
    }

    // OS bars
    try {
        const osData = await apiFetch('/dashboard/os-breakdown');
        const breakdown = osData.breakdown || [];
        const osBarsEl = document.getElementById('os-bars-body');
        const osCountEl = document.getElementById('os-version-count');
        if (osCountEl) osCountEl.textContent = `${breakdown.length}種類`;
        if (osBarsEl) {
            if (breakdown.length === 0) {
                osBarsEl.textContent = 'データなし';
            } else {
                const max = Math.max(...breakdown.map(d => d.count), 1);
                const rows = breakdown.map((d, i) => {
                    const pct = Math.round((d.count / max) * 100);
                    const color = OS_COLORS[i % OS_COLORS.length];
                    const row = document.createElement('div');
                    row.className = 'os-bar-row';
                    const label = document.createElement('span');
                    label.className = 'os-bar-label';
                    label.title = d.os || '';
                    label.textContent = d.os || '—';
                    const track = document.createElement('div');
                    track.className = 'os-bar-track';
                    const fill = document.createElement('div');
                    fill.className = 'os-bar-fill';
                    fill.style.cssText = `width:${pct}%;background:${color};`;
                    track.appendChild(fill);
                    const count = document.createElement('span');
                    count.className = 'os-bar-count';
                    count.textContent = d.count;
                    row.appendChild(label); row.appendChild(track); row.appendChild(count);
                    return row;
                });
                osBarsEl.replaceChildren(...rows);
            }
        }
    } catch (e) {
        console.error('OS bars error:', e);
    }

    // Alerts table
    try {
        const alertsData = await apiFetch('/alerts?per_page=5');
        const unresolvedAlerts = (alertsData.alerts || []).filter(a => !a.resolved);
        const count = alertsData.unresolved_count ?? unresolvedAlerts.length;
        const countEl = document.getElementById('dashboard-alert-count');
        if (countEl) {
            countEl.textContent = count > 0 ? `未解決 ${count}件` : 'アラートなし';
            countEl.style.color = count > 0 ? 'var(--danger)' : 'var(--text-muted)';
        }
        const tbody = document.getElementById('dashboard-alerts-body');
        if (tbody) {
            tbody.replaceChildren();
            const show = unresolvedAlerts.slice(0, 5);
            if (show.length === 0) {
                const tr = document.createElement('tr');
                const td = document.createElement('td');
                td.colSpan = 5; td.className = 'text-center';
                td.style.color = 'var(--text-muted)';
                td.textContent = 'アクティブアラートはありません';
                tr.appendChild(td); tbody.appendChild(tr);
            } else {
                show.forEach(a => {
                    const tr = document.createElement('tr');
                    const time = a.created_at ? new Date(a.created_at).toLocaleString('ja-JP') : '—';
                    const cells = [
                        severityBadge(a.severity),
                        escHtml(a.alert_type),
                        escHtml(a.pc_name || '—'),
                        escHtml(a.message),
                        escHtml(time),
                    ];
                    cells.forEach((html, idx) => {
                        const td = document.createElement('td');
                        if (idx === 3) { td.style.cssText = 'max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'; }
                        if (idx === 4) { td.style.whiteSpace = 'nowrap'; }
                        td.innerHTML = html; // html is either escHtml() output or a hardcoded badge span
                        tr.appendChild(td);
                    });
                    tbody.appendChild(tr);
                });
            }
        }
    } catch (e) {
        console.error('Alerts error:', e);
    }

    // Recent tasks feed
    try {
        const tasksData = await apiFetch('/tasks?per_page=6');
        const feed = document.getElementById('recent-tasks-feed');
        if (feed) {
            const tasks = tasksData.tasks || [];
            feed.replaceChildren();
            if (tasks.length === 0) {
                const item = document.createElement('div');
                item.className = 'feed-item';
                const body = document.createElement('div');
                body.className = 'feed-body';
                const title = document.createElement('span');
                title.className = 'feed-title';
                title.style.color = 'var(--text-muted)';
                title.textContent = 'タスクはまだありません';
                body.appendChild(title); item.appendChild(body); feed.appendChild(item);
            } else {
                tasks.forEach(t => {
                    const item = document.createElement('div');
                    item.className = 'feed-item';
                    const statusColors = { completed:'var(--success-soft)', failed:'var(--danger-soft)', running:'var(--info-soft)' };
                    const iconColor = statusColors[t.status] || 'var(--bg-elevated)';
                    const time = t.created_at ? new Date(t.created_at).toLocaleString('ja-JP') : '—';
                    const body = document.createElement('div');
                    body.className = 'feed-body';
                    const titleEl = document.createElement('div');
                    titleEl.className = 'feed-title';
                    titleEl.textContent = `${t.task_type || 'タスク'} → ${t.pc_name || '全PC'}`;
                    const meta = document.createElement('div');
                    meta.className = 'feed-meta';
                    meta.innerHTML = taskStatusBadge(t.status) + `<span>${escHtml(t.created_by || '')}</span>`;
                    body.appendChild(titleEl); body.appendChild(meta);
                    const timeEl = document.createElement('div');
                    timeEl.className = 'feed-time';
                    timeEl.textContent = time;
                    item.appendChild(body); item.appendChild(timeEl);
                    feed.appendChild(item);
                });
            }
        }
    } catch (e) {
        console.error('Tasks feed error:', e);
    }

    // Audit log feed
    try {
        const recent = await apiFetch('/dashboard/recent');
        const feed = document.getElementById('recent-ops-feed');
        if (feed) {
            const ops = recent.operations || [];
            feed.replaceChildren();
            if (ops.length === 0) {
                const item = document.createElement('div');
                item.className = 'feed-item';
                const body = document.createElement('div');
                body.className = 'feed-body';
                const title = document.createElement('span');
                title.className = 'feed-title';
                title.style.color = 'var(--text-muted)';
                title.textContent = '操作ログはまだありません';
                body.appendChild(title); item.appendChild(body); feed.appendChild(item);
            } else {
                ops.slice(0, 6).forEach(op => {
                    const item = document.createElement('div');
                    item.className = 'feed-item';
                    const color = auditActionColor(op.action);
                    const iconEl = document.createElement('div');
                    iconEl.className = 'feed-icon';
                    iconEl.style.cssText = `background:${color}1a;color:${color};`;
                    iconEl.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="14" height="14"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
                    const body = document.createElement('div');
                    body.className = 'feed-body';
                    const titleEl = document.createElement('div');
                    titleEl.className = 'feed-title';
                    titleEl.textContent = op.action || '操作';
                    const meta = document.createElement('div');
                    meta.className = 'feed-meta';
                    const s1 = document.createElement('span'); s1.textContent = op.target || '';
                    const s2 = document.createElement('span'); s2.textContent = op.created_by || '';
                    meta.appendChild(s1); meta.appendChild(s2);
                    body.appendChild(titleEl); body.appendChild(meta);
                    const time = document.createElement('div');
                    time.className = 'feed-time';
                    time.textContent = op.created_at ? new Date(op.created_at).toLocaleString('ja-JP') : '—';
                    item.appendChild(iconEl); item.appendChild(body); item.appendChild(time);
                    feed.appendChild(item);
                });
            }
        }
    } catch (e) {
        console.error('Audit feed error:', e);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const refreshBtn = document.getElementById('btn-refresh-dashboard');
    if (refreshBtn) refreshBtn.addEventListener('click', refreshDashboard);
    const kpiTotal = document.getElementById('kpi-total');
    if (kpiTotal) kpiTotal.addEventListener('click', () => { location.href = '/pcs'; });
    refreshDashboard();
    setInterval(refreshDashboard, 30000);
});
