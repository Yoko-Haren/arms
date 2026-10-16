// Runs inside the page. Walks the rendered DOM and returns an SVG that Figma imports as editable layers.
// Names (SVG ids) carry data for the Figma pass:  "→group/slug|label" = link,  "btn|label|hint" = button,
// "~sh:x,y,blur,spread,r,g,b,a" = drop shadow,  "~ls:n" = letter spacing.
window.__armsExtract = async function (opts) {
  const VW = window.innerWidth, VH = opts.height;
  const N = v => +(Math.round(v * 100) / 100);
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  // characters XML 1.0 does not allow
  const clean = s => String(s).replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F￾￿]/g, '');
  let seq = 0;
  const defs = [], layers = [];
  const stats = { text: 0, shape: 0, icon: 0, image: 0, link: 0, btn: 0, clip: 0, group: 0, pseudoText: 0, pseudoBox: 0, skippedPseudo: {}, fonts: {}, notes: [] };
  const buttons = [], links = [];
  const ctx = document.createElement('canvas').getContext('2d');

  // ---------- colours ----------
  function col(c) {
    if (!c) return null;
    let m = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)/.exec(c);
    let rgb, a = 1;
    if (m) { rgb = [1, 2, 3].map(i => Math.round(+m[i])); if (m[4] !== undefined) a = m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]); }
    else {
      m = /color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+))?\)/.exec(c);
      if (!m) return null;
      rgb = [1, 2, 3].map(i => Math.round(+m[i] * 255)); if (m[4] !== undefined) a = parseFloat(m[4]);
    }
    return { hex: '#' + rgb.map(v => Math.max(0, Math.min(255, v)).toString(16).padStart(2, '0')).join(''), a, rgb };
  }
  const paint = (c, attr) => `${attr}="${c.hex}"` + (c.a < 1 ? ` ${attr}-opacity="${N(c.a)}"` : '');
  function splitTop(s) { const out = []; let d = 0, cur = ''; for (const ch of s) { if (ch === '(') d++; if (ch === ')') d--; if (ch === ',' && d === 0) { out.push(cur.trim()); cur = ''; } else cur += ch; } if (cur.trim()) out.push(cur.trim()); return out; }
  function stopsOf(parts) {
    const st = parts.map(p => { const c = col(p); if (!c) return null; const rest = p.replace(/rgba?\([^)]*\)|color\([^)]*\)/, ''); const pm = /(-?[\d.]+)%/.exec(rest); return { c, pos: pm ? parseFloat(pm[1]) / 100 : null }; });
    if (st.length < 2 || st.some(s => !s)) return null;
    if (st[0].pos === null) st[0].pos = 0; if (st[st.length - 1].pos === null) st[st.length - 1].pos = 1;
    for (let i = 1; i < st.length - 1; i++) if (st[i].pos === null) { let j = i; while (st[j].pos === null) j++; const a = st[i - 1].pos, b = st[j].pos; for (let k = i; k < j; k++) st[k].pos = a + (b - a) * (k - i + 1) / (j - i + 1); }
    return st.map(s => `<stop offset="${N(Math.max(0, Math.min(1, s.pos)))}" stop-color="${s.c.hex}"${s.c.a < 1 ? ` stop-opacity="${N(s.c.a)}"` : ''}/>`).join('');
  }
  function gradient(layer, b) {
    let m = /^linear-gradient\(([\s\S]*)\)$/.exec(layer);
    if (m) {
      const parts = splitTop(m[1]); let ang = 180; const first = parts[0];
      if (/^-?[\d.]+(deg|rad|turn|grad)$/.test(first)) { const v = parseFloat(first); ang = first.endsWith('rad') ? v * 180 / Math.PI : first.endsWith('turn') ? v * 360 : first.endsWith('grad') ? v * 0.9 : v; parts.shift(); }
      else if (/^to /.test(first)) {
        const t = first.slice(3).trim().split(/\s+/).sort().join(' '); const diag = Math.atan2(b.h, b.w) * 180 / Math.PI;
        ang = { top: 0, right: 90, bottom: 180, left: 270, 'right top': diag, 'bottom right': 180 - diag, 'bottom left': 180 + diag, 'left top': 360 - diag }[t]; if (ang === undefined) ang = 180; parts.shift();
      }
      const stops = stopsOf(parts); if (!stops) return null;
      const t = ang * Math.PI / 180, dx = Math.sin(t), dy = -Math.cos(t), L = Math.abs(b.w * dx) + Math.abs(b.h * dy), cx = b.x + b.w / 2, cy = b.y + b.h / 2, id = 'g' + (++seq);
      defs.push(`<linearGradient id="${id}" gradientUnits="userSpaceOnUse" x1="${N(cx - dx * L / 2)}" y1="${N(cy - dy * L / 2)}" x2="${N(cx + dx * L / 2)}" y2="${N(cy + dy * L / 2)}">${stops}</linearGradient>`);
      return `url(#${id})`;
    }
    m = /^radial-gradient\(([\s\S]*)\)$/.exec(layer);
    if (m) {
      const parts = splitTop(m[1]); if (!col(parts[0])) parts.shift();
      const stops = stopsOf(parts); if (!stops) return null; const id = 'g' + (++seq);
      defs.push(`<radialGradient id="${id}" gradientUnits="userSpaceOnUse" cx="${N(b.x + b.w / 2)}" cy="${N(b.y + b.h / 2)}" r="${N(Math.max(b.w, b.h) / 2)}">${stops}</radialGradient>`);
      return `url(#${id})`;
    }
    return null;
  }

  // ---------- geometry ----------
  function radii(cs, b) {
    return ['borderTopLeftRadius', 'borderTopRightRadius', 'borderBottomRightRadius', 'borderBottomLeftRadius'].map(k => {
      const v = (cs[k] || '0').split(' ')[0]; const n = v.endsWith('%') ? parseFloat(v) / 100 * Math.min(b.w, b.h) : parseFloat(v) || 0;
      return Math.max(0, Math.min(n, b.w / 2, b.h / 2));
    });
  }
  function rrPath(x, y, w, h, r) {
    const [tl, tr, br, bl] = r;
    return `M${N(x + tl)} ${N(y)}H${N(x + w - tr)}` + (tr ? `A${N(tr)} ${N(tr)} 0 0 1 ${N(x + w)} ${N(y + tr)}` : '') + `V${N(y + h - br)}` + (br ? `A${N(br)} ${N(br)} 0 0 1 ${N(x + w - br)} ${N(y + h)}` : '') +
      `H${N(x + bl)}` + (bl ? `A${N(bl)} ${N(bl)} 0 0 1 ${N(x)} ${N(y + h - bl)}` : '') + `V${N(y + tl)}` + (tl ? `A${N(tl)} ${N(tl)} 0 0 1 ${N(x + tl)} ${N(y)}` : '') + 'Z';
  }
  function shape(b, r, inset) {
    const x = b.x + inset, y = b.y + inset, w = b.w - 2 * inset, h = b.h - 2 * inset; if (w <= 0.05 || h <= 0.05) return null;
    const rr = r.map(v => Math.max(0, Math.min(v - inset, w / 2, h / 2)));
    if (rr.every(v => Math.abs(v - rr[0]) < 0.05)) return `<rect x="${N(x)}" y="${N(y)}" width="${N(w)}" height="${N(h)}"` + (rr[0] > 0.05 ? ` rx="${N(rr[0])}"` : '');
    return `<path d="${rrPath(x, y, w, h, rr)}"`;
  }
  function clipDef(b, r) { const s = shape(b, r, 0); if (!s) return null; const id = 'c' + (++seq); defs.push(`<clipPath id="${id}">${s}/></clipPath>`); stats.clip++; return id; }
  function shadowMark(v) {
    if (!v || v === 'none') return '';
    for (const part of splitTop(v)) {
      if (/inset/.test(part)) continue; const c = col(part); if (!c || c.a <= 0) continue;
      const nums = part.replace(/rgba?\([^)]*\)|color\([^)]*\)/, '').trim().split(/\s+/).map(parseFloat);
      if (nums.length < 2 || nums.some(isNaN)) continue;
      const [x, y, blur = 0, spread = 0] = nums; if (blur === 0 && spread === 0 && x === 0 && y === 0) continue;
      return ` ~sh:${N(x)},${N(y)},${N(blur)},${N(spread)},${c.rgb.join(',')},${N(c.a)}`;
    }
    return '';
  }

  // ---------- naming ----------
  const UTIL = /^(d-|m[trblxyse]?-|p[trblxyse]?-|col|row$|g-|gap-|w-|h-|text-|align-|justify-|flex|fi$|fi-|fa$|fa-|fas$|far$|fab$|bg-|border|rounded|shadow|position-|fw-|fs-|small$|float-|me-|ms-|mt-|mb-|active$|show$|fade$|container|table-|overflow|lh-|opacity|visible|order-|list-)/;
  function label(el) {
    if (el.id && el.id.length < 32 && !/^\d/.test(el.id)) return el.id;
    for (const c of el.classList) if (!UTIL.test(c)) return c;
    return el.tagName.toLowerCase();
  }
  const short = (el, n) => clean((el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').trim().replace(/\s+/g, ' ')).slice(0, n);
  function target(el) {
    if (el.tagName === 'A') {
      const raw = el.getAttribute('href') || ''; if (!raw || raw[0] === '#' || /^javascript/i.test(raw)) return null;
      const m = /\/screens\/([a-z]+)\/([a-z0-9-]+)\.html/.exec(el.href); return m ? m[1] + '/' + m[2] : null;
    }
    return null;
  }

  // ---------- fonts ----------
  const metricCache = {};
  function metrics(cs) {
    const key = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    if (!metricCache[key]) { ctx.font = key; const m = ctx.measureText('Hg'); metricCache[key] = { asc: Math.round(m.fontBoundingBoxAscent), desc: Math.round(m.fontBoundingBoxDescent) }; }
    return metricCache[key];
  }
  const ICON = /uicons|font ?awesome|bootstrap-icons|material icons/i;
  function psName(cs) {
    const fam = cs.fontFamily.split(',')[0].replace(/["']/g, '').trim().toLowerCase();
    const w = parseInt(cs.fontWeight) || 400, it = cs.fontStyle !== 'normal';
    let name;
    if (/mono/.test(fam)) name = 'RobotoMono-' + (w >= 600 ? 'Bold' : 'Regular') + (it ? 'Italic' : '');
    else {
      const st = w < 350 ? 'Light' : w < 550 ? 'Regular' : w < 650 ? 'SemiBold' : w < 750 ? 'Bold' : 'ExtraBold';
      name = 'OpenSans-' + (it ? (st === 'Regular' ? 'Italic' : st + 'Italic') : st);
    }
    stats.fonts[name] = (stats.fonts[name] || 0) + 1;
    return name;
  }
  function textEl(str, x, base, cs, anchor, extra) {
    const c = col(cs.color); if (!c || c.a <= 0) return ''; const fs = parseFloat(cs.fontSize); if (!fs) return '';
    const ls = parseFloat(cs.letterSpacing) || 0;
    let s = clean(str);
    const tt = cs.textTransform; if (tt === 'uppercase') s = s.toUpperCase(); else if (tt === 'lowercase') s = s.toLowerCase(); else if (tt === 'capitalize') s = s.replace(/(^|\s)(\S)/g, (m, a, b) => a + b.toUpperCase());
    if (!s.trim()) return '';
    stats.text++;
    return `<text x="${N(x)}" y="${N(base)}" font-family="${psName(cs)}" font-size="${N(fs)}" ${paint(c, 'fill')}` + (anchor && anchor !== 'start' ? ` text-anchor="${anchor}"` : '') +
      (/underline/.test(cs.textDecorationLine || '') || (extra && extra.underline) ? ' text-decoration="underline"' : '') + (/line-through/.test(cs.textDecorationLine || '') ? ' text-decoration="line-through"' : '') +
      (Math.abs(ls) >= 0.2 ? ` id="~ls:${N(ls)}"` : '') + `>${esc(s)}</text>`;
  }
  function textNode(node, el, cs) {
    const text = node.nodeValue; if (!text || !text.trim()) return [];
    const pb = el.getBoundingClientRect(); if (pb.width <= 1.5 && pb.height <= 1.5) return [];
    const m = metrics(cs), range = document.createRange(), re = /\S+/g, lines = []; let w, cur = null;
    while ((w = re.exec(text))) {
      range.setStart(node, w.index); range.setEnd(node, w.index + w[0].length);
      const rects = range.getClientRects(); if (!rects.length) continue; const r = rects[0], last = rects[rects.length - 1];
      if (r.width === 0 && r.height === 0) continue;
      if (cur && Math.abs(r.top - cur.top) < 3 && r.left >= cur.right - 3) { cur.end = w.index + w[0].length; cur.right = last.right; }
      else { cur = { start: w.index, end: w.index + w[0].length, top: r.top, left: r.left, right: last.right }; lines.push(cur); }
    }
    const out = [], pcs = el.parentElement ? getComputedStyle(el) : cs;
    let under = false; for (let a = el, i = 0; a && i < 3; a = a.parentElement, i++) if (/underline/.test(getComputedStyle(a).textDecorationLine)) under = true;
    for (const ln of lines) {
      if (ln.top > VH || ln.top + m.asc + m.desc < 0 || ln.left > VW || ln.right < 0) continue;
      const str = /pre/.test(cs.whiteSpace) ? text.slice(ln.start, ln.end) : text.slice(ln.start, ln.end).replace(/\s+/g, ' ');
      // anchor: keep centred / right-aligned text anchored so small width differences stay put
      let anchor = 'start', x = ln.left; const width = ln.right - ln.left;
      const pl = pb.left + (parseFloat(pcs.paddingLeft) || 0) + (parseFloat(pcs.borderLeftWidth) || 0), pr = pb.right - (parseFloat(pcs.paddingRight) || 0) - (parseFloat(pcs.borderRightWidth) || 0);
      if (lines.length === 1 && el.childNodes.length === 1 && pr - pl - width > 3) {
        if (Math.abs((pl + pr) / 2 - (ln.left + ln.right) / 2) <= 1) { anchor = 'middle'; x = (ln.left + ln.right) / 2; }
        else if (Math.abs(pr - ln.right) <= 1 && /right|end/.test(pcs.textAlign)) { anchor = 'end'; x = ln.right; }
      }
      const f = textEl(str, x, ln.top + m.asc, cs, anchor, { underline: under }); if (f) out.push(f);
    }
    return out;
  }

  // ---------- pseudo elements ----------
  function unquote(c) { const m = /^"((?:[^"\\]|\\.)*)"$/.exec(c) || /^'((?:[^'\\]|\\.)*)'$/.exec(c); return m ? m[1].replace(/\\([0-9a-fA-F]{1,6})\s?/g, (x, h) => String.fromCodePoint(parseInt(h, 16))).replace(/\\(.)/g, '$1') : null; }
  function marker(el, which) {
    const mk = document.createElement('span');
    mk.style.cssText = 'display:inline-block!important;width:0!important;height:0!important;padding:0!important;margin:0!important;border:0!important;vertical-align:baseline!important;position:static!important;float:none!important;min-width:0!important;';
    if (which === '::before') el.insertBefore(mk, el.firstChild); else el.appendChild(mk);
    const r = mk.getBoundingClientRect(); mk.remove(); return r;
  }
  function pseudo(el, cs, which) {
    const ps = getComputedStyle(el, which), content = ps.content;
    if (!content || content === 'none' || content === 'normal' || ps.display === 'none' || ps.visibility === 'hidden' || parseFloat(ps.opacity) === 0) return [];
    const str = unquote(content); if (str === null) { stats.skippedPseudo[content.slice(0, 20)] = 1; return []; }
    const out = [], eb = el.getBoundingClientRect(), fam = ps.fontFamily, size = parseFloat(ps.fontSize);
    const flexy = /flex|grid/.test(cs.display);
    if (str === '') {
      // decorative box
      const bg = col(ps.backgroundColor), img = ps.backgroundImage !== 'none' ? splitTop(ps.backgroundImage) : [];
      const bw = parseFloat(ps.borderTopWidth) || 0, bcol = col(ps.borderTopColor), hasBorder = bw > 0 && ps.borderTopStyle !== 'none' && bcol && bcol.a > 0;
      if (!(bg && bg.a > 0) && !img.length && !hasBorder) return [];
      let b = null; const w = parseFloat(ps.width), h = parseFloat(ps.height);
      if (ps.position === 'absolute' || ps.position === 'fixed') {
        const cbEl = cs.position !== 'static' ? el : (el.offsetParent || document.documentElement), cr = cbEl.getBoundingClientRect(), ccs = getComputedStyle(cbEl);
        const cb = { x: cr.left + (parseFloat(ccs.borderLeftWidth) || 0), y: cr.top + (parseFloat(ccs.borderTopWidth) || 0), w: cbEl.clientWidth || cr.width, h: cbEl.clientHeight || cr.height };
        const L = parseFloat(ps.left), T = parseFloat(ps.top), R = parseFloat(ps.right), B = parseFloat(ps.bottom);
        const bx = 2 * (parseFloat(ps.borderLeftWidth) || 0), by = 2 * bw, px = (parseFloat(ps.paddingLeft) || 0) + (parseFloat(ps.paddingRight) || 0), py = (parseFloat(ps.paddingTop) || 0) + (parseFloat(ps.paddingBottom) || 0);
        const border = ps.boxSizing === 'border-box';
        let ww = isNaN(w) ? (isNaN(L) || isNaN(R) ? 0 : cb.w - L - R) : w + (border ? 0 : bx + px), hh = isNaN(h) ? (isNaN(T) || isNaN(B) ? 0 : cb.h - T - B) : h + (border ? 0 : by + py);
        b = { x: !isNaN(L) ? cb.x + L : !isNaN(R) ? cb.x + cb.w - R - ww : cb.x, y: !isNaN(T) ? cb.y + T : !isNaN(B) ? cb.y + cb.h - B - hh : cb.y, w: ww, h: hh };
        const tm = /matrix\(([^)]+)\)/.exec(ps.transform); if (tm) { const v = tm[1].split(',').map(parseFloat); b.x += v[4]; b.y += v[5]; }
      } else if (!isNaN(w) && !isNaN(h) && w > 0 && h > 0 && !flexy) {
        const r = marker(el, which), mr = parseFloat(ps.marginRight) || 0, ml = parseFloat(ps.marginLeft) || 0;
        const va = ps.verticalAlign, m = metrics(cs);
        const y = va === 'middle' ? r.bottom - m.asc * 0.25 - h / 2 : r.bottom - h - (parseFloat(ps.marginBottom) || 0);
        b = { x: which === '::before' ? r.left - mr - w : r.left + ml, y, w, h };
      } else if (!isNaN(w) && !isNaN(h) && w > 0 && h > 0) {
        b = { x: eb.left + (parseFloat(cs.paddingLeft) || 0), y: eb.top + (eb.height - h) / 2, w, h };
      }
      if (!b || b.w <= 0 || b.h <= 0 || b.w > VW * 1.5 || b.h > VH * 1.5) return [];
      const r = radii(ps, b), base = shape(b, r, 0); if (!base) return [];
      if (bg && bg.a > 0) out.push(`${base} id="${which === '::before' ? 'before' : 'after'}${shadowMark(ps.boxShadow)}" ${paint(bg, 'fill')}/>`);
      for (const layer of img) { const g = gradient(layer, b); if (g) out.push(`${base} id="${which === '::before' ? 'before' : 'after'}" fill="${g}"/>`); }
      if (hasBorder) { const s = shape(b, r, bw / 2); if (s) out.push(`${s} fill="none" ${paint(bcol, 'stroke')} stroke-width="${N(bw)}"/>`); }
      if (out.length) { stats.pseudoBox++; stats.shape += out.length; }
      const po = parseFloat(ps.opacity); return po < 1 && out.length ? [`<g opacity="${N(po)}">${out.join('')}</g>`] : out;
    }
    const c = col(ps.color); if (!c || c.a <= 0 || !size) return [];
    ctx.font = `${ps.fontStyle} ${ps.fontWeight} ${size}px ${fam}`;
    const tm = ctx.measureText(str), adv = tm.width, A = Math.round(tm.fontBoundingBoxAscent), D = Math.round(tm.fontBoundingBoxDescent);
    let x, base;
    if (ps.position === 'absolute' || ps.position === 'fixed') { stats.skippedPseudo['abs:' + str.slice(0, 6)] = 1; return []; }
    if (flexy) {
      const pl = parseFloat(cs.paddingLeft) || 0, pr = parseFloat(cs.paddingRight) || 0, pt = parseFloat(cs.paddingTop) || 0, pb2 = parseFloat(cs.paddingBottom) || 0;
      const cw = eb.width - pl - pr, ch = eb.height - pt - pb2, lh = parseFloat(ps.lineHeight) || (A + D);
      x = /center/.test(cs.justifyContent) ? eb.left + pl + (cw - adv) / 2 : eb.left + pl;
      const top = /center/.test(cs.alignItems) ? eb.top + pt + (ch - lh) / 2 : eb.top + pt;
      base = top + (lh - (A + D)) / 2 + A;
    } else {
      const r = marker(el, which);
      x = which === '::before' ? r.left - adv - (parseFloat(ps.marginRight) || 0) - (parseFloat(ps.paddingRight) || 0) : r.left + (parseFloat(ps.marginLeft) || 0) + (parseFloat(ps.paddingLeft) || 0);
      base = r.bottom;
    }
    if (x > VW || x + adv < 0 || base < 0 || base - size > VH) return [];
    if (ICON.test(fam)) {
      const famName = fam.split(',')[0].replace(/["']/g, '').trim();
      for (const ch of str) { out.push(`<path data-icon="${esc(famName)}|${ps.fontWeight}|${ch.codePointAt(0)}|${N(size)}|${N(x)}|${N(base)}|${c.hex}|${N(c.a)}"/>`); x += ctx.measureText(ch).width; stats.icon++; }
    } else if (str.trim()) { const f = textEl(str, x, base, ps, 'start'); if (f) { out.push(f); stats.pseudoText++; } }
    return out;
  }

  // ---------- form controls ----------
  function control(el, cs, b) {
    const tag = el.tagName, type = (el.getAttribute('type') || 'text').toLowerCase(), out = [], m = metrics(cs);
    const pl = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.borderLeftWidth) || 0), pr = (parseFloat(cs.paddingRight) || 0) + (parseFloat(cs.borderRightWidth) || 0), pt = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.borderTopWidth) || 0);
    const mid = b.y + b.h / 2 + (m.asc - m.desc) / 2;
    const place = (str, colour) => {
      const st = Object.create(null); for (const k of ['fontStyle', 'fontWeight', 'fontSize', 'fontFamily', 'letterSpacing', 'textTransform', 'whiteSpace', 'textDecorationLine']) st[k] = cs[k]; st.color = colour;
      if (/center/.test(cs.textAlign)) return textEl(str, b.x + pl + (b.w - pl - pr) / 2, mid, st, 'middle');
      return textEl(str, b.x + pl, mid, st, 'start');
    };
    if (tag === 'INPUT') {
      if (type === 'checkbox' || type === 'radio') {
        const on = el.checked, acc = col(cs.accentColor) || { hex: '#123499', a: 1 }, r = type === 'radio' ? b.w / 2 : Math.min(3, b.w / 4);
        out.push(`<rect id="${type}" x="${N(b.x + 0.5)}" y="${N(b.y + 0.5)}" width="${N(b.w - 1)}" height="${N(b.h - 1)}" rx="${N(r)}" fill="${on ? acc.hex : '#ffffff'}" stroke="${on ? acc.hex : '#767676'}" stroke-width="1"/>`);
        if (on && type === 'checkbox') out.push(`<path d="M${N(b.x + b.w * 0.22)} ${N(b.y + b.h * 0.52)}L${N(b.x + b.w * 0.42)} ${N(b.y + b.h * 0.72)}L${N(b.x + b.w * 0.78)} ${N(b.y + b.h * 0.28)}" fill="none" stroke="#ffffff" stroke-width="${N(Math.max(1.5, b.w / 8))}" stroke-linecap="round" stroke-linejoin="round"/>`);
        if (on && type === 'radio') out.push(`<circle cx="${N(b.x + b.w / 2)}" cy="${N(b.y + b.h / 2)}" r="${N(b.w / 5)}" fill="#ffffff"/>`);
        stats.shape += out.length; return out;
      }
      if (type === 'file') { out.push(place('Choose File   No file chosen', cs.color)); return out; }
      if (type === 'color') { const c = col(getComputedStyle(el).color); out.push(`<rect x="${N(b.x + 4)}" y="${N(b.y + 4)}" width="${N(b.w - 8)}" height="${N(b.h - 8)}" fill="${el.value || '#000000'}"/>`); return out; }
      if (['submit', 'button', 'reset'].includes(type)) { out.push(place(el.value || 'Submit', cs.color)); return out; }
      let v = el.value;
      if (v && type === 'password') v = '•'.repeat(Math.min(v.length, 24));
      if (v && type === 'date') { const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v); if (d) v = `${d[2]}/${d[3]}/${d[1]}`; }
      if (v) out.push(place(v, cs.color));
      else if (type === 'date') out.push(place('mm/dd/yyyy', cs.color));
      else if (el.placeholder) out.push(place(el.placeholder, getComputedStyle(el, '::placeholder').color));
      return out;
    }
    if (tag === 'TEXTAREA') {
      const v = el.value, str = v || el.placeholder || ''; if (!str) return out;
      const colour = v ? cs.color : getComputedStyle(el, '::placeholder').color, lh = parseFloat(cs.lineHeight) || (m.asc + m.desc);
      const st = Object.create(null); for (const k of ['fontStyle', 'fontWeight', 'fontSize', 'fontFamily', 'letterSpacing', 'textTransform', 'whiteSpace', 'textDecorationLine']) st[k] = cs[k]; st.color = colour;
      ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
      const maxW = b.w - pl - pr - 4, rows = [];
      for (const para of str.split('\n')) { let line = ''; for (const word of para.split(' ')) { const t = line ? line + ' ' + word : word; if (line && ctx.measureText(t).width > maxW) { rows.push(line); line = word; } else line = t; } rows.push(line); }
      rows.slice(0, Math.max(1, Math.floor((b.h - pt) / lh))).forEach((row, i) => { const f = textEl(row, b.x + pl, b.y + pt + (lh - (m.asc + m.desc)) / 2 + m.asc + i * lh, st, 'start'); if (f) out.push(f); });
      return out;
    }
    if (tag === 'SELECT') {
      const opt = el.options[el.selectedIndex]; if (opt) out.push(place(opt.text.trim(), cs.color));
      if (!/url\(/.test(cs.backgroundImage)) { const cx = b.x + b.w - Math.max(12, Math.min(18, pr || 14)), cy = b.y + b.h / 2; const c = col(cs.color) || { hex: '#4a5568', a: 1 }; out.push(`<path id="chevron" d="M${N(cx - 4)} ${N(cy - 2)}L${N(cx)} ${N(cy + 2)}L${N(cx + 4)} ${N(cy - 2)}" fill="none" stroke="${c.hex}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>`); stats.shape++; }
      return out;
    }
    return out;
  }

  // ---------- images ----------
  const imgData = new Map();
  await Promise.all([...document.images].map(async img => {
    try { const r = await fetch(img.currentSrc || img.src); const blob = await r.blob(); imgData.set(img, await new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(blob); })); } catch (e) { stats.notes.push('img failed ' + (img.src || '').slice(0, 60)); }
  }));
  const bgUrlData = new Map();
  function inlineSvg(el, b) {
    const clone = el.cloneNode(true), src = [el, ...el.querySelectorAll('*')], dst = [clone, ...clone.querySelectorAll('*')];
    src.forEach((s, i) => {
      const d = dst[i]; if (!(s instanceof SVGGraphicsElement) || s === el) { d.removeAttribute('class'); return; }
      const st = getComputedStyle(s);
      if (!/^(g|svg|defs|use)$/i.test(s.tagName)) {
        const fill = st.fill, stroke = st.stroke;
        if (fill && !/^url/.test(fill)) { const c = col(fill); if (fill === 'none' || !c) d.setAttribute('fill', 'none'); else { d.setAttribute('fill', c.hex); if (c.a < 1) d.setAttribute('fill-opacity', N(c.a)); } }
        if (stroke && stroke !== 'none' && !/^url/.test(stroke)) { const c = col(stroke); if (c) { d.setAttribute('stroke', c.hex); d.setAttribute('stroke-width', parseFloat(st.strokeWidth) || 1); if (st.strokeLinecap !== 'butt') d.setAttribute('stroke-linecap', st.strokeLinecap); if (st.strokeLinejoin !== 'miter') d.setAttribute('stroke-linejoin', st.strokeLinejoin); } }
      }
      d.removeAttribute('class'); d.removeAttribute('style');
    });
    const vb = el.viewBox && el.viewBox.baseVal && el.viewBox.baseVal.width ? el.viewBox.baseVal : { x: 0, y: 0, width: b.w, height: b.h };
    const s = Math.min(b.w / vb.width, b.h / vb.height), ox = b.x + (b.w - vb.width * s) / 2, oy = b.y + (b.h - vb.height * s) / 2;
    stats.image++;
    return `<g id="${esc(label(el) === 'svg' ? 'icon' : label(el))}" transform="translate(${N(ox)} ${N(oy)}) scale(${N(s)}) translate(${N(-vb.x)} ${N(-vb.y)})">${clone.innerHTML.replace(/\s+xmlns="[^"]*"/g, '')}</g>`;
  }

  // ---------- element walk ----------
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'HEAD', 'META', 'LINK', 'TITLE', 'OPTION', 'OPTGROUP', 'DATALIST', 'BR', 'WBR', 'IFRAME']);
  const SEMANTIC = new Set(['NAV', 'ASIDE', 'HEADER', 'MAIN', 'SECTION', 'FOOTER', 'TABLE', 'THEAD', 'TBODY', 'TR', 'FORM', 'UL', 'OL', 'ARTICLE']);
  function touchesCorner(el, b, r) {
    const rad = Math.max(...r); let n = 0;
    for (const d of el.querySelectorAll('*')) {
      if (++n > 400) break; const st = getComputedStyle(d); const bg = col(st.backgroundColor);
      if (!(bg && bg.a > 0) && st.backgroundImage === 'none' && d.tagName !== 'IMG' && d.tagName !== 'CANVAS') continue;
      const q = d.getBoundingClientRect(); if (!q.width || !q.height) continue; const t = rad * 0.3;
      const L = q.left <= b.x + t, R = q.right >= b.x + b.w - t, T = q.top <= b.y + t, B = q.bottom >= b.y + b.h - t;
      if ((L && T) || (R && T) || (L && B) || (R && B) || q.left < b.x - 1 || q.right > b.x + b.w + 1 || q.top < b.y - 1 || q.bottom > b.y + b.h + 1) return true;
    }
    return false;
  }
  function render(el, isRoot) {
    if (SKIP.has(el.tagName)) return [];
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.visibility === 'collapse' || parseFloat(cs.opacity) === 0) return [];
    const q = el.getBoundingClientRect(), b = { x: q.left, y: q.top, w: q.width, h: q.height };
    const contents = cs.display === 'contents';
    // content of a closed <details>, and anything else the browser is not drawing
    if (!contents && !isRoot && el.checkVisibility && !el.checkVisibility()) return [];
    if (!contents && !isRoot) {
      if (b.x > VW + 1 || b.y > VH + 1 || b.x + b.w < -1 || b.y + b.h < -1) { if (cs.position === 'fixed' || cs.position === 'absolute' || cs.overflow !== 'visible') return []; }
      if ((b.w <= 1.5 || b.h <= 1.5) && cs.overflow !== 'visible' && cs.position === 'absolute') return [];   // visually-hidden helpers
    }
    const own = [], kids = [], name = label(el), r = radii(cs, b);
    const tgt = target(el), oc = el.getAttribute('onclick') || '';
    const isBtn = !tgt && (el.tagName === 'BUTTON' || (el.tagName === 'INPUT' && /^(submit|button|reset)$/i.test(el.type)) || (el.tagName === 'A' && /\bbtn\b|button/.test(el.className)) || el.getAttribute('role') === 'button' || (oc && !/stopPropagation\(\);?$/.test(oc.trim())));

    // --- own box ---
    if (!contents && b.w > 0 && b.h > 0 && el.tagName !== 'svg') {
      const bg = col(cs.backgroundColor), layersBg = cs.backgroundImage !== 'none' ? splitTop(cs.backgroundImage) : [];
      const side = ['Top', 'Right', 'Bottom', 'Left'], bw = side.map(s => /none|hidden/.test(cs['border' + s + 'Style']) ? 0 : parseFloat(cs['border' + s + 'Width']) || 0), bc = side.map(s => col(cs['border' + s + 'Color']));
      const uniform = bw[0] > 0 && bw.every(v => v === bw[0]) && bc.every(c => c && c.hex === bc[0].hex && c.a === bc[0].a) && bc[0].a > 0;
      const sh = shadowMark(cs.boxShadow), grads = [];
      for (const layer of layersBg.slice().reverse()) { const g = gradient(layer, b); if (g) grads.push(g); }
      const dash = uniform && /dashed|dotted/.test(cs.borderTopStyle) ? ` stroke-dasharray="${cs.borderTopStyle === 'dashed' ? `${N(bw[0] * 3)} ${N(bw[0] * 2)}` : `${N(bw[0])} ${N(bw[0])}`}"` : '';
      const hasBg = bg && bg.a > 0;
      if (hasBg && uniform && !grads.length) { const s = shape(b, r, bw[0] / 2); if (s) own.push(`${s} id="${esc(name + sh)}" ${paint(bg, 'fill')} ${paint(bc[0], 'stroke')} stroke-width="${N(bw[0])}"${dash}/>`); }
      else {
        const base = shape(b, r, 0); let marked = false;
        if (base && hasBg) { own.push(`${base} id="${esc(name + sh)}" ${paint(bg, 'fill')}/>`); marked = true; }
        if (base) for (const g of grads) { own.push(`${base} id="${esc(name + (marked ? '' : sh))}" fill="${g}"/>`); marked = true; }
        if (uniform) { const s = shape(b, r, bw[0] / 2); if (s) own.push(`${s} id="${esc(name)} border" fill="none" ${paint(bc[0], 'stroke')} stroke-width="${N(bw[0])}"${dash}/>`); }
        else if (bw.some((v, i) => v > 0 && bc[i] && bc[i].a > 0)) {
          const strips = [];
          const rc = (x, y, w, h, c) => strips.push(`<rect x="${N(x)}" y="${N(y)}" width="${N(w)}" height="${N(h)}" ${paint(c, 'fill')}/>`);
          if (bw[0] && bc[0].a > 0) rc(b.x, b.y, b.w, bw[0], bc[0]); if (bw[2] && bc[2].a > 0) rc(b.x, b.y + b.h - bw[2], b.w, bw[2], bc[2]);
          if (bw[3] && bc[3].a > 0) rc(b.x, b.y, bw[3], b.h, bc[3]); if (bw[1] && bc[1].a > 0) rc(b.x + b.w - bw[1], b.y, bw[1], b.h, bc[1]);
          if (Math.max(...r) > 0.5) { const id = clipDef(b, r); own.push(`<g id="${esc(name)} border" clip-path="url(#${id})">${strips.join('')}</g>`); }
          else if (strips.length === 1) own.push(strips[0].replace('<rect ', `<rect id="${esc(name)} border" `)); else own.push(`<g id="${esc(name)} border">${strips.join('')}</g>`);
        }
      }
      stats.shape += own.length;
    }

    // --- replaced content / controls ---
    let leaf = false;
    if (el.tagName === 'IMG') { const u = imgData.get(el); if (u && b.w > 0 && b.h > 0) { own.push(`<image id="${esc(el.alt || 'image')}" x="${N(b.x)}" y="${N(b.y)}" width="${N(b.w)}" height="${N(b.h)}" preserveAspectRatio="${cs.objectFit === 'cover' ? 'xMidYMid slice' : cs.objectFit === 'contain' ? 'xMidYMid meet' : 'none'}" xlink:href="${u}"/>`); stats.image++; } leaf = true; }
    else if (el.tagName === 'CANVAS') { try { if (b.w > 0 && b.h > 0 && el.width > 0) { own.push(`<image id="chart" x="${N(b.x)}" y="${N(b.y)}" width="${N(b.w)}" height="${N(b.h)}" preserveAspectRatio="none" xlink:href="${el.toDataURL('image/png')}"/>`); stats.image++; } } catch (e) { stats.notes.push('canvas failed'); } leaf = true; }
    else if (el.tagName === 'svg' || el.tagName === 'SVG') { if (b.w > 0 && b.h > 0) own.push(inlineSvg(el, b)); leaf = true; }
    else if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') { if ((el.getAttribute('type') || '').toLowerCase() === 'hidden') return []; own.push(...control(el, cs, b).filter(Boolean)); leaf = true; }

    // --- children ---
    if (!leaf) {
      kids.push({ k: -0.5, f: pseudo(el, cs, '::before') });
      let i = 0;
      for (const node of el.childNodes) {
        i++;
        if (node.nodeType === 3) { kids.push({ k: 0, f: textNode(node, el, cs) }); continue; }
        if (node.nodeType !== 1) continue;
        const ks = getComputedStyle(node), z = parseInt(ks.zIndex), pos = ks.position;
        if (pos === 'fixed' || (pos !== 'static' && !isNaN(z) && z >= 50)) { const f = render(node, false); if (f.length) layers.push({ z: isNaN(z) ? (pos === 'fixed' ? 1 : 0) : z, f }); continue; }
        kids.push({ k: pos === 'static' ? 0 : isNaN(z) ? 0.5 : z === 0 ? 0.5 : z, f: render(node, false) });
      }
      kids.push({ k: 0.6, f: pseudo(el, cs, '::after') });
    }
    let inner = []; kids.map((o, i) => ({ o, i })).sort((a, c) => a.o.k - c.o.k || a.i - c.i).forEach(e => inner.push(...e.o.f));

    // --- clipping ---
    if (inner.length && !contents && (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') && b.w > 0 && b.h > 0 && !isRoot && el.tagName !== 'BODY') {
      const over = el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
      if (over || (Math.max(...r) > 0.5 && touchesCorner(el, b, r))) { const id = clipDef(b, r); if (id) inner = [`<g id="${esc(name)} content" clip-path="url(#${id})">${inner.join('')}</g>`]; }
    }

    // --- interactive wrappers ---
    let all = own.concat(inner);
    if (!all.length) return [];
    const op = parseFloat(cs.opacity), opAttr = op < 1 ? ` opacity="${N(op)}"` : '';
    if ((tgt || isBtn) && b.w > 2 && b.h > 2) {
      const text = short(el, 40), hit = `<rect id="hit" x="${N(b.x)}" y="${N(b.y)}" width="${N(b.w)}" height="${N(b.h)}" fill="#000000" fill-opacity="0.002"/>`;
      if (tgt) { stats.link++; links.push({ to: tgt, text }); return [`<g id="${esc('→' + tgt + '|' + (text || name))}"${opAttr}>${hit}${all.join('')}</g>`]; }
      const hint = clean(oc.replace(/\s+/g, ' ')).slice(0, 60);
      stats.btn++; buttons.push({ text, name, hint, tag: el.tagName, type: el.getAttribute('type') || '', form: el.form ? (el.form.getAttribute('action') || '') : '' });
      return [`<g id="${esc('btn|' + (text || name) + '|' + hint)}"${opAttr}>${hit}${all.join('')}</g>`];
    }
    const wrap = opAttr || (own.length && inner.length) || (SEMANTIC.has(el.tagName) && all.length > 1) || (all.length > 1 && (el.id || /card|modal|dialog|sidebar|header|panel|item|row|stat|section|table|form|alert|flash|badge|nav|top-bar|toolbar|hero|box|tile|list|group/.test(name)));
    if (wrap) { stats.group++; return [`<g id="${esc(name)}"${opAttr}>${all.join('')}</g>`]; }
    return all;
  }

  const body = document.body, bcs = getComputedStyle(body), hcs = getComputedStyle(document.documentElement);
  let pageBg = col(bcs.backgroundColor); if (!pageBg || pageBg.a === 0) pageBg = col(hcs.backgroundColor); if (!pageBg || pageBg.a === 0) pageBg = { hex: '#ffffff', a: 1 };
  const bgParts = [`<rect id="background" width="${VW}" height="${VH}" fill="${pageBg.hex}"/>`];
  for (const st of [hcs, bcs]) if (st.backgroundImage !== 'none') for (const layer of splitTop(st.backgroundImage).reverse()) { const g = gradient(layer, { x: 0, y: 0, w: VW, h: VH }); if (g) bgParts.push(`<rect id="background" width="${VW}" height="${VH}" fill="${g}"/>`); }
  const main = render(body, true);
  layers.sort((a, c) => a.z - c.z);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${VW}" height="${VH}" viewBox="0 0 ${VW} ${VH}">` +
    (defs.length ? `<defs>${defs.join('')}</defs>` : '') + bgParts.join('') + main.join('') + layers.map(l => l.f.join('')).join('') + '</svg>';
  return { svg, width: VW, height: VH, stats, buttons, links };
};
