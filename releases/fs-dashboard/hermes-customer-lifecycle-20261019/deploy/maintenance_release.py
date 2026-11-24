"""Build a customer-maintenance delta from captured active files.

This prepares byte-exact candidates for the existing publishers. It does not
connect to a host, enable the dispatcher, or write to an active installation.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


RELEASE = 'releases/fs-dashboard/hermes-customer-lifecycle-20261019'
STATIC = '/var/lib/fs-navigation-formal-static/customer-maintenance-20261124'
OLD = '/dashboard/fs-home/hermes/customer-tracking/'
NEW = '/dashboard/customers/'
GUARD = 'auth_request /__nav_formal_native_session;'
NGINX = '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
NAV = 'ui-system/modules/navigation-experience'
CONNECTOR = 'fs_mcp_connector/catalog.json'
RBAC = 'opt/fs-access-policy/rbac.py'

TARGETS = {
    **{f'{RELEASE}/source/{name}': '/opt/fs-hermes-fc/' + name for name in (
        'tracking_controller.py', 'vip_maintenance.py', 'maintenance_coupon_bridge.cjs',
        'maintenance_dispatch.py', 'maintenance_effects.py', 'maintenance_ledger.py',
        'maintenance_reconcile.py', 'maintenance_review.py', 'maintenance_service.py',
        'maintenance_sources.py', 'maintenance_stages.py')},
    **{f'{RELEASE}/frontend/{name}': STATIC + '/' + name for name in (
        'index.html', 'page.js', 'page.css', 'phase.js', 'reconcile.html')},
}
ACTIVE = {
    'routes': NGINX,
    'registry': '/var/www/dashboard/fs-home/navigation.json',
    'hubnav': '/var/www/hub/hubnav.js',
    'nav': '/var/www/hub/nav.js',
    'iam': '/opt/fs-access-policy/rbac.py',
    'catalog': '/app/fs_mcp_connector/catalog.json',
}


def encoded(value, **kwargs):
    options = dict(ensure_ascii=False, **kwargs)
    return json.dumps(value, **options)


def replace_routes(text):
    locator = lambda path: r'(?m)^location = ' + re.escape(path) + r' \{\n(?P<body>[\s\S]*?)^\}'
    if f'location = {NEW}' in text:
        raise ValueError('existing_customer_route')
    old = list(re.finditer(locator(OLD), text))
    if len(old) != 1 or GUARD not in old[0]['body']:
        raise ValueError('prior_tracking_route_or_guard')
    script = list(re.finditer(locator(OLD + 'page.js'), text))
    style = list(re.finditer(locator(OLD + 'page.css'), text))
    if len(script) != 1 or len(style) != 1:
        raise ValueError('prior_tracking_assets_route')
    if any(GUARD not in item['body'] for item in script + style):
        raise ValueError('prior_tracking_asset_guard')

    def alias(block, route, name):
        body, count = re.subn(r'(?m)^(\s*alias )[^;]+;', r'\g<1>' + STATIC + '/' + name + ';', block['body'])
        if count != 1:
            raise ValueError('prior_tracking_alias')
        body, _ = re.subn(r'((?:hubnav|nav)\.js\?v=)[\w-]+', r'\g<1>customer-maintenance-20261124', body)
        return f'location = {route} {{\n{body}}}'

    new = [
        f'location = {OLD} {{ return 302 {NEW}; }}',
        alias(old[0], NEW, 'index.html'),
        alias(script[0], NEW + 'page.js', 'page.js'),
        alias(style[0], NEW + 'page.css', 'page.css'),
        alias(script[0], NEW + 'phase.js', 'phase.js'),
        alias(old[0], NEW + 'reconcile/', 'reconcile.html'),
    ]
    old_index = list(re.finditer(locator(OLD + 'index.html'), text))
    if len(old_index) > 1:
        raise ValueError('duplicate_old_tracking_route')
    if old_index:
        text = text[:old_index[0].start()] + f'location = {OLD}index.html {{ return 302 {NEW}; }}' + text[old_index[0].end():]
    return re.sub(locator(OLD), lambda _: '\n\n'.join(new), text, count=1)


def update_registry(document):
    result = deepcopy(document)
    sections = {row['id']: row for row in result['sections']}
    analytics, brain = sections['analytics'], sections['brain']
    tool = next(row for row in result['tools'] if row['id'] == 'customer-tracking')
    if tool['path'] != OLD or tool['section'] != 'brain' or 'customer-tracking' in analytics['ids']:
        raise ValueError('prior_tracking_registry')
    brain['ids'].remove('customer-tracking')
    position = analytics['ids'].index('user-analytics') + 1
    analytics['ids'].insert(position, 'customer-tracking')
    brain['intro'] = brain['intro'].replace('、持续对话与客单追踪', '与持续对话')
    tool.update(section='analytics', label='客户维护', path=NEW,
                short='FC27 周名单、客户阶段、维护规则与跟进结果')
    return result


def update_script(text, main=False):
    count = 0

    def js_registry(match):
        nonlocal count
        count += 1
        return match[1] + encoded(update_registry(json.loads(match[2])), separators=(',', ':')) + ';'

    text = re.sub(r'(?m)^(\s*const (?:BUILTIN|registry)=)(\{[^\n]*\});$', js_registry, text)

    def fallback(match):
        nonlocal count
        groups = json.loads(match[2])
        old = rf'<a class="hn-tool" href="{re.escape(OLD)}">[^<]*</a>'
        groups['brain'], removed = re.subn(old, '', groups['brain'])
        after = 'href="/dashboard/users/">用户分析</a>'
        if removed != 1 or groups['analytics'].count(after) != 1:
            raise ValueError('prior_tracking_nav_fallback')
        groups['analytics'] = groups['analytics'].replace(after, after +
            f'<a class="hn-tool" href="{NEW}">客户维护</a>')
        count += 1
        return match[1] + encoded(groups, separators=(',', ':')) + ';'
    text = re.sub(r'(?m)^(\s*var sharedGroups = )(\{[^\n]*\});$', fallback, text)
    if count == 0 or main and 'const BUILTIN=' not in text or OLD in text:
        raise ValueError('prior_tracking_nav_script')
    return text


def patch_iam(text):
    marker = '("/dashboard/fs-home/brain", "/dashboard/fs-home/hermes",'
    if text.count(marker) != 1 or '"/dashboard/customers"' in text:
        raise ValueError('prior_tracking_iam')
    return text.replace(marker, marker + ' "/dashboard/customers",', 1)


def patch_catalog(active, candidate):
    result = deepcopy(active)
    updated = {row['name']: row for row in candidate['operations'] if row['name'].startswith('customer_tracking.')}
    current = [row for row in active['operations'] if row['name'].startswith('customer_tracking.')]
    for row in current:
        if row['name'] not in updated:
            raise ValueError('unknown_active_tracking_operation')
        copied = next(item for item in result['operations'] if item['name'] == row['name'])
        copied['permission_path'] = NEW
    inactive = [name for name in updated if name not in {row['name'] for row in current}]
    if any(not name.startswith('customer_tracking.stage_') for name in inactive):
        raise ValueError('tracking_operation_baseline_incomplete')
    result['operations'].extend(updated[name] for name in inactive)
    coverage = next(row for row in result['coverage'] if row['module'] == 'customer-tracking')
    coverage.update(permission_path=NEW, operations=len(updated))
    guide = next(row for row in result['data_methods']['guides'] if row['id'] == 'customer_business_details')
    guide['operations'].extend(name for name in inactive if name not in guide['operations'])
    return result


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(repo, baseline, output, commit):
    if not re.fullmatch(r'[0-9a-f]{40}', commit) or output.exists():
        raise ValueError('source_commit_and_new_output_required')
    prior = json.loads((baseline / 'sha256.json').read_bytes())
    required = set(TARGETS.values()) | set(ACTIVE.values())
    if set(prior) != required:
        raise ValueError('capture_target_set')
    def captured(name):
        raw = (baseline / name).read_bytes()
        if sha(raw) != prior[ACTIVE[name]]:
            raise ValueError('active_capture_changed')
        return raw.decode()
    def blob(path):
        return subprocess.check_output(['git', '-C', str(repo), 'cat-file', 'blob', commit + ':' + path])
    candidates = {target: (blob(source), source) for source, target in TARGETS.items()}
    generated = {
        'routes': replace_routes(captured('routes')),
        'registry': encoded(update_registry(json.loads(captured('registry'))), indent=2) + '\n',
        'hubnav': update_script(captured('hubnav'), main=True),
        'nav': update_script(captured('nav')),
        'iam': patch_iam(captured('iam')),
        'catalog': encoded(patch_catalog(json.loads(captured('catalog')),
                                        json.loads(blob(CONNECTOR))), indent=2) + '\n',
    }
    for name, value in generated.items():
        candidates[ACTIVE[name]] = value.encode(), name
    (output / 'candidate').mkdir(parents=True)
    files = []
    for index, (target, (raw, source)) in enumerate(sorted(candidates.items())):
        name = f'candidate/{index:02d}-{Path(target).name}'
        (output / name).write_bytes(raw)
        files.append(dict(candidate=name, target=target, source=source, beforeSha256=prior[target],
                          sha256=sha(raw), owner='0:0', mode='0o644'))
    payload = dict(schemaVersion=1, scope='customer-maintenance-phase2-20261124',
                   sourceCommit=commit, releaseReady=False, businessWrites=False, timersChanged=False, files=files)
    (output / 'candidate-manifest.json').write_text(encoded(payload, indent=2)+'\n', encoding='utf-8')
    return payload


if __name__ == '__main__':
    root, captured, output = map(Path, sys.argv[1:4])
    prepare(root, captured, output, sys.argv[4])