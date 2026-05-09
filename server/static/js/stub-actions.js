// stub-actions.js
// Handles buttons that show "not yet implemented" toast messages.
// Reads the message from data-stub-alert attribute so no inline onclick is needed.

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-stub-alert]').forEach((el) => {
        el.addEventListener('click', () => {
            const msg = el.dataset.stubAlert;
            if (typeof showToast === 'function') {
                showToast('🔧 ' + msg, 'info');
            } else {
                window.alert(msg);
            }
        });
    });
});
