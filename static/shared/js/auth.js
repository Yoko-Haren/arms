/* Sign-in and account pages: show or hide a password, digits-only codes, live password rules,
   one submit per click, and the "Need help?" dialog. */
(function () {
    'use strict';

    // Show or hide a password.
    document.querySelectorAll('.toggle[data-target]').forEach(function (button) {
        var input = document.getElementById(button.getAttribute('data-target'));
        if (!input) return;
        button.setAttribute('aria-pressed', 'false');
        button.addEventListener('click', function () {
            var show = input.type === 'password';
            input.type = show ? 'text' : 'password';
            button.setAttribute('aria-pressed', show ? 'true' : 'false');
            button.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
            var icon = button.querySelector('i');
            if (icon) icon.className = 'fi ' + (show ? 'fi-rr-eye-crossed' : 'fi-rr-eye');
            input.focus();
        });
    });

    // Codes are six digits.
    document.querySelectorAll('input.code-input').forEach(function (input) {
        input.addEventListener('input', function () { input.value = input.value.replace(/\D/g, '').slice(0, 6); });
    });

    // Password rules tick as the user types.
    var rules = document.querySelector('[data-password-rules]');
    if (rules) {
        var password = document.getElementById(rules.getAttribute('data-password-rules'));
        var confirm = document.getElementById('confirm_password');
        var mark = function (rule, ok) {
            var item = rules.querySelector('[data-rule="' + rule + '"]');
            if (item) item.classList.toggle('ok', ok);
        };
        var refresh = function () {
            var value = password.value;
            mark('length', value.length >= 8);
            mark('mix', value.length > 0 && !/^\d+$/.test(value));
            if (confirm) mark('match', value.length > 0 && value === confirm.value);
        };
        password.addEventListener('input', refresh);
        if (confirm) confirm.addEventListener('input', refresh);
        refresh();
    }

    // "Forgot password?" passes what was typed as the username here without putting it in the address bar.
    var prefill = document.querySelector('input[data-prefill-signin]');
    if (prefill && !prefill.value) {
        try { prefill.value = sessionStorage.getItem('arms-signin-id') || ''; } catch (e) { /* storage blocked */ }
    }

    // One submit per click on ordinary forms.
    document.querySelectorAll('form[data-busy]').forEach(function (form) {
        form.addEventListener('submit', function (e) {
            var button = form.querySelector('button[type="submit"]');
            if (!button) return;
            // Wait for the page's own checks: if one of them stopped the submit, leave the button alone.
            setTimeout(function () {
                if (e.defaultPrevented) return;
                button.disabled = true;
                button.textContent = form.getAttribute('data-busy');
            }, 0);
        });
    });

    // "Need help?" dialog.
    var dialog = document.getElementById('helpDialog');
    if (!dialog) return;
    var openers = document.querySelectorAll('[data-open-help]');
    if (typeof dialog.showModal !== 'function') {
        openers.forEach(function (button) {
            button.addEventListener('click', function () { window.location.href = dialog.getAttribute('data-mailto'); });
        });
        return;
    }
    var opener = null;
    var close = function () { if (dialog.open) dialog.close(); };
    openers.forEach(function (button) {
        button.addEventListener('click', function (e) {
            e.preventDefault();
            opener = button;
            dialog.showModal();
        });
    });
    dialog.querySelectorAll('[data-close-help]').forEach(function (button) { button.addEventListener('click', close); });
    dialog.addEventListener('click', function (e) { if (e.target === dialog) close(); });
    dialog.addEventListener('close', function () {
        if (opener) { var back = opener; opener = null; back.focus(); }
    });
})();
