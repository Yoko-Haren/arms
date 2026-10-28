/*
 * Forecast charts for the School Head pages (Academic Dashboard, Honors Outlook, School Performance).
 *
 * The server builds one spec per chart (heads/forecasts.py) into a JSON script tag; an element with
 * data-forecast="<id of that tag>" becomes the chart. Three views, as on Our World in Data: Line (one
 * chart, or one small panel per series when there are more than ten), Bar (every series at one
 * grading period) and Table (every value). Solid lines are averages so far, dashed lines the
 * forecast, the band its 90% likely range, and hollow diamonds what the model forecast one period
 * earlier. Colors follow the series, never their rank; labels and values stay in ink.
 */
(function () {
    'use strict';
    var SVG = 'http://www.w3.org/2000/svg';
    var MAX_LINES = 10;             // every discipline in one chart; more than ten become small panels
    var LINE_H = 310, PANEL_H = 150;

    function remember(key, value) {
        try {
            if (value === undefined) return localStorage.getItem(key);
            localStorage.setItem(key, value);
        } catch (e) { /* private mode: the default view is fine */ }
        return null;
    }
    function el(tag, attrs, parent) {
        var node = document.createElementNS(SVG, tag);
        Object.keys(attrs || {}).forEach(function (k) { if (attrs[k] !== null && attrs[k] !== undefined) node.setAttribute(k, attrs[k]); });
        if (parent) parent.appendChild(node);
        return node;
    }
    function tag(name, cls, parent, text) {
        var node = document.createElement(name);
        if (cls) node.className = cls;
        if (text !== undefined && text !== null) node.textContent = text;
        if (parent) parent.appendChild(node);
        return node;
    }
    function fmt(v) { return v === null || v === undefined ? '—' : (+v).toFixed(1); }
    function levelOf(levels, v) {
        for (var i = 0; i < levels.length; i++) if (v >= levels[i].min) return levels[i];
        return levels[levels.length - 1];
    }
    function lineKey(parent, color, dashed) {
        var k = tag('i', 'fc-key-line' + (dashed ? ' dash' : ''), parent);
        k.style.borderTopColor = color;
        k.setAttribute('aria-hidden', 'true');
        return k;
    }

    // ---------- the spec, period by period ----------
    function prepare(spec) {
        spec.levels.sort(function (a, b) { return b.min - a.min; });
        spec.series.forEach(function (se) {
            se.points = spec.periods.map(function (p) {
                var f = se.future[p.p];
                return { actual: se.actual[p.p] === undefined ? null : se.actual[p.p],
                         forecast: f ? f[0] : null, low: f ? f[1] : null, high: f ? f[2] : null,
                         back: se.back[p.p] === undefined ? null : se.back[p.p] };
            });
            se.lastIndex = -1; se.endIndex = -1;
            se.points.forEach(function (pt, i) {
                if (pt.actual !== null) se.lastIndex = i;
                if (pt.actual !== null || pt.forecast !== null) se.endIndex = i;
            });
            se.visible = true;
        });
        spec.firstFuture = -1;
        spec.periods.forEach(function (p, i) {
            if (spec.firstFuture < 0 && spec.series.some(function (se) { return se.points[i].forecast !== null && se.points[i].actual === null; })) spec.firstFuture = i;
        });
        spec.hasBack = spec.series.some(function (se) { return se.points.some(function (pt) { return pt.back !== null; }); });
        spec.hasForecast = spec.firstFuture >= 0;
        return spec;
    }

    function valueAt(se, i) {
        var pt = se.points[i];
        if (!pt) return null;
        return pt.actual !== null ? pt.actual : pt.forecast;
    }

    // the value axis hugs the data so lines a point apart stay apart; the passing mark joins it when the data comes near
    function domain(spec, list) {
        var values = [];
        list.forEach(function (se) {
            se.points.forEach(function (pt) {
                [pt.actual, pt.forecast, pt.low, pt.high, pt.back].forEach(function (v) { if (v !== null) values.push(v); });
            });
        });
        if (!values.length) values = [spec.threshold];
        var min = Math.min.apply(null, values), max = Math.max.apply(null, values);
        if (min - spec.threshold < 3) min = Math.min(min, spec.threshold - 1);
        var lo = Math.max(60, Math.floor(min - 1)), hi = Math.min(100, Math.ceil(max + 1));
        if (hi - lo < 6) { lo = Math.max(60, Math.floor((lo + hi) / 2 - 3)); hi = Math.min(100, lo + 6); }
        return { lo: lo, hi: hi };
    }

    // ---------- the tooltip: every series at one period, values first ----------
    function showTip(host, tip, spec, list, i, anchorX, anchorY) {
        tip.textContent = '';
        var p = spec.periods[i];
        var future = list.some(function (se) { return se.points[i].actual === null && se.points[i].forecast !== null; });
        tag('h5', '', tip, p.name + (future ? ' (forecast)' : ''));
        list.slice().sort(function (a, b) { return (valueAt(b, i) || 0) - (valueAt(a, i) || 0); }).forEach(function (se) {
            var pt = se.points[i];
            if (pt.actual === null && pt.forecast === null) return;
            var row = tag('div', 'fc-tip-row', tip);
            lineKey(row, se.color, pt.actual === null);
            tag('b', '', row, fmt(valueAt(se, i)) + '%');
            var name = tag('span', '', row, se.name);
            if (pt.actual === null) tag('small', '', name, ' likely ' + fmt(pt.low) + '–' + fmt(pt.high));
            else if (pt.back !== null) tag('small', '', name, ' forecast was ' + fmt(pt.back));
        });
        tip.hidden = false;
        var box = host.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
        var left = anchorX - box.left + 14;
        if (left + w > box.width - 4) left = anchorX - box.left - w - 14;
        var top = Math.min(Math.max(anchorY - box.top - h / 2, 4), box.height - h - 4);
        tip.style.left = Math.max(4, left) + 'px';
        tip.style.top = top + 'px';
    }

    // ---------- line chart (also each small panel) ----------
    function drawLines(box, spec, opts) {
        var list = opts.list;
        var W = Math.max(240, Math.floor(box.clientWidth));
        var ends = opts.labels && W >= 560;
        var labelW = 0;
        if (ends) {
            var longest = 0;
            list.forEach(function (se) { longest = Math.max(longest, se.name.length + 7); });
            labelW = Math.min(200, Math.max(116, longest * 6.3 + 26));
        }
        var m = { t: opts.compact ? 10 : 18, r: ends ? labelW : 10, b: 26, l: 36 };
        var H = opts.height, iw = W - m.l - m.r, ih = H - m.t - m.b;
        var P = spec.periods, n = P.length, d = opts.dom;
        var X = function (i) { return m.l + iw * (i + 0.5) / n; };
        var Y = function (v) { return m.t + ih * (1 - (v - d.lo) / (d.hi - d.lo)); };
        var root = el('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, 'class': 'fc-svg', role: 'img', 'aria-label': opts.label }, box);

        // proficiency level bands across the whole year, with their letters
        spec.levels.forEach(function (lv, k) {
            var top = k === 0 ? 100.01 : spec.levels[k - 1].min;
            var a = Math.max(lv.min, d.lo), b = Math.min(top, d.hi);
            if (b <= a) return;
            el('rect', { x: m.l, y: Y(b), width: iw, height: Y(a) - Y(b), 'class': 'fc-band level-' + lv.key }, root);
            if (!opts.compact && Y(a) - Y(b) >= 13) el('text', { x: m.l + 5, y: Y(b) + 11, 'class': 'fc-band-tag' }, root).textContent = lv.letter;
        });
        // the period being reviewed and the forecast part of the year, as light veils that keep the bands visible
        P.forEach(function (p, i) {
            if (p.p === spec.selected) el('rect', { x: X(i) - iw / (2 * n), y: m.t, width: iw / n, height: ih, 'class': 'fc-selected' }, root);
        });
        if (spec.firstFuture >= 0) {
            var fx = X(spec.firstFuture) - iw / (2 * n);
            el('rect', { x: fx, y: m.t, width: m.l + iw - fx, height: ih, 'class': 'fc-future' }, root);
            el('line', { x1: fx, x2: fx, y1: m.t, y2: m.t + ih, 'class': 'fc-future-edge' }, root);
            if (!opts.compact) el('text', { x: fx + 6, y: m.t - 5, 'class': 'fc-future-tag' }, root).textContent = 'Forecast';
        }
        // grid, ticks (as many as the height allows), period labels, passing mark
        var step = [1, 2, 5, 10].filter(function (s) { return (d.hi - d.lo) / s <= ih / 22; })[0] || 10;
        for (var v = Math.ceil(d.lo / step) * step; v <= d.hi + 1e-9; v += step) {
            el('line', { x1: m.l, x2: m.l + iw, y1: Y(v), y2: Y(v), 'class': 'fc-grid' }, root);
            el('text', { x: m.l - 6, y: Y(v) + 3.5, 'class': 'fc-tick', 'text-anchor': 'end' }, root).textContent = v;
        }
        P.forEach(function (p, i) {
            el('text', { x: X(i), y: H - 8, 'class': 'fc-xlabel' + (p.p === spec.selected ? ' is-selected' : ''), 'text-anchor': 'middle' }, root).textContent = p.label;
        });
        if (spec.threshold >= d.lo && spec.threshold <= d.hi) {
            el('line', { x1: m.l, x2: m.l + iw, y1: Y(spec.threshold), y2: Y(spec.threshold), 'class': 'fc-threshold' }, root);
            if (!opts.compact) el('text', { x: m.l + iw - 4, y: Y(spec.threshold) - 4, 'class': 'fc-threshold-tag', 'text-anchor': 'end' }, root).textContent = 'Passing 75';
        }

        // series: likely range, line so far, dashed forecast, earlier forecasts, points. With many lines only the
        // overall line keeps its range in view (a legend chip shows another's); a small panel shows its own series' range.
        var layer = el('g', { 'class': 'fc-layer' }, root);
        var crowded = list.length > 3;
        list.forEach(function (se) {
            var quiet = opts.compact ? se.reference && list.length > 1 : crowded && !se.reference;
            var g = el('g', { 'class': 'fc-series' + (se.reference ? ' is-ref' : ''), 'data-key': se.key }, layer);
            var li = se.lastIndex, fore = [];
            se.points.forEach(function (pt, i) { if (pt.actual === null && pt.forecast !== null && i > li) fore.push(i); });
            if (fore.length && li >= 0) {
                var start = [X(li), Y(se.points[li].actual)];
                var upper = [start].concat(fore.map(function (i) { return [X(i), Y(se.points[i].high)]; }));
                var lower = fore.slice().reverse().map(function (i) { return [X(i), Y(se.points[i].low)]; }).concat([start]);
                el('path', { d: 'M' + upper.concat(lower).map(function (xy) { return xy[0].toFixed(1) + ',' + xy[1].toFixed(1); }).join('L') + 'Z',
                             fill: se.color, 'class': 'fc-range' + (quiet ? ' is-quiet' : '') }, g);
            }
            var d1 = '', pen = false;
            se.points.forEach(function (pt, i) {
                if (pt.actual === null) { pen = false; return; }
                d1 += (pen ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(pt.actual).toFixed(1);
                pen = true;
            });
            if (d1) el('path', { d: d1, stroke: se.color, 'class': 'fc-line' + (se.reference ? ' is-ref' : '') }, g);
            if (fore.length && li >= 0) {
                var d2 = 'M' + X(li).toFixed(1) + ',' + Y(se.points[li].actual).toFixed(1) +
                    fore.map(function (i) { return 'L' + X(i).toFixed(1) + ',' + Y(se.points[i].forecast).toFixed(1); }).join('');
                el('path', { d: d2, stroke: se.color, 'class': 'fc-line fc-dash' + (se.reference ? ' is-ref' : '') }, g);
            }
            se.points.forEach(function (pt, i) {
                if (pt.back !== null && opts.showBack) {
                    var bx = X(i), by = Y(pt.back), r = opts.compact ? 3.5 : 4.5;
                    el('path', { d: 'M' + bx + ',' + (by - r) + 'L' + (bx + r) + ',' + by + 'L' + bx + ',' + (by + r) + 'L' + (bx - r) + ',' + by + 'Z',
                                 stroke: se.color, 'class': 'fc-back' }, g);
                }
                var r0 = opts.compact ? 3.5 : 4.5, cy = pt.actual !== null ? Y(pt.actual) : (pt.forecast !== null ? Y(pt.forecast) : null);
                if (cy === null) return;
                // a series that shares its color with an earlier one has square points (color and shape tell them apart)
                var dot = se.marker === 'square'
                    ? el('rect', { x: X(i) - r0, y: cy - r0, width: 2 * r0, height: 2 * r0, rx: 1 }, g)
                    : el('circle', { cx: X(i), cy: cy, r: r0 }, g);
                if (pt.actual !== null) { dot.setAttribute('fill', se.color); dot.setAttribute('class', 'fc-dot'); }
                else { dot.setAttribute('style', 'stroke:' + se.color); dot.setAttribute('class', 'fc-dot is-fc'); }
            });
        });

        // labels at the line ends; when they crowd, leader lines keep each tied to its line
        if (ends) {
            var labels = list.filter(function (se) { return se.endIndex >= 0; }).map(function (se) {
                var v2 = valueAt(se, se.endIndex);
                return { se: se, x: X(se.endIndex), y0: Y(v2), y: Y(v2), v: v2 };
            }).sort(function (a, b) { return a.y0 - b.y0; });
            var gap = 15, lowest = m.t + ih + 4;
            labels.forEach(function (l, k) { if (k && l.y - labels[k - 1].y < gap) l.y = labels[k - 1].y + gap; });
            var overflow = labels.length ? labels[labels.length - 1].y - lowest : 0;
            if (overflow > 0) labels.forEach(function (l) { l.y -= overflow; });
            for (var k = labels.length - 2; k >= 0; k--) if (labels[k + 1].y - labels[k].y < gap) labels[k].y = labels[k + 1].y - gap;
            var lx = m.l + iw + 12;
            labels.forEach(function (l) {
                if (Math.abs(l.y - l.y0) > 1.5 || l.x < m.l + iw - 2) {
                    el('path', { d: 'M' + (l.x + 6) + ',' + l.y0 + 'L' + (lx - 4) + ',' + l.y, 'class': 'fc-leader' }, root);
                }
                el('line', { x1: lx, x2: lx + 10, y1: l.y, y2: l.y, stroke: l.se.color, 'class': 'fc-end-key' + (l.se.points[l.se.endIndex].actual === null ? ' fc-dash' : '') }, root);
                var t = el('text', { x: lx + 14, y: l.y + 3.5, 'class': 'fc-end' }, root);
                var name = l.se.name.length > 22 ? l.se.name.slice(0, 21) + '…' : l.se.name;
                el('tspan', { 'class': 'fc-end-value' }, t).textContent = fmt(l.v);
                el('tspan', { dx: 5 }, t).textContent = name;
            });
        }

        // the crosshair finds the period; arrow keys walk it
        var cross = el('line', { x1: m.l, x2: m.l, y1: m.t, y2: m.t + ih, 'class': 'fc-cross', visibility: 'hidden' }, root);
        var hit = el('rect', { x: m.l, y: m.t, width: iw, height: ih, 'class': 'fc-hit', tabindex: 0, focusable: 'true',
                               'aria-label': 'Read each period with the arrow keys' }, root);
        var current = -1;
        function place(i, evt) {
            current = Math.max(0, Math.min(n - 1, i));
            var scale = root.getBoundingClientRect().width / W;
            cross.setAttribute('x1', X(current)); cross.setAttribute('x2', X(current)); cross.setAttribute('visibility', 'visible');
            var r = root.getBoundingClientRect();
            showTip(opts.host, opts.tip, spec, list, current,
                    evt && evt.clientX !== undefined ? evt.clientX : r.left + X(current) * scale,
                    evt && evt.clientY !== undefined ? evt.clientY : r.top + (m.t + ih / 2) * scale);
        }
        function hide() { current = -1; cross.setAttribute('visibility', 'hidden'); opts.tip.hidden = true; }
        hit.addEventListener('pointermove', function (e) {
            var r = root.getBoundingClientRect(), px = (e.clientX - r.left) * (W / r.width);
            place(Math.floor((px - m.l) / (iw / n)), e);
        });
        hit.addEventListener('pointerleave', hide);
        hit.addEventListener('blur', hide);
        hit.addEventListener('focus', function () {
            var start = P.findIndex(function (p) { return p.p === spec.selected; });
            place(start >= 0 ? start : Math.max(0, list[0] ? list[0].lastIndex : 0));
        });
        hit.addEventListener('keydown', function (e) {
            if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                e.preventDefault();
                place((current < 0 ? 0 : current) + (e.key === 'ArrowRight' ? 1 : -1));
            } else if (e.key === 'Escape') { hide(); }
        });
        return root;
    }

    // ---------- bar view: every series at one period ----------
    function drawBars(stage, spec, list, index, host, tip) {
        var rows = list.map(function (se) {
            var pt = se.points[index];
            return { se: se, pt: pt, v: valueAt(se, index), fc: pt.actual === null && pt.forecast !== null };
        }).filter(function (r) { return r.v !== null; });
        if (!rows.length) { tag('p', 'fc-empty', stage, 'No averages for this period yet.'); return; }
        rows.sort(function (a, b) { return (b.se.reference - a.se.reference) || b.v - a.v; });
        var lo = 60, hi = 100, pos = function (v) { return ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo) * 100).toFixed(2) + '%'; };
        var wrap = tag('div', 'fc-bars', stage);
        rows.forEach(function (r) {
            var row = tag('div', 'fc-bar-row' + (r.se.reference ? ' is-ref' : ''), wrap);
            row.tabIndex = 0;
            var name = tag('span', 'fc-bar-name', row);
            lineKey(name, r.se.color, false);
            tag('span', '', name, r.se.name);
            var track = tag('span', 'fc-track', row);
            [70, 80, 90].forEach(function (g) { var gl = tag('span', 'fc-track-grid', track); gl.style.left = pos(g); });
            var pass = tag('span', 'fc-track-pass', track); pass.style.left = pos(spec.threshold);
            var bar = tag('span', 'fc-bar' + (r.fc ? ' is-fc' : ''), track);
            bar.style.width = pos(r.v);
            bar.style.background = r.se.color;
            if (r.fc) {
                var whisker = tag('span', 'fc-whisker', track);
                whisker.style.left = pos(r.pt.low);
                whisker.style.width = 'calc(' + pos(r.pt.high) + ' - ' + pos(r.pt.low) + ')';
            }
            var val = tag('span', 'fc-bar-value', row, fmt(r.v) + '%');
            var lv = levelOf(spec.levels, r.v);
            tag('small', 'lvl level-' + lv.key, val, lv.letter);
            var say = function (e) {
                tip.textContent = '';
                tag('h5', '', tip, spec.periods[index].name + (r.fc ? ' (forecast)' : ''));
                var line = tag('div', 'fc-tip-row', tip);
                lineKey(line, r.se.color, r.fc);
                tag('b', '', line, fmt(r.v) + '%');
                var nm = tag('span', '', line, r.se.name);
                tag('small', '', nm, r.fc ? ' likely ' + fmt(r.pt.low) + '–' + fmt(r.pt.high) : ' ' + lv.name);
                tip.hidden = false;
                var hb = host.getBoundingClientRect(), rb = row.getBoundingClientRect();
                tip.style.left = Math.min(hb.width - tip.offsetWidth - 4, Math.max(4, (e && e.clientX ? e.clientX : rb.left + rb.width / 2) - hb.left + 12)) + 'px';
                tip.style.top = Math.max(4, rb.top - hb.top - tip.offsetHeight - 6) + 'px';
            };
            row.addEventListener('pointermove', say);
            row.addEventListener('focus', function () { say(null); });
            row.addEventListener('pointerleave', function () { tip.hidden = true; });
            row.addEventListener('blur', function () { tip.hidden = true; });
            if (r.se.url) row.addEventListener('click', function () { window.location.href = r.se.url; });
        });
        var axis = tag('div', 'fc-bar-axis', wrap);
        tag('span', '', axis);
        var ticks = tag('span', 'fc-bar-ticks', axis);
        [60, 70, 80, 90, 100].forEach(function (t) { var s = tag('span', '', ticks, t); s.style.left = pos(t); });
        tag('span', '', axis);
        tag('p', 'fc-bar-note', stage, 'Bars start at 60, the lowest quarterly grade. ' +
            (rows.some(function (r) { return r.fc; }) ? 'Lighter bars are forecasts; the thin line marks their likely range.' : ''));
    }

    // ---------- table view: every value ----------
    function drawTable(stage, spec, list) {
        var wrap = tag('div', 'fc-table-wrap', stage);
        var table = tag('table', 'fc-table', wrap);
        var head = tag('tr', '', tag('thead', '', table));
        tag('th', '', head, 'Series').scope = 'col';
        spec.periods.forEach(function (p, i) {
            var th = tag('th', 'num', head, p.label);
            th.scope = 'col';
            if (spec.firstFuture >= 0 && i >= spec.firstFuture) tag('small', '', th, 'forecast');
        });
        tag('th', '', head, 'Level').scope = 'col';
        var body = tag('tbody', '', table);
        list.forEach(function (se) {
            var tr = tag('tr', se.reference ? 'is-ref' : '', body);
            var th = tag('th', '', tr);
            th.scope = 'row';
            lineKey(th, se.color, false);
            if (se.url) { var a = tag('a', '', th, se.name); a.href = se.url; } else tag('span', '', th, se.name);
            se.points.forEach(function (pt) {
                var td = tag('td', 'num', tr);
                if (pt.actual !== null) {
                    tag('b', '', td, fmt(pt.actual));
                    if (pt.back !== null) tag('small', '', td, 'forecast ' + fmt(pt.back));
                } else if (pt.forecast !== null) {
                    td.className = 'num is-fc';
                    tag('b', '', td, fmt(pt.forecast));
                    tag('small', '', td, fmt(pt.low) + '–' + fmt(pt.high));
                } else { td.textContent = '—'; }
            });
            var end = valueAt(se, se.endIndex);
            var lv = end !== null ? levelOf(spec.levels, end) : null;
            var cell = tag('td', '', tr);
            if (lv) {
                tag('span', 'lvl level-' + lv.key, cell, lv.short + ' (' + lv.letter + ')');
                if (se.points[se.endIndex].actual === null) tag('small', 'fc-by', cell, 'by ' + spec.periods[se.endIndex].label);
            }
        });
    }

    // ---------- one chart: toolbar, legend, view ----------
    function mount(host) {
        var source = document.getElementById(host.dataset.forecast);
        if (!source) return;
        var spec = prepare(JSON.parse(source.textContent));
        host.classList.add('fc');
        host.textContent = '';
        if (!spec.series.length) { tag('p', 'fc-empty', host, 'No grades yet for this selection, so there is nothing to forecast.'); return; }
        var id = host.dataset.forecast;
        var groups = spec.series.filter(function (se) { return !se.reference; });
        var ref = spec.series.filter(function (se) { return se.reference; })[0] || null;
        var panels = groups.length > MAX_LINES;
        var state = { view: remember('arms-fc-view:' + id) || 'line' };
        if (['line', 'bar', 'table'].indexOf(state.view) < 0) state.view = 'line';
        var withValues = spec.periods.map(function (p, i) { return spec.series.some(function (se) { return valueAt(se, i) !== null; }); });
        state.period = spec.firstFuture >= 0 ? spec.firstFuture : withValues.lastIndexOf(true);

        var bar = tag('div', 'fc-toolbar', host);
        var tabs = tag('div', 'fc-tabs', bar);
        tabs.setAttribute('role', 'tablist');
        tabs.setAttribute('aria-label', 'Show the forecast as');
        var stageId = id + '-view';
        var buttons = [['line', panels ? 'Panels' : 'Line', 'fi-rr-chart-line-up'], ['bar', 'Bar', 'fi-rr-chart-simple-horizontal'],
                       ['table', 'Table', 'fi-rr-table-list']].map(function (v) {
            var b = tag('button', '', tabs);
            b.type = 'button';
            b.setAttribute('role', 'tab');
            b.setAttribute('aria-controls', stageId);
            b.dataset.view = v[0];
            tag('i', 'fi ' + v[2], b).setAttribute('aria-hidden', 'true');
            tag('span', '', b, v[1]);
            b.addEventListener('click', function () { state.view = v[0]; remember('arms-fc-view:' + id, v[0]); render(); });
            return b;
        });
        var periodPick = tag('label', 'fc-period', bar);
        tag('span', '', periodPick, 'Period');
        var select = tag('select', '', periodPick);
        spec.periods.forEach(function (p, i) {
            if (!withValues[i]) return;
            var o = tag('option', '', select, p.name + (spec.firstFuture >= 0 && i >= spec.firstFuture ? ' (forecast)' : ''));
            o.value = i;
        });
        select.addEventListener('change', function () { state.period = +select.value; render(); });

        var legend = tag('div', 'fc-legend', host);
        var stage = tag('div', 'fc-stage', host);
        stage.id = stageId;
        stage.setAttribute('role', 'tabpanel');
        var tip = tag('div', 'fc-tip', host);
        tip.hidden = true;
        tip.setAttribute('aria-hidden', 'true');
        tag('p', 'fc-method explain', host, spec.method.text);

        function drawLegend() {
            legend.textContent = '';
            if (state.view === 'line' && !panels) {
                spec.series.forEach(function (se) {
                    var chip = tag('button', 'fc-chip' + (se.reference ? ' is-ref' : ''), legend);
                    chip.type = 'button';
                    chip.setAttribute('aria-pressed', se.visible ? 'true' : 'false');
                    chip.title = se.visible ? 'Hide ' + se.name : 'Show ' + se.name;
                    lineKey(chip, se.color, false);
                    tag('span', '', chip, se.name);
                    chip.addEventListener('click', function () {
                        if (se.visible && spec.series.filter(function (s) { return s.visible; }).length === 1) return;
                        se.visible = !se.visible;
                        render();
                    });
                    // pointing at a chip (or tabbing to it) brings its line forward with its likely range
                    var spot = function () {
                        stage.querySelectorAll('.fc-series').forEach(function (g) {
                            g.classList.toggle('is-dim', g.dataset.key !== se.key);
                            g.classList.toggle('is-focus', g.dataset.key === se.key);
                        });
                    };
                    var unspot = function () { stage.querySelectorAll('.fc-series').forEach(function (g) { g.classList.remove('is-dim', 'is-focus'); }); };
                    chip.addEventListener('pointerenter', spot);
                    chip.addEventListener('focus', spot);
                    chip.addEventListener('pointerleave', unspot);
                    chip.addEventListener('blur', unspot);
                });
            } else if (state.view === 'line' && ref) {
                var refKey = tag('span', 'fc-style', legend);
                lineKey(refKey, ref.color, false);
                tag('span', '', refKey, ref.name);
            }
            if (state.view === 'line') {
                var keys = tag('span', 'fc-styles', legend);
                var k1 = tag('span', 'fc-style', keys); lineKey(k1, '#4a5568', false); tag('span', '', k1, 'Average so far');
                if (spec.hasForecast) {
                    var k2 = tag('span', 'fc-style', keys); lineKey(k2, '#4a5568', true); tag('span', '', k2, 'Forecast');
                    var k3 = tag('span', 'fc-style', keys); tag('i', 'fc-key-range', k3); tag('span', '', k3, 'Likely range (90%)');
                }
                if (spec.hasBack) { var k4 = tag('span', 'fc-style', keys); tag('i', 'fc-key-back', k4); tag('span', '', k4, 'Earlier forecast'); }
                var k5 = tag('span', 'fc-style', keys); tag('i', 'fc-key-pass', k5); tag('span', '', k5, 'Passing 75');
            }
        }

        function render() {
            buttons.forEach(function (b) { b.setAttribute('aria-selected', b.dataset.view === state.view ? 'true' : 'false'); });
            periodPick.hidden = state.view !== 'bar';
            select.value = state.period;
            tip.hidden = true;
            drawLegend();
            stage.textContent = '';
            var visible = spec.series.filter(function (se) { return se.visible; });
            var label = 'Average grade by grading period: ' + visible.map(function (se) {
                var i = se.endIndex;
                return se.name + ' ' + fmt(valueAt(se, i)) + (se.points[i] && se.points[i].actual === null ? ' forecast for ' : ' in ') + (spec.periods[i] || {}).name;
            }).join('; ');
            if (state.view === 'table') { drawTable(stage, spec, spec.series); return; }
            if (state.view === 'bar') { drawBars(stage, spec, visible, state.period, host, tip); return; }
            if (!panels) {
                // a taller chart for many lines, so the labels at their ends keep apart
                drawLines(stage, spec, { list: visible, dom: domain(spec, visible), height: LINE_H + Math.max(0, visible.length - 6) * 16,
                                         labels: true, showBack: true,
                                         host: host, tip: tip, label: label });
                return;
            }
            var grid = tag('div', 'fc-panels', stage);
            var dom = domain(spec, spec.series);
            groups.forEach(function (se) {
                var card = tag('div', 'fc-panel', grid);
                var head = tag('div', 'fc-panel-head', card);
                lineKey(head, se.color, false);
                var name = tag(se.url ? 'a' : 'span', 'fc-panel-name', head, se.name);
                name.title = se.name;
                if (se.url) name.href = se.url;
                var last = se.lastIndex >= 0 ? se.points[se.lastIndex].actual : null;
                var end = valueAt(se, se.endIndex);
                var val = tag('span', 'fc-panel-value', head);
                tag('b', '', val, fmt(last));
                if (se.endIndex > se.lastIndex) tag('small', '', val, ' → ' + fmt(end));
                var plot = tag('div', 'fc-panel-plot', card);
                drawLines(plot, spec, { list: ref ? [ref, se] : [se], dom: dom, height: PANEL_H, compact: true, labels: false,
                                        showBack: true, host: host, tip: tip, label: se.name + ': ' + fmt(last) + (se.endIndex > se.lastIndex ? ', forecast ' + fmt(end) : '') });
            });
        }

        render();
        var width = host.clientWidth, pending = false;
        var onResize = function () {
            if (pending) return;
            pending = true;
            requestAnimationFrame(function () {
                pending = false;
                if (Math.abs(host.clientWidth - width) > 4) { width = host.clientWidth; render(); }
            });
        };
        if (window.ResizeObserver) new ResizeObserver(onResize).observe(host);
        else window.addEventListener('resize', onResize);
    }

    function mountAll() { document.querySelectorAll('[data-forecast]').forEach(mount); }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountAll);
    else mountAll();
    window.ArmsForecast = { mount: mount };
})();
