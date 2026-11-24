"""Prepare a complete navigation cache revision for the existing FS UI publisher."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import types


MAIN = '/etc/nginx/conf.d/iggm-web.conf'
FORMAL = '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
CONFIGS = (MAIN, FORMAL)
DASHBOARD = '/var/www/dashboard/'
BUSINESS_HTML = DASHBOARD + 'index.html'
FORMAL_STATIC = '/var/lib/fs-navigation-formal-static/'
ASSETS = ('/var/www/hub/hubnav.js', '/var/www/hub/nav.js')
HTML_SUFFIXES = {'.html', '.htm'}
SUFFIXES = HTML_SUFFIXES | {'.js', '.mjs'}
HTML_COMMENT = re.compile(rb'(<!--.*?-->)', re.S)
NAV_URL = re.compile(rb'''(/__hub/(?:hubnav|nav)\.js)(?:\?v=[A-Za-z0-9._-]+)?(?=$|[\s"'<>\\);])''')
SUB_FILTER = re.compile(rb'(?m)^[ \t]*sub_filter[ \t]+[^\r\n]+')
ALIAS = re.compile(rb'(?m)^[ \t]*(?:alias|root)[ \t]+(/[^;\s$]+);')
HUB_LOCATION = re.compile(
    rb'(?ms)^(?P<indent>[ \t]*)location /__hub/ \{\r?\n(?P<body>.*?)^(?P=indent)\}',
)
LONG_CACHE = b'add_header Cache-Control "public, max-age=2592000";'
SHORT_CACHE = b'add_header Cache-Control "public, max-age=300, stale-while-revalidate=604800";'
UI_RELEASE = Path('/opt/fs-release-stage/traffic-source-tabs-20261019-v3')
PUBLISHER_PINS = {
    'release_ui_finish.py': 'fcab510f397582596e86fa913e7edfa4220ff6b44d679839452f920d63160188',
    'release_source_tabs.py': '78b4b054162a9cf578543f11bc6cea3b0041b535d49ea1c8f6059514f90e3466',
    'release_navigation_base.py': '57f4baf8db15fc791375b641fb618ef87a867901643bc0aa33f10804b8fcb840',
}
SCOPE = 'traffic-source-tabs-ui-finish-20261019'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def references(raw, *, nginx=False):
    if nginx:
        raw = b'\n'.join(match[0] for match in SUB_FILTER.finditer(raw))
    return [match[0] for match in NAV_URL.finditer(raw)]


def replace_references(raw, version, *, nginx=False, html=False):
    def replace(match):
        return match[1] + b'?v=' + version.encode('ascii')

    if nginx:
        return SUB_FILTER.sub(lambda line: NAV_URL.sub(replace, line[0]), raw)
    if html:
        parts = HTML_COMMENT.split(raw)
        parts[::2] = [NAV_URL.sub(replace, part) for part in parts[::2]]
        return b''.join(parts)
    return NAV_URL.sub(replace, raw)


def apply_cache_policy(raw):
    locations = list(HUB_LOCATION.finditer(raw))
    if len(locations) != 1:
        raise ValueError('expected one active /__hub/ location')
    location = locations[0]
    body = location['body']
    if body.count(LONG_CACHE) != 1 or b'alias /var/www/hub/;' not in body:
        raise ValueError('shared /__hub/ location drift')

    indent = location['indent']
    newline = b'\r\n' if b'\r\n' in location[0] else b'\n'
    blocks = []
    for target in ASSETS:
        name = Path(target).name.encode('ascii')
        header = b'location = /__hub/' + name
        lines = [
            header + b' {',
            b'    alias ' + target.encode('ascii') + b';',
            b'    ' + SHORT_CACHE,
            b'    default_type application/javascript;',
            b'    charset utf-8;',
            b'    charset_types application/javascript;',
            b'}',
        ]
        block = b''.join(indent + line + newline for line in lines)
        matches = re.findall(rb'(?m)^[ \t]*' + re.escape(header) + rb'[ \t]*\{', raw)
        if matches and (len(matches) != 1 or block not in raw):
            raise ValueError('existing exact navigation cache location drift')
        if not matches:
            blocks.append(block)
    return raw[:location.start()] + b''.join(blocks) + raw[location.start():]


def is_static(target):
    return target.startswith((DASHBOARD, FORMAL_STATIC)) and Path(target).suffix in SUFFIXES


def sources(root, configs):
    # Site files under the dashboard root, plus files aliased from outside that root.
    paths = {
        '/' + path.relative_to(root).as_posix()
        for path in (root / DASHBOARD.lstrip('/')).rglob('*')
        if path.suffix in SUFFIXES and path.is_file()
    }
    paths.update(
        match[1].decode('utf-8')
        for raw in configs.values()
        for match in ALIAS.finditer(raw)
        if is_static(match[1].decode('utf-8'))
    )
    for target in sorted(paths):
        path = root / target.lstrip('/')
        if not path.is_file():
            continue
        raw = path.read_bytes()
        active = HTML_COMMENT.sub(b'', raw) if path.suffix in HTML_SUFFIXES else raw
        if references(active):
            if path.is_symlink() or (os.name == 'posix' and stat.S_IMODE(path.stat().st_mode) != 0o644):
                raise ValueError('unexpected static source permissions: ' + target)
            yield target, raw


def prepare(root, output, scripts=None):
    configs = {target: (root / target.lstrip('/')).read_bytes() for target in CONFIGS}
    live_scripts = {target: (root / target.lstrip('/')).read_bytes() for target in ASSETS}
    new_scripts = (
        {target: (scripts / Path(target).name).read_bytes() for target in ASSETS}
        if scripts is not None else live_scripts
    )
    version = 'nav-' + sha(b'\0'.join(new_scripts[target] for target in ASSETS))[:16]
    consumers = dict(sources(root, configs))
    business_html = (root / BUSINESS_HTML.lstrip('/')).read_bytes()
    if BUSINESS_HTML in consumers:
        raise ValueError('the protected business HTML must use Nginx navigation injection')
    output.mkdir(mode=0o700)
    files = []
    for target, before in {**live_scripts, **consumers, **configs}.items():
        if target in live_scripts:
            after = new_scripts[target]
        else:
            after = replace_references(before, version, nginx=target in CONFIGS,
                                       html=Path(target).suffix in HTML_SUFFIXES)
            if target == MAIN:
                after = apply_cache_policy(after)
        if before == after:
            continue
        # Place the Nginx configuration after the static assets in apply order.
        candidate = ('routes/' if target in CONFIGS else 'site/') + target.lstrip('/')
        dest = output / 'candidate' / candidate
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(after)
        files.append(dict(candidate=candidate, target=target,
                          beforeSha256=sha(before), sha256=sha(after)))
    protected = {BUSINESS_HTML: business_html, **{target: raw for target, raw in live_scripts.items()
                                                  if new_scripts[target] == raw}}
    manifest = dict(
        schemaVersion=1, scope=SCOPE, releaseReady=True, businessWrites=False, timersChanged=False,
        runtimeRequired={'nginx.service': {'ActiveState': 'active'},
                         'fs-marketing-range.service': {'ActiveState': 'active'}},
        unchangedRequired=[dict(path=target, sha256=sha(raw)) for target, raw in protected.items()],
        files=files,
    )
    raw = (json.dumps(manifest, indent=2) + '\n').encode()
    (output / 'manifest.json').write_bytes(raw)
    return dict(version=version, manifest=manifest, manifestSha256=sha(raw),
                referenceFiles=sorted(consumers), referenceCount=sum(
                    len(references(data, nginx=target in CONFIGS))
                    for target, data in {**configs, **consumers}.items()
                ))


def run_publisher(action, stage, approval=None, release_id=None):
    raw = (stage / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    targets = {}
    for row in manifest['files']:
        target = row['target']
        if target == BUSINESS_HTML or (target not in (*CONFIGS, *ASSETS) and not is_static(target)):
            raise ValueError('navigation-only target required: ' + target)
        prefix = 'routes/' if target in CONFIGS else 'site/'
        if (row['candidate'] != prefix + target.lstrip('/') or '..' in Path(target).parts
                or row['beforeSha256'] is None or target in targets.values()):
            raise ValueError('invalid navigation target mapping')
        targets[row['candidate']] = target
    if not targets:
        raise ValueError('navigation is already current')

    for name, pin in PUBLISHER_PINS.items():
        if sha((UI_RELEASE / name).read_bytes()) != pin:
            raise ValueError('existing UI publisher drift: ' + name)
    entry = UI_RELEASE / 'release_ui_finish.py'
    ui = types.ModuleType('navigation_ui_publisher')
    ui.__file__ = str(entry)
    exec(compile(entry.read_bytes(), str(entry), 'exec'), ui.__dict__)
    ui.TARGETS = targets
    publisher = ui.publisher()
    if action == 'inspect':
        return publisher.inspect(manifest, stage)
    if approval != sha(raw):
        raise ValueError('reviewed manifest SHA required')
    if action == 'apply':
        return publisher.apply(manifest, stage, approval, raw, release_id)
    if not re.fullmatch(r'nav-[0-9]{8}T[0-9]{6}Z', release_id or ''):
        raise ValueError('invalid rollback release ID')
    backup = Path('/var/backups/fs-navigation-20261006') / release_id
    return publisher.rollback(backup, approval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    build = sub.add_parser('prepare')
    build.add_argument('stage', type=Path)
    build.add_argument('--scripts', type=Path, help='directory with the reviewed nav.js and hubnav.js')
    for action in ('inspect', 'apply', 'rollback'):
        command = sub.add_parser(action)
        command.add_argument('stage', type=Path)
        if action != 'inspect':
            command.add_argument('approval')
            command.add_argument('release_id')
    args = parser.parse_args()
    if args.action == 'prepare':
        result = prepare(Path('/'), args.stage, args.scripts)
        print(json.dumps({key: value for key, value in result.items() if key != 'manifest'}))
    else:
        print(json.dumps(run_publisher(args.action, args.stage,
                                       getattr(args, 'approval', None), getattr(args, 'release_id', None))))


if __name__ == '__main__':
    main()
