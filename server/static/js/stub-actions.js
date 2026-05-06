// stub-actions.js
// Handles buttons that show "not yet implemented" alert messages.
// Reads the message from data-stub-alert attribute so no inline onclick is needed.

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-stub-alert]').forEach((el) => {
        el.addEventListener('click', () => {
            window.alert(el.dataset.stubAlert);
        });
    });
});
