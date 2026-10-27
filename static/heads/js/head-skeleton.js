/*
 * School Head portal: skeleton screens while the next page loads.
 *
 * Pages arrive fully built from the server, so the wait is between a click and the next page. When
 * the user opens another principal page (a link, a row, a filter change), the current content gives
 * way to a grey outline of the page that is coming, so the screen answers at once. The new page
 * replaces it as soon as it arrives. A filter change keeps the filter bar in place and outlines the
 * rest. If the browser brings this page back from its back/forward cache, the old content returns.
 *
 * Page scripts that navigate by themselves use ArmsSkeleton.go(url) and ArmsSkeleton.submit(form).
 */
(function () {
    'use strict';
    var DELAY = 120;            // a quick page never flashes an outline
    var GIVE_UP = 20000;        // a navigation that never happened (a download, a stop) gives the page back
    var ROUTES = [
        [/^\/heads\/(ai-dashboard\/)?$/, 'dashboard'],
        [/^\/heads\/ai-section\/\d+\/\d+\/\d+\/$/, 'dashboard'],         // old section links open the dashboard
        [/^\/heads\/notifications\/\d+\/open\/$/, 'generic'],
        [/^\/heads\/performance\/(\d+\/)?$/, 'performance'],
        [/^\/heads\/users\/$/, 'users'],
        [/^\/accounts\/settings\/$/, 'settings']
    ];
    var NAV = { dashboard: 'dashboard', performance: 'performance', users: 'users', settings: 'settings' };
    var wrap = document.querySelector('#mainContent .content-wrap');
    var timer = null, giveUp = null, active = null;

    function urlOf(href) {
        try { return new URL(href, location.href); } catch (e) { return null; }
    }
    function kindOf(url) {
        if (!url || url.origin !== location.origin) return null;
        for (var i = 0; i < ROUTES.length; i++) {
            if (ROUTES[i][0].test(url.pathname)) return ROUTES[i][1];
        }
        return null;
    }
    var here = kindOf(urlOf(location.href));

    function markNav(kind) {
        var target = NAV[kind];
        if (!target) return;
        document.querySelectorAll('.sidebar .nav-link').forEach(function (a) {
            var k = NAV[kindOf(urlOf(a.getAttribute('href') || ''))];
            if (k) a.classList.toggle('active', k === target);
        });
    }

    function restore() {
        clearTimeout(timer); clearTimeout(giveUp);
        timer = giveUp = null;
        if (!active) return;
        active.node.remove();
        active.hidden.forEach(function (el) { el.classList.remove('skel-hide'); });
        active.nav.forEach(function (pair) { pair[0].classList.toggle('active', pair[1]); });
        document.body.removeAttribute('aria-busy');
        active = null;
    }

    function show(kind, keepFilters) {
        var tpl = document.getElementById('skel-' + kind) || document.getElementById('skel-generic');
        if (!tpl || !wrap || active) return;
        var node = tpl.content.firstElementChild.cloneNode(true);
        var hidden = [], keep = keepFilters ? document.querySelector('[data-skel-keep]') : null;
        var nav = Array.prototype.map.call(document.querySelectorAll('.sidebar .nav-link'), function (a) { return [a, a.classList.contains('active')]; });

        if (keep) {
            // same page, new filters: keep the filter bar, outline everything after it
            var filler = node.querySelector('[data-skel-filter]');
            if (filler) filler.remove();
            var root = keep.parentElement;
            Array.prototype.forEach.call(root.children, function (el) {
                if (el !== keep && !el.classList.contains('skel-hide')) { el.classList.add('skel-hide'); hidden.push(el); }
            });
            node.classList.add('skel-after');
            root.appendChild(node);
        } else {
            Array.prototype.forEach.call(wrap.children, function (el) {
                if (el.classList.contains('top-bar') || el.id === 'toastContainer' || el.classList.contains('skel-hide')) return;
                el.classList.add('skel-hide'); hidden.push(el);
            });
            wrap.appendChild(node);
            window.scrollTo(0, 0);
        }
        document.body.setAttribute('aria-busy', 'true');
        active = { node: node, hidden: hidden, nav: nav };
        markNav(kind);
        giveUp = setTimeout(restore, GIVE_UP);
    }

    function schedule(kind, keepFilters) {
        if (!kind || active || timer) return;
        timer = setTimeout(function () { timer = null; show(kind, keepFilters); }, DELAY);
    }

    function forUrl(url) {
        var kind = kindOf(url);
        return { kind: kind, keep: !!kind && kind === here && url.pathname === location.pathname };
    }

    // links (bubble phase, so page handlers that cancel a click are respected)
    document.addEventListener('click', function (e) {
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        var a = e.target.closest ? e.target.closest('a[href]') : null;
        if (!a || a.hasAttribute('download') || (a.target && a.target !== '_self')) return;
        var url = urlOf(a.getAttribute('href'));
        if (!url || (url.hash && url.pathname === location.pathname && url.search === location.search)) return;
        var t = forUrl(url);
        schedule(t.kind, false);
    });

    // filter forms sent with Enter or a button
    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (e.defaultPrevented || (form.method || 'get').toLowerCase() !== 'get') return;
        var t = forUrl(urlOf(form.getAttribute('action') || location.pathname));
        schedule(t.kind, t.keep);
    });

    // back/forward cache: the page comes back as it was
    window.addEventListener('pageshow', function (e) { if (e.persisted) restore(); });

    window.ArmsSkeleton = {
        go: function (href) {
            var t = forUrl(urlOf(href));
            schedule(t.kind, false);
            window.location.href = href;
        },
        submit: function (form) {
            var t = forUrl(urlOf(form.getAttribute('action') || location.pathname));
            schedule(t.kind, t.keep);
            form.submit();
        },
        show: function (kind, keepFilters) { show(kind, keepFilters); },
        restore: restore
    };
})();
