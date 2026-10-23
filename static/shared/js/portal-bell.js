/*
 * Teacher and registrar portals: the notification bell (markup in templates/shared/_bell.html).
 *
 * Shows what still needs the signed-in person in the current grading period (for a teacher:
 * learners without a grade, classes to submit, returned classes; for a registrar: classes waiting
 * for validation) and their notifications. It asks the server when the page opens and then every
 * two minutes while the tab is visible.
 */
(function () {
    'use strict';
    var root = document.querySelector('[data-portal-bell]');
    if (!root) return;
    var INTERVAL = 120000;
    var $ = function (id) { return document.getElementById(id); };
    var btn = $('liveBtn'), panel = $('livePanel'), badge = $('liveBadge'), list = $('liveList');

    function esc(s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function csrf() {
        var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }
    function item(x, cls) {
        var inner = '<span class="live-ico"><i class="fi ' + esc(x.icon) + '"></i></span><span><span class="live-title">' + esc(x.title) +
            '</span><span class="live-msg">' + esc(x.message) + '</span>' + (x.when ? '<span class="live-when">' + esc(x.when) + '</span>' : '') + '</span>';
        return '<li class="live-item ' + cls + '">' + (x.url ? '<a href="' + esc(x.url) + '">' + inner + '</a>' : '<div>' + inner + '</div>') + '</li>';
    }
    function render(d) {
        badge.hidden = !d.count;
        badge.textContent = d.count > 99 ? '99+' : String(d.count);
        btn.setAttribute('aria-label', d.count ? 'Notifications, ' + d.count + ' need attention' : 'Notifications');
        $('livePeriod').textContent = d.period ? d.period : '';
        var html = '';
        if (d.reminders.length) {
            html += '<li class="live-group">To do' + (d.period ? ' in ' + esc(d.period) : '') + '</li>';
            html += d.reminders.map(function (r) { return item(r, r.urgent ? 'urgent' : ''); }).join('');
        }
        if (d.notifications.length) {
            html += '<li class="live-group">Notifications</li>';
            html += d.notifications.map(function (n) { return item(n, n.unread ? 'unread' : ''); }).join('');
        }
        list.innerHTML = html || '<li class="live-empty">' + esc(root.dataset.empty || 'You are all caught up.') + '</li>';
        list.removeAttribute('aria-busy');
    }
    function poll() {
        if (document.hidden) return;
        fetch(root.dataset.updatesUrl, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { if (d && d.reminders) render(d); })
            .catch(function () {});
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
            .then(poll);
    });
    document.addEventListener('visibilitychange', function () { if (!document.hidden) poll(); });
    setTimeout(poll, 400);
    setInterval(poll, INTERVAL);
})();
