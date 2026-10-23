/* ARMS landing page: header state, mobile menu, section highlighting, scroll-in effects and the photo viewer. */
(function () {
    'use strict';
    window.armsLanding = true;

    var root = document.documentElement;
    var header = document.getElementById('siteHeader');
    var nav = document.getElementById('siteNav');
    var menuBtn = header.querySelector('.menu-btn');
    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // A hairline under the header once the page has scrolled.
    function onScroll() { header.classList.toggle('is-scrolled', window.scrollY > 8); }
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });

    // Mobile menu.
    function setMenu(open) {
        header.classList.toggle('menu-open', open);
        menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
        menuBtn.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
        menuBtn.querySelector('i').className = 'fi ' + (open ? 'fi-rr-cross' : 'fi-rr-menu-burger');
    }
    menuBtn.addEventListener('click', function () { setMenu(!header.classList.contains('menu-open')); });
    nav.addEventListener('click', function (e) { if (e.target.closest('a')) setMenu(false); });
    document.addEventListener('click', function (e) {
        if (header.classList.contains('menu-open') && !header.contains(e.target)) setMenu(false);
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && header.classList.contains('menu-open')) { setMenu(false); menuBtn.focus(); }
    });
    var wide = window.matchMedia('(min-width: 900px)');
    var closeOnWide = function () { if (wide.matches) setMenu(false); };
    if (wide.addEventListener) wide.addEventListener('change', closeOnWide); else wide.addListener(closeOnWide);

    if (!('IntersectionObserver' in window)) {
        root.classList.remove('js');
    } else {
        // Highlight the menu link of the section in the middle of the screen.
        var links = {};
        Array.prototype.forEach.call(nav.querySelectorAll('a[href^="#"]'), function (a) { links[a.getAttribute('href').slice(1)] = a; });
        var spy = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                Object.keys(links).forEach(function (id) {
                    var on = id === entry.target.id;
                    links[id].classList.toggle('is-active', on);
                    if (on) links[id].setAttribute('aria-current', 'location'); else links[id].removeAttribute('aria-current');
                });
            });
        }, { rootMargin: '-45% 0px -50% 0px' });
        ['hero', 'features', 'how', 'partner', 'contact'].forEach(function (id) {
            var section = document.getElementById(id);
            if (section) spy.observe(section);
        });

        // Fade sections in as they arrive; afterwards the element goes back to its normal styles.
        var reveals = document.querySelectorAll('[data-reveal]');
        function settle(el) {
            el.removeAttribute('data-reveal');
            el.classList.remove('is-in');
        }
        if (reduceMotion) {
            Array.prototype.forEach.call(reveals, settle);
        } else {
            var io = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (!entry.isIntersecting) return;
                    var el = entry.target;
                    io.unobserve(el);
                    el.addEventListener('transitionend', function done(e) {
                        if (e.target !== el || e.propertyName !== 'opacity') return;
                        el.removeEventListener('transitionend', done);
                        settle(el);
                    });
                    el.classList.add('is-in');
                });
            }, { rootMargin: '0px 0px -8% 0px', threshold: 0.1 });
            Array.prototype.forEach.call(reveals, function (el) { io.observe(el); });
        }
    }

    // Photo viewer.
    var viewer = document.getElementById('lightbox');
    var photos = Array.prototype.slice.call(document.querySelectorAll('[data-photo]'));
    if (!viewer || typeof viewer.showModal !== 'function' || !photos.length) return;
    var viewerImg = viewer.querySelector('img');
    var caption = viewer.querySelector('.lb-caption');
    var count = viewer.querySelector('.lb-count');
    var current = 0;
    var opener = null;

    function show(index) {
        current = (index + photos.length) % photos.length;
        var link = photos[current];
        viewerImg.src = link.getAttribute('href');
        viewerImg.alt = link.querySelector('img').alt;
        caption.textContent = link.getAttribute('data-caption');
        count.textContent = (current + 1) + ' of ' + photos.length;
    }
    photos.forEach(function (link, index) {
        link.addEventListener('click', function (e) {
            e.preventDefault();
            opener = link;
            show(index);
            viewer.showModal();
            root.classList.add('lb-open');
        });
    });
    // Every way out (button, backdrop, Escape) unlocks the page and puts focus back on the photo that was opened.
    function unlock() { root.classList.remove('lb-open'); }
    function restoreFocus() {
        if (!opener) return;
        var link = opener;
        opener = null;
        link.focus();
    }
    function closeViewer() {
        if (viewer.open) viewer.close();
        unlock();
        restoreFocus();
    }
    viewer.querySelector('.lb-prev').addEventListener('click', function () { show(current - 1); });
    viewer.querySelector('.lb-next').addEventListener('click', function () { show(current + 1); });
    viewer.querySelector('.lb-close').addEventListener('click', closeViewer);
    viewer.addEventListener('click', function (e) { if (e.target === viewer) closeViewer(); });
    viewer.addEventListener('keydown', function (e) {
        if (e.key === 'ArrowLeft') { e.preventDefault(); show(current - 1); }
        if (e.key === 'ArrowRight') { e.preventDefault(); show(current + 1); }
    });
    // Escape: the dialog is still open during "cancel", so only unlock here; focus returns on "close".
    viewer.addEventListener('cancel', unlock);
    viewer.addEventListener('close', function () { unlock(); restoreFocus(); });
})();
