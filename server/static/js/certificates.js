let _editCertId = null;

function _certStatusBadge(daysLeft) {
    if (daysLeft === null || daysLeft === undefined) return '';
    const badge = document.createElement('span');
    if (daysLeft <= 30) { badge.className = 'badge badge-danger'; badge.textContent = `期限 ${daysLeft} 日 ⚠️`; }
    else if (daysLeft <= 90) { badge.className = 'badge badge-warning'; badge.textContent = `期限 ${daysLeft} 日`; }
    else { badge.className = 'badge badge-success'; badge.textContent = '有効'; }
    return badge;
}

function _makeErrorRow(message, cols) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = cols; td.className = 'text-center'; td.textContent = message;
    tr.appendChild(td); return tr;
}

async function loadCerts() {
    const tbody = document.getElementById('certs-body');
    if (!tbody) return;
    try {
        const data = await apiFetch('/certificates');
        tbody.replaceChildren();
        const certs = data.certificates || [];

        // Update stat cards
        const countEl = document.getElementById('cert-stat-count');
        if (countEl) countEl.textContent = certs.length;
        const validEl = document.getElementById('cert-stat-valid');
        if (validEl) validEl.textContent = certs.filter(c => c.days_left == null || c.days_left > 90).length;
        const expiringEl = document.getElementById('cert-stat-expiring');
        if (expiringEl) expiringEl.textContent = certs.filter(c => c.days_left != null && c.days_left > 30 && c.days_left <= 90).length;
        const criticalEl = document.getElementById('cert-stat-critical');
        if (criticalEl) criticalEl.textContent = certs.filter(c => c.days_left != null && c.days_left <= 30).length;

        if (certs.length === 0) {
            tbody.appendChild(_makeErrorRow('証明書が登録されていません。+ 証明書を登録から追加してください。', 7));
            return;
        }
        certs.forEach(c => {
            const tr = document.createElement('tr');
            const td = t => { const el = document.createElement('td'); el.textContent = t ?? '—'; return el; };
            tr.appendChild(td(c.domain));
            tr.appendChild(td(c.issuer));
            tr.appendChild(td(c.issued_at));
            tr.appendChild(td(c.expires_at));
            tr.appendChild(td(c.days_left != null ? c.days_left + ' 日' : '—'));
            const statusTd = document.createElement('td');
            const badge = _certStatusBadge(c.days_left);
            if (badge) statusTd.appendChild(badge);
            tr.appendChild(statusTd);
            const actionTd = document.createElement('td');
            actionTd.className = 'd-flex-gap';
            const editBtn = document.createElement('button');
            editBtn.className = 'btn btn-secondary text-xs role-admin-only';
            editBtn.textContent = '編集';
            editBtn.addEventListener('click', () => openEditCertModal(c));
            actionTd.appendChild(editBtn);
            const delBtn = document.createElement('button');
            delBtn.className = 'btn btn-danger text-xs role-admin-only';
            delBtn.textContent = '削除';
            delBtn.addEventListener('click', () => deleteCert(c.id, c.domain));
            actionTd.appendChild(delBtn);
            tr.appendChild(actionTd);
            tbody.appendChild(tr);
        });
    } catch(e) {
        if (tbody) tbody.replaceChildren(_makeErrorRow('読み込みに失敗しました', 7));
    }
}

function openCreateCertModal() {
    _editCertId = null;
    document.getElementById('cert-modal-title').textContent = '証明書を登録';
    ['cert-name','cert-domain','cert-issuer','cert-issued-at','cert-expires-at','cert-notes'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    document.getElementById('cert-type').value = 'server';
    document.getElementById('cert-auto-renew').checked = true;
    document.getElementById('cert-modal').classList.add('open');
}

function openEditCertModal(c) {
    _editCertId = c.id;
    document.getElementById('cert-modal-title').textContent = '証明書を編集';
    document.getElementById('cert-name').value = c.name || '';
    document.getElementById('cert-domain').value = c.domain || '';
    document.getElementById('cert-issuer').value = c.issuer || '';
    document.getElementById('cert-type').value = c.cert_type || 'server';
    document.getElementById('cert-issued-at').value = c.issued_at || '';
    document.getElementById('cert-expires-at').value = c.expires_at || '';
    document.getElementById('cert-auto-renew').checked = !!c.auto_renew;
    document.getElementById('cert-notes').value = c.notes || '';
    document.getElementById('cert-modal').classList.add('open');
}

function closeCertModal() {
    document.getElementById('cert-modal').classList.remove('open');
}

async function submitCert(e) {
    e.preventDefault();
    const payload = {
        name: document.getElementById('cert-name').value.trim(),
        domain: document.getElementById('cert-domain').value.trim(),
        issuer: document.getElementById('cert-issuer').value.trim() || null,
        cert_type: document.getElementById('cert-type').value,
        issued_at: document.getElementById('cert-issued-at').value || null,
        expires_at: document.getElementById('cert-expires-at').value,
        auto_renew: document.getElementById('cert-auto-renew').checked,
        notes: document.getElementById('cert-notes').value.trim() || null,
    };
    if (!payload.domain || !payload.expires_at) { showError('ドメインと有効期限は必須です'); return; }
    try {
        if (_editCertId) {
            await apiFetch(`/certificates/${_editCertId}`, { method: 'PUT', body: JSON.stringify(payload) });
            showSuccess('証明書を更新しました');
        } else {
            await apiFetch('/certificates', { method: 'POST', body: JSON.stringify(payload) });
            showSuccess('証明書を登録しました');
        }
        closeCertModal();
        loadCerts();
    } catch(e) { showError('保存に失敗しました'); }
}

async function deleteCert(id, domain) {
    if (!confirm(`「${domain}」の証明書を削除しますか？`)) return;
    try {
        await apiFetch(`/certificates/${id}`, { method: 'DELETE' });
        showSuccess('削除しました');
        loadCerts();
    } catch(e) { showError('削除に失敗しました'); }
}

document.addEventListener('DOMContentLoaded', () => {
    loadCerts();
    const addBtn = document.getElementById('btn-add-cert');
    if (addBtn) addBtn.addEventListener('click', openCreateCertModal);
    ['btn-close-cert-modal', 'btn-close-cert-modal-foot'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('click', closeCertModal);
    });
    const form = document.getElementById('cert-form');
    if (form) form.addEventListener('submit', submitCert);
});
