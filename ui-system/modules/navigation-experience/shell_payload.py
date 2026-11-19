"""Build the dashboard and campaign inputs for prepare-combined.py."""
import base64
from hashlib import sha256
import json
from pathlib import Path


def homepage_startup(live, source):
    if sha256(live).hexdigest() != 'f985e1d802bafb01b376a4c344d5997d155660d92fc3ff501103309d97b58c6b':
        raise ValueError('homepage_shell_baseline_changed')
    source = source.replace(b'\r\n', b'\n')
    start, previous, end = b'const homeShortcuts=', b'async function boot(){', b'function homeData(){'
    if any(buf.count(marker) != 1 for buf, marker in ((source,start),(source,end),(live,previous),(live,end))):
        raise ValueError('homepage_shell_startup_boundary_changed')
    startup = source[source.index(start):source.index(end)]
    base = b"new URL('navigation.json',base)"
    if startup.count(base) != 1 or b"path:'/repricing/'" not in startup:
        raise ValueError('homepage_shell_route_binding_changed')
    # The homepage's asset and registry directories differ from the native template's.
    startup = startup.replace(base, b"new URL('navigation.json',logicBase)")
    return live[:live.index(previous)] + startup + live[live.index(end):]


def analytics_document(live, template):
    if sha256(live).hexdigest() != 'dd989f51468c0d9fa72f7e1a2c3485db59c8f95ad7e3d3af72745d80092b1104':
        raise ValueError('analytics_document_baseline_changed')
    start, end = b'<p class="muted">', b'</p></dialog>'
    def description(body):
        return body[body.index(start,body.index(b'id="data-dialog"')):body.index(end)]
    old, new = description(live), description(template)
    if live.count(old) != 1 or old == new:
        raise ValueError('analytics_dialog_source_changed')
    preload = b'<link rel="modulepreload" href="/dashboard/workspace-assets/workspace-native-20261006-ba0a83afd594/runtime.js">'
    theme = b'<script src="/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/ui/fs-theme.js">'
    module = b'<script type="module" src='
    if preload not in template or live.count(module) != 1 or live.count(theme) != 1:
        raise ValueError('analytics_startup_sources_changed')
    return live.replace(old,new).replace(theme,theme.replace(b'<script ',b'<script defer ')).replace(module,preload+module)


def prepare(capture_file, destination):
    root = Path(__file__).resolve().parents[3]
    native = root / 'ui-system/modules/native'
    releases = root / 'releases/fs-dashboard'
    capture = json.loads(Path(capture_file).read_text(encoding='ascii'))

    def active(name):
        row = capture['old-' + name]
        data = base64.b64decode(row['base64'], validate=True)
        if sha256(data).hexdigest() != row['sha256']:
            raise ValueError('active payload hash mismatch: ' + name)
        return data

    def source(path):
        return path.read_bytes().replace(b'\r\n', b'\n')

    payloads = {}
    for name in ('shell.js', 'home-shell.js', 'legacy-shell.js'):
        old = active(name).replace(b'\r\n', b'\n')
        current = source(releases / 'dashboard-refresh-20261025/source' / name)
        # The shared publisher binds the navigation version for all shells in one step.
        start, end = b'async function boot(){', b'function homeData(){'
        new_start = b'const homeShortcuts='
        if any(blob.count(marker) != 1 for blob, marker in ((old,start),(old,end),(current,new_start),(current,end))):
            raise ValueError('shell startup boundary changed: ' + name)
        payloads[name] = old[:old.index(start)] + current[current.index(new_start):current.index(end)] + old[old.index(end):]
    payloads['homepage-shell.js'] = homepage_startup(active('homepage-shell.js'), source(native / 'shell.js'))
    payloads['analytics-index.html'] = analytics_document(active('analytics-index.html'), source(native / 'index.html'))
    payloads['production-server.mjs'] = source(releases / 'campaign-analytics-20261023/app/analytics/production-server.mjs')
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=False)
    for name, data in payloads.items():
        (output / name).write_bytes(data)


if __name__ == '__main__':
    import sys
    prepare(*sys.argv[1:])
