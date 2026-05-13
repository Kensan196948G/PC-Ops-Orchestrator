const _SETTING_IDS = [
    'timezone', 'language', 'log_level', 'session_timeout_minutes',
    'jwt_expiry_hours', 'refresh_token_days', 'password_min_length',
    'login_lock_threshold', 'mfa_mode',
    'heartbeat_interval_seconds', 'agent_timeout_seconds',
    'collection_interval_minutes', 'agent_auto_approve',
];

async function loadSettings() {
    try {
        const data = await apiFetch('/settings');
        const s = data.settings || {};
        _SETTING_IDS.forEach(key => {
            const el = document.getElementById('setting-' + key);
            if (el && s[key] != null) el.value = s[key];
        });
    } catch (e) {
        // settings are pre-filled with defaults; silently ignore load error
    }
}

async function saveSettings() {
    const payload = {};
    _SETTING_IDS.forEach(key => {
        const el = document.getElementById('setting-' + key);
        if (el) payload[key] = el.value;
    });
    try {
        await apiFetch('/settings', { method: 'PUT', body: JSON.stringify(payload) });
        showSuccess('設定を保存しました');
    } catch (e) {
        showError('保存に失敗しました');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    const saveBtn = document.getElementById('btn-save-settings');
    if (saveBtn) saveBtn.addEventListener('click', saveSettings);
});
