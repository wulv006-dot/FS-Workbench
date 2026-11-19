from pathlib import Path
import argparse, json, base64, hashlib, re, shutil
parser = argparse.ArgumentParser(description='Prepare the reviewed shared UI cache release; no server writes.')
parser.add_argument('--base-stage', type=Path, required=True)
parser.add_argument('--static-capture', type=Path, required=True)
parser.add_argument('--weekly-capture', type=Path, required=True)
parser.add_argument('--review-js', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
old = args.base_stage
out = args.output
if not not out.exists():
    raise ValueError('release preparation validation failed')
if not hashlib.sha256((old / 'manifest.json').read_bytes()).hexdigest() == 'e2a36cd810c31ab4ac0daba141bb8541a9c934348b098ba47d398eb6d9ee356d':
    raise ValueError('release preparation validation failed')
manifest = json.loads((old / 'manifest.json').read_text(encoding='utf8'))
rows = {x['candidate']: x for x in manifest['files']}
raw = {k: (old / 'candidate' / k).read_bytes() for k in rows}
cap = json.loads(args.static_capture.read_text(encoding='ascii'))
w = json.loads(args.weekly_capture.read_text(encoding='ascii'))
expected_assets = {
    'workspace-native-20261006-ba0a83afd594/runtime.js': '7d021464703e02dbd879fa1c4eede18f948416e15998b9531bab8d2e4607c41c',
    'workspace-native-20261006-ba0a83afd594/workspace.css': 'c08de4e8db104444446cba0012c857a744e0807fb06abea733049d7534c3f239',
    'workspace-native-20261006-561eda9b98e2/ui/fs-tokens.css': 'c88351ce12f9ab3e3ada169bb5e9ee6fe8d82bb53f93b2073050be93f3569df6',
    'workspace-native-20261006-561eda9b98e2/ui/fs-ui.css': '4cfd403f6958ed235159adaf65d882099f36fb310619a558fa89cb83217c0615',
    'workspace-native-20261006-561eda9b98e2/ui/fs-theme.js': 'b9fa6f6a30fafab089db7a9b7d3f5190c08ca05b8232b57064cd5171cbe54910',
    'workspace-native-20261006-561eda9b98e2/ui/legacy.css': '5431b4de33217810f7a9d50d5322abf13a4aaad0096d55be25214c0109085245',
}
if set(cap) != set(expected_assets):
    raise ValueError('shared asset capture must contain exactly the six reviewed paths')
for rel, expected in expected_assets.items():
    if cap[rel].get('sha256') != expected:
        raise ValueError('unreviewed shared asset: ' + rel)
if w.get('target') != '/opt/fs-campaign-dashboard/analytics/weekly.html' or w.get('sha256') != '9b2682c67b965e6d2b7305712bfbb5b85187a3ffd83289c62524efdb6bb93290':
    raise ValueError('unreviewed weekly page')
for row in manifest['files']:
    if hashlib.sha256(raw[row['candidate']]).hexdigest() != row['sha256']:
        raise ValueError('base stage payload drift: ' + row['candidate'])
if hashlib.sha256((old / 'release_ui.py').read_bytes()).hexdigest() != '8cc0b9fa66e784d2b81966d172d2e44b29bcce3d8b7b82eee4cadf2e3c253ba1':
    raise ValueError('publisher drift')
sha = lambda b: hashlib.sha256(b).hexdigest()
assets = {}
for rel, v in cap.items():
    b = base64.b64decode(v['base64'], validate=True)
    if not sha(b) == v['sha256']:
        raise ValueError('release preparation validation failed')
    name = Path(rel).name
    if not name not in assets:
        raise ValueError('release preparation validation failed')
    ident = 'fs-shared-sha256-' + v['sha256']
    assets[name] = (b, '/dashboard/workspace-assets/' + ident + '/' + name, '/var/lib/fs-navigation-formal-static/' + ident + '/' + name)
urls = {n: t[1] for n, t in assets.items()}
oldroot = '/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/ui/'
base = '/dashboard/workspace-assets/workspace-native-20261006-ba0a83afd594/'

def replace(s, a, b, count=1):
    if not s.count(a) == count:
        raise ValueError((a, s.count(a), count))
    return s.replace(a, b)

def text(k):
    return raw[k].decode('utf8')
new = {}
hub = text('b-shared/hubnav.js')
oldline = "const uiRoot='/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/ui/';"
newmap = json.dumps({n: urls[n] for n in ['fs-tokens.css', 'fs-ui.css', 'legacy.css', 'fs-theme.js']}, separators=(',', ':'))
hub = replace(hub, oldline, oldline + '\nconst sharedAssetURLs=' + newmap + ';')
hub = replace(hub, 'new URL(uiRoot+name,document.baseURI).href', 'new URL(sharedAssetURLs[name]||uiRoot+name,document.baseURI).href')
hub = replace(hub, "new URL(uiRoot+'fs-theme.js',document.baseURI).href", "new URL(sharedAssetURLs['fs-theme.js'],document.baseURI).href")
nav = raw['b-shared/nav.js']
hub = hub.encode('utf8')
version = 'nav-unified-20261120-' + sha(nav + b'\x00' + hub)[:12]
prior = 'nav-unified-20261120-aaec928afc3e'
print('nav_version', version)

def update_version(s):
    if not prior in s:
        raise ValueError('release preparation validation failed')
    return s.replace(prior, version)
shells = {}
for n in ['shell.js', 'home-shell.js', 'legacy-shell.js', 'homepage-shell.js']:
    s = text('a-assets/' + n)
    s = replace(s, "'./runtime.js'" if n == 'legacy-shell.js' else "'" + base + "runtime.js'", "'" + urls['runtime.js'] + "'")
    if n != 'legacy-shell.js':
        anchor = "new URL('ui/'+name,new URL('" + oldroot.removesuffix('ui/') + "',location.origin))"
        if not s.count(anchor) == 1:
            raise ValueError((n, anchor))
        s = s.replace(anchor, "(name==='fs-ui.css'?'" + urls['fs-ui.css'] + "':new URL('ui/'+name,new URL('" + oldroot.removesuffix('ui/') + "',location.origin)))")
    shells[n] = update_version(s).encode('utf8')
html = text('a-assets/analytics-index.html')
for name in ['workspace.css', 'runtime.js']:
    html = replace(html, base + name, urls[name])
for name in ['fs-tokens.css', 'fs-ui.css', 'fs-theme.js']:
    html = replace(html, oldroot + name, urls[name])
shells['analytics-index.html'] = html.encode('utf8')
package = 'fs-shared-ui-cache-' + sha(b'\x00'.join((shells[n] for n in sorted(shells))))[:12]
review = args.review_js.read_bytes().replace(b'\r\n', b'\n')
if not sha(review) == '3fb51aab7462e2bfd65e0e71f548f70a2d278784d69b67c649557db68b32bf09':
    raise ValueError('release preparation validation failed')
review_old = '/var/lib/fs-navigation-formal-static/fc-project-review-20261119-5dd53aaff318/review.js'
review_new = '/var/lib/fs-navigation-formal-static/fs-fc-review-' + sha(review) + '/review.js'
new['a-fc/review.js'] = (review_new, None, review)
newfolder = '/var/lib/fs-navigation-formal-static/' + package + '/'
for n, data in shells.items():
    new['a-shells/' + n] = (newfolder + n, None, data)
for n, (b, url, target) in assets.items():
    new['a-shared/' + n] = (target, None, b)
new['b-shared/hubnav.js'] = (rows['b-shared/hubnav.js']['target'], sha(raw['b-shared/hubnav.js']), hub)
for k in rows:
    if k.startswith('d-pages/'):
        s = update_version(text(k))
        # Reuse the same exact content URLs on every page in this release.
        for name in ('workspace.css', 'runtime.js'):
            s = s.replace(base + name, urls[name])
        for name in ('fs-tokens.css', 'fs-ui.css', 'fs-theme.js', 'legacy.css'):
            s = s.replace(oldroot + name, urls[name])
        new[k] = (rows[k]['target'], sha(raw[k]), s.encode('utf8'))
s = update_version(text('c-navigation.js'))
new['c-navigation.js'] = (rows['c-navigation.js']['target'], sha(raw['c-navigation.js']), s.encode('utf8'))
for k in ('zz-main.conf', 'zz-formal.conf'):
    s = update_version(text(k))
    if k == 'zz-formal.conf':
        oldfolder = '/var/lib/fs-navigation-formal-static/nav-unified-20261120-e73f51dd383a/'
        for n in shells:
            s = replace(s, oldfolder + n, newfolder + n)
        s = replace(s, review_old, review_new)
        blocks = []
        for name, (b, url, target) in assets.items():
            blocks.append('\nlocation = %s {\n    if ($request_method !~ ^(GET|HEAD)$) { return 405; }\n    auth_request /__nav_formal_native_session;\n    error_page 401 = @auth_login;\n    alias %s;\n    disable_symlinks on;\n    add_header Cache-Control "private, max-age=2592000, immutable";\n    sub_filter "</body>" "</body>";\n}\n' % (url, target))
        s += ''.join(blocks)
    new[k] = (rows[k]['target'], sha(raw[k]), s.encode('utf8'))
weekly = base64.b64decode(w['base64'], validate=True)
if not sha(weekly) == w['sha256']:
    raise ValueError('release preparation validation failed')
s = weekly.decode('utf8')
for n in ['fs-tokens.css', 'fs-ui.css']:
    s = replace(s, 'href="' + n + '"', 'href="' + urls[n] + '"')
new['c-weekly.html'] = (w['target'], w['sha256'], s.encode('utf8'))
out.mkdir()
files = []
targets = {}
for k, (target, before, data) in sorted(new.items()):
    p = out / 'candidate' / k
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    files.append({'candidate': k, 'target': target, 'beforeSha256': before, 'sha256': sha(data)})
    targets[k] = target
protected = list(manifest['unchangedRequired'])
for rel, v in cap.items():
    protected.append({'path': '/var/lib/fs-navigation-formal-static/' + rel, 'sha256': v['sha256']})
protected.append({'path': '/var/lib/fs-navigation-formal-static/workspace-native-20261006-fd4cfd0a70aa/runtime.js', 'sha256': cap['workspace-native-20261006-ba0a83afd594/runtime.js']['sha256']})
protected.append({'path': review_old, 'sha256': '7f216e087f59a9584512107084ab98981d32f2d22e99af154232bd3d0fca793b'})
for n in shells:
    k = 'a-assets/' + n
    protected.append({'path': rows[k]['target'], 'sha256': sha(raw[k])})
m = {'schemaVersion': 1, 'scope': 'traffic-source-tabs-ui-finish-20261019', 'releaseReady': True, 'businessWrites': False, 'timersChanged': False, 'runtimeRequired': manifest['runtimeRequired'], 'unchangedRequired': protected, 'files': files}
(out / 'manifest.json').write_text(json.dumps(m, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
(out / 'targets.json').write_text(json.dumps(targets, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
shutil.copyfile(old / 'release_ui.py', out / 'release_ui.py')
print('assets', len(assets), 'files', len(files), 'package', package, 'manifest', sha((out / 'manifest.json').read_bytes()))
