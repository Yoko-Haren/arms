"""Render every exported ARMS screen in headless Chrome and write an SVG that Figma imports as editable layers.

usage: python convert.py [substring-filter ...]      e.g.  python convert.py registrar/

Run `python manage.py export_screens` first. Needs Google Chrome and: pip install fonttools brotli websockets requests
Output goes to a temp folder (printed at the end): one SVG per screen plus meta.json. The SVGs are then sent to
Figma with upload.py, using upload URLs from the Figma connector.
"""
import asyncio, functools, http.server, io, json, os, re, subprocess, sys, tempfile, threading, time, urllib.parse, urllib.request

import requests, websockets
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

HERE = os.path.dirname(os.path.abspath(__file__))
DESIGN = os.path.dirname(os.path.dirname(HERE))          # design/tools/figma -> design
WORK = os.path.join(tempfile.gettempdir(), 'arms-figma')
OUT = os.path.join(WORK, 'out')
CACHE = os.path.join(WORK, 'cache')
CHROME = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
PORT, DEBUG_PORT = 8765, 9333
BASE = f'http://127.0.0.1:{PORT}'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
WIDTH, MIN_HEIGHT = 1440, 900
os.makedirs(OUT, exist_ok=True); os.makedirs(CACHE, exist_ok=True)


def cached(url, binary=False):
    path = os.path.join(CACHE, re.sub(r'[^A-Za-z0-9.]+', '_', url)[-150:])
    if not os.path.exists(path):
        r = requests.get(url, headers={'User-Agent': UA}, timeout=30); r.raise_for_status()
        open(path, 'wb').write(r.content)
    data = open(path, 'rb').read()
    return data if binary else data.decode('utf-8', 'replace')


# ---------- text fonts: Open Sans stands in for Segoe UI (Figma has no Segoe UI) ----------
def font_css():
    css = cached('https://fonts.googleapis.com/css2?family=Open+Sans:ital,wght@0,300;0,400;0,600;0,700;0,800;1,400;1,600;1,700'
                 '&family=Roboto+Mono:wght@400;700&display=block')
    alias = css.replace("font-family: 'Open Sans'", "font-family: 'Segoe UI'")
    return css + '\n' + alias


# ---------- icon fonts ----------
class Icons:
    def __init__(self):
        self.faces = {}      # family(lower) -> [(weight, TTFont)]
        self.seen_css = set()
        self.missing = {}

    def add_css(self, url):
        if url in self.seen_css or not re.search(r'uicons|font-?awesome|bootstrap-icons', url, re.I):
            return
        self.seen_css.add(url)
        try:
            css = cached(url)
        except Exception as e:
            print('  ! icon css failed', url, e); return
        for block in re.findall(r'@font-face\s*\{([^}]*)\}', css):
            fam = re.search(r'font-family:\s*["\']?([^;"\']+)', block)
            if not fam:
                continue
            weight = re.search(r'font-weight:\s*(\d+)', block)
            srcs = re.findall(r'url\(["\']?([^)"\']+)["\']?\)\s*format\(["\']?([^)"\']+)', block)
            pick = next((u for u, f in srcs if f == 'woff2'), None) or next((u for u, f in srcs if f == 'woff'), None) or next((u for u, f in srcs if f == 'truetype'), None)
            if not pick:
                continue
            try:
                font = TTFont(io.BytesIO(cached(urllib.parse.urljoin(url, pick), binary=True)))
            except Exception as e:
                print('  ! icon font failed', pick, e); continue
            self.faces.setdefault(fam.group(1).strip().lower(), []).append((int(weight.group(1)) if weight else 400, font))

    def path(self, family, weight, cp, size, x, base):
        faces = self.faces.get(family.lower())
        if not faces:
            self.missing[family] = self.missing.get(family, 0) + 1; return None
        font = min(faces, key=lambda f: abs(f[0] - weight))[1]
        name = font.getBestCmap().get(cp)
        if not name:
            self.missing[f'{family} U+{cp:04X}'] = 1; return None
        glyphs = font.getGlyphSet()
        pen = SVGPathPen(glyphs, ntos=lambda v: ('%.2f' % v).rstrip('0').rstrip('.'))
        s = size / font['head'].unitsPerEm
        glyphs[name].draw(TransformPen(pen, (s, 0, 0, -s, x, base)))
        return pen.getCommands()


ICON_RE = re.compile(r'<path data-icon="([^"|]*)\|(\d+)\|(\d+)\|([\d.]+)\|(-?[\d.]+)\|(-?[\d.]+)\|(#[0-9a-f]{6})\|([\d.]+)"/>')


def place_icons(svg, icons):
    def sub(m):
        fam, weight, cp, size, x, base, colour, alpha = m.groups()
        d = icons.path(fam.replace('&quot;', ''), int(weight), int(cp), float(size), float(x), float(base))
        if not d:
            return ''
        return f'<path id="icon" d="{d}" fill="{colour}"' + (f' fill-opacity="{alpha}"' if float(alpha) < 1 else '') + '/>'
    return ICON_RE.sub(sub, svg)


# ---------- Chrome over the DevTools protocol ----------
class Chrome:
    async def start(self):
        self.proc = subprocess.Popen([CHROME, '--headless=new', f'--remote-debugging-port={DEBUG_PORT}', f'--user-data-dir={os.path.join(WORK, "chrome-profile")}',
                                      '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', '--disable-extensions', '--mute-audio',
                                      f'--window-size={WIDTH},{MIN_HEIGHT}', 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                info = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{DEBUG_PORT}/json/version', timeout=1).read()); break
            except Exception:
                await asyncio.sleep(0.25)
        else:
            raise RuntimeError('Chrome did not start')
        self.ws = await websockets.connect(info['webSocketDebuggerUrl'], max_size=None, ping_interval=None)
        self.n, self.waiting, self.events = 0, {}, []
        self.reader = asyncio.create_task(self._read())
        target = (await self.send('Target.createTarget', {'url': 'about:blank'}))['targetId']
        self.session = (await self.send('Target.attachToTarget', {'targetId': target, 'flatten': True}))['sessionId']
        await self.cmd('Page.enable'); await self.cmd('Runtime.enable')
        await self.cmd('Emulation.setDeviceMetricsOverride', {'width': WIDTH, 'height': MIN_HEIGHT, 'deviceScaleFactor': 2, 'mobile': False})

    async def _read(self):
        async for raw in self.ws:
            msg = json.loads(raw)
            if 'id' in msg and msg['id'] in self.waiting:
                self.waiting.pop(msg['id']).set_result(msg)
            elif 'method' in msg:
                self.events.append(msg)

    async def send(self, method, params=None, session=None):
        self.n += 1
        fut = asyncio.get_event_loop().create_future(); self.waiting[self.n] = fut
        msg = {'id': self.n, 'method': method, 'params': params or {}}
        if session:
            msg['sessionId'] = session
        await self.ws.send(json.dumps(msg))
        res = await asyncio.wait_for(fut, 120)
        if 'error' in res:
            raise RuntimeError(f'{method}: {res["error"]}')
        return res['result']

    def cmd(self, method, params=None):
        return self.send(method, params, self.session)

    async def js(self, expr):
        res = await self.cmd('Runtime.evaluate', {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
        if 'exceptionDetails' in res:
            d = res['exceptionDetails']
            raise RuntimeError('JS: ' + (d.get('exception', {}).get('description') or d.get('text', '')))
        return res['result'].get('value')

    async def goto(self, url):
        self.events.clear()
        await self.cmd('Page.navigate', {'url': url})
        for _ in range(240):
            if any(e['method'] == 'Page.loadEventFired' for e in self.events):
                return
            await asyncio.sleep(0.1)
        print('  ! load event not seen for', url)

    async def stop(self):
        try:
            await self.send('Browser.close')
        except Exception:
            pass
        try:
            self.proc.wait(5)
        except Exception:
            self.proc.kill()


PREPARE = r"""
(async () => {
  for (const el of document.querySelectorAll('body, body *')) {
    const fam = getComputedStyle(el).fontFamily, first = fam.split(',')[0].replace(/["']/g, '').trim().toLowerCase();
    if (first === 'segoe ui' || first === 'roboto mono' || /uicons|font ?awesome|bootstrap-icons/.test(first)) continue;
    el.style.setProperty('font-family', /mono|consolas|courier/.test(fam.toLowerCase()) ? "'Roboto Mono', monospace" : "'Segoe UI', sans-serif", 'important');
  }
  const want = ['300', '400', '600', '700', '800', 'italic 400', 'italic 600', 'italic 700'].map(w => document.fonts.load(w + ' 16px "Segoe UI"'));
  want.push(document.fonts.load('400 16px "Roboto Mono"'), document.fonts.load('700 16px "Roboto Mono"'));
  await Promise.all(want); await document.fonts.ready;
  await new Promise(r => setTimeout(r, %d));
  await document.fonts.ready;
  return [...document.fonts].filter(f => /Segoe/.test(f.family) && f.status === 'loaded').length;
})()
"""
MEASURE = r"""
(() => {
  let extra = 0;
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (/(auto|scroll)/.test(cs.overflowY) && el.clientHeight > 0 && el.scrollHeight > el.clientHeight + 1) extra = Math.max(extra, el.scrollHeight - el.clientHeight);
  }
  const modal = [...document.querySelectorAll('body *')].some(el => {
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed' || cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
    const r = el.getBoundingClientRect(), bg = cs.backgroundColor;
    return r.width >= innerWidth * 0.9 && r.height >= innerHeight * 0.9 && (parseInt(cs.zIndex) || 0) >= 100 && /rgba?\(/.test(bg) && !/,\s*0\)$/.test(bg);
  });
  return {doc: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight), extra, modal,
          links: [...document.querySelectorAll('link[rel=stylesheet]')].map(l => l.href)};
})()
"""


async def capture(chrome, icons, screen, extract_src, css):
    key = f'{screen["group"]}/{screen["slug"]}'
    await chrome.cmd('Emulation.setDeviceMetricsOverride', {'width': WIDTH, 'height': MIN_HEIGHT, 'deviceScaleFactor': 2, 'mobile': False})
    await chrome.goto(f'{BASE}/screens/{screen["group"]}/{screen["slug"]}.html')
    await chrome.js('(() => { const s = document.createElement("style"); s.textContent = %s; document.head.appendChild(s); })()' % json.dumps(css))
    loaded = await chrome.js(PREPARE % 1800)
    m = await chrome.js(MEASURE)
    height = MIN_HEIGHT
    if not m['modal']:
        height = max(MIN_HEIGHT, int(m['doc']))
        for _ in range(3):
            await chrome.cmd('Emulation.setDeviceMetricsOverride', {'width': WIDTH, 'height': height, 'deviceScaleFactor': 2, 'mobile': False})
            await asyncio.sleep(0.35)
            m2 = await chrome.js(MEASURE)
            target = max(MIN_HEIGHT, int(m2['doc']))
            if m2['extra'] > 1 and m2['extra'] < 6000 and height < 12000:
                trial = max(target, height) + int(m2['extra'])
                await chrome.cmd('Emulation.setDeviceMetricsOverride', {'width': WIDTH, 'height': trial, 'deviceScaleFactor': 2, 'mobile': False})
                await asyncio.sleep(0.35)
                m3 = await chrome.js(MEASURE)
                if m3['extra'] < m2['extra'] - 1:
                    height = trial; continue
                await chrome.cmd('Emulation.setDeviceMetricsOverride', {'width': WIDTH, 'height': max(target, height), 'deviceScaleFactor': 2, 'mobile': False})
            if target == height:
                break
            height = target
        await asyncio.sleep(0.5)
        height = max(MIN_HEIGHT, int((await chrome.js(MEASURE))['doc']), height if m['extra'] > 1 else 0)
        await chrome.cmd('Emulation.setDeviceMetricsOverride', {'width': WIDTH, 'height': height, 'deviceScaleFactor': 2, 'mobile': False})
        await asyncio.sleep(0.4)
    for href in m['links']:
        icons.add_css(href)
    await chrome.js(extract_src + '; true')
    res = await chrome.js('__armsExtract({height: %d})' % height)
    svg = place_icons(res['svg'], icons)
    name = f'{screen["group"]}__{screen["slug"]}.svg'
    open(os.path.join(OUT, name), 'w', encoding='utf-8').write(svg)
    st = res['stats']
    print(f'{key:44s} {res["width"]}x{res["height"]:<5d} {len(svg) // 1024:5d} KB  text {st["text"]:4d} shape {st["shape"]:4d} icon {st["icon"]:3d} img {st["image"]:2d} link {st["link"]:3d} btn {st["btn"]:3d} clip {st["clip"]:3d}'
          + ('  MODAL' if m['modal'] else '') + ('' if loaded else '  !fonts'))
    return {'key': key, 'file': name, 'title': screen['title'], 'group': screen['group'], 'slug': screen['slug'], 'width': res['width'], 'height': res['height'],
            'bytes': len(svg.encode('utf-8')), 'stats': st, 'buttons': res['buttons'], 'links': res['links'], 'modal': m['modal']}


def manifest():
    src = open(os.path.join(DESIGN, 'screens', 'manifest.js'), encoding='utf-8').read()
    return json.loads(re.search(r'window\.ARMS_SCREENS = (\[.*?\]);\s*window\.ARMS_EXPORTED', src, re.S).group(1))


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


async def main():
    filters = sys.argv[1:]
    screens = [s for s in manifest() if not filters or any(f in f'{s["group"]}/{s["slug"]}' for f in filters)]
    server = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), functools.partial(Quiet, directory=DESIGN))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    css, extract_src = font_css(), open(os.path.join(HERE, 'extract.js'), encoding='utf-8').read()
    chrome, icons, meta = Chrome(), Icons(), []
    await chrome.start()
    try:
        for s in screens:
            try:
                meta.append(await capture(chrome, icons, s, extract_src, css))
            except Exception as e:
                print(f'{s["group"]}/{s["slug"]}: FAILED {e}')
    finally:
        await chrome.stop(); server.shutdown()
    path = os.path.join(OUT, 'meta.json')
    old = {m['key']: m for m in json.load(open(path, encoding='utf-8'))} if os.path.exists(path) else {}
    old.update({m['key']: m for m in meta})
    order = [f'{s["group"]}/{s["slug"]}' for s in manifest()]
    json.dump([old[k] for k in order if k in old], open(path, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    if icons.missing:
        print('missing icons:', icons.missing)
    print(f'{len(meta)} of {len(screens)} screens written to {OUT}')


asyncio.run(main())
