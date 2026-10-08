/*
 * ARMS dialogs — replaces the browser's alert() / confirm() with dialogs in the system design.
 *
 *   ARMS.alert('Saved.')                          -> Promise
 *   ARMS.confirm('Delete this?', {danger: true})  -> Promise<boolean>
 *   ARMS.toast('Copied', 'success')
 *
 * Declarative use (no script needed):
 *   <form data-confirm="Delete this school year?" data-confirm-danger>…</form>
 *   <a href="…" data-confirm="Set as current?">…</a>
 *   <button type="submit" data-confirm="Approve all?">…</button>
 */
(function () {
    'use strict';

    var CSS = [
        '.arms-overlay{position:fixed;inset:0;background:rgba(45,55,72,.45);backdrop-filter:blur(3px);display:flex;align-items:center;justify-content:center;z-index:5000;padding:1rem;opacity:0;transition:opacity .18s ease;font-family:"Segoe UI","Century Gothic",sans-serif}',
        '.arms-overlay.show{opacity:1}',
        '.arms-dialog{background:#fff;border-radius:20px;width:100%;max-width:420px;padding:1.6rem 1.6rem 1.3rem;box-shadow:0 20px 60px rgba(0,0,0,.25);transform:translateY(12px) scale(.98);transition:transform .18s ease;text-align:center}',
        '.arms-overlay.show .arms-dialog{transform:none}',
        '.arms-dialog-icon{width:54px;height:54px;border-radius:16px;margin:0 auto .9rem;display:flex;align-items:center;justify-content:center;font-size:1.5rem;font-weight:700;color:#fff;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);box-shadow:0 0 20px rgba(102,126,234,.3)}',
        '.arms-dialog.danger .arms-dialog-icon{background:linear-gradient(135deg,#dc3545,#f39c12)}',
        '.arms-dialog.warning .arms-dialog-icon{background:linear-gradient(135deg,#f39c12,#e67e22)}',
        '.arms-dialog h3{font-size:1.02rem;color:#00072D;margin:0 0 .4rem;font-weight:700}',
        '.arms-dialog p{font-size:.84rem;color:#718096;line-height:1.55;margin:0;white-space:pre-line;word-break:break-word}',
        '.arms-dialog-actions{display:flex;gap:.6rem;margin-top:1.3rem}',
        '.arms-btn{flex:1;padding:.65rem 1rem;border-radius:10px;font-size:.82rem;font-weight:600;cursor:pointer;border:2px solid #e9ecef;background:#fff;color:#2d3748;font-family:inherit;transition:all .2s}',
        '.arms-btn:hover{border-color:#cbd5e0}',
        '.arms-btn:focus-visible{outline:3px solid rgba(18,52,153,.35);outline-offset:1px}',
        '.arms-btn.primary{background:#123499;border-color:#123499;color:#fff}',
        '.arms-btn.primary:hover{background:#051650;border-color:#051650}',
        '.arms-dialog.danger .arms-btn.primary{background:#dc3545;border-color:#dc3545}',
        '.arms-dialog.danger .arms-btn.primary:hover{background:#b02a37;border-color:#b02a37}',
        '.arms-toasts{position:fixed;top:24px;right:24px;z-index:5100;display:flex;flex-direction:column;gap:.5rem;font-family:"Segoe UI","Century Gothic",sans-serif}',
        '.arms-toast{background:#fff;border-radius:12px;padding:.8rem 1.1rem;box-shadow:0 8px 25px rgba(0,0,0,.15);border-left:4px solid #123499;font-size:.8rem;color:#2d3748;min-width:260px;max-width:380px;animation:armsIn .25s ease}',
        '.arms-toast.error{border-left-color:#dc3545}.arms-toast.warning{border-left-color:#f39c12}.arms-toast.info{border-left-color:#2D6AFF}',
        '@keyframes armsIn{from{transform:translateX(40px);opacity:0}to{transform:none;opacity:1}}'
    ].join('');

    function ensureStyle() {
        if (document.getElementById('arms-ui-style')) return;
        var style = document.createElement('style');
        style.id = 'arms-ui-style';
        style.textContent = CSS;
        document.head.appendChild(style);
    }

    function dialog(message, opts, withCancel) {
        opts = opts || {};
        ensureStyle();
        return new Promise(function (resolve) {
            var previous = document.activeElement;
            var overlay = document.createElement('div');
            overlay.className = 'arms-overlay';
            overlay.setAttribute('role', 'dialog');
            overlay.setAttribute('aria-modal', 'true');

            var box = document.createElement('div');
            var kind = opts.danger ? 'danger' : (opts.type === 'warning' || opts.type === 'error' ? 'warning' : '');
            box.className = 'arms-dialog ' + kind;

            var icon = document.createElement('div');
            icon.className = 'arms-dialog-icon';
            icon.textContent = withCancel ? '?' : (kind ? '!' : 'i');

            var title = document.createElement('h3');
            title.textContent = opts.title || (withCancel ? 'Please confirm' : 'Notice');

            var text = document.createElement('p');
            text.textContent = message;

            var actions = document.createElement('div');
            actions.className = 'arms-dialog-actions';

            function close(result) {
                overlay.classList.remove('show');
                document.removeEventListener('keydown', onKey, true);
                setTimeout(function () { overlay.remove(); }, 180);
                if (previous && previous.focus) previous.focus();
                resolve(result);
            }
            function onKey(e) {
                if (e.key === 'Escape') { e.preventDefault(); close(false); }
            }

            if (withCancel) {
                var cancel = document.createElement('button');
                cancel.type = 'button';
                cancel.className = 'arms-btn';
                cancel.textContent = opts.cancelText || 'Cancel';
                cancel.addEventListener('click', function () { close(false); });
                actions.appendChild(cancel);
            }
            var okBtn = document.createElement('button');
            okBtn.type = 'button';
            okBtn.className = 'arms-btn primary';
            okBtn.textContent = opts.confirmText || (withCancel ? 'Confirm' : 'OK');
            okBtn.addEventListener('click', function () { close(true); });
            actions.appendChild(okBtn);

            box.appendChild(icon);
            box.appendChild(title);
            box.appendChild(text);
            box.appendChild(actions);
            overlay.appendChild(box);
            overlay.addEventListener('click', function (e) { if (e.target === overlay) close(false); });
            document.addEventListener('keydown', onKey, true);
            document.body.appendChild(overlay);
            requestAnimationFrame(function () { overlay.classList.add('show'); okBtn.focus(); });
        });
    }

    function toast(message, type) {
        ensureStyle();
        var holder = document.querySelector('.arms-toasts');
        if (!holder) {
            holder = document.createElement('div');
            holder.className = 'arms-toasts';
            document.body.appendChild(holder);
        }
        var item = document.createElement('div');
        item.className = 'arms-toast ' + (type || 'success');
        item.textContent = message;
        holder.appendChild(item);
        setTimeout(function () { item.remove(); }, 4000);
    }

    // Deleting, removing, dropping, deactivating, rejecting and signing out are destructive.
    var DESTRUCTIVE = /\b(delete|remove|drop|deactivate|reject|discard|log ?out|sign ?out|cannot be undone)\b/i;

    function optionsFrom(el) {
        var message = el.getAttribute('data-confirm') || '';
        return {
            title: el.getAttribute('data-confirm-title') || '',
            confirmText: el.getAttribute('data-confirm-ok') || '',
            danger: el.hasAttribute('data-confirm-danger') || DESTRUCTIVE.test(message)
        };
    }

    // Links and buttons carrying data-confirm
    document.addEventListener('click', function (e) {
        var el = e.target.closest ? e.target.closest('a[data-confirm], button[data-confirm]') : null;
        if (!el || el.dataset.armsConfirmed === '1') return;
        e.preventDefault();
        e.stopPropagation();
        dialog(el.getAttribute('data-confirm'), optionsFrom(el), true).then(function (yes) {
            if (!yes) return;
            if (el.tagName === 'A') { window.location.href = el.href; return; }
            el.dataset.armsConfirmed = '1';
            if (el.form) { el.form.dataset.armsConfirmed = '1'; }
            el.click();
            delete el.dataset.armsConfirmed;
        });
    }, true);

    // Forms carrying data-confirm
    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!form.hasAttribute || !form.hasAttribute('data-confirm')) return;
        if (form.dataset.armsConfirmed === '1') { delete form.dataset.armsConfirmed; return; }
        e.preventDefault();
        e.stopPropagation();
        var submitter = e.submitter || null;
        dialog(form.getAttribute('data-confirm'), optionsFrom(form), true).then(function (yes) {
            if (!yes) return;
            form.dataset.armsConfirmed = '1';
            if (form.requestSubmit) { form.requestSubmit(submitter); } else { form.submit(); }
        });
    }, true);

    // Fields marked data-remember keep their value while the browser tab is open, so a
    // search or filter is still there after visiting another page and coming back.
    (function () {
        var fields = document.querySelectorAll('[data-remember]');
        if (!fields.length) return;
        var restored = [];
        function key(el) { return 'arms:' + location.pathname + ':' + el.getAttribute('data-remember'); }
        fields.forEach(function (el) {
            try {
                var saved = sessionStorage.getItem(key(el));
                if (saved !== null && saved !== el.value) { el.value = saved; restored.push(el); }
            } catch (e) {}
            function remember() { try { sessionStorage.setItem(key(el), el.value); } catch (e) {} }
            el.addEventListener('input', remember);
            el.addEventListener('change', remember);
        });
        // let the page's own handlers re-apply the restored filters
        window.addEventListener('load', function () {
            restored.forEach(function (el) {
                ['input', 'keyup', 'change'].forEach(function (name) { el.dispatchEvent(new Event(name, {bubbles: true})); });
            });
        });
    })();

    window.ARMS = {
        alert: function (message, opts) { return dialog(message, opts, false); },
        confirm: function (message, opts) {
            opts = opts || {};
            if (opts.danger === undefined && DESTRUCTIVE.test(String(message))) opts.danger = true;
            return dialog(message, opts, true);
        },
        toast: toast
    };
})();
