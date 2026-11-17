"""Build the exact FC publisher manifest from staged Git bytes and live CAS."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from target_map import LOOTBAR_CALLER_NAMES,LOOTBAR_CALLER_SCOPE,LOOTBAR_CALLER_SOURCE,LOOTBAR_CALLER_EXTRA,LOOTBAR_CALLER_REPOSITORY_SOURCES

from target_map import COUPON_DISPLAY_NAMES, COUPON_DISPLAY_SCOPE, COUPON_DISPLAY_SOURCE, COUPON_DISPLAY_EXTRA, COUPON_DISPLAY_PROTECTED, DAILY_SUMMARY_NAMES, DAILY_SUMMARY_SCOPE, DAILY_REPAIR_NAMES, DAILY_REPAIR_SCOPE, QUOTE_PREVIEW_NAMES, QUOTE_PREVIEW_SCOPE, QUOTE_FRAGMENT_NAMES, QUOTE_FRAGMENT_SCOPE, REPAIR_NAMES, REPAIR_SCOPE, BIDIRECTIONAL_NAMES, BIDIRECTIONAL_SCOPE, DELTA_NAMES, DELTA_SCOPE, DELTA_NEW, SHADOW_NAMES, SHADOW_SCOPE, OPERATING_SCOPE, OPERATING_NAMES, OPERATING_NEW, COLLECTION_SCOPE, COLLECTION_NAMES, TARGET_COUNT, targets
from target_map import (THREE_PLATFORM_SCOPE, THREE_PLATFORM_NAMES, THREE_PLATFORM_NEW,
    THREE_PLATFORM_EXTRA, THREE_PLATFORM_REPOSITORY_SOURCES, THREE_PLATFORM_TARGET_COUNT, three_platform_targets,
    MONITOR_SQLITE_CANDIDATE, MONITOR_SQLITE_SOURCE, MONITOR_SQLITE_SHA, MONITOR_SQLITE_PROVENANCE)
from target_map import (CURVE_V6_BASE, CURVE_V6_SCOPE, CURVE_V6_NEW, CURVE_V6_TARGET_COUNT, CURVE_V6_PROTECTED,
                        CURVE_V6_REPOSITORY_SOURCES,
                        curve_v6_targets, require_curve_scope_for_imports)
from target_map import CURVE_AVERAGE_SCOPE, CURVE_AVERAGE_NEW, CURVE_AVERAGE_TARGET_COUNT, curve_average_targets
from target_map import CURVE_INSURANCE_SCOPE, CURVE_INSURANCE_TARGET_COUNT, curve_insurance_targets
from target_map import CURVE_WEEKLY_SCOPE, CURVE_WEEKLY_TARGET_COUNT, CURVE_WEEKLY_NEW, curve_weekly_targets
from target_map import CURVE_MARKET_SCOPE, CURVE_MARKET_TARGET_COUNT, curve_market_targets
from target_map import CURVE_STABILITY_SCOPE, CURVE_STABILITY_TARGET_COUNT, CURVE_STABILITY_REPOSITORY_SOURCES, curve_stability_targets

HERE = Path(__file__).resolve().parent
STAGE = HERE.parent
SCOPE = 'fc-pricing-v3-20261026'
IMAGE_ID = 'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular(path, existing=True):
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('symlink_boundary:' + str(item))
    if existing and not path.is_file():
        raise ValueError('required_file_missing:' + str(path))
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError('unsafe_file:' + str(path))


def load_base():
    path = HERE / 'release_navigation_base.py'
    if sha(path) != '57f4baf8db15fc791375b641fb618ef87a867901643bc0aa33f10804b8fcb840':
        raise ValueError('frozen_publisher_drift')
    spec = importlib.util.spec_from_file_location('fc_v3_original_base', path)
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    return base


def prepare(delta=False, shadow=False, operating=False, collection=False, bidirectional=False, repair=False, quote_fragment=False, quote_preview=False, daily_repair=False, daily_summary=False, coupon_display=False, three_platform=False, bundle_bootstrap=None,lootbar=False,curve_v6=False,curve_average=False,curve_insurance=False, curve_stability=False, curve_market=False, curve_weekly=False):
    if sum(map(bool,(delta,shadow,operating,collection,bidirectional,repair,quote_fragment,quote_preview,daily_repair,daily_summary,coupon_display,three_platform,lootbar,curve_v6,curve_average,curve_insurance,curve_stability,curve_market,curve_weekly)))>1:
        raise ValueError('exclusive_release_scope_required')
    if bundle_bootstrap is not None and not three_platform:raise ValueError('bundle_bootstrap_requires_three_platform_scope')
    provenance = json.loads((STAGE / 'source-manifest.json').read_text(encoding='utf-8'))
    source_commit = provenance.get('sourceCommit')
    if not re.fullmatch('[a-f0-9]{40}', source_commit or ''):
        raise ValueError('source_commit_required')
    source = STAGE / 'candidate/source'
    mapping = (curve_weekly_targets(source) if curve_weekly else curve_market_targets(source) if curve_market else curve_stability_targets(source) if curve_stability else curve_insurance_targets(source) if curve_insurance else curve_average_targets(source) if curve_average else curve_v6_targets(source) if curve_v6
               else three_platform_targets(source) if three_platform else targets(source))
    all_expected = {'source/' + name: target for name, target in mapping.items()}
    expected_count = (CURVE_WEEKLY_TARGET_COUNT if curve_weekly else CURVE_MARKET_TARGET_COUNT if curve_market else CURVE_STABILITY_TARGET_COUNT if curve_stability else CURVE_INSURANCE_TARGET_COUNT if curve_insurance else CURVE_AVERAGE_TARGET_COUNT if curve_average else CURVE_V6_TARGET_COUNT if curve_v6
                      else THREE_PLATFORM_TARGET_COUNT if three_platform else TARGET_COUNT)
    if len(all_expected) != expected_count:raise ValueError('staged_payload_differs_from_git_source_manifest')
    if curve_v6 and (provenance.get('scope') != CURVE_V6_SCOPE or provenance.get('sourceBaseCommit') != CURVE_V6_BASE
                     or provenance.get('repositorySources') != CURVE_V6_REPOSITORY_SOURCES):
        raise ValueError('curve_v6_source_provenance_changed')
    if three_platform:
        if provenance.get('repositorySources')!=THREE_PLATFORM_REPOSITORY_SOURCES:raise ValueError('three_platform_repository_source_changed')
        if provenance.get('externalSources')!=[MONITOR_SQLITE_PROVENANCE] or sha(STAGE/'candidate'/MONITOR_SQLITE_CANDIDATE)!=MONITOR_SQLITE_SHA:
            raise ValueError('monitor_sqlite_provenance_changed')
        all_expected.update(THREE_PLATFORM_EXTRA)
    if coupon_display:
        if provenance.get('repositorySources')!={'source/storefront_monitor.py':COUPON_DISPLAY_SOURCE}:raise ValueError('coupon_display_repository_source_changed')
        all_expected.update(COUPON_DISPLAY_EXTRA)
    if lootbar:
        if provenance.get('repositorySources')!=LOOTBAR_CALLER_REPOSITORY_SOURCES:raise ValueError('lootbar_repository_source_changed')
        all_expected.update(LOOTBAR_CALLER_EXTRA)
    if curve_average and provenance.get('scope') != CURVE_AVERAGE_SCOPE:
        raise ValueError('curve_average_source_provenance_changed')
    if curve_stability and (provenance.get('scope') != CURVE_STABILITY_SCOPE
                            or provenance.get('repositorySources') != CURVE_STABILITY_REPOSITORY_SOURCES):
        raise ValueError('curve_stability_source_provenance_changed')
    if curve_weekly and provenance.get('scope') != CURVE_WEEKLY_SCOPE:
        raise ValueError('curve_weekly_source_provenance_changed')
    if curve_market and provenance.get('scope') != CURVE_MARKET_SCOPE:
        raise ValueError('curve_market_source_provenance_changed')
    if curve_insurance and provenance.get('scope') != CURVE_INSURANCE_SCOPE:
        raise ValueError('curve_insurance_source_provenance_changed')
    if curve_v6 or curve_average or curve_insurance or curve_stability or curve_market or curve_weekly:
        candidate_root = STAGE / 'candidate'
        actual = {path.relative_to(candidate_root).as_posix() for path in candidate_root.rglob('*')
                  if path.is_symlink() or not path.is_dir()}
        if actual != set(all_expected):
            raise ValueError('staged_payload_differs_from_git_source_manifest')
        for name in all_expected:
            regular(candidate_root / name)
    if provenance.get('files') != {
            name: sha(STAGE / 'candidate' / name) for name in sorted(all_expected)}:
        raise ValueError('staged_payload_differs_from_git_source_manifest')
    selected = THREE_PLATFORM_NAMES if three_platform else COUPON_DISPLAY_NAMES if coupon_display else DAILY_SUMMARY_NAMES if daily_summary else DAILY_REPAIR_NAMES if daily_repair else QUOTE_PREVIEW_NAMES if quote_preview else QUOTE_FRAGMENT_NAMES if quote_fragment else REPAIR_NAMES if repair else BIDIRECTIONAL_NAMES if bidirectional else COLLECTION_NAMES if collection else OPERATING_NAMES if operating else SHADOW_NAMES if shadow else DELTA_NAMES if delta else None
    new_targets = (CURVE_WEEKLY_NEW if curve_weekly else CURVE_AVERAGE_NEW if curve_average else CURVE_V6_NEW if curve_v6 else THREE_PLATFORM_NEW
                   if three_platform else OPERATING_NEW if operating else DELTA_NEW if delta else frozenset())
    if lootbar:selected=LOOTBAR_CALLER_NAMES
    if curve_v6 or curve_average or curve_insurance or curve_stability or curve_market or curve_weekly:selected=tuple(all_expected)
    expected = {name: all_expected[name] for name in selected} if selected else all_expected
    if not (curve_v6 or curve_average or curve_insurance or curve_stability or curve_market or curve_weekly):
        for name in expected:
            if name.endswith('.py'):
                require_curve_scope_for_imports(name, (STAGE / 'candidate' / name).read_bytes())
    base = load_base()
    changed = set(expected.values())
    protected = {'/opt/fs-exact-range-20261001/' + name for name in (
        'boss_insights.py', 'fc_deep_model.py', 'fc_daily.py', 'fc_daily_model.py',
        'fc_detail.py', 'fc_detail_model.py', 'fc_detail_reader.py', 'fc_detail_config.json',
        'fc_deep_sources.py', 'summary_bridge.py')}
    protected.update(('/var/www/dashboard/index.html', '/var/www/dashboard/fs-home/index.html',
        '/var/www/dashboard/fs-home/navigation.js', '/opt/fs-access-policy/access_policy.py'))
    protected.update(set(base.HERMES_TARGETS.values()) - changed)
    protected.update((set(base.HERMES_CAPABILITY_TARGETS.values()) | set(base.CAP_PROTECTED_SESSION)) - changed)
    protected.update(set(base.HERMES_DIRECT_TARGETS.values()) - changed)
    if selected:
        protected.update(set(all_expected.values()) - changed)
    if coupon_display:protected.update(COUPON_DISPLAY_PROTECTED)
    if lootbar:protected.update(COUPON_DISPLAY_PROTECTED)
    if three_platform:
        protected.update(COUPON_DISPLAY_PROTECTED)
        protected.add('/opt/fc27-cloud-browser/storefront_monitor.py')
        protected.add(MONITOR_SQLITE_SOURCE)
    if curve_v6 or curve_average or curve_insurance or curve_stability or curve_market or curve_weekly:
        protected.update(set(three_platform_targets(source).values()) - changed)
        protected.update(COUPON_DISPLAY_PROTECTED)
        protected.update(CURVE_V6_PROTECTED)
        protected.update(THREE_PLATFORM_EXTRA[name] for name in ('source/monitor-hooks.py', 'source/monitor-collector.py'))
    if curve_average or curve_insurance or curve_stability or curve_market or curve_weekly:
        protected.update(set(curve_v6_targets(source).values()) - changed)
        protected.update(('/opt/fs-hermes-fc/user_source.py', '/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json'))
    rows = []
    for name, target in sorted(expected.items()):
        current = Path(target)
        regular(current, existing=bool(selected) and name not in new_targets)
        if (curve_v6 or curve_average or curve_insurance or curve_stability or curve_market or curve_weekly) and name in new_targets and current.exists():
            raise ValueError('curve_v6_new_target_already_exists:' + target)
        if current.exists():
            info = current.stat()
            if info.st_uid != 0 or info.st_gid != 0:
                raise ValueError('target_owner_drift:' + target)
            mode = oct(stat.S_IMODE(info.st_mode))
            before = sha(current)
        else:
            mode = '0o755' if target == '/opt/fc27-cloud-browser/reconcile_price.sh' else '0o644'
            before = None
        rows.append(dict(candidate=name, target=target, sha256=provenance['files'][name],
                         beforeSha256=before, owner='0:0', mode=mode))
    if sum(row['beforeSha256'] is None for row in rows) != (len(new_targets) if selected else 54):
        raise ValueError('new_target_count_drift')
    required = []
    for target in sorted(protected):
        path = Path(target)
        regular(path)
        required.append(dict(path=target, sha256=sha(path)))
    runtime = {}
    units=('fs-business-range.service', 'fs-hermes-fc.service',
           'fc27-cloud-api.service', 'fc27-cloud-worker.service')
    if three_platform:units+=('fc27-pack-bundles.service',)
    if curve_v6 or curve_average or curve_insurance or curve_stability or curve_market or curve_weekly:units+=('fc-pricing-v3.service',)
    for unit in units:
        state = subprocess.check_output(['systemctl', 'show', unit, '--no-pager',
            '-p', 'ActiveState'], universal_newlines=True).strip()
        if state != 'ActiveState=active':
            raise ValueError('required_service_not_active:' + unit)
        runtime[unit] = {'ActiveState': 'active'}
    manifest = dict(schemaVersion=1, scope=THREE_PLATFORM_SCOPE if three_platform else COUPON_DISPLAY_SCOPE if coupon_display else DAILY_SUMMARY_SCOPE if daily_summary else DAILY_REPAIR_SCOPE if daily_repair else QUOTE_PREVIEW_SCOPE if quote_preview else QUOTE_FRAGMENT_SCOPE if quote_fragment else REPAIR_SCOPE if repair else BIDIRECTIONAL_SCOPE if bidirectional else COLLECTION_SCOPE if collection else OPERATING_SCOPE if operating else SHADOW_SCOPE if shadow else DELTA_SCOPE if delta else SCOPE, sourceCommit=source_commit,
        releaseReady=True, businessWrites=False, timersChanged=False, imageId=IMAGE_ID,
        runtimeRequired=runtime, unchangedRequired=required, files=rows)
    if lootbar:manifest['scope']=LOOTBAR_CALLER_SCOPE
    if curve_v6:manifest['scope']=CURVE_V6_SCOPE
    if curve_average:manifest['scope']=CURVE_AVERAGE_SCOPE
    if curve_stability:manifest['scope']=CURVE_STABILITY_SCOPE
    if curve_weekly:manifest['scope']=CURVE_WEEKLY_SCOPE
    if curve_market:manifest['scope']=CURVE_MARKET_SCOPE
    if curve_insurance:manifest['scope']=CURVE_INSURANCE_SCOPE
    if bundle_bootstrap is not None:
        manifest['bundleBootstrap']=json.loads(Path(bundle_bootstrap).read_text('utf-8'))
    raw = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    path = HERE / 'approved-manifest.json'
    runtime_path = STAGE / 'approved-manifest.json'
    if path.exists() or runtime_path.exists():
        raise ValueError('existing_manifest_must_be_reconciled')
    path.write_bytes(raw)
    os.chmod(path, 0o600)
    try:
        from fc_v3_release_adapter import load_base as load_adapter
        result = load_adapter().inspect(manifest, STAGE)
        runtime_path.write_bytes(raw)
        os.chmod(runtime_path, 0o600)
    except Exception:
        path.unlink()
        runtime_path.unlink(missing_ok=True)
        raise
    return dict(manifestSha256=hashlib.sha256(raw).hexdigest(), sourceCommit=source_commit,
        files=len(rows), existing=len(rows)-len(new_targets) if selected else 30, new=len(new_targets) if selected else 54,
        protected=len(required), inspect=result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    kind = parser.add_mutually_exclusive_group()
    kind.add_argument('--delta', action='store_true')
    kind.add_argument('--shadow', action='store_true')
    kind.add_argument('--operating',action='store_true')
    kind.add_argument('--collection',action='store_true')
    kind.add_argument('--bidirectional',action='store_true')
    kind.add_argument('--repair',action='store_true')
    kind.add_argument('--quote-fragment',action='store_true')
    kind.add_argument('--quote-preview',action='store_true')
    kind.add_argument('--daily-repair',action='store_true')
    kind.add_argument('--daily-summary',action='store_true')
    kind.add_argument('--coupon-display',action='store_true')
    kind.add_argument('--lootbar',action='store_true')
    kind.add_argument('--three-platform',action='store_true')
    kind.add_argument('--curve-v6', action='store_true')
    kind.add_argument('--curve-average', action='store_true')
    kind.add_argument('--curve-insurance', action='store_true')
    kind.add_argument('--curve-stability', action='store_true')
    kind.add_argument('--curve-market', action='store_true')
    kind.add_argument('--curve-weekly', action='store_true')
    parser.add_argument('--bundle-bootstrap',help='Read-only proof metadata from capture-bundle-bootstrap; no private config')
    args = parser.parse_args()
    print(json.dumps(prepare(args.delta,args.shadow,args.operating,args.collection,args.bidirectional,args.repair,args.quote_fragment,args.quote_preview,args.daily_repair,args.daily_summary,args.coupon_display,args.three_platform,args.bundle_bootstrap,args.lootbar,curve_v6=args.curve_v6,curve_average=args.curve_average,curve_insurance=args.curve_insurance, curve_stability=args.curve_stability, curve_market=args.curve_market, curve_weekly=args.curve_weekly), sort_keys=True))
