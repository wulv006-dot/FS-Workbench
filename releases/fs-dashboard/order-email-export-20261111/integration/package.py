"""Build only the exact email-export candidates from an already verified main SHA."""
import hashlib
import re

from prepare import prepare
from workspace_patch import prepare_workspace
from nginx_patch import prepare_nginx

PREFIX = 'releases/fs-dashboard/order-email-export-20261111/'
FRONTEND = 'releases/fs-dashboard/hermes-data-workspace-20261018/frontend/'
BACKEND = 'releases/fs-dashboard/tiered-data-access-20261101/source/'
STATIC = '/var/lib/fs-navigation-formal-static/workspace-native-20261006-4f4a56f7a335/'
PROTECTED = {
    '/opt/fs-hermes-fc/controller.py': '104e16a785240c471fc8d9f209b9430cfc1286111e4c093f8e12b3eca4f5fa29',
    '/opt/fs-exact-range-20261001/fc_daily.py': '213cca2a7a02218f67aff6ca3bf905aac9fe3ba0165017b590949b3828bac35e',
    '/opt/fs-hermes-fc/admin_live_admission.py': '6cbb9a7d7a852c8c3ee0e13fe78ed277569b64f64bb7a6578757561f7b1e24ad',
    '/opt/fs-hermes-fc/cache_retention.py': '9c06e87a47d04df817c6d6aadc8f3762d4b6f2bd7c0a8b7b4a45a29ce4fe7ebb',
    '/etc/systemd/system/fs-business-range.service': '87b1eafebc1a01179bb50f77e05b04364c3cb3cc784e706b9dcc0f1f87497439',
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def build(sha, read_git, nginx_source):
    """read_git receives fixed repository paths and returns bytes at SHA, not working files.

    This does not assert CI/main identity or publish. The release caller verifies those
    before invoking it; the original writer independently checks live CAS under locks.
    """
    if not isinstance(sha, str) or not re.fullmatch('[a-f0-9]{40}', sha):
        raise ValueError('exact main SHA required')
    baseline = {name: read_git(PREFIX + 'integration/fixtures/' + name)
                for name in ('range_api.py', 'page.js', 'data-workspace.js')}
    candidates = prepare(baseline['range_api.py'], baseline['page.js'])
    candidates['data-workspace.js'] = prepare_workspace(baseline['data-workspace.js'])
    candidates['formal.locations.conf'] = prepare_nginx(nginx_source)
    candidates['admin_order_email_export.py'] = read_git(BACKEND + 'admin_order_email_export.py')
    for name in ('order-email-panel.js', 'order-email-run.js', 'order-email-csv.js', 'order-email-xlsx.js'):
        candidates[name] = read_git(FRONTEND + name)
    targets = {name: STATIC + name for name in candidates if name.endswith('.js')}
    targets.update({'range_api.py': '/opt/fs-exact-range-20261001/range_api.py',
                    'admin_order_email_export.py': '/opt/fs-hermes-fc/admin_order_email_export.py',
                    'formal.locations.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'})
    baseline['formal.locations.conf'] = nginx_source
    manifest = {'schemaVersion': 1, 'scope': 'order-email-export-20261111',
                'releaseReady': True, 'businessWrites': False, 'timersChanged': False,
                'sourceCommit': sha, 'runtimeRequired': {'fs-business-range.service': {'ActiveState': 'active'}},
                'unchangedRequired': [{'path': p, 'sha256': h} for p, h in sorted(PROTECTED.items())],
                'files': [{'candidate': name, 'target': targets[name], 'sha256': digest(raw),
                           'beforeSha256': digest(baseline[name]) if name in baseline else None}
                          for name, raw in sorted(candidates.items())]}
    return candidates, manifest
