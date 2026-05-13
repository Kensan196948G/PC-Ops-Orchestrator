let _editChannelId = null;

const _channelTypeLabels = {
    slack: 'Slack', teams: 'Microsoft Teams',
    email: 'Email', webhook: 'Webhook',
};

function _makeErrorRow(message, cols) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = cols; td.className = 'text-center';
    td.textContent = message;
    tr.appendChild(td);
    return tr;
}

async function loadChannels() {
    const tbody = document.getElementById('notif-channels-body');
    if (!tbody) return;
    try {
        const data = await apiFetch('/notification-channels');
        tbody.replaceChildren();

        // Update stat cards
        const channels = data.channels || [];
        const activeCount = channels.filter(c => c.is_active).length;
        const statActive = document.getElementById('notif-stat-active');
        if (statActive) statActive.textContent = activeCount;

        if (channels.length === 0) {
            tbody.appendChild(_makeErrorRow('チャネルが登録されていません。+ チャネル追加から登録してください。', 6));
            return;
        }

        channels.forEach(ch => {
            const tr = document.createElement('tr');
            const td = t => { const el = document.createElement('td'); el.textContent = t ?? '—'; return el; };

            tr.appendChild(td(ch.name));
            tr.appendChild(td(_channelTypeLabels[ch.channel_type] || ch.channel_type));

            const targetTd = document.createElement('td');
            targetTd.textContent = ch.target.length > 50 ? ch.target.slice(0, 50) + '…' : ch.target;
            targetTd.title = ch.target;
            tr.appendChild(targetTd);

            // sent/fail stats placeholder (API does not expose per-channel counts yet)
            tr.appendChild(td('—'));

            const statusTd = document.createElement('td');
            const badge = document.createElement('span');
            badge.className = 'badge ' + (ch.is_active ? 'badge-success' : 'badge-secondary');
            badge.textContent = ch.is_active ? '有効' : '無効';
            statusTd.appendChild(badge);
            tr.appendChild(statusTd);

            const actionTd = document.createElement('td');
            actionTd.className = 'd-flex-gap';

            const testBtn = document.createElement('button');
            testBtn.className = 'btn btn-secondary text-xs role-admin-only';
            testBtn.textContent = 'テスト送信';
            testBtn.addEventListener('click', () => testSendChannel(ch.id, ch.name));
            actionTd.appendChild(testBtn);

            const editBtn = document.createElement('button');
            editBtn.className = 'btn btn-secondary text-xs role-admin-only';
            editBtn.textContent = '編集';
            editBtn.addEventListener('click', () => openEditModal(ch));
            actionTd.appendChild(editBtn);

            const delBtn = document.createElement('button');
            delBtn.className = 'btn btn-danger text-xs role-admin-only';
            delBtn.textContent = '削除';
            delBtn.addEventListener('click', () => deleteChannel(ch.id, ch.name));
            actionTd.appendChild(delBtn);

            tr.appendChild(actionTd);
            tbody.appendChild(tr);
        });
    } catch (e) {
        if (tbody) tbody.replaceChildren(_makeErrorRow('読み込みに失敗しました', 6));
    }
}

async function testSendChannel(id, name) {
    try {
        await apiFetch(`/notification-channels/${id}/test-send`, { method: 'POST' });
        showSuccess(`「${name}」へテスト送信しました`);
    } catch (e) {
        showError(`テスト送信に失敗しました: ${name}`);
    }
}

function openCreateModal() {
    _editChannelId = null;
    document.getElementById('channel-modal-title').textContent = 'チャネル追加';
    document.getElementById('channel-name').value = '';
    document.getElementById('channel-type').value = 'slack';
    document.getElementById('channel-target').value = '';
    document.getElementById('channel-active').checked = true;
    document.getElementById('channel-modal').classList.add('open');
}

function openEditModal(ch) {
    _editChannelId = ch.id;
    document.getElementById('channel-modal-title').textContent = 'チャネル編集';
    document.getElementById('channel-name').value = ch.name;
    document.getElementById('channel-type').value = ch.channel_type;
    document.getElementById('channel-target').value = ch.target;
    document.getElementById('channel-active').checked = ch.is_active;
    document.getElementById('channel-modal').classList.add('open');
}

function closeChannelModal() {
    document.getElementById('channel-modal').classList.remove('open');
}

async function submitChannel(e) {
    e.preventDefault();
    const payload = {
        name: document.getElementById('channel-name').value.trim(),
        channel_type: document.getElementById('channel-type').value,
        target: document.getElementById('channel-target').value.trim(),
        is_active: document.getElementById('channel-active').checked,
    };
    if (!payload.name || !payload.target) { showError('名前と送信先は必須です'); return; }
    try {
        if (_editChannelId) {
            await apiFetch(`/notification-channels/${_editChannelId}`, { method: 'PUT', body: JSON.stringify(payload) });
            showSuccess('チャネルを更新しました');
        } else {
            await apiFetch('/notification-channels', { method: 'POST', body: JSON.stringify(payload) });
            showSuccess('チャネルを追加しました');
        }
        closeChannelModal();
        loadChannels();
    } catch (e) { showError('保存に失敗しました'); }
}

async function deleteChannel(id, name) {
    if (!confirm(`「${name}」を削除しますか？`)) return;
    try {
        await apiFetch(`/notification-channels/${id}`, { method: 'DELETE' });
        showSuccess('削除しました');
        loadChannels();
    } catch (e) { showError('削除に失敗しました'); }
}

document.addEventListener('DOMContentLoaded', () => {
    loadChannels();
    const addBtn = document.getElementById('btn-add-channel');
    if (addBtn) addBtn.addEventListener('click', openCreateModal);
    ['btn-close-channel-modal', 'btn-close-channel-modal-foot'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('click', closeChannelModal);
    });
    const form = document.getElementById('channel-form');
    if (form) form.addEventListener('submit', submitChannel);
});
