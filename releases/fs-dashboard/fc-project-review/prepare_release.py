"""Prepare the FC project dashboard release from current FS navigation and runtime sources."""
import argparse
import hashlib
import html
import json
import re
from pathlib import Path

ROUTE = '/dashboard/modules/sports/fc-project-review/'
ENTRY = dict(id='fc-project-review', label='FC 项目经营看板', path=ROUTE, icon='▥',
             short='围绕 FC26 / FC27 分析经营、获客与履约',
             section='sports', requiredGroup='dashboard', category='FC',
             scope='global-portal', serverGuard='/__nav_formal_native_session')
SCOPE = 'fc-project-review-20261119'
STATIC_FILES = ('index.html', 'fs-tokens.css', 'fs-ui.css', 'fs-theme.js', 'review.css', 'review.js')
RUNTIME = {'nginx.service': {'ActiveState': 'active'}, 'fs-business-range.service': {'ActiveState': 'active'}}
FORMAL = '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
EXACT = '/opt/fs-exact-range-20261001/'
NAV = {
    'hubnav.js': '/var/www/hub/hubnav.js', 'nav.js': '/var/www/hub/nav.js',
    'z-main.conf': '/etc/nginx/conf.d/iggm-web.conf', 'zz-formal.conf': FORMAL,
    'home.html': '/var/www/dashboard/fs-home/index.html',
    **{f'{name}.html': f'/var/www/dashboard/modules/{name}/index.html'
       for name in ('analytics', 'hermes', 'sports', 'arpg', 'collaboration', 'about')},
    'report.html': '/var/www/dashboard/fs-home/brain/index.html',
    'conversation.html': '/var/www/dashboard/fs-home/hermes/conversation/index.html',
    'tasks.html': '/var/www/dashboard/tasks/index.html',
    'fc-coins.html': '/var/www/dashboard/fc27-coins.html',
    'navigation.json': '/var/www/dashboard/fs-home/navigation.json',
    'module-registry.json': '/var/www/dashboard/fs-home/module-registry.json',
}
BACKEND = {f'backend/{name}': EXACT + name for name in ('range_api.py', 'fc_dashboard.py')}
BACKEND.update({f'backend/{name}': EXACT + 'fc_project_review/' + name
                for name in ('api.py', 'same_order.py', 'review.py', 'orders.py', 'traffic.py', 'prices.py', 'fulfillment.py',
                             'fulfillment_completion_bridge.py')})
SHA = lambda raw: hashlib.sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def register(registry):
    if any(row.get('id') == ENTRY['id'] or row.get('path') == ROUTE for row in registry['tools']):
        raise ValueError('The FC project dashboard entry already exists.')
    tool = dict(ENTRY)
    if 'sections' in registry:
        sports = next(row for row in registry['sections'] if row['id'] == 'sports')
        sports['ids'].insert(sports['ids'].index('ops'), ENTRY['id'])
    else:
        tool.pop('section')
    registry['tools'].insert(next(i for i,row in enumerate(registry['tools']) if row['id'] == 'ops'), tool)
    return registry


def patch_registry_script(text, old_registry, new_registry):
    matches = list(re.finditer(r'(?m)^[ \t]*const registry=(.*);\r?$', text))
    if len(matches) != 1 or json.loads(matches[0][1]) != old_registry:
        raise ValueError('The embedded menu differs from the current navigation registry.')
    needle = matches[0]
    value = json.dumps(new_registry, ensure_ascii=False, separators=(',', ':'))
    return text[:needle.start(1)] + value + text[needle.end(1):]


def sports_cards(text, tool_count):
    label = html.escape(ENTRY['label'])
    short = html.escape(ENTRY['short'])
    card = f'<a class="tool-card" href="{ROUTE}" data-tool="{ENTRY["id"]}"><span class="tool-icon">▥</span><strong>{label}</strong><p>{short}</p><span class="card-arrow">打开功能页面 ↗</span></a>\n'
    main = re.compile(r'(?m)^(?=<a class="tool-card" [^\n]*data-tool="ops")')
    text, n = main.subn(lambda _: card, text)
    if n != 1:
        raise ValueError('Could not identify the existing FC workspace card.')
    text, n = re.subn(r'\d+ 个功能入口(?= · 各自沿用原有访问门禁)', f'{tool_count} 个功能入口', text)
    if n != 1:
        raise ValueError('Could not identify the existing sports workspace count.')
    return text


def routes(static, version):
    guard = '''    if ($request_method !~ ^(GET|HEAD)$) { return 405; }
    auth_request /__nav_formal_native_session;
    error_page 401 = @auth_login;
    disable_symlinks on;
    add_header Cache-Control "private, no-store" always;
'''
    head = f'<link rel="stylesheet" href="/__hub/navigation-experience.css?v=navigation-experience-20261103-v1"></head>'
    tail = f'<script defer src="/__hub/hubnav.js?v={version}"></script></body>'
    landing = f'''# FC project operations dashboard (HTML, CSS, JS only; data through the authenticated range API).
location = {ROUTE[:-1]} {{ return 308 {ROUTE}; }}
location = {ROUTE} {{ rewrite ^ {ROUTE}index.html last; }}
location = {ROUTE}index.html {{
{guard}    alias {static}/index.html;
    sub_filter '</head>' '{head}';
    sub_filter '</body>' '{tail}';
}}
'''
    assets = []
    for name in STATIC_FILES:
        if name != 'index.html':
            assets.append(f'location = {ROUTE}{name} {{\n{guard}    alias {static}/{name};\n}}\n')
    return '\n' + landing + ''.join(assets)


def prepare(stage, root=Path('/')):
    stage = Path(stage)
    root = Path(root)
    location = lambda target: root / target.lstrip('/')
    candidate = stage / 'candidate'
    if candidate.exists():
        raise ValueError('Use a new release staging directory.')
    old_registry = json.loads(location(NAV['navigation.json']).read_bytes())
    new_registry = register(json.loads(encode(old_registry)))
    version = SCOPE + '-' + SHA(encode(new_registry))[:12]
    static_assets = {name: (stage / 'frontend' / name).read_bytes() for name in STATIC_FILES}
    static = '/var/lib/fs-navigation-formal-static/' + SCOPE + '-' + SHA(b''.join(static_assets.values()))[:12]
    rows, targets = [], {}

    def add(name, target, raw):
        path = location(target)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError('Invalid target: ' + target)
        before = SHA(path.read_bytes()) if path.exists() else None
        if SHA(raw) == before:
            raise ValueError('Candidate does not change target: ' + target)
        rows.append(dict(candidate=name, target=target, beforeSha256=before, sha256=SHA(raw)))
        targets[name] = target
        dst = candidate / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(raw)

    candidate.mkdir(parents=True, mode=0o700)
    for name,target in NAV.items():
        raw = location(target).read_text(encoding='utf-8')
        if name in ('hubnav.js', 'nav.js'):
            text = patch_registry_script(raw, old_registry, new_registry)
        elif name in ('navigation.json', 'module-registry.json'):
            text = (encode(new_registry) if name == 'navigation.json' else encode(register(json.loads(raw)))).decode()
        else:
            text, count = re.subn(r'((?:hubnav|nav)\.js\?v=)[A-Za-z0-9_-]+', lambda m: m[1] + version, raw)
            if not count:
                raise ValueError('No active menu asset references in ' + target)
            if name == 'sports.html':
                text = sports_cards(text, len(next(s['ids'] for s in new_registry['sections'] if s['id'] == 'sports')))
            if name == 'zz-formal.conf':
                if ROUTE in text:
                    raise ValueError('FC project dashboard route already configured.')
                text += routes(static,version)
        add(name, target, text.encode())

    for name, raw in static_assets.items():
        add('frontend/' + name, static + '/' + name, raw)
    baseline = json.loads((stage / 'backend' / 'baseline.json').read_text())
    for name, target in BACKEND.items():
        path = location(target)
        if '/' not in target[len(EXACT):]:
            if not path.is_file() or baseline.get(path.name) != SHA(path.read_bytes()):
                raise ValueError('Backend baseline differs from the source used to prepare ' + target)
        elif path.exists():
            raise ValueError('Expected new backend module: ' + target)
        source = (stage / name).read_bytes()
        compile(source, name, 'exec')
        add(name, target, source)

    protected = '/var/www/dashboard/index.html'
    manifest = dict(schemaVersion=1, scope=SCOPE, releaseReady=True, businessWrites=False,
                    timersChanged=False, runtimeRequired=RUNTIME, files=rows,
                    unchangedRequired=[dict(path=protected, sha256=SHA(location(protected).read_bytes()))])
    content = encode(manifest)
    (stage / 'manifest.json').write_bytes(content)
    (stage / 'targets.json').write_bytes(encode(targets))
    return dict(version=version, files=len(rows), manifest_sha=SHA(content), entry=ENTRY)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', type=Path)
    parser.add_argument('--root', type=Path, default=Path('/'))
    args = parser.parse_args()
    print(json.dumps(prepare(args.stage,args.root),ensure_ascii=False))
