"""Prepare the bounded learning candidate offline; no network, application or service action."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MODULE = Path('releases/fs-dashboard/hermes-learning-closure-20261023')
KNOWLEDGE = Path('releases/fs-dashboard/knowledge-layering-20261023')
SKILLS = Path('releases/fs-dashboard/hermes-memory-approval-20261022')
SOURCES = {'runtime/' + name: KNOWLEDGE / 'source' / name
           for name in ('knowledge_catalog.py', 'business_context.py', 'controller.py')}
SOURCES.update({'runtime/conversation_service.py': Path('releases/fc-coins/fc-pricing-v2-20261022/source/conversation_service.py'),
                'runtime/business-baseline.md': Path('releases/fc-coins/fc-pricing-v2-20261022/source/business-baseline.md'),
                'runtime/reviewed_skills.py': SKILLS / 'reviewed_skills.py',
                'approval/review_queue.py': SKILLS / 'review_queue.py',
                'approval/reviewed_skills.py': SKILLS / 'reviewed_skills.py',
                'daily/daily_review.py': SKILLS / 'daily_review.py'})
PUBLISHERS = {
    'release_adapter_base.py': (Path('releases/fs-dashboard/fs-business-baseline-20261021/deploy/release.py'),
                                '65794d515f78826e5a23c4c88966c603e1a46dd3c977c3dd0956bc770a581344'),
    'release_navigation_base.py': (Path('releases/fs-dashboard/channel-effects-20261021/deploy/release_navigation_base.py'),
                                   '1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de')}


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def raw(root, name):
    return (Path(root) / name).read_bytes().replace(b'\r\n', b'\n')


def prepare(root, output, before=None, commit=None):
    root, output = Path(root), Path(output)
    if output.exists():
        raise ValueError('learning_stage_exists_reconcile_original_operation')
    if commit is not None and not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('learning_exact_commit_required')
    scope = load(root / MODULE / 'deploy/release.py', 'learning_release_scope')
    catalog = load(root / KNOWLEDGE / 'source/knowledge_catalog.py', 'learning_catalog_scope')
    index = catalog.validate(json.loads(raw(root, 'knowledge/index.json')))
    chosen = catalog.select(root, 'knowledge/index.json', hashlib.sha256(raw(root, 'knowledge/index.json')).hexdigest(),
                            ['FS', 'FC27'], preview=True)
    if chosen['status'] != 'available_preview':
        raise ValueError('learning_current_catalog_unavailable')
    inputs = set(SOURCES.values()) | {Path('knowledge/index.json'), MODULE / 'deploy/release.py'}
    inputs.update(path for path, sha in PUBLISHERS.values())
    inputs.update(Path(row['source']['path']) for row in index['entries'] if row['layer'] != 'candidate')
    if commit is not None:
        for name in sorted(inputs):
            frozen = subprocess.check_output(['git', 'show', commit + ':' + name.as_posix()], cwd=root)
            if frozen.replace(b'\r\n', b'\n') != raw(root, name):
                raise ValueError('learning_commit_source_drift:' + name.as_posix())
    publishers = {}
    for name, (path, sha) in PUBLISHERS.items():
        data = (root / path).read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            raise ValueError('learning_frozen_publisher_drift:' + name)
        publishers[name] = data
    derived = copy.deepcopy(index)
    derived.update(release=scope.RELEASE, release_state='published' if commit else 'candidate',
                   source_commit=commit, source_root='knowledge-releases/' + scope.RELEASE + '/sources')
    if commit:
        for row in derived['entries']:
            if row.get('source_commit') is None:
                row['source_commit'] = commit
    payloads = {name: raw(root, path) for name, path in SOURCES.items()}
    payloads['artifact/index.json'] = (json.dumps(derived, ensure_ascii=False, indent=2) + '\n').encode()
    for row in derived['entries']:
        if row['layer'] == 'candidate':
            continue
        name = row['source']['path']
        content = catalog.read_bound(root, name).replace(b'\r\n', b'\n')
        if hashlib.sha256(content).hexdigest() != row['source']['sha256']:
            raise ValueError('learning_release_source_drift:' + name)
        payloads['artifact/sources/' + name] = content
    before = before or {}
    rows = [dict(candidate=name, target=scope.RUNTIME.get(name, scope.PREFIX + name[len('artifact/'):]),
                 sha256=hashlib.sha256(content).hexdigest(),
                 beforeSha256=before.get(scope.RUNTIME.get(name)), owner='0:0', mode='0o644')
            for name, content in sorted(payloads.items())]
    manifest = dict(schemaVersion=1, scope=scope.SCOPE, releaseReady=False, sourceCommit=commit,
                    baseCommit=index.get('base_commit', index.get('source_commit')), businessWrites=False,
                    timersChanged=False, files=rows, unchangedRequired=[], runtimeRequired={})
    scope.targets(manifest)
    output.mkdir(parents=True)
    for name, content in payloads.items():
        path = output / 'candidate' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    for name, content in {**publishers, 'release.py': raw(root, MODULE / 'deploy/release.py')}.items():
        # Frozen publisher hashes cover original bytes, including its recorded CRLF.
        (output / name).write_bytes(content)
    (output / 'candidate-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return dict(status='offline_candidate_not_published', release=scope.RELEASE, files=len(rows), manifest=manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--source-commit')
    args = parser.parse_args()
    baseline = json.loads(args.before.read_text(encoding='utf-8')) if args.before else None
    print(json.dumps(prepare(ROOT, args.output, baseline, args.source_commit), ensure_ascii=False, indent=2))
