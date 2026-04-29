function formatTime(iso) {
    if (!iso) return '-';
    return new Date(iso).toLocaleString('ja-JP');
}

function roleBadge(role) {
    const span = document.createElement('span');
    span.className = 'status-badge ' + (role === 'admin' ? 'status-critical' : 'status-healthy');
    span.textContent = role;
    return span;
}

function activeBadge(isActive) {
    const span = document.createElement('span');
    span.className = 'status-badge ' + (isActive ? 'status-healthy' : 'status-unknown');
    span.textContent = isActive ? '有効' : '無効';
    return span;
}

async function loadUsers() {
    const tbody = document.getElementById('user-table-body');
    try {
        const data = await apiFetch('/auth/users');
        tbody.replaceChildren();

        const currentUser = JSON.parse(localStorage.getItem('user') || '{}');

        if (data.users && data.users.length > 0) {
            data.users.forEach(u => {
                const tr = document.createElement('tr');
                const td = (text) => {
                    const el = document.createElement('td');
                    el.textContent = text;
                    return el;
                };

                tr.appendChild(td(u.id));
                tr.appendChild(td(u.username));

                const roleTd = document.createElement('td');
                roleTd.appendChild(roleBadge(u.role));
                tr.appendChild(roleTd);

                const activeTd = document.createElement('td');
                activeTd.appendChild(activeBadge(u.is_active));
                tr.appendChild(activeTd);

                tr.appendChild(td(formatTime(u.created_at)));

                const actionTd = document.createElement('td');
                if (u.id !== currentUser.id) {
                    const editBtn = document.createElement('button');
                    editBtn.className = 'btn btn-secondary role-admin-only';
                    editBtn.style.marginRight = '4px';
                    editBtn.textContent = '編集';
                    editBtn.addEventListener('click', () => openEditModal(u));
                    actionTd.appendChild(editBtn);

                    const delBtn = document.createElement('button');
                    delBtn.className = 'btn btn-danger role-admin-only';
                    delBtn.textContent = '削除';
                    delBtn.addEventListener('click', () => deleteUser(u.id, u.username));
                    actionTd.appendChild(delBtn);
                } else {
                    actionTd.textContent = '（自分）';
                    actionTd.style.color = 'var(--text-muted)';
                }
                tr.appendChild(actionTd);
                tbody.appendChild(tr);
            });
        } else {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 6;
            td.className = 'text-center';
            td.textContent = 'ユーザーが登録されていません';
            tr.appendChild(td);
            tbody.appendChild(tr);
        }
    } catch (e) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 6;
        td.className = 'text-center';
        td.style.color = 'var(--danger)';
        td.textContent = '読み込みに失敗しました';
        tr.appendChild(td);
        tbody.replaceChildren(tr);
    }
}

function openCreateModal() {
    document.getElementById('new-username').value = '';
    document.getElementById('new-password').value = '';
    document.getElementById('new-role').value = 'operator';
    document.getElementById('create-modal').style.display = 'flex';
}

function closeCreateModal() {
    document.getElementById('create-modal').style.display = 'none';
}

async function submitCreate() {
    const username = document.getElementById('new-username').value.trim();
    const password = document.getElementById('new-password').value;
    const role = document.getElementById('new-role').value;

    if (!username || !password) {
        showError('ユーザー名とパスワードを入力してください');
        return;
    }

    try {
        const data = await apiFetch('/auth/users', {
            method: 'POST',
            body: JSON.stringify({ username, password, role }),
        });
        if (data.error) {
            showError(data.error);
            return;
        }
        showSuccess('ユーザーを作成しました');
        closeCreateModal();
        loadUsers();
    } catch (e) {
        showError('作成に失敗しました');
    }
}

function openEditModal(user) {
    document.getElementById('edit-user-id').value = user.id;
    document.getElementById('edit-role').value = user.role;
    document.getElementById('edit-active').value = user.is_active ? 'true' : 'false';
    document.getElementById('edit-password').value = '';
    document.getElementById('edit-modal').style.display = 'flex';
}

function closeEditModal() {
    document.getElementById('edit-modal').style.display = 'none';
}

async function submitEdit() {
    const userId = document.getElementById('edit-user-id').value;
    const role = document.getElementById('edit-role').value;
    const isActive = document.getElementById('edit-active').value === 'true';
    const password = document.getElementById('edit-password').value;

    const body = { role, is_active: isActive };
    if (password) body.password = password;

    try {
        const data = await apiFetch(`/auth/users/${userId}`, {
            method: 'PATCH',
            body: JSON.stringify(body),
        });
        if (data.error) {
            showError(data.error);
            return;
        }
        showSuccess('ユーザーを更新しました');
        closeEditModal();
        loadUsers();
    } catch (e) {
        showError('更新に失敗しました');
    }
}

async function deleteUser(userId, username) {
    if (!confirm(`ユーザー「${username}」を削除しますか？`)) return;

    try {
        const data = await apiFetch(`/auth/users/${userId}`, { method: 'DELETE' });
        if (data.error) {
            showError(data.error);
            return;
        }
        showSuccess(data.message);
        loadUsers();
    } catch (e) {
        showError('削除に失敗しました');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const currentUser = JSON.parse(localStorage.getItem('user') || '{}');
    if (currentUser.role !== 'admin') {
        window.location.href = '/';
        return;
    }
    loadUsers();
});
