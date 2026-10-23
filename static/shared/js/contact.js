/* Contact forms (the landing page's "Contact us" and the sign-in help dialog): send without leaving the page,
   show what needs fixing next to the field, then confirm. Without JavaScript the form posts normally. */
(function () {
    'use strict';

    var FAILED = 'Your message could not be sent. Please try again, or email us directly.';

    document.querySelectorAll('form[data-contact-form]').forEach(function (form) {
        var fields = form.querySelector('[data-contact-fields]');
        var sent = form.querySelector('[data-contact-sent]');
        var button = form.querySelector('button[type="submit"]');

        function clearErrors() {
            form.querySelectorAll('[data-error-for]').forEach(function (el) { el.hidden = true; el.textContent = ''; });
            form.querySelectorAll('.is-error').forEach(function (el) { el.classList.remove('is-error'); el.removeAttribute('aria-invalid'); });
        }
        function showError(name, text) {
            var box = form.querySelector('[data-error-for="' + name + '"]') || form.querySelector('[data-error-for="__all__"]');
            if (box) { box.textContent = text; box.hidden = false; }
            var input = form.elements[name];
            if (input && input.classList) {
                input.classList.add('is-error');
                input.setAttribute('aria-invalid', 'true');
                if (box && box.id) input.setAttribute('aria-describedby', box.id);
            }
        }
        form.querySelectorAll('input, textarea, select').forEach(function (input) {
            input.addEventListener('input', function () {
                if (!input.classList.contains('is-error')) return;
                input.classList.remove('is-error');
                input.removeAttribute('aria-invalid');
                var box = form.querySelector('[data-error-for="' + input.name + '"]');
                if (box) box.hidden = true;
            });
        });

        form.addEventListener('submit', function (e) {
            if (!window.fetch || !window.FormData) return;
            e.preventDefault();
            clearErrors();
            var missing = Array.prototype.filter.call(form.querySelectorAll('[required]'), function (el) { return !el.value.trim(); });
            if (missing.length) {
                missing.forEach(function (el) { showError(el.name, el.getAttribute('data-required') || 'This field is required.'); });
                missing[0].focus();
                return;
            }
            var label = button.innerHTML;
            button.disabled = true;
            button.textContent = 'Sending...';
            fetch(form.action, {
                method: 'POST', body: new FormData(form), credentials: 'same-origin',
                headers: { 'X-Requested-With': 'fetch', 'Accept': 'application/json' }
            }).then(function (response) {
                return response.json().catch(function () { return { ok: false }; });
            }).then(function (data) {
                if (data.ok) {
                    var name = sent.querySelector('[data-sent-name]');
                    var email = sent.querySelector('[data-sent-email]');
                    if (name) name.textContent = data.name ? ', ' + data.name : '';
                    if (email) email.textContent = data.email || '';
                    form.reset();
                    fields.hidden = true;
                    sent.hidden = false;
                    sent.focus();
                    return;
                }
                if (data.errors) {
                    Object.keys(data.errors).forEach(function (key) { showError(key, data.errors[key][0]); });
                    var first = form.querySelector('.is-error');
                    if (first) first.focus();
                } else {
                    showError('__all__', data.error || FAILED);
                }
            }).catch(function () {
                showError('__all__', FAILED);
            }).then(function () {
                button.disabled = false;
                button.innerHTML = label;
            });
        });

        var again = form.querySelector('[data-contact-again]');
        if (again) again.addEventListener('click', function () { sent.hidden = true; fields.hidden = false; form.querySelector('input:not([type="hidden"])').focus(); });
    });
})();
