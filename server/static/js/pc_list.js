let currentPage = 1;
let searchTimer = null;
const _selectedPcNames = new Set();

function statusBadgeEl(status) {
    const map = {
        'healthy': ['status-healthy', '正常'],
        'warning': ['status-warning', '要注意'],
        'critical': ['status-critical', '危険'],
        'unknown': ['status-unknown', '不明'],
    };
    const [cls, label] = map[status] || map['unknown'];
    const span = document.createElement('span');
    span.className = `status-badge ${cls}`;
    span.textContent = label;
    return span;
}

function formatGB(val) {
    if (val === null || val === undefined) return '-';
    return val.toFixed(1) + ' GB';
}

function formatDisk(free, total) {
    if (free === null || free === undefined || total === null || total === undefined) return '-';
    const pct = (free / total * 100).toFixed(0);
    return `${free.toFixed(1)} / ${total.toFixed(1)} GB (${pct}%)`;
}

function formatTime(iso) {
    if (!iso) return '-';
    return new Date(iso).toLocaleString('ja-JP');
}

function truncate(str, len) {
    if (!str) return '-';
    return str.length > len ? str.substring(0, len) + '...' : str;
}

function makeMessageRow(message, cols, style) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = cols;
    td.className = 'text-center';
    td.textContent = message;
    if (style) td.style.cssText = style;
    tr.appendChild(td);
    return tr;
}

function _mkEl(tag, props) {
    const el = document.createElement(tag);
    Object.entries(props || {}).forEach(([k, v]) => {
        if (k === 'text') el.textContent = v;
        else if (k === 'class') el.className = v;
        else if (k === 'style') el.style.cssText = v;
        else el.setAttribute(k, v);
    });
    return el;
}

function _updateBulkButton() {
    const btn = document.getElementById('bulk-task-btn');
    const countEl = document.getElementById('bulk-count');
    if (!btn) return;
    const n = _selectedPcNames.size;
    if (n > 0) {
        btn.style.display = '';
        if (countEl) countEl.textContent = n;
    } else {
        btn.style.display = 'none';
    }
}

function toggleSelectAll(checked) {
    const cbs = document.querySelectorAll('.pc-row-cb');
    cbs.forEach(cb => {
        cb.checked = checked;
        if (checked) _selectedPcNames.add(cb.dataset.pcName);
        else _selectedPcNames.delete(cb.dataset.pcName);
    });
    _updateBulkButton();
}

async function loadPCs(page) {
    currentPage = page || currentPage;
    const search = document.getElementById('search-input').value.trim();
    const status = document.getElementById('status-filter').value;
    const os = document.getElementById('os-filter').value;
    const tbody = document.getElementById('pc-table-body');
    tbody.replaceChildren(makeMessageRow('読み込み中...', 11, null));

    try {
        const params = new URLSearchParams();
        if (search) params.set('search', search);
        if (status) params.set('status', status);
        if (os) params.set('os', os);
        params.set('page', currentPage);
        params.set('per_page', '30');

        const data = await apiFetch('/pcs?' + params.toString());
        tbody.replaceChildren();

        if (data.pcs && data.pcs.length > 0) {
            data.pcs.forEach(pc => {
                const tr = document.createElement('tr');

                const cbTd = document.createElement('td');
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.className = 'pc-row-cb';
                cb.dataset.pcName = pc.pc_name;
                cb.checked = _selectedPcNames.has(pc.pc_name);
                cb.addEventListener('change', e => {
                    e.stopPropagation();
                    if (cb.checked) _selectedPcNames.add(pc.pc_name);
                    else _selectedPcNames.delete(pc.pc_name);
                    _updateBulkButton();
                    const allCbs = document.querySelectorAll('.pc-row-cb');
                    const allChecked = Array.from(allCbs).every(c => c.checked);
                    const allCb = document.getElementById('select-all-cb');
                    if (allCb) allCb.checked = allChecked;
                });
                cbTd.addEventListener('click', e => e.stopPropagation());
                cbTd.appendChild(cb);
                tr.appendChild(cbTd);

                tr.style.cursor = 'pointer';
                tr.addEventListener('click', () => { location.href = `/pcs/${pc.id}`; });

                const td = (text) => {
                    const el = document.createElement('td');
                    el.textContent = text;
                    return el;
                };

                const nameTd = document.createElement('td');
                const strong = document.createElement('strong');
                strong.textContent = pc.pc_name;
                nameTd.appendChild(strong);

                tr.appendChild(nameTd);
                tr.appendChild(td(pc.ip_address || '-'));
                tr.appendChild(td(pc.os_version || '-'));
                tr.appendChild(td(truncate(pc.cpu_name, 30) || '-'));
                tr.appendChild(td(formatGB(pc.memory_total_gb)));
                tr.appendChild(td(formatDisk(pc.disk_free_gb, pc.disk_total_gb)));

                const statusTd = document.createElement('td');
                statusTd.appendChild(statusBadgeEl(pc.status));
                tr.appendChild(statusTd);

                tr.appendChild(td(pc.health_score ?? '-'));
                tr.appendChild(td(formatTime(pc.last_seen)));

                const dotTd = document.createElement('td');
                if (pc.last_seen) {
                    const dot = document.createElement('span');
                    dot.textContent = '●';
                    dot.style.color = Date.now() - new Date(pc.last_seen).getTime() < 300000
                        ? 'var(--success)' : 'var(--text-muted)';
                    dotTd.appendChild(dot);
                }
                tr.appendChild(dotTd);

                tbody.appendChild(tr);
            });
        } else {
            tbody.replaceChildren(makeMessageRow('PCが登録されていません', 11, null));
        }

        renderPagination(data.total, data.page, data.pages);
    } catch (e) {
        tbody.replaceChildren(makeMessageRow('読み込みに失敗しました', 11, 'color:var(--danger);'));
    }
}

function renderPagination(total, page, pages) {
    const el = document.getElementById('pagination');
    el.replaceChildren();
    if (!pages || pages <= 1) return;
    for (let i = 1; i <= pages; i++) {
        const btn = document.createElement('button');
        btn.textContent = i;
        if (i === page) btn.className = 'active';
        btn.addEventListener('click', () => loadPCs(i));
        el.appendChild(btn);
    }
}

function searchPCs() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadPCs(1), 300);
}

async function exportPCsCSV() {
    const search = document.getElementById('search-input')?.value.trim() || '';
    const status = document.getElementById('status-filter')?.value || '';
    const os = document.getElementById('os-filter')?.value.trim() || '';
    const params = new URLSearchParams();
    if (search) params.set('search', search);
    if (status) params.set('status', status);
    if (os) params.set('os', os);
    try {
        const res = await apiFetchRaw('/pcs/export.csv?' + params.toString());
        if (!res.ok) { showError('エクスポートに失敗しました'); return; }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'pcs.csv';
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) {
        showError('エクスポートに失敗しました');
    }
}

function openBulkModal() {
    if (_selectedPcNames.size === 0) return;
    const info = document.getElementById('bulk-target-info');
    if (info) {
        info.textContent = `対象: ${[..._selectedPcNames].join(', ')} (${_selectedPcNames.size} 台)`;
    }
    document.getElementById('bulk-task-type').value = '';
    document.getElementById('bulk-command').value = '';
    document.getElementById('bulk-command-group').style.display = 'none';
    document.getElementById('bulk-modal').classList.add('open');
}

function closeBulkModal() {
    document.getElementById('bulk-modal').classList.remove('open');
}

function closeBulkResultModal() {
    document.getElementById('bulk-result-modal').classList.remove('open');
}

function _appendListSection(container, label, items, color, itemFn) {
    if (!items || items.length === 0) return;
    const p = document.createElement('p');
    p.style.color = color;
    p.textContent = label + ` ${items.length} 件`;
    container.appendChild(p);
    const ul = document.createElement('ul');
    items.forEach(item => {
        const li = document.createElement('li');
        li.textContent = itemFn(item);
        ul.appendChild(li);
    });
    container.appendChild(ul);
}

async function submitBulkTask() {
    const taskType = document.getElementById('bulk-task-type').value;
    if (!taskType) { showError('タスク種別を選択してください'); return; }

    const command = taskType === 'custom' ? document.getElementById('bulk-command').value.trim() : null;
    const btn = document.getElementById('bulk-submit-btn');
    btn.disabled = true;
    btn.textContent = '実行中...';

    try {
        const body = { task_type: taskType, pc_names: [..._selectedPcNames] };
        if (command) body.command = command;

        const res = await apiFetchRaw('/tasks/bulk', {
            method: 'POST',
            body: JSON.stringify(body),
        });
        const data = await res.json();
        closeBulkModal();

        const resultBody = document.getElementById('bulk-result-body');
        resultBody.replaceChildren();

        const msgP = document.createElement('p');
        msgP.textContent = data.message || '';
        resultBody.appendChild(msgP);

        _appendListSection(
            resultBody, '✓ 成功', data.successes, 'var(--success)',
            s => `${s.pc_name} (Task #${s.task_id})`
        );
        _appendListSection(
            resultBody, '✗ 失敗', data.failures, 'var(--danger)',
            f => `${f.pc_name}: ${f.error}`
        );

        document.getElementById('bulk-result-modal').classList.add('open');

        if (data.successes) data.successes.forEach(s => _selectedPcNames.delete(s.pc_name));
        _updateBulkButton();

    } catch (e) {
        showError('一括タスク実行に失敗しました');
    } finally {
        btn.disabled = false;
        btn.textContent = '実行';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('search-input');
    if (searchInput) searchInput.addEventListener('input', searchPCs);

    const statusFilter = document.getElementById('status-filter');
    if (statusFilter) statusFilter.addEventListener('change', searchPCs);

    const osFilter = document.getElementById('os-filter');
    if (osFilter) osFilter.addEventListener('change', searchPCs);

    const exportCsvBtn = document.getElementById('btn-export-pcs-csv');
    if (exportCsvBtn) exportCsvBtn.addEventListener('click', exportPCsCSV);

    const bulkTaskBtn = document.getElementById('bulk-task-btn');
    if (bulkTaskBtn) bulkTaskBtn.addEventListener('click', openBulkModal);

    const selectAllCb = document.getElementById('select-all-cb');
    if (selectAllCb) selectAllCb.addEventListener('change', () => toggleSelectAll(selectAllCb.checked));

    const closeBulkModalBtn = document.getElementById('btn-close-bulk-modal');
    if (closeBulkModalBtn) closeBulkModalBtn.addEventListener('click', closeBulkModal);

    const cancelBulkModalBtn = document.getElementById('btn-cancel-bulk-modal');
    if (cancelBulkModalBtn) cancelBulkModalBtn.addEventListener('click', closeBulkModal);

    const closeBulkResultBtn = document.getElementById('btn-close-bulk-result-modal');
    if (closeBulkResultBtn) closeBulkResultBtn.addEventListener('click', closeBulkResultModal);

    const closeBulkResult2 = document.getElementById('btn-close-bulk-result');
    if (closeBulkResult2) closeBulkResult2.addEventListener('click', closeBulkResultModal);

    const bulkForm = document.getElementById('bulk-form');
    if (bulkForm) bulkForm.addEventListener('submit', (e) => { e.preventDefault(); submitBulkTask(); });

    const taskTypeEl = document.getElementById('bulk-task-type');
    if (taskTypeEl) {
        taskTypeEl.addEventListener('change', () => {
            const grp = document.getElementById('bulk-command-group');
            if (grp) grp.style.display = taskTypeEl.value === 'custom' ? '' : 'none';
        });
    }
    loadPCs(1);
    setInterval(() => loadPCs(currentPage), 30000);
});
