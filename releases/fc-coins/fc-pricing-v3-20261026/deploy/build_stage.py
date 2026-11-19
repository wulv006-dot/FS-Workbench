"""Create the exact private FC code stage from a committed FS-Workbench tree."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

from target_map import COUPON_DISPLAY_EXTRA, COUPON_DISPLAY_NAMES, COUPON_DISPLAY_SOURCE, TARGET_COUNT, targets
from target_map import LOOTBAR_CALLER_EXTRA, LOOTBAR_CALLER_NAMES, LOOTBAR_CALLER_REPOSITORY_SOURCES
from target_map import (CURVE_V6_BASE, CURVE_V6_SCOPE, CURVE_V6_SOURCE_NAMES, CURVE_V6_TARGET_COUNT,
                        CURVE_V6_SEPARATE_ROLE_SOURCES,
                        CURVE_V6_REPOSITORY_SOURCES,
                        curve_v6_targets, require_curve_scope_for_imports,
                        THREE_PLATFORM_EXTRA, THREE_PLATFORM_NAMES, THREE_PLATFORM_REPOSITORY_SOURCES,
                        THREE_PLATFORM_TARGET_COUNT, three_platform_targets,
                        MONITOR_SQLITE_CANDIDATE, MONITOR_SQLITE_SHA, MONITOR_SQLITE_PROVENANCE)
from target_map import CURVE_AVERAGE_SCOPE, CURVE_AVERAGE_TARGET_COUNT, curve_average_targets
from target_map import CURVE_INSURANCE_SCOPE, CURVE_INSURANCE_TARGET_COUNT, curve_insurance_targets
from target_map import CURVE_WEEKLY_SCOPE, CURVE_WEEKLY_TARGET_COUNT, CURVE_WEEKLY_NEW, curve_weekly_targets
from target_map import CURVE_MARKET_SCOPE, CURVE_MARKET_TARGET_COUNT, curve_market_targets
from target_map import CURVE_ARAB_QUOTE_SCOPE, CURVE_ARAB_QUOTE_TARGET_COUNT, curve_arab_quote_targets
from target_map import CURVE_RECOVERY_SCOPES, CURVE_RECOVERY_TARGETS
from target_map import HOURLY_COST_CHANNEL_BASE, HOURLY_COST_CHANNEL_OVERLAY, hourly_cost_channel_overlay
from target_map import (ORDER_COST_CHANNEL_INSERT, ORDER_COST_CHANNEL_OVERLAY,
                        ORDER_COST_CHANNEL_REPOSITORY, order_cost_channel_overlay)
from target_map import CURVE_MARGIN_BAND_SCOPE, CURVE_MARGIN_BAND_TARGET_COUNT, curve_margin_band_targets
from target_map import CURVE_REVIEW_SCOPE, CURVE_REVIEW_TARGET_COUNT, curve_review_targets
from target_map import CURVE_STABILITY_SCOPE, CURVE_STABILITY_TARGET_COUNT, CURVE_STABILITY_REPOSITORY_SOURCES, curve_stability_targets


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob(checkout, path, commit='HEAD'):
    relative = path.relative_to(checkout).as_posix()
    return subprocess.check_output(['git', 'show', commit + ':' + relative], cwd=checkout)


def monitor_library(path):
    if path is None:raise ValueError('monitor_sqlite_library_required')
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('monitor_sqlite_library_invalid')
    payload=path.read_bytes()
    if not payload.startswith(b'\x7fELF\x02\x01') or hashlib.sha256(payload).hexdigest()!=MONITOR_SQLITE_SHA:
        raise ValueError('monitor_sqlite_library_sha_mismatch')
    return payload


def build(checkout, output, coupon_display=False, three_platform=False, monitor_sqlite_library=None, lootbar=False,
          curve_v6=False, curve_average=False, curve_insurance=False, curve_stability=False, curve_market=False, curve_weekly=False, curve_review=False, curve_margin_band=False, curve_arab_quote=False, curve_recovery=None, order_cost_channel_baseline=None):
    curve_modes = (curve_v6, curve_average, curve_insurance, curve_stability, curve_market,
                   curve_weekly, curve_review, curve_margin_band, curve_arab_quote, curve_recovery)
    if sum(map(bool,(coupon_display,three_platform,lootbar,*curve_modes)))>1:raise ValueError('exclusive_stage_mode_required')
    if monitor_sqlite_library is not None and not three_platform:raise ValueError('monitor_library_requires_three_platform_scope')
    if (curve_recovery in ('order-cost', 'hourly-order-cost')) != (order_cost_channel_baseline is not None):
        raise ValueError('order_cost_channel_baseline_required_for_scope')
    checkout = Path(checkout).resolve()
    release = checkout / 'releases/fc-coins/fc-pricing-v3-20261026'
    source = release / 'source'
    channel_overlay = None
    if order_cost_channel_baseline is not None:
        baseline = Path(order_cost_channel_baseline)
        if baseline.is_symlink() or not baseline.is_file():
            raise ValueError('order_cost_channel_baseline_invalid')
        live = baseline.read_bytes()
        if curve_recovery == 'order-cost':
            channel_overlay = order_cost_channel_overlay(live)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout, text=True).strip()
    if curve_recovery == 'hourly-order-cost':
        channel_path = checkout / ORDER_COST_CHANNEL_REPOSITORY
        previous, updated = (git_blob(checkout, channel_path, rev) for rev in (HOURLY_COST_CHANNEL_BASE, commit))
        channel_overlay = hourly_cost_channel_overlay(live, updated, repository_before=previous)
    paths=[str(release.relative_to(checkout))]
    if coupon_display:paths.append(COUPON_DISPLAY_SOURCE)
    if lootbar:paths.extend(LOOTBAR_CALLER_REPOSITORY_SOURCES.values())
    if three_platform:paths.extend(THREE_PLATFORM_REPOSITORY_SOURCES.values())
    if curve_stability:paths.extend(CURVE_STABILITY_REPOSITORY_SOURCES.values())
    if curve_v6:paths.extend(CURVE_V6_REPOSITORY_SOURCES.values())
    if channel_overlay is not None:paths.append(ORDER_COST_CHANNEL_REPOSITORY)
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--', *paths],
                                    cwd=checkout, text=True).strip()
    if dirty:
        raise ValueError('source_tree_has_uncommitted_changes')
    if curve_v6:
        source_path = source.relative_to(checkout).as_posix() + '/'
        changed = subprocess.check_output(
            ['git', 'diff', '--name-only', '--no-renames', '-z', CURVE_V6_BASE, commit, '--', source_path],
            cwd=checkout, text=True)
        actual = {path.removeprefix(source_path) for path in changed.split('\0') if path}
        actual -= CURVE_V6_SEPARATE_ROLE_SOURCES
        if actual != CURVE_V6_SOURCE_NAMES:
            raise ValueError('curve_v6_source_scope_changed:missing='
                             + ','.join(sorted(CURVE_V6_SOURCE_NAMES - actual))
                             + ':extra=' + ','.join(sorted(actual - CURVE_V6_SOURCE_NAMES)))
    library=monitor_library(monitor_sqlite_library) if three_platform else None
    mapping = (CURVE_RECOVERY_TARGETS[curve_recovery].copy() if curve_recovery else curve_arab_quote_targets(source) if curve_arab_quote else curve_margin_band_targets(source) if curve_margin_band else curve_review_targets(source) if curve_review else curve_weekly_targets(source) if curve_weekly else curve_market_targets(source) if curve_market else curve_stability_targets(source) if curve_stability else curve_insurance_targets(source) if curve_insurance else curve_average_targets(source) if curve_average else curve_v6_targets(source) if curve_v6
               else three_platform_targets(source) if three_platform else targets(source))
    expected_count = (len(CURVE_RECOVERY_TARGETS[curve_recovery]) if curve_recovery else CURVE_ARAB_QUOTE_TARGET_COUNT if curve_arab_quote else CURVE_MARGIN_BAND_TARGET_COUNT if curve_margin_band else CURVE_REVIEW_TARGET_COUNT if curve_review else CURVE_WEEKLY_TARGET_COUNT if curve_weekly else CURVE_MARKET_TARGET_COUNT if curve_market else CURVE_STABILITY_TARGET_COUNT if curve_stability else CURVE_INSURANCE_TARGET_COUNT if curve_insurance else CURVE_AVERAGE_TARGET_COUNT if curve_average else CURVE_V6_TARGET_COUNT if curve_v6
                      else THREE_PLATFORM_TARGET_COUNT if three_platform else TARGET_COUNT)
    if len(mapping) != expected_count:
        raise ValueError('exact_target_count_required')
    if coupon_display:mapping.update({name.removeprefix('source/'):target for name,target in COUPON_DISPLAY_EXTRA.items()})
    if lootbar:mapping.update({name.removeprefix('source/'):target for name,target in LOOTBAR_CALLER_EXTRA.items()})
    if three_platform:mapping.update({name.removeprefix('source/'):target for name,target in THREE_PLATFORM_EXTRA.items()})
    selected = (THREE_PLATFORM_NAMES if three_platform else COUPON_DISPLAY_NAMES if coupon_display
                else LOOTBAR_CALLER_NAMES if lootbar else None)
    curve_stage = any(curve_modes)
    def read_blob(path):
        return git_blob(checkout, path, commit) if curve_stage else git_blob(checkout, path)

    if curve_recovery == 'order-cost' and ORDER_COST_CHANNEL_INSERT not in read_blob(checkout / ORDER_COST_CHANNEL_REPOSITORY):
        raise ValueError('order_cost_channel_repository_delta_missing')
    with tempfile.TemporaryDirectory(prefix='fc-v3-stage-') as temporary:
        stage = Path(temporary) / 'fc-pricing-v3-20261026'
        candidate = stage / 'candidate/source'
        candidate.mkdir(parents=True)
        for name in mapping:
            original = checkout/COUPON_DISPLAY_SOURCE if coupon_display and name=='storefront_monitor.py' else source / name.removeprefix('hermes-copy/')
            if lootbar and 'source/'+name in LOOTBAR_CALLER_REPOSITORY_SOURCES:original=checkout/LOOTBAR_CALLER_REPOSITORY_SOURCES['source/'+name]
            if three_platform and 'source/'+name in THREE_PLATFORM_REPOSITORY_SOURCES:
                original=checkout/THREE_PLATFORM_REPOSITORY_SOURCES['source/'+name]
            if curve_v6 and 'source/'+name in CURVE_V6_REPOSITORY_SOURCES:
                original=checkout/CURVE_V6_REPOSITORY_SOURCES['source/'+name]
            if curve_stability and 'source/'+name in CURVE_STABILITY_REPOSITORY_SOURCES:
                original=checkout/CURVE_STABILITY_REPOSITORY_SOURCES['source/'+name]
            destination = candidate / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if channel_overlay is not None and 'source/' + name == ORDER_COST_CHANNEL_OVERLAY['candidate']:
                payload = channel_overlay
            else:
                payload = library if 'source/'+name==MONITOR_SQLITE_CANDIDATE else read_blob(original)
            if not curve_stage and (selected is None or 'source/' + name in selected):
                require_curve_scope_for_imports(name, payload)
            if original.suffix == '.sh' and (not payload.startswith(b'#!/bin/sh\n') or b'\r' in payload):
                raise ValueError('committed_shell_line_endings_invalid:' + name)
            destination.write_bytes(payload)
        deployment = stage / 'deploy'
        deployment.mkdir()
        for name in ('target_map.py', 'release_navigation_base.py', 'fc_v3_release_adapter.py',
                     'prepare_manifest.py','release_readiness.py'):
            (deployment / name).write_bytes(read_blob(release / 'deploy' / name))
        provenance = {'sourceCommit': commit,
                      'files': {'source/' + name: digest(candidate / name) for name in sorted(mapping)}}
        if coupon_display:provenance['repositorySources']={'source/storefront_monitor.py':COUPON_DISPLAY_SOURCE}
        if lootbar:provenance['repositorySources']=LOOTBAR_CALLER_REPOSITORY_SOURCES
        if three_platform:
            provenance['repositorySources']=THREE_PLATFORM_REPOSITORY_SOURCES
            provenance['externalSources']=[MONITOR_SQLITE_PROVENANCE]
        if curve_v6:
            provenance.update(scope=CURVE_V6_SCOPE, sourceBaseCommit=CURVE_V6_BASE,
                              repositorySources=CURVE_V6_REPOSITORY_SOURCES)
        if curve_average:
            provenance['scope'] = CURVE_AVERAGE_SCOPE
        if curve_stability:
            provenance.update(scope=CURVE_STABILITY_SCOPE, repositorySources=CURVE_STABILITY_REPOSITORY_SOURCES)
        if curve_weekly:
            provenance['scope'] = CURVE_WEEKLY_SCOPE
        if curve_arab_quote:
            provenance['scope'] = CURVE_ARAB_QUOTE_SCOPE
        if curve_recovery:
            provenance['scope'] = CURVE_RECOVERY_SCOPES[curve_recovery]
        if curve_recovery == 'hourly-order-cost':
            provenance.update(sourceBaseCommit=HOURLY_COST_CHANNEL_BASE,
                              repositorySources={HOURLY_COST_CHANNEL_OVERLAY['candidate']: ORDER_COST_CHANNEL_REPOSITORY},
                              liveSourceOverlays=[HOURLY_COST_CHANNEL_OVERLAY])
        elif curve_recovery == 'order-cost':
            provenance['liveSourceOverlays'] = [ORDER_COST_CHANNEL_OVERLAY]
        if curve_margin_band:
            provenance['scope'] = CURVE_MARGIN_BAND_SCOPE
        if curve_review:
            provenance['scope'] = CURVE_REVIEW_SCOPE
        if curve_market:
            provenance['scope'] = CURVE_MARKET_SCOPE
        if curve_insurance:
            provenance['scope'] = CURVE_INSURANCE_SCOPE
        (stage / 'source-manifest.json').write_text(
            json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        output = Path(output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output, 'w:gz') as bundle:
            bundle.add(stage, arcname=stage.name)
    return {'archive': str(output), 'sha256': digest(output), 'sourceCommit': commit,
            'targets': len(mapping)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('checkout')
    parser.add_argument('output')
    kind=parser.add_mutually_exclusive_group()
    kind.add_argument('--coupon-display',action='store_true')
    kind.add_argument('--lootbar',action='store_true')
    kind.add_argument('--three-platform',action='store_true')
    kind.add_argument('--curve-v6', action='store_true')
    kind.add_argument('--curve-average', action='store_true')
    kind.add_argument('--curve-insurance', action='store_true')
    kind.add_argument('--curve-stability', action='store_true')
    kind.add_argument('--curve-market', action='store_true')
    kind.add_argument('--curve-weekly', action='store_true')
    kind.add_argument('--curve-review', action='store_true')
    kind.add_argument('--curve-margin-band', action='store_true')
    kind.add_argument('--curve-arab-quote', action='store_true')
    kind.add_argument('--curve-recovery', choices=CURVE_RECOVERY_SCOPES)
    parser.add_argument('--monitor-sqlite-library',type=Path)
    parser.add_argument('--order-cost-channel-baseline',type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.checkout, args.output,args.coupon_display,args.three_platform,args.monitor_sqlite_library,args.lootbar,
                           curve_v6=args.curve_v6, curve_average=args.curve_average, curve_insurance=args.curve_insurance, curve_stability=args.curve_stability, curve_market=args.curve_market, curve_weekly=args.curve_weekly, curve_review=args.curve_review, curve_margin_band=args.curve_margin_band, curve_arab_quote=args.curve_arab_quote, curve_recovery=args.curve_recovery, order_cost_channel_baseline=args.order_cost_channel_baseline), sort_keys=True))
