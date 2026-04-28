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
    document.getElementById('create-task-card').style.display = 'block';
}

function hideCreateForm() {
    document.getElementById('create-task-card').style.display = 'none';
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
        tbody.innerHTML = data.tasks && data.tasks.length > 0 ? data.tasks.map(t => `
            <tr onclick="showTaskDetail(${JSON.stringify(t).replace(/"/g, '&quot;')})" style="cursor:pointer;">
                <td>#${t.id}</td>
                <td>${t.task_type}</td>
                <td>${t.pc_id || '全PC'}</td>
                <td>${statusBadge(t.status)}</td>
                <td>${t.priority || 0}</td>
                <td>${t.created_by || '-'}</td>
                <td>${formatTime(t.created_at)}</td>
                <td>${formatTime(t.completed_at)}</td>
                <td><button class="btn btn-danger" onclick="event.stopPropagation();deleteTask(${t.id})" style="padding:0.2rem 0.5rem;font-size:0.75rem;">削除</button></td>
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

function showTaskDetail(task) {
    const el = document.getElementById('task-detail');
    el.textContent = JSON.stringify(task, null, 2);
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
    cmdInput.style.display = this.value === 'custom' ? 'inline-block' : 'none';
});

document.addEventListener('DOMContentLoaded', () => loadTasks(1));
