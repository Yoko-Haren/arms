/* Upload guides.
   - [data-guide-open="id"] opens that .tp-modal; its [data-close] buttons, a click outside the card and Escape close it,
     and focus goes back to the button that opened it.
   - [data-guide-tabs] is a tablist choosing between kinds of file: a click or the arrow keys show one panel. */
(function () {
    var opened = null, from = null;
    function close() {
        if (!opened) return;
        opened.hidden = true;
        opened = null;
        if (from) from.focus();
    }
    document.addEventListener('click', function (e) {
        var open = e.target.closest('[data-guide-open]');
        if (open) {
            var modal = document.getElementById(open.getAttribute('data-guide-open'));
            if (!modal) return;
            e.preventDefault();
            from = open;
            opened = modal;
            modal.hidden = false;
            modal.querySelector('.tp-modal-card').focus();
            return;
        }
        if (opened && (e.target === opened || e.target.closest('[data-close]'))) close();
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });

    document.querySelectorAll('[data-guide-tabs]').forEach(function (list) {
        var tabs = Array.prototype.slice.call(list.querySelectorAll('[role="tab"]'));
        function select(tab) {
            tabs.forEach(function (t) {
                var on = t === tab;
                t.setAttribute('aria-selected', on ? 'true' : 'false');
                t.tabIndex = on ? 0 : -1;
                document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
            });
        }
        tabs.forEach(function (tab, i) {
            tab.addEventListener('click', function () { select(tab); });
            tab.addEventListener('keydown', function (e) {
                var step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
                if (!step) return;
                var next = tabs[(i + step + tabs.length) % tabs.length];
                select(next);
                next.focus();
                e.preventDefault();
            });
        });
    });
})();
