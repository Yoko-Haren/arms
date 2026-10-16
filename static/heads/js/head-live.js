/*
 * School Head portal: notification bell and automatic page updates.
 *
 * Every minute while the tab is visible (and at once when the user comes back to it) the page asks
 * the server for its notifications and a fingerprint of the school's grades. Pages that show grade
 * data (they contain #armsLive) update themselves when the fingerprint changes, but only while the
 * user is not typing, choosing, reading a dialog or scrolling; otherwise a "New grades are available"
 * notice waits for them. The scroll position is kept, and the update is announced to screen readers.
 */
(function () {
    'use strict';
    var root = document.getElementById('armsBell');
    if (!root) return;

    var INTERVAL = 60000, QUIET = 20000;
    var $ = function (id) { return document.getElementById(id); };
    var btn = $('liveBtn'), panel = $('livePanel'), badge = $('liveBadge'), list = $('liveList'), auto = $('liveAuto'),
        time = $('liveTime'), upd = $('liveUpdate'), pill = $('livePill'), announce = $('liveAnnounce');
    var page = $('armsLive');
    var known = page ? page.dataset.fingerprint : null;
    var path = location.pathname + location.search;
    var pending = false, lastInput = Date.now(), timer = null;
    var autoOn = true;
    try { autoOn = localStorage.getItem('arms-auto-update') !== 'off'; } catch (e) {}
    auto.checked = autoOn;

    ['keydown', 'pointerdown', 'wheel', 'touchstart', 'input', 'scroll'].forEach(function (ev) {
        window.addEventListener(ev, function () { lastInput = Date.now(); }, { passive: true });
    });

    function csrf() {
        var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }
    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    // ---------- bell ----------
    function render(data) {
        var unread = data.unread || 0;
        badge.hidden = !unread;
        badge.textContent = unread > 99 ? '99+' : String(unread);
        btn.setAttribute('aria-label', unread ? 'Notifications, ' + unread + ' unread' : 'Notifications');
        if (!data.notifications.length) {
            list.innerHTML = '<li class="live-empty">You are all caught up. Grade validations and locked periods will show here.</li>';
            return;
        }
        list.innerHTML = data.notifications.map(function (n) {
            var inner = '<span class="live-ico"><i class="fi ' + esc(n.icon) + '"></i></span><span><span class="live-title">' + esc(n.title) +
                '</span><span class="live-msg">' + esc(n.message) + '</span><span class="live-when">' + esc(n.when) + '</span></span>';
            var cls = 'live-item' + (n.unread ? ' unread' : '') + ' ' + esc((n.priority || '').toLowerCase());
            return '<li class="' + cls + '">' + (n.url ? '<a href="' + esc(n.url) + '">' + inner + '</a>' : '<div>' + inner + '</div>') + '</li>';
        }).join('');
    }
    function open(show) {
        panel.hidden = !show;
        btn.setAttribute('aria-expanded', show ? 'true' : 'false');
        if (show) poll();
    }
    btn.addEventListener('click', function (e) { e.stopPropagation(); open(panel.hidden); });
    document.addEventListener('click', function (e) { if (!panel.hidden && !root.contains(e.target)) open(false); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !panel.hidden) { open(false); btn.focus(); } });
    $('liveReadAll').addEventListener('click', function () {
        fetch(root.dataset.readUrl, { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function () { poll(); });
    });
    auto.addEventListener('change', function () {
        autoOn = auto.checked;
        try { localStorage.setItem('arms-auto-update', autoOn ? 'on' : 'off'); } catch (e) {}
    });

    // ---------- updates ----------
    function busy() {
        var a = document.activeElement;
        if (a && a.matches && a.matches('input, select, textarea, [contenteditable="true"]')) return true;
        if (!panel.hidden) return true;
        if (document.querySelector('.modal-overlay.show, .modal.show, .chart-modal:not([hidden]), [aria-modal="true"]:not([hidden]), details[open].keep-open')) return true;
        if (window.getSelection && String(window.getSelection()).length) return true;
        return Date.now() - lastInput < QUIET;
    }
    function apply() {
        try {
            sessionStorage.setItem('arms-scroll:' + path, String(window.scrollY));
            sessionStorage.setItem('arms-updated', String(Date.now()));
        } catch (e) {}
        // skip the cached copy of the page once, so the new grades are drawn
        document.cookie = 'arms_fresh=1; path=/; max-age=30; SameSite=Lax';
        location.reload();
    }
    function recentlyApplied() {
        try { return Date.now() - (+sessionStorage.getItem('arms-applied-at') || 0) < 120000; } catch (e) { return false; }
    }
    function changed() {
        pending = true;
        btn.classList.add('pending');
        upd.hidden = false;
        if (autoOn && !busy() && !recentlyApplied()) { apply(); return; }
        pill.hidden = false;
    }
    function poll() {
        return fetch(root.dataset.updatesUrl, { credentials: 'same-origin', cache: 'no-store', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d) return;
                render(d);
                time.textContent = 'Checked ' + d.checked_at;
                if (page && known && d.fingerprint !== known) { known = d.fingerprint; changed(); }
            })
            .catch(function () {});
    }
    function tick() {
        if (document.hidden) return;
        if (pending && autoOn && !busy() && !recentlyApplied()) { apply(); return; }
        poll();
    }
    $('liveApply').addEventListener('click', apply);
    $('livePillApply').addEventListener('click', apply);
    $('livePillClose').addEventListener('click', function () { pill.hidden = true; });
    document.addEventListener('visibilitychange', function () { if (!document.hidden) tick(); });

    // after an automatic update: back to the same place, and say what happened
    try {
        var at = +sessionStorage.getItem('arms-updated');
        if (at) {
            sessionStorage.removeItem('arms-updated');
            sessionStorage.setItem('arms-applied-at', String(at));
            var y = +sessionStorage.getItem('arms-scroll:' + path) || 0;
            window.addEventListener('load', function () { window.scrollTo(0, y); });
            announce.textContent = 'Updated with the latest grades.';
            if (window.showToast) window.showToast('Updated with the latest grades.', 'success');
        }
    } catch (e) {}

    poll();
    timer = setInterval(tick, INTERVAL);
})();
