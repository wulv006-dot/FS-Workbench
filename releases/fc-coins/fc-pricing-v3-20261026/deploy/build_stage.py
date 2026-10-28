"""Create the exact private code stage from a committed FS-Workbench V3 tree."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

from target_map import targets


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob(checkout, path):
    relative = path.relative_to(checkout).as_posix()
    return subprocess.check_output(['git', 'show', 'HEAD:' + relative], cwd=checkout)


def build(checkout, output):
    checkout = Path(checkout).resolve()
    release = checkout / 'releases/fc-coins/fc-pricing-v3-20261026'
    source = release / 'source'
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--', str(release.relative_to(checkout))],
                                    cwd=checkout, text=True).strip()
    if dirty:
        raise ValueError('source_tree_has_uncommitted_changes')
    mapping = targets(source)
    if len(mapping) != 96:
        raise ValueError('exact_target_count_required')
    with tempfile.TemporaryDirectory(prefix='fc-v3-stage-') as temporary:
        stage = Path(temporary) / 'fc-pricing-v3-20261026'
        candidate = stage / 'candidate/source'
        candidate.mkdir(parents=True)
        for name in mapping:
            original = source / name.removeprefix('hermes-copy/')
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
    args = parser.parse_args()
    print(json.dumps(build(args.checkout, args.output), sort_keys=True))
