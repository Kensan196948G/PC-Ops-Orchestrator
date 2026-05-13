let currentTaskPage = 1;

function statusBadge(status) {
    const map = {
        'pending': '<span class="status-badge status-pending">未処理</span>',
        'running': '<span class="status-badge status-running">実行中</span>',
        'completed': '<span class="status-badge status-completed">完了</span>',
        'failed': '<span class="status-badge status-failed">失敗</span>',
        'cancelled': '<span class="status-badge status-unknown">キャンセル</span>',
    };
    return map[status] || status;
}

function formatTime(iso) {
    if (!iso) return '-';
    return new Date(iso).toLocaleString('ja-JP');
}

function showCreateForm() {
    document.getElementById('create-task-card').classList.remove('hidden');
}

function hideCreateForm() {
    document.getElementById('create-task-card').classList.add('hidden');
}

async function loadTasks(page) {
    currentTaskPage = page || currentTaskPage;
    const status = document.getElementById('task-status-filter').value;
    const type = document.getElementById('task-type-filter').value;
    const tbody = document.getElementById('tasks-body');
    tbody.innerHTML = '<tr><td colspan="9" class="text-center">読み込み中...</td></tr>';

    try {
        const params = new URLSearchParams();
        if (status) params.set('status', status);
        if (type) params.set('task_type', type);
        params.set('page', currentTaskPage);
        params.set('per_page', '30');

        const data = await apiFetch('/tasks?' + params.toString());
        // escapeHTML wraps every API-returned scalar so an injection vector via
        // task_type / pc_id / created_by cannot break out of attribute or text
        // context. statusBadge/formatTime emit known-safe HTML/strings.
        tbody.innerHTML = data.tasks && data.tasks.length > 0 ? data.tasks.map(t => `
            <tr onclick="showTaskDetail(${JSON.stringify(t).replace(/"/g, '&quot;')})" style="cursor:pointer;">
                <td>#${escapeHTML(t.id)}</td>
                <td>${escapeHTML(t.task_type)}</td>
                <td>${escapeHTML(t.pc_id || '全PC')}</td>
                <td>${statusBadge(t.status)}</td>
                <td>${escapeHTML(t.priority || 0)}</td>
                <td>${escapeHTML(t.created_by || '-')}</td>
                <td>${escapeHTML(formatTime(t.created_at))}</td>
                <td>${escapeHTML(formatTime(t.completed_at))}</td>
                <td><button class="btn btn-danger role-admin-only" onclick="event.stopPropagation();deleteTask(${Number(t.id)})" style="padding:0.2rem 0.5rem;font-size:0.75rem;">削除</button></td>
            </tr>
        `).join('') : '<tr><td colspan="9" class="text-center">タスクがありません</td></tr>';

        const pagination = document.getElementById('task-pagination');
        if (data.pages && data.pages > 1) {
            let html = '';
            for (let i = 1; i <= data.pages; i++) {
                html += `<button class="${i === data.page ? 'active' : ''}" onclick="loadTasks(${i})">${i}</button>`;
            }
            pagination.innerHTML = html;
        } else {
            pagination.innerHTML = '';
        }
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-center" style="color:var(--danger);">読み込みに失敗しました</td></tr>';
    }
}

function openTaskModal() {
    document.getElementById('task-detail-modal').classList.add('open');
    document.addEventListener('keydown', handleModalKey);
}

function closeTaskModalDirect() {
    document.getElementById('task-detail-modal').classList.remove('open');
    document.removeEventListener('keydown', handleModalKey);
}

function closeTaskModal(event) {
    if (event.target === document.getElementById('task-detail-modal')) {
        closeTaskModalDirect();
    }
}

function handleModalKey(event) {
    if (event.key === 'Escape') closeTaskModalDirect();
}

function _makeDetailRow(key, td) {
    const tr = document.createElement('tr');
    const th = document.createElement('th');
    th.textContent = key;
    tr.appendChild(th);
    tr.appendChild(td);
    return tr;
}

function _textRow(key, value) {
    const td = document.createElement('td');
    td.textContent = value;
    return _makeDetailRow(key, td);
}

function _preRow(key, text, extraClass) {
    const td = document.createElement('td');
    const pre = document.createElement('pre');
    pre.className = extraClass ? 'detail-pre ' + extraClass : 'detail-pre';
    pre.textContent = text;
    td.appendChild(pre);
    return _makeDetailRow(key, td);
}

async function showTaskDetail(task) {
    const body = document.getElementById('task-detail-body');
    const loading = document.createElement('p');
    loading.className = 'text-center';
    loading.textContent = '読み込み中...';
    body.replaceChildren(loading);
    openTaskModal();

    try {
        const data = await apiFetch('/tasks/' + task.id);
        const t = data.task;
        const table = document.createElement('table');
        table.className = 'detail-table';

        table.appendChild(_textRow('ID', '#' + t.id));
        table.appendChild(_textRow('種類', t.task_type || '-'));
        table.appendChild(_textRow('PC', t.pc_id ? '#' + t.pc_id : '全PC対象'));

        const statusTd = document.createElement('td');
        statusTd.innerHTML = statusBadge(t.status);
        table.appendChild(_makeDetailRow('状態', statusTd));

        table.appendChild(_textRow('優先度', String(t.priority ?? 0)));
        table.appendChild(_textRow('作成者', t.created_by || '-'));
        table.appendChild(_textRow('作成日時', formatTime(t.created_at)));
        table.appendChild(_textRow('開始日時', formatTime(t.started_at)));
        table.appendChild(_textRow('完了日時', formatTime(t.completed_at)));

        if (t.command) {
            const td = document.createElement('td');
            const code = document.createElement('code');
            code.textContent = t.command;
            td.appendChild(code);
            table.appendChild(_makeDetailRow('コマンド', td));
        }
        if (t.parameters) table.appendChild(_preRow('パラメータ', t.parameters));
        if (t.result)     table.appendChild(_preRow('実行結果', t.result));
        if (t.error_message) table.appendChild(_preRow('エラー', t.error_message, 'detail-error'));

        body.replaceChildren(table);
    } catch (e) {
        const err = document.createElement('p');
        err.style.color = 'var(--danger)';
        err.textContent = '読み込みに失敗しました';
        body.replaceChildren(err);
    }
}

async function createTask() {
    const type = document.getElementById('new-task-type').value;
    const pcName = document.getElementById('new-task-pc').value.trim();
    const command = document.getElementById('new-task-command').value.trim();

    if (type === 'custom' && !command) {
        showError('カスタムタスクのコマンドを入力してください');
        return;
    }

    try {
        const body = { task_type: type, priority: 1 };
        if (pcName) body.pc_name = pcName;
        if (type === 'custom') body.command = command;
        else body.parameters = {};

        const res = await apiFetch('/tasks', {
            method: 'POST',
            body: JSON.stringify(body),
        });

        if (res.task) {
            showSuccess('タスクを作成しました (ID: ' + res.task.id + ')');
            hideCreateForm();
            loadTasks(1);
        } else {
            showError(res.error || '作成に失敗しました');
        }
    } catch (e) {
        showError('APIエラー');
    }
}

async function deleteTask(taskId) {
    if (!confirm('タスク #' + taskId + ' を削除しますか？')) return;

    try {
        const res = await apiFetch('/tasks/' + taskId, { method: 'DELETE' });
        if (res.message) {
            showSuccess(res.message);
            loadTasks(currentTaskPage);
        }
    } catch (e) {
        showError('削除に失敗しました');
    }
}

document.getElementById('new-task-type').addEventListener('change', function() {
    const cmdInput = document.getElementById('new-task-command');
    this.value === 'custom' ? cmdInput.classList.remove('hidden') : cmdInput.classList.add('hidden');
});

async function exportTasksCSV() {
    const status = document.getElementById('task-status-filter')?.value || '';
    const taskType = document.getElementById('task-type-filter')?.value || '';
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (taskType) params.set('task_type', taskType);
    try {
        const res = await apiFetchRaw('/tasks/export.csv?' + params.toString());
        if (!res.ok) { showError('エクスポートに失敗しました'); return; }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'tasks.csv';
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) {
        showError('エクスポートに失敗しました');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const showCreateBtn = document.getElementById('btn-show-create-task');
    if (showCreateBtn) showCreateBtn.addEventListener('click', showCreateForm);

    const exportCsvBtn = document.getElementById('btn-export-tasks-csv');
    if (exportCsvBtn) exportCsvBtn.addEventListener('click', exportTasksCSV);

    const createBtn = document.getElementById('btn-create-task');
    if (createBtn) createBtn.addEventListener('click', createTask);

    const hideCreateBtn = document.getElementById('btn-hide-create-task');
    if (hideCreateBtn) hideCreateBtn.addEventListener('click', hideCreateForm);

    const statusFilter = document.getElementById('task-status-filter');
    if (statusFilter) statusFilter.addEventListener('change', () => loadTasks());

    const typeFilter = document.getElementById('task-type-filter');
    if (typeFilter) typeFilter.addEventListener('change', () => loadTasks());

    const modal = document.getElementById('task-detail-modal');
    if (modal) modal.addEventListener('click', closeTaskModal);

    const closeModalBtn = document.getElementById('btn-close-task-modal');
    if (closeModalBtn) closeModalBtn.addEventListener('click', closeTaskModalDirect);

    loadTasks(1);
    setInterval(() => loadTasks(currentTaskPage), 30000);
});
