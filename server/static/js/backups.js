function _fmtSize(bytes) {
    if (bytes == null) return '—';
    if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + ' GB';
    if (bytes >= 1e6) return (bytes / 1e6).toFixed(0) + ' MB';
    return (bytes / 1e3).toFixed(0) + ' KB';
}

function _fmtDuration(secs) {
    if (secs == null) return '—';
    const m = Math.floor(secs / 60), s = secs % 60;
    return `${m} 分 ${String(s).padStart(2, '0')} 秒`;
}

async function loadBackups() {
    const tbody = document.getElementById('backups-body');
    if (!tbody) return;
    try {
        const data = await apiFetch('/backups');
        tbody.replaceChildren();
        const jobs = data.backups || [];

        // Stat cards
        const now = new Date();
        const ago7d = new Date(now.getTime() - 7 * 86400 * 1000);
        const recent = jobs.filter(j => j.started_at && new Date(j.started_at) >= ago7d);
        const suc7d = recent.filter(j => j.status === 'success').length;
        const fail7d = recent.filter(j => j.status === 'failed').length;
        const lastSuccess = jobs.find(j => j.status === 'success');

        const s7 = document.getElementById('backup-stat-success7d');
        if (s7) s7.textContent = suc7d;
        const total = document.getElementById('backup-stat-total');
        if (total) total.textContent = data.total ?? jobs.length;
        const f7 = document.getElementById('backup-stat-failed7d');
        if (f7) f7.textContent = fail7d;
        const last = document.getElementById('backup-stat-last');
        if (last) last.textContent = lastSuccess
            ? new Date(lastSuccess.started_at).toLocaleString('ja-JP', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
            : '—';

        if (jobs.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 7; td.className = 'text-center';
            td.textContent = 'バックアップ履歴がありません。▶ 即時バックアップで実行してください。';
            tr.appendChild(td); tbody.appendChild(tr);
            return;
        }

        jobs.forEach(j => {
            const tr = document.createElement('tr');
            tr.classList.add('row-clickable');
            tr.addEventListener('click', () => openBackupDrawer(j));
            const td = t => { const el = document.createElement('td'); el.textContent = t ?? '—'; return el; };
            tr.appendChild(td(j.started_at ? new Date(j.started_at).toLocaleString('ja-JP') : '—'));
            tr.appendChild(td(j.backup_type));
            tr.appendChild(td(j.target));
            tr.appendChild(td(_fmtSize(j.size_bytes)));
            tr.appendChild(td(_fmtDuration(j.duration_seconds)));
            tr.appendChild(td(j.storage_path));
            const statusTd = document.createElement('td');
            const badge = document.createElement('span');
            if (j.status === 'success') { badge.className = 'badge badge-success'; badge.textContent = '成功'; }
            else if (j.status === 'running') { badge.className = 'badge badge-info'; badge.textContent = '実行中'; }
            else { badge.className = 'badge badge-danger'; badge.textContent = '失敗'; }
            statusTd.appendChild(badge); tr.appendChild(statusTd);
            tbody.appendChild(tr);
        });
    } catch (e) {
        if (tbody) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 7; td.className = 'text-center text-danger';
            td.textContent = '読み込みに失敗しました';
            tr.appendChild(td); tbody.appendChild(tr);
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadBackups();

    document.getElementById('btn-trigger-backup')?.addEventListener('click', async () => {
        if (!confirm('即時バックアップを実行しますか？')) return;
        try {
            await apiFetch('/backups/trigger', { method: 'POST' });
            showSuccess('バックアップを実行しました');
            loadBackups();
        } catch (e) { showError('バックアップに失敗しました'); }
    });

    document.getElementById('btn-integrity-check')?.addEventListener('click', async () => {
        try {
            const data = await apiFetch('/backups/integrity-check', { method: 'POST' });
            if (data.ok) showSuccess('整合性チェック: OK');
            else showError('整合性チェック: エラーあり — ' + (data.result || []).join(', '));
        } catch (e) { showError('整合性チェックに失敗しました'); }
    });

    document.getElementById('btn-restore')?.addEventListener('click', () => {
        const dt = document.getElementById('restore-datetime')?.value;
        const target = document.getElementById('restore-target')?.value;
        if (!dt) { showError('復元日時を指定してください'); return; }
        if (!confirm(`「${target}」に ${dt} 時点のデータをリストアします。よろしいですか？`)) return;
        const resultEl = document.getElementById('restore-result');
        if (resultEl) resultEl.textContent = `リストアリクエストを受け付けました: ${target} ← ${dt}`;
        showSuccess('リストアリクエストを受け付けました');
    });

    document.getElementById('btn-close-backup-drawer')?.addEventListener('click', closeBackupDrawer);
    document.getElementById('btn-close-backup-drawer-footer')?.addEventListener('click', closeBackupDrawer);
    document.getElementById('backup-drawer-overlay')?.addEventListener('click', e => {
        if (e.target === e.currentTarget) closeBackupDrawer();
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeBackupDrawer(); });
});

// ── Drawer ──────────────────────────────────────────────────────────────────

function openBackupDrawer(j) {
    const overlay = document.getElementById('backup-drawer-overlay');
    const titleEl = document.getElementById('backup-drawer-title');
    const bodyEl = document.getElementById('backup-drawer-body');
    if (!overlay || !bodyEl) return;

    const label = j.status === 'success' ? '成功' : j.status === 'running' ? '実行中' : '失敗';
    if (titleEl) titleEl.textContent = (j.backup_type || '-') + ' — ' + label;

    bodyEl.textContent = '';

    const kvSection = document.createElement('div');
    const kvHead = document.createElement('div');
    kvHead.className = 'drawer-section-title';
    kvHead.textContent = 'バックアップ情報';
    kvSection.appendChild(kvHead);

    const dl = document.createElement('dl');
    dl.className = 'kv-grid';
    const pairs = [
        ['実行日時', j.started_at ? new Date(j.started_at).toLocaleString('ja-JP') : '-'],
        ['種別', j.backup_type || '-'],
        ['対象', j.target || '-'],
        ['サイズ', _fmtSize(j.size_bytes)],
        ['所要時間', _fmtDuration(j.duration_seconds)],
        ['保存先', j.storage_path || '-'],
        ['状態', label],
    ];
    for (const [k, v] of pairs) {
        const dt = document.createElement('dt'); dt.textContent = k; dl.appendChild(dt);
        const dd = document.createElement('dd'); dd.textContent = v; dl.appendChild(dd);
    }
    kvSection.appendChild(dl);
    bodyEl.appendChild(kvSection);

    if (j.error_message) {
        const errSection = document.createElement('div');
        const errHead = document.createElement('div');
        errHead.className = 'drawer-section-title';
        errHead.textContent = 'エラー詳細';
        errSection.appendChild(errHead);
        const pre = document.createElement('pre');
        pre.style.cssText = 'font-size:0.78rem;white-space:pre-wrap;word-break:break-word;' +
            'background:var(--danger-soft);border:1px solid var(--danger);' +
            'border-radius:var(--radius);padding:0.75rem;color:var(--danger);';
        pre.textContent = j.error_message;
        errSection.appendChild(pre);
        bodyEl.appendChild(errSection);
    }

    overlay.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

function closeBackupDrawer() {
    const overlay = document.getElementById('backup-drawer-overlay');
    if (overlay) overlay.classList.add('hidden');
    document.body.style.overflow = '';
}
