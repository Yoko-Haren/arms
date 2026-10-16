"""Send SVG files to Figma upload URLs.

usage: upload.py urls.txt jobs.json results.json
  urls.txt   one single-use submit URL per line (from the Figma upload_assets tool)
  jobs.json  [{"file": "out/x.svg", "name": "Layer name", "key": "group/slug"}, ...]   (file is relative to the temp folder)
"""
import concurrent.futures, json, os, sys, tempfile, time
import requests

WORK = os.path.join(tempfile.gettempdir(), 'arms-figma')        # where convert.py writes
urls = [u.strip() for u in open(sys.argv[1], encoding='utf-8') if u.strip().startswith('http')]
jobs = json.load(open(sys.argv[2], encoding='utf-8'))
if len(urls) < len(jobs):
    sys.exit(f'{len(jobs)} files but only {len(urls)} upload URLs')


def send(pair):
    url, job = pair
    data = open(os.path.join(WORK, job['file']), 'rb').read()
    for attempt in range(2):
        try:
            r = requests.post(url, files={'file': (job['name'] + '.svg', data, 'image/svg+xml')}, timeout=300)
            body = r.json() if r.headers.get('content-type', '').startswith('application/json') else {'raw': r.text[:200]}
            return {**job, 'status': r.status_code, 'node': body.get('placedOnNodeId'), 'ok': bool(body.get('success')), 'error': None if body.get('success') else body}
        except Exception as e:      # the URL is single-use, so only retry when nothing was sent
            err = str(e)
            if 'Read timed out' in err:
                break
            time.sleep(2)
    return {**job, 'status': 0, 'node': None, 'ok': False, 'error': err}


t0 = time.time()
with concurrent.futures.ThreadPoolExecutor(int(os.environ.get('UPLOAD_WORKERS', '4'))) as pool:
    results = list(pool.map(send, zip(urls, jobs)))
json.dump(results, open(sys.argv[3], 'w', encoding='utf-8'), indent=1)
for r in results:
    print(('ok  ' if r['ok'] else 'FAIL') + f' {r["key"]:42s} {r["node"] or ""} {"" if r["ok"] else r["error"]}')
print(f'{sum(r["ok"] for r in results)} of {len(results)} uploaded in {time.time() - t0:.0f}s')
