let _editLicenseId = null;

const _licenseTypeLabels = { subscription: 'サブスクリプション', perpetual: '永続ライセンス', volume: 'ボリューム' };

function _makeErrorRow(message, cols) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = cols; td.className = 'text-center'; td.textContent = message;
    tr.appendChild(td); return tr;
}

function _formatYen(v) {
    if (v == null) return '—';
    return '¥' + Number(v).toLocaleString('ja-JP');
}

async function loadLicenses() {
    const tbody = document.getElementById('licenses-body');
    if (!tbody) return;
    let total = 0;
    try {
        const data = await apiFetch('/licenses');
        tbody.replaceChildren();
        if (!data.licenses || data.licenses.length === 0) {
            tbody.appendChild(_makeErrorRow('ライセンスが登録されていません。+ ライセンス登録から追加してください。', 7));
            return;
        }
        data.licenses.forEach(lic => {
            total += lic.total_cost || 0;
            const tr = document.createElement('tr');
            const td = t => { const el = document.createElement('td'); el.textContent = t ?? '—'; return el; };
            tr.appendChild(td(lic.product_name));
            tr.appendChild(td(lic.vendor));
            tr.appendChild(td(_licenseTypeLabels[lic.license_type] || lic.license_type));
            tr.appendChild(td(lic.seat_count != null ? lic.seat_count + ' 席' : '—'));
            tr.appendChild(td(_formatYen(lic.unit_price)));
            tr.appendChild(td(_formatYen(lic.total_cost)));
            tr.appendChild(td(lic.expires_at || '永続'));
            const actionTd = document.createElement('td');
            actionTd.style.display = 'flex'; actionTd.style.gap = '4px';
            const editBtn = document.createElement('button');
            editBtn.className = 'btn btn-secondary text-xs role-admin-only';
            editBtn.textContent = '編集';
            editBtn.addEventListener('click', () => openEditLicenseModal(lic));
            actionTd.appendChild(editBtn);
            const delBtn = document.createElement('button');
            delBtn.className = 'btn btn-danger text-xs role-admin-only';
            delBtn.textContent = '削除';
            delBtn.addEventListener('click', () => deleteLicense(lic.id, lic.product_name));
            actionTd.appendChild(delBtn);
            tr.appendChild(actionTd);
            tbody.appendChild(tr);
        });
        const totalEl = document.getElementById('licenses-total');
        if (totalEl) totalEl.textContent = _formatYen(total);
    } catch(e) {
        if (tbody) tbody.replaceChildren(_makeErrorRow('読み込みに失敗しました', 7));
    }
}

function openCreateLicenseModal() {
    _editLicenseId = null;
    document.getElementById('license-modal-title').textContent = 'ライセンス登録';
    ['license-product','license-vendor','license-seats','license-price','license-expires','license-notes'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    document.getElementById('license-type').value = 'subscription';
    document.getElementById('license-modal').classList.add('open');
}

function openEditLicenseModal(lic) {
    _editLicenseId = lic.id;
    document.getElementById('license-modal-title').textContent = 'ライセンス編集';
    document.getElementById('license-product').value = lic.product_name || '';
    document.getElementById('license-vendor').value = lic.vendor || '';
    document.getElementById('license-type').value = lic.license_type || 'subscription';
    document.getElementById('license-seats').value = lic.seat_count || '';
    document.getElementById('license-price').value = lic.unit_price || '';
    document.getElementById('license-expires').value = lic.expires_at || '';
    document.getElementById('license-notes').value = lic.notes || '';
    document.getElementById('license-modal').classList.add('open');
}

function closeLicenseModal() {
    document.getElementById('license-modal').classList.remove('open');
}

async function submitLicense(e) {
    e.preventDefault();
    const payload = {
        product_name: document.getElementById('license-product').value.trim(),
        vendor: document.getElementById('license-vendor').value.trim() || null,
        license_type: document.getElementById('license-type').value,
        seat_count: parseInt(document.getElementById('license-seats').value) || null,
        unit_price: parseInt(document.getElementById('license-price').value) || null,
        expires_at: document.getElementById('license-expires').value || null,
        notes: document.getElementById('license-notes').value.trim() || null,
    };
    if (!payload.product_name) { showError('製品名は必須です'); return; }
    try {
        if (_editLicenseId) {
            await apiFetch(`/licenses/${_editLicenseId}`, { method: 'PUT', body: JSON.stringify(payload) });
            showSuccess('ライセンスを更新しました');
        } else {
            await apiFetch('/licenses', { method: 'POST', body: JSON.stringify(payload) });
            showSuccess('ライセンスを登録しました');
        }
        closeLicenseModal();
        loadLicenses();
    } catch(e) { showError('保存に失敗しました'); }
}

async function deleteLicense(id, name) {
    if (!confirm(`「${name}」を削除しますか？`)) return;
    try {
        await apiFetch(`/licenses/${id}`, { method: 'DELETE' });
        showSuccess('削除しました');
        loadLicenses();
    } catch(e) { showError('削除に失敗しました'); }
}

document.addEventListener('DOMContentLoaded', () => {
    loadLicenses();
    const addBtn = document.getElementById('btn-add-license');
    if (addBtn) addBtn.addEventListener('click', openCreateLicenseModal);
    ['btn-close-license-modal', 'btn-close-license-modal-foot'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('click', closeLicenseModal);
    });
    const form = document.getElementById('license-form');
    if (form) form.addEventListener('submit', submitLicense);
});
