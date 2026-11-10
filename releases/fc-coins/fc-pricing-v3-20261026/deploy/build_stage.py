"""Create the exact private code stage from a committed FS-Workbench V3 tree."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

from target_map import COUPON_DISPLAY_EXTRA, COUPON_DISPLAY_SOURCE, TARGET_COUNT, targets
from target_map import (THREE_PLATFORM_EXTRA, THREE_PLATFORM_REPOSITORY_SOURCES,
                        THREE_PLATFORM_TARGET_COUNT, three_platform_targets)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob(checkout, path):
    relative = path.relative_to(checkout).as_posix()
    return subprocess.check_output(['git', 'show', 'HEAD:' + relative], cwd=checkout)


def build(checkout, output, coupon_display=False, three_platform=False):
    if coupon_display and three_platform:raise ValueError('exclusive_stage_mode_required')
    checkout = Path(checkout).resolve()
    release = checkout / 'releases/fc-coins/fc-pricing-v3-20261026'
    source = release / 'source'
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout, text=True).strip()
    paths=[str(release.relative_to(checkout))]
    if coupon_display:paths.append(COUPON_DISPLAY_SOURCE)
    if three_platform:paths.extend(THREE_PLATFORM_REPOSITORY_SOURCES.values())
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--', *paths],
                                    cwd=checkout, text=True).strip()
    if dirty:
        raise ValueError('source_tree_has_uncommitted_changes')
    mapping = three_platform_targets(source) if three_platform else targets(source)
    if len(mapping) != (THREE_PLATFORM_TARGET_COUNT if three_platform else TARGET_COUNT):
        raise ValueError('exact_target_count_required')
    if coupon_display:mapping.update({name.removeprefix('source/'):target for name,target in COUPON_DISPLAY_EXTRA.items()})
    if three_platform:mapping.update({name.removeprefix('source/'):target for name,target in THREE_PLATFORM_EXTRA.items()})
    with tempfile.TemporaryDirectory(prefix='fc-v3-stage-') as temporary:
        stage = Path(temporary) / 'fc-pricing-v3-20261026'
        candidate = stage / 'candidate/source'
        candidate.mkdir(parents=True)
        for name in mapping:
            original = checkout/COUPON_DISPLAY_SOURCE if coupon_display and name=='storefront_monitor.py' else source / name.removeprefix('hermes-copy/')
            if three_platform and 'source/'+name in THREE_PLATFORM_REPOSITORY_SOURCES:
                original=checkout/THREE_PLATFORM_REPOSITORY_SOURCES['source/'+name]
            destination = candidate / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            payload = git_blob(checkout, original)
            if original.suffix == '.sh' and (not payload.startswith(b'#!/bin/sh\n') or b'\r' in payload):
                raise ValueError('committed_shell_line_endings_invalid:' + name)
            destination.write_bytes(payload)
        deployment = stage / 'deploy'
        deployment.mkdir()
        for name in ('target_map.py', 'release_navigation_base.py', 'fc_v3_release_adapter.py',
                     'prepare_manifest.py','release_readiness.py'):
            (deployment / name).write_bytes(git_blob(checkout, release / 'deploy' / name))
        provenance = {'sourceCommit': commit,
                      'files': {'source/' + name: digest(candidate / name) for name in sorted(mapping)}}
        if coupon_display:provenance['repositorySources']={'source/storefront_monitor.py':COUPON_DISPLAY_SOURCE}
        if three_platform:provenance['repositorySources']=THREE_PLATFORM_REPOSITORY_SOURCES
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
    kind.add_argument('--three-platform',action='store_true')
    args = parser.parse_args()
    print(json.dumps(build(args.checkout, args.output,args.coupon_display,args.three_platform), sort_keys=True))
