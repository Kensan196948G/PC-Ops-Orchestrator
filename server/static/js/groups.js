'use strict';

let currentPage = 1;
let currentGroupId = null;

async function loadGroups(page = 1) {
    currentPage = page;
    const data = await apiFetch(`/groups?page=${page}&per_page=20`);
    const tbody = document.getElementById('groups-body');
    tbody.textContent = '';

    if (!data.groups || data.groups.length === 0) {
        const row = tbody.insertRow();
        const cell = row.insertCell();
        cell.colSpan = 6;
        cell.className = 'text-center';
        cell.textContent = 'グループがありません';
        document.getElementById('groups-pagination').textContent = '';
        return;
    }

    for (const g of data.groups) {
        const row = tbody.insertRow();
        row.dataset.id = g.id;
        row.classList.add('row-clickable');
        row.addEventListener('click', (e) => {
            if (e.target.closest('[data-action]')) return;
            openGroupDrawer(g);
        });

        const tdName = row.insertCell();
        const strong = document.createElement('strong');
        strong.textContent = g.name;
        tdName.appendChild(strong);

        row.insertCell().textContent = g.description || '-';

        const tdCount = row.insertCell();
        const countLink = document.createElement('a');
        countLink.href = '#';
        countLink.textContent = `${g.pc_count} 台`;
        countLink.dataset.action = 'members';
        countLink.dataset.id = g.id;
        tdCount.appendChild(countLink);

        row.insertCell().textContent = g.created_by || '-';
        row.insertCell().textContent = g.created_at ? formatDatetime(g.created_at) : '-';

        const tdActions = row.insertCell();
        tdActions.className = 'action-cell';
        tdActions.appendChild(makeBtn('▶', 'btn-secondary btn-xs', 'run-task', g.id, '一括タスク実行', 'role-admin-only'));
        tdActions.appendChild(makeBtn('✎', 'btn-secondary btn-xs', 'edit', g.id, '編集', 'role-admin-only'));
        tdActions.appendChild(makeBtn('✕', 'btn-danger btn-xs', 'delete', g.id, '削除', 'role-admin-only'));
    }

    renderPagination('groups-pagination', data.page, data.pages, loadGroups);
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

document.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const id = parseInt(btn.dataset.id, 10);
    const action = btn.dataset.action;

    if (action === 'members') {
        e.preventDefault();
        await openMembersModal(id);
    } else if (action === 'run-task') {
        openGroupTaskModal(id);
    } else if (action === 'edit') {
        await editGroup(id);
    } else if (action === 'delete') {
        const name = btn.closest('tr')?.querySelector('strong')?.textContent || '';
        if (!confirm(`「${name}」を削除しますか？`)) return;
        const data = await apiFetch(`/groups/${id}`, { method: 'DELETE' });
        if (data.error) { showError(data.error); return; }
        showSuccess(data.message);
        loadGroups(currentPage);
    } else if (action === 'remove-pc') {
        const pcId = parseInt(btn.dataset.pcId, 10);
        const data = await apiFetch(`/groups/${currentGroupId}/pcs/${pcId}`, { method: 'DELETE' });
        if (data.error) { showError(data.error); return; }
        await openMembersModal(currentGroupId);
    }
});

function showCreateModal() {
    document.getElementById('group-modal-title').textContent = 'グループの作成';
    document.getElementById('group-form').reset();
    document.getElementById('group-id').value = '';
    document.getElementById('group-modal').classList.add('active');
}

function closeGroupModal(e) {
    if (e.target.id === 'group-modal') closeGroupModalDirect();
}

function closeGroupModalDirect() {
    document.getElementById('group-modal').classList.remove('active');
}

async function editGroup(id) {
    const data = await apiFetch(`/groups/${id}`);
    const g = data.group;
    if (!g) return;
    document.getElementById('group-modal-title').textContent = 'グループの編集';
    document.getElementById('group-id').value = g.id;
    document.getElementById('group-name').value = g.name;
    document.getElementById('group-description').value = g.description || '';
    document.getElementById('group-pc-names').value = (g.pcs || []).map(p => p.pc_name).join(', ');
    document.getElementById('group-modal').classList.add('active');
}

async function submitGroupForm(e) {
    e.preventDefault();
    const id = document.getElementById('group-id').value;
    const rawPcNames = document.getElementById('group-pc-names').value;
    const pc_names = rawPcNames.split(',').map(s => s.trim()).filter(Boolean);

    const payload = {
        name: document.getElementById('group-name').value,
        description: document.getElementById('group-description').value,
        pc_names,
    };

    const method = id ? 'PUT' : 'POST';
    const path = id ? `/groups/${id}` : '/groups';
    const data = await apiFetch(path, { method, body: JSON.stringify(payload) });
    if (data.error) { showError(data.error); return; }
    showSuccess(data.message);
    closeGroupModalDirect();
    loadGroups(currentPage);
}

// Group Task Modal
function openGroupTaskModal(groupId) {
    document.getElementById('group-task-group-id').value = groupId;
    document.getElementById('group-task-form').reset();
    toggleGroupTaskCommand();
    document.getElementById('group-task-modal').classList.add('active');
}

function closeGroupTaskModal(e) {
    if (e.target.id === 'group-task-modal') closeGroupTaskModalDirect();
}

function closeGroupTaskModalDirect() {
    document.getElementById('group-task-modal').classList.remove('active');
}

function toggleGroupTaskCommand() {
    const type = document.getElementById('group-task-type').value;
    const el = document.getElementById('group-command-group');
    type === 'custom' ? el.classList.remove('hidden') : el.classList.add('hidden');
}

async function submitGroupTask(e) {
    e.preventDefault();
    const groupId = document.getElementById('group-task-group-id').value;
    const taskType = document.getElementById('group-task-type').value;
    const command = document.getElementById('group-task-command').value || null;

    const payload = { task_type: taskType };
    if (command) payload.command = command;

    const data = await apiFetch(`/groups/${groupId}/tasks`, { method: 'POST', body: JSON.stringify(payload) });
    if (data.error) { showError(data.error); return; }
    showSuccess(data.message);
    closeGroupTaskModalDirect();
}

// Members Modal
async function openMembersModal(groupId) {
    currentGroupId = groupId;
    const data = await apiFetch(`/groups/${groupId}`);
    const g = data.group;
    if (!g) return;

    document.getElementById('members-modal-title').textContent = `所属 PC — ${g.name}`;
    document.getElementById('add-pc-name').value = '';

    const tbody = document.getElementById('members-body');
    tbody.textContent = '';
    for (const pc of (g.pcs || [])) {
        const row = tbody.insertRow();
        row.insertCell().textContent = pc.pc_name;
        const tdStatus = row.insertCell();
        const badge = document.createElement('span');
        badge.className = pc.status === 'healthy' ? 'badge badge-success' : 'badge badge-secondary';
        badge.textContent = pc.status || '-';
        tdStatus.appendChild(badge);
        const tdOp = row.insertCell();
        const btn = document.createElement('button');
        btn.className = 'btn btn-danger btn-xs role-admin-only';
        btn.textContent = '削除';
        btn.dataset.action = 'remove-pc';
        btn.dataset.id = groupId;
        btn.dataset.pcId = pc.id;
        tdOp.appendChild(btn);
    }
    if ((g.pcs || []).length === 0) {
        const row = tbody.insertRow();
        const cell = row.insertCell();
        cell.colSpan = 3;
        cell.className = 'text-center text-muted';
        cell.textContent = 'PC が登録されていません';
    }

    document.getElementById('members-modal').classList.add('active');
}

async function addPcToGroup() {
    const pcName = document.getElementById('add-pc-name').value.trim();
    if (!pcName) return;
    const data = await apiFetch(`/groups/${currentGroupId}/pcs`, {
        method: 'POST',
        body: JSON.stringify({ pc_name: pcName }),
    });
    if (data.error) { showError(data.error); return; }
    showSuccess(data.message);
    await openMembersModal(currentGroupId);
}

function closeMembersModal(e) {
    if (e.target.id === 'members-modal') closeMembersModalDirect();
}

function closeMembersModalDirect() {
    document.getElementById('members-modal').classList.remove('active');
    currentGroupId = null;
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

document.addEventListener('DOMContentLoaded', () => {
    const createGroupBtn = document.getElementById('btn-create-group');
    if (createGroupBtn) createGroupBtn.addEventListener('click', showCreateModal);

    // Group modal
    const groupModal = document.getElementById('group-modal');
    if (groupModal) groupModal.addEventListener('click', closeGroupModal);

    const closeGroupModalBtn = document.getElementById('btn-close-group-modal');
    if (closeGroupModalBtn) closeGroupModalBtn.addEventListener('click', closeGroupModalDirect);

    const cancelGroupModalBtn = document.getElementById('btn-cancel-group-modal');
    if (cancelGroupModalBtn) cancelGroupModalBtn.addEventListener('click', closeGroupModalDirect);

    const groupForm = document.getElementById('group-form');
    if (groupForm) groupForm.addEventListener('submit', submitGroupForm);

    // Group task modal
    const groupTaskModal = document.getElementById('group-task-modal');
    if (groupTaskModal) groupTaskModal.addEventListener('click', closeGroupTaskModal);

    const closeGroupTaskModalBtn = document.getElementById('btn-close-group-task-modal');
    if (closeGroupTaskModalBtn) closeGroupTaskModalBtn.addEventListener('click', closeGroupTaskModalDirect);

    const cancelGroupTaskModalBtn = document.getElementById('btn-cancel-group-task-modal');
    if (cancelGroupTaskModalBtn) cancelGroupTaskModalBtn.addEventListener('click', closeGroupTaskModalDirect);

    const groupTaskType = document.getElementById('group-task-type');
    if (groupTaskType) groupTaskType.addEventListener('change', toggleGroupTaskCommand);

    const groupTaskForm = document.getElementById('group-task-form');
    if (groupTaskForm) groupTaskForm.addEventListener('submit', submitGroupTask);

    // Members modal
    const membersModal = document.getElementById('members-modal');
    if (membersModal) membersModal.addEventListener('click', closeMembersModal);

    const closeMembersModalBtn = document.getElementById('btn-close-members-modal');
    if (closeMembersModalBtn) closeMembersModalBtn.addEventListener('click', closeMembersModalDirect);

    const addPcBtn = document.getElementById('btn-add-pc-to-group');
    if (addPcBtn) addPcBtn.addEventListener('click', addPcToGroup);

    document.getElementById('btn-close-group-drawer')?.addEventListener('click', closeGroupDrawer);
    document.getElementById('btn-close-group-drawer-footer')?.addEventListener('click', closeGroupDrawer);
    document.getElementById('group-drawer-overlay')?.addEventListener('click', e => {
        if (e.target === e.currentTarget) closeGroupDrawer();
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeGroupDrawer(); });

    loadGroups(1);
});

// ── Drawer ──────────────────────────────────────────────────────────────────

function openGroupDrawer(g) {
    const overlay = document.getElementById('group-drawer-overlay');
    const titleEl = document.getElementById('group-drawer-title');
    const bodyEl = document.getElementById('group-drawer-body');
    if (!overlay || !bodyEl) return;

    if (titleEl) titleEl.textContent = g.name;
    bodyEl.textContent = '';

    const kvSection = document.createElement('div');
    const kvHead = document.createElement('div');
    kvHead.className = 'drawer-section-title';
    kvHead.textContent = 'グループ情報';
    kvSection.appendChild(kvHead);

    const dl = document.createElement('dl');
    dl.className = 'kv-grid';
    const pairs = [
        ['説明', g.description || '-'],
        ['PC台数', (g.pc_count ?? '-') + ' 台'],
        ['作成者', g.created_by || '-'],
        ['作成日時', g.created_at ? formatDatetime(g.created_at) : '-'],
    ];
    for (const [k, v] of pairs) {
        const dt = document.createElement('dt'); dt.textContent = k; dl.appendChild(dt);
        const dd = document.createElement('dd'); dd.textContent = v; dl.appendChild(dd);
    }
    kvSection.appendChild(dl);
    bodyEl.appendChild(kvSection);

    overlay.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

function closeGroupDrawer() {
    const overlay = document.getElementById('group-drawer-overlay');
    if (overlay) overlay.classList.add('hidden');
    document.body.style.overflow = '';
}
