async function loadAgents() {
    const tbody = document.getElementById('agents-body');
    if (!tbody) return;
    try {
        const data = await apiFetch('/agents');
        tbody.replaceChildren();
        if (!data.agents || data.agents.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 7;
            td.className = 'text-center';
            td.textContent = 'エージェントが登録されていません';
            tr.appendChild(td);
            tbody.appendChild(tr);
            return;
        }
        data.agents.forEach(a => {
            const tr = document.createElement('tr');
            const td = (text) => {
                const el = document.createElement('td');
                el.textContent = text ?? '—';
                return el;
            };
            tr.appendChild(td(a.pc_name));
            tr.appendChild(td(a.os_version));
            tr.appendChild(td(a.cpu_usage != null ? a.cpu_usage.toFixed(1) + '%' : '—'));
            tr.appendChild(td(a.memory_usage != null ? a.memory_usage.toFixed(1) + '%' : '—'));
            tr.appendChild(td(a.agent_version));
            tr.appendChild(td(a.last_seen ? new Date(a.last_seen).toLocaleString('ja-JP') : '—'));
            const statusTd = document.createElement('td');
            const badge = document.createElement('span');
            badge.className = 'badge ' + (a.online ? 'badge-success' : 'badge-secondary');
            badge.textContent = a.online ? 'オンライン' : 'オフライン';
            statusTd.appendChild(badge);
            tr.appendChild(statusTd);
            tbody.appendChild(tr);
        });
    } catch (e) {
        if (tbody) {
            tbody.replaceChildren();
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 7;
            td.className = 'text-center';
            td.style.color = 'var(--danger)';
            td.textContent = '読み込みに失敗しました';
            tr.appendChild(td);
            tbody.appendChild(tr);
        }
    }
}
document.addEventListener('DOMContentLoaded', loadAgents);
