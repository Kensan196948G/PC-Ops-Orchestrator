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
    try {
        const data = await apiFetch('/licenses');
        tbody.replaceChildren();

        const licenses = data.licenses || [];

        if (licenses.length === 0) {
            tbody.appendChild(_makeErrorRow('ライセンスが登録されていません。+ ライセンス登録から追加してください。', 8));
        } else {
            licenses.forEach(lic => {
                const tr = document.createElement('tr');
                tr.classList.add('row-clickable');
                tr.addEventListener('click', (e) => {
                    if (e.target.closest('button')) return;
                    openLicenseDrawer(lic);
                });
                const td = t => { const el = document.createElement('td'); el.textContent = t ?? '—'; return el; };
                tr.appendChild(td(lic.product_name));
                tr.appendChild(td(lic.vendor));
                tr.appendChild(td(_licenseTypeLabels[lic.license_type] || lic.license_type));
                tr.appendChild(td(lic.seat_count != null ? lic.seat_count + ' 席' : '—'));
                tr.appendChild(td(_formatYen(lic.unit_price)));
                tr.appendChild(td(_formatYen(lic.total_cost)));
                tr.appendChild(td(lic.expires_at || '永続'));

                const actionTd = document.createElement('td');
                actionTd.className = 'd-flex-gap';
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
        }

        // Update stat cards
        const countEl = document.getElementById('lic-stat-count');
        if (countEl) countEl.textContent = licenses.length;

        const totalCost = licenses.reduce((s, l) => s + (l.total_cost || 0), 0);
        const costEl = document.getElementById('lic-stat-cost');
        if (costEl) costEl.textContent = _formatYen(totalCost);

        const now = new Date();
        const in90 = new Date(now.getTime() + 90 * 24 * 60 * 60 * 1000);
        const expiringCount = licenses.filter(l => {
            if (!l.expires_at) return false;
            const d = new Date(l.expires_at);
            return d >= now && d <= in90;
        }).length;
        const expiringEl = document.getElementById('lic-stat-expiring');
        if (expiringEl) expiringEl.textContent = expiringCount;

        // "over" stat is not available from API; show placeholder
        const overEl = document.getElementById('lic-stat-over');
        if (overEl) overEl.textContent = '—';

        const totalEl = document.getElementById('licenses-total');
        if (totalEl) totalEl.textContent = _formatYen(totalCost);
    } catch (e) {
        if (tbody) tbody.replaceChildren(_makeErrorRow('読み込みに失敗しました', 8));
    }
}

function openCreateLicenseModal() {
    _editLicenseId = null;
    document.getElementById('license-modal-title').textContent = 'ライセンス登録';
    ['license-product', 'license-vendor', 'license-seats', 'license-price', 'license-expires', 'license-notes'].forEach(id => {
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
    } catch (e) { showError('保存に失敗しました'); }
}

async function deleteLicense(id, name) {
    if (!confirm(`「${name}」を削除しますか？`)) return;
    try {
        await apiFetch(`/licenses/${id}`, { method: 'DELETE' });
        showSuccess('削除しました');
        loadLicenses();
    } catch (e) { showError('削除に失敗しました'); }
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

    document.getElementById('btn-csv-licenses')?.addEventListener('click', async () => {
        try {
            const res = await apiFetchRaw('/licenses/export.csv');
            if (!res.ok) { showError('CSVダウンロードに失敗しました'); return; }
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = 'licenses.csv'; a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            showError('CSVダウンロードに失敗しました');
        }
    });

    document.getElementById('btn-close-license-drawer')?.addEventListener('click', closeLicenseDrawer);
    document.getElementById('btn-close-license-drawer-footer')?.addEventListener('click', closeLicenseDrawer);
    document.getElementById('license-drawer-overlay')?.addEventListener('click', e => {
        if (e.target === e.currentTarget) closeLicenseDrawer();
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLicenseDrawer(); });
});

// ── Drawer ──────────────────────────────────────────────────────────────────

function openLicenseDrawer(lic) {
    const overlay = document.getElementById('license-drawer-overlay');
    const titleEl = document.getElementById('license-drawer-title');
    const bodyEl = document.getElementById('license-drawer-body');
    if (!overlay || !bodyEl) return;

    if (titleEl) titleEl.textContent = lic.product_name || '-';
    bodyEl.textContent = '';

    const kvSection = document.createElement('div');
    const kvHead = document.createElement('div');
    kvHead.className = 'drawer-section-title';
    kvHead.textContent = 'ライセンス情報';
    kvSection.appendChild(kvHead);

    const dl = document.createElement('dl');
    dl.className = 'kv-grid';
    const pairs = [
        ['ベンダー', lic.vendor || '-'],
        ['種別', _licenseTypeLabels[lic.license_type] || lic.license_type || '-'],
        ['契約席数', lic.seat_count != null ? lic.seat_count + ' 席' : '-'],
        ['単価', _formatYen(lic.unit_price)],
        ['合計コスト', _formatYen(lic.total_cost)],
        ['有効期限', lic.expires_at || '永続'],
    ];
    for (const [k, v] of pairs) {
        const dt = document.createElement('dt'); dt.textContent = k; dl.appendChild(dt);
        const dd = document.createElement('dd'); dd.textContent = v; dl.appendChild(dd);
    }
    kvSection.appendChild(dl);
    bodyEl.appendChild(kvSection);

    if (lic.notes) {
        const noteSection = document.createElement('div');
        const noteHead = document.createElement('div');
        noteHead.className = 'drawer-section-title';
        noteHead.textContent = '備考';
        noteSection.appendChild(noteHead);
        const pre = document.createElement('pre');
        pre.style.cssText = 'font-size:0.78rem;white-space:pre-wrap;word-break:break-word;' +
            'background:var(--bg-tertiary);border:1px solid var(--border);' +
            'border-radius:var(--radius);padding:0.75rem;color:var(--text-secondary);';
        pre.textContent = lic.notes;
        noteSection.appendChild(pre);
        bodyEl.appendChild(noteSection);
    }

    overlay.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

function closeLicenseDrawer() {
    const overlay = document.getElementById('license-drawer-overlay');
    if (overlay) overlay.classList.add('hidden');
    document.body.style.overflow = '';
}
