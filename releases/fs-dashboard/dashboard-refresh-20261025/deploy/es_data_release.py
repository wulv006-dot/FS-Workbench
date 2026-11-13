"""Exact Admin ES host/data-page scope over the existing navigation publisher."""
import hashlib
import json
from pathlib import Path
import re
import types

SCOPE = 'fs-admin-es-data-20261113'
DELTA_SCOPE = 'fs-admin-es-data-delta-20261113'
RANGE = '/opt/fs-exact-range-20261001/'
HERMES = '/opt/fs-hermes-fc/'
STATIC = '/var/lib/fs-navigation-formal-static/'
FORMAL = '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
RUNTIME = {'fs-business-range.service': {'ActiveState': 'active'}}
ADAPTER = 'email-export-adapter.py'
ADAPTER_SHA = '683d5b4a6c52954383c998a98ad0963a361ca59a9983378f4d73b0fd4159c40a'
PROTECTED = frozenset({HERMES + n for n in ('controller.py','admin_live_admission.py','cache_retention.py',
    'user_weekly.py','user_contract.py','user_lifecycle.py','channel_effects.py','channel_source.py',
    'coupon_channels.py','coupon_channels.json','admin_discount_analysis.py')} |
    {RANGE + n for n in ('fc_daily.py','fc_detail_config.json','fc_detail_reader.py','fc_detail_model.py','management_profiles.py','supplement_fields.py')} |
    {'/etc/systemd/system/fs-business-range.service'})
RANGE_FILES = ('admin_scope.py','admin_summary.py','daily_archive.py','live_summary.py','local_repeat_source.py',
    'order_facts.py','order_facts_api.py','order_facts_runtime.py','order_facts_source.py','range_api.py',
    'site_summary.py','summary_bridge.py','fc_detail.py','fc_dashboard.py')
HOST_FILES = ('es_order_structure.py','order_attribution.py','user_store.py')
UI = ('business.js','home-business.js','legacy-business.js','index.html','channel.js','channel.css')
NEW = {'range/'+n for n in ('admin_scope.py','local_repeat_source.py','order_facts.py','order_facts_api.py',
    'order_facts_runtime.py','order_facts_source.py')} | {'host/order_attribution.py'} | {'ui/'+n for n in UI}
DELTA_UI = (*UI[:3], 'shell.js', 'home-shell.js', 'legacy-shell.js', 'homepage-shell.js')
DELTA_CODE = {'range/order_facts.py':RANGE+'order_facts.py', 'range/order_facts_api.py':RANGE+'order_facts_api.py',
              'host/channel_cost_source.py':HERMES+'channel_cost_source.py'}
DEPLOYED_ASSET_VERSION = 'admin-es-20261113-bf229232f385'
SUMMARY_ASSET_VERSION = 'summary-performance-20261107-7309593bc091'
SEO_ASSET_VERSION = 'seo-ui-c9e4111c43b04308'


def targets(version, *, delta=False):
    if not re.fullmatch(r'admin-es-20261113-[a-f0-9]{12}',version or ''):
        raise ValueError('exact ES asset version required')
    if delta:
        return {'routes.conf':FORMAL, **DELTA_CODE, **{'ui/'+n:STATIC+version+'/'+n for n in DELTA_UI}}
    return {'routes.conf':FORMAL, **{'range/'+n:RANGE+n for n in RANGE_FILES},
        **{'host/'+n:HERMES+n for n in HOST_FILES}, **{'ui/'+n:STATIC+version+'/'+n for n in UI}}


DELTA_PROTECTED = (PROTECTED | set(targets(DEPLOYED_ASSET_VERSION).values()) |
    {STATIC+SUMMARY_ASSET_VERSION+'/'+n for n in DELTA_UI[3:]} |
    {STATIC+SEO_ASSET_VERSION+'/'+n for n in ('index.html','seo.css','app.mjs','model.mjs','ai.mjs','fs-tokens.css','fs-theme.js')}) - {
    FORMAL, *DELTA_CODE.values()}


def contract(manifest):
    scope = manifest.get('scope')
    delta = scope == DELTA_SCOPE
    expected = targets(manifest.get('assetVersion'), delta=delta)
    new = {'ui/'+n for n in DELTA_UI} if delta else NEW
    required = DELTA_PROTECTED if delta else PROTECTED
    if (set(manifest) != {'schemaVersion','scope','releaseReady','businessWrites','timersChanged','files',
            'unchangedRequired','runtimeRequired','sourceCommit','assetVersion'}
            or manifest.get('schemaVersion') != 1 or scope not in (SCOPE, DELTA_SCOPE)
            or type(manifest.get('releaseReady')) is not bool or manifest.get('businessWrites') is not False
            or manifest.get('timersChanged') is not False or manifest.get('runtimeRequired') != RUNTIME
            or not re.fullmatch(r'[0-9a-f]{40}',manifest.get('sourceCommit',''))):
        raise ValueError('exact read-only ES manifest required')
    files = manifest['files']
    if len(files) != len(expected) or {r.get('candidate') for r in files} != set(expected):
        raise ValueError('exact ES targets required')
    for row in files:
        name, before = row['candidate'], row['beforeSha256']
        if (set(row) != {'candidate','target','sha256','beforeSha256'} or row['target'] != expected[name]
                or not re.fullmatch(r'[a-f0-9]{64}',row['sha256'] or '')
                or (before is None) != (name in new) or before is not None and not re.fullmatch(r'[a-f0-9]{64}',before)):
            raise ValueError('invalid ES payload or before CAS')
    protected = manifest['unchangedRequired']
    if len(protected) != len(required) or {row.get('path') for row in protected} != required or required.intersection(expected.values()):
        raise ValueError('exact ES protected dependencies required')
    if any(set(row) != {'path','sha256'} or not re.fullmatch(r'[a-f0-9]{64}',row.get('sha256') or '') for row in protected):
        raise ValueError('invalid protected ES hash')
    return files


def publisher(stage, manifest, *, frozen_base=None):
    """Reuse the prior exact range/nginx adapter, with ES-only scope and targets."""
    contract(manifest)
    stage = Path(stage)
    path = stage / ADAPTER
    raw = path.read_bytes()
    if path.is_symlink() or hashlib.sha256(raw).hexdigest() != ADAPTER_SHA:
        raise ValueError('range publisher adapter SHA differs')
    delegate = types.ModuleType('_es_range_publisher_adapter')
    delegate.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), delegate.__dict__)
    scope = manifest['scope']
    delta = scope == DELTA_SCOPE
    delegate.SCOPE = scope
    delegate.TARGETS = targets(manifest['assetVersion'], delta=delta)
    delegate.PROTECTED = DELTA_PROTECTED if delta else PROTECTED
    delegate.contract = contract
    if frozen_base is not None:
        delegate.BASE = Path(frozen_base)
    return delegate.load_base()


def load_manifest(path):
    raw = path.read_bytes()
    manifest = json.loads(raw)
    contract(manifest)
    return raw, manifest


if __name__ == '__main__':
    import argparse
    import os
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('plan','inspect','apply','rollback'))
    parser.add_argument('--manifest', type=Path, default=Path(__file__).with_name('manifest.json'))
    parser.add_argument('--approved-manifest-sha')
    parser.add_argument('--release-id')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    if args.action in ('apply','rollback') and os.name != 'posix':
        raise ValueError('mutation requires original Linux writer environment')
    raw, manifest = load_manifest(args.manifest)
    base = publisher(args.manifest.parent, manifest)
    if args.action == 'plan':
        result = {'files':len(base.validate(manifest,args.manifest.parent)),'mutations':False}
    elif args.action == 'inspect':
        result = base.inspect(manifest,args.manifest.parent)
    elif args.action == 'apply':
        result = base.apply(manifest,args.manifest.parent,args.approved_manifest_sha,raw,args.release_id)
    else:
        if (not args.backup or args.backup.parent != Path('/var/backups/fs-navigation-20261006')
                or not re.fullmatch(r'nav-[0-9]{8}T[0-9]{6}Z',args.backup.name)):
            raise ValueError('exact original writer backup required')
        result = base.rollback(args.backup,args.approved_manifest_sha)
    print(json.dumps(result,indent=2))
