'use strict';

const WEEKDAY_NAMES = ['月', '火', '水', '木', '金', '土', '日'];
let currentPage = 1;

async function loadScheduledTasks(page = 1) {
    currentPage = page;
    const enabled = document.getElementById('enabled-filter').value;
    let path = `/scheduled-tasks?page=${page}&per_page=20`;
    if (enabled) path += `&enabled=${enabled}`;

    const data = await apiFetch(path);
    const tbody = document.getElementById('scheduled-tasks-body');

    if (!data.scheduled_tasks || data.scheduled_tasks.length === 0) {
        tbody.textContent = '';
        const row = tbody.insertRow();
        const cell = row.insertCell();
        cell.colSpan = 9;
        cell.className = 'text-center';
        cell.textContent = 'スケジュールタスクがありません';
        document.getElementById('scheduled-tasks-pagination').textContent = '';
        return;
    }

    tbody.textContent = '';
    for (const st of data.scheduled_tasks) {
        const row = tbody.insertRow();
        row.dataset.id = st.id;

        // Name + description
        const tdName = row.insertCell();
        const strong = document.createElement('strong');
        strong.textContent = st.name;
        tdName.appendChild(strong);
        if (st.description) {
            const small = document.createElement('small');
            small.className = 'text-muted';
            small.textContent = st.description;
            tdName.appendChild(document.createElement('br'));
            tdName.appendChild(small);
        }

        row.insertCell().textContent = taskTypeLabel(st.task_type);

        const tdPc = row.insertCell();
        if (st.pc_name) {
            tdPc.textContent = st.pc_name;
        } else {
            const span = document.createElement('span');
            span.className = 'text-muted';
            span.textContent = '全PC';
            tdPc.appendChild(span);
        }

        row.insertCell().textContent = scheduleLabel(st);
        row.insertCell().textContent = st.next_run_at ? formatDatetime(st.next_run_at) : '-';
        row.insertCell().textContent = st.last_run_at ? formatDatetime(st.last_run_at) : '-';

        const tdCount = row.insertCell();
        tdCount.className = 'text-center';
        tdCount.textContent = st.run_count || 0;

        const tdState = row.insertCell();
        const badge = document.createElement('span');
        badge.className = st.is_enabled ? 'badge badge-success' : 'badge badge-secondary';
        badge.textContent = st.is_enabled ? '有効' : '無効';
        tdState.appendChild(badge);

        // Action buttons — pass only numeric id via data-* to avoid injection
        const tdActions = row.insertCell();
        tdActions.className = 'action-cell';
        tdActions.appendChild(makeBtn('▶', 'btn-secondary btn-xs', 'run-now', st.id, '今すぐ実行', 'role-operator-or-admin'));
        tdActions.appendChild(makeBtn(
            st.is_enabled ? '停止' : '開始',
            st.is_enabled ? 'btn-warning btn-xs' : 'btn-success btn-xs',
            'toggle', st.id,
            st.is_enabled ? '無効化' : '有効化',
            'role-operator-or-admin',
        ));
        tdActions.appendChild(makeBtn('✎', 'btn-secondary btn-xs', 'edit', st.id, '編集', 'role-operator-or-admin'));
        tdActions.appendChild(makeBtn('✕', 'btn-danger btn-xs', 'delete', st.id, '削除', 'role-admin-only'));
    }

    renderPagination('scheduled-tasks-pagination', data.page, data.pages, loadScheduledTasks);
}

function makeBtn(label, classes, action, id, title, roleClass) {
    const btn = document.createElement('button');
    btn.className = `btn ${classes}` + (roleClass ? ` ${roleClass}` : '');
    btn.textContent = label;
    btn.title = title;
    btn.dataset.action = action;
    btn.dataset.id = id;
    return btn;
}

// Event delegation for action buttons
document.addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;
    const id = parseInt(btn.dataset.id, 10);
    const action = btn.dataset.action;

    if (action === 'run-now') {
        const name = btn.closest('tr')?.querySelector('strong')?.textContent || '';
        if (!confirm(`「${name}」を今すぐ実行しますか？`)) return;
        const data = await apiFetch(`/scheduled-tasks/${id}/run-now`, { method: 'POST' });
        if (data.error) { showError(data.error); return; }
        showSuccess(data.message + (data.task ? ` (タスクID: ${data.task.id})` : ''));
    } else if (action === 'toggle') {
        const data = await apiFetch(`/scheduled-tasks/${id}/toggle`, { method: 'POST' });
        if (data.error) { showError(data.error); return; }
        showSuccess(data.message);
        loadScheduledTasks(currentPage);
    } else if (action === 'edit') {
        await editTask(id);
    } else if (action === 'delete') {
        const name = btn.closest('tr')?.querySelector('strong')?.textContent || '';
        if (!confirm(`「${name}」を削除しますか？`)) return;
        const data = await apiFetch(`/scheduled-tasks/${id}`, { method: 'DELETE' });
        if (data.error) { showError(data.error); return; }
        showSuccess(data.message);
        loadScheduledTasks(currentPage);
    }
});

function taskTypeLabel(type) {
    const map = { cleanup: 'クリーンアップ', update: '更新実行', diagnose: '診断実行', collect: '情報収集', custom: 'カスタム' };
    return map[type] || type;
}

function scheduleLabel(st) {
    if (st.schedule_type === 'interval') return `${st.interval_minutes}分ごと`;
    if (st.schedule_type === 'daily') return `毎日 ${st.daily_time || ''}`;
    if (st.schedule_type === 'weekly') {
        const day = WEEKDAY_NAMES[st.weekly_day] ?? '?';
        return `毎週${day}曜 ${st.weekly_time || ''}`;
    }
    return st.schedule_type;
}

function formatDatetime(iso) {
    if (!iso) return '-';
    const d = new Date(iso);
    return d.toLocaleString('ja-JP', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function renderPagination(containerId, page, pages, callback) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.textContent = '';
    if (pages <= 1) return;
    if (page > 1) {
        const prev = document.createElement('button');
        prev.className = 'btn btn-secondary btn-sm';
        prev.textContent = '‹ 前';
        prev.addEventListener('click', () => callback(page - 1));
        el.appendChild(prev);
        el.append(' ');
    }
    el.append(`${page} / ${pages}`);
    if (page < pages) {
        el.append(' ');
        const next = document.createElement('button');
        next.className = 'btn btn-secondary btn-sm';
        next.textContent = '次 ›';
        next.addEventListener('click', () => callback(page + 1));
        el.appendChild(next);
    }
}

// ── Modal ──

function showCreateModal() {
    document.getElementById('st-modal-title').textContent = 'スケジュールタスクの作成';
    document.getElementById('st-form').reset();
    document.getElementById('st-id').value = '';
    document.getElementById('st-interval').value = '60';
    document.getElementById('st-daily-time').value = '02:00';
    document.getElementById('st-weekly-time').value = '02:00';
    toggleScheduleFields();
    toggleCommandField();
    document.getElementById('st-modal').classList.add('active');
}

function closeModal(e) {
    if (e.target.id === 'st-modal') closeModalDirect();
}

function closeModalDirect() {
    document.getElementById('st-modal').classList.remove('active');
}

function toggleScheduleFields() {
    const type = document.getElementById('st-schedule-type').value;
    const toggle = (id, show) => document.getElementById(id).classList.toggle('hidden', !show);
    toggle('interval-group', type === 'interval');
    toggle('daily-group', type === 'daily');
    toggle('weekly-group', type === 'weekly');
}

function toggleCommandField() {
    const type = document.getElementById('st-task-type').value;
    document.getElementById('command-group').classList.toggle('hidden', type !== 'custom');
}

async function editTask(id) {
    const data = await apiFetch(`/scheduled-tasks/${id}`);
    const st = data.scheduled_task;
    if (!st) return;

    document.getElementById('st-modal-title').textContent = 'スケジュールタスクの編集';
    document.getElementById('st-id').value = st.id;
    document.getElementById('st-name').value = st.name;
    document.getElementById('st-description').value = st.description || '';
    document.getElementById('st-task-type').value = st.task_type;
    document.getElementById('st-command').value = st.command || '';
    document.getElementById('st-pc-name').value = st.pc_name || '';
    document.getElementById('st-schedule-type').value = st.schedule_type;
    document.getElementById('st-interval').value = st.interval_minutes || 60;
    document.getElementById('st-daily-time').value = st.daily_time || '02:00';
    document.getElementById('st-weekly-day').value = st.weekly_day !== null ? st.weekly_day : 0;
    document.getElementById('st-weekly-time').value = st.weekly_time || '02:00';
    document.getElementById('st-enabled').checked = st.is_enabled;
    toggleScheduleFields();
    toggleCommandField();
    document.getElementById('st-modal').classList.add('active');
}

async function submitForm(e) {
    e.preventDefault();
    const id = document.getElementById('st-id').value;
    const scheduleType = document.getElementById('st-schedule-type').value;

    const payload = {
        name: document.getElementById('st-name').value,
        description: document.getElementById('st-description').value,
        task_type: document.getElementById('st-task-type').value,
        command: document.getElementById('st-command').value || null,
        pc_name: document.getElementById('st-pc-name').value || null,
        schedule_type: scheduleType,
        is_enabled: document.getElementById('st-enabled').checked,
    };

    if (scheduleType === 'interval') {
        payload.interval_minutes = parseInt(document.getElementById('st-interval').value, 10);
    } else if (scheduleType === 'daily') {
        payload.daily_time = document.getElementById('st-daily-time').value;
    } else if (scheduleType === 'weekly') {
        payload.weekly_day = parseInt(document.getElementById('st-weekly-day').value, 10);
        payload.weekly_time = document.getElementById('st-weekly-time').value;
    }

    const method = id ? 'PUT' : 'POST';
    const path = id ? `/scheduled-tasks/${id}` : '/scheduled-tasks';
    const data = await apiFetch(path, { method, body: JSON.stringify(payload) });

    if (data.error) { showError(data.error); return; }
    showSuccess(data.message);
    closeModalDirect();
    loadScheduledTasks(currentPage);
}

document.addEventListener('DOMContentLoaded', () => {
    const showCreateBtn = document.getElementById('btn-show-create-st');
    if (showCreateBtn) showCreateBtn.addEventListener('click', showCreateModal);

    const enabledFilter = document.getElementById('enabled-filter');
    if (enabledFilter) enabledFilter.addEventListener('change', () => loadScheduledTasks(1));

    const stModal = document.getElementById('st-modal');
    if (stModal) stModal.addEventListener('click', closeModal);

    const closeStModalBtn = document.getElementById('btn-close-st-modal');
    if (closeStModalBtn) closeStModalBtn.addEventListener('click', closeModalDirect);

    const cancelStModalBtn = document.getElementById('btn-cancel-st-modal');
    if (cancelStModalBtn) cancelStModalBtn.addEventListener('click', closeModalDirect);

    const stTaskType = document.getElementById('st-task-type');
    if (stTaskType) stTaskType.addEventListener('change', toggleCommandField);

    const stScheduleType = document.getElementById('st-schedule-type');
    if (stScheduleType) stScheduleType.addEventListener('change', toggleScheduleFields);

    const stForm = document.getElementById('st-form');
    if (stForm) stForm.addEventListener('submit', submitForm);

    loadScheduledTasks(1);
});
