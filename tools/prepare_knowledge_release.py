"""Prepare an offline immutable payload; never connect, publish or operate services."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'releases/fs-dashboard/knowledge-layering-20261023'
sys.path.insert(0, str(MODULE / 'source'))
from knowledge_catalog import select, validate


def git_bytes(root, path):
    return subprocess.check_output(['git', 'show', 'HEAD:' + path], cwd=root)


def prepare(root, output, commit):
    root, output = Path(root), Path(output)
    if output.exists():
        raise ValueError('stage_already_exists_reconcile_original')
    index = validate(json.loads((root / 'knowledge/index.json').read_text(encoding='utf-8')))
    raw = (root / 'knowledge/index.json').read_bytes().replace(b'\r\n', b'\n')
    ids = [r['id'] for r in index['entries'] if r['layer'] == 'current' and r['status'] == 'effective']
    chosen = select(root, 'knowledge/index.json', hashlib.sha256(raw).hexdigest(), ['FS', 'FC27'], ids, preview=True)
    if chosen['status'] != 'available_preview':
        raise ValueError('release_current_knowledge_unavailable')
    spec = importlib.util.spec_from_file_location('knowledge_release_scope', root / 'releases/fs-dashboard/knowledge-layering-20261023/deploy/release.py')
    scope = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scope)
    index.update(release=scope.RELEASE, release_state='published', source_commit=commit,
                 source_root='knowledge-releases/' + scope.RELEASE + '/sources')
    for row in index['entries']:
        if row.get('source_commit') is None:
            row['source_commit'] = commit
    payloads = {'artifact/index.json': (json.dumps(index, ensure_ascii=False, indent=2) + '\n').encode()}
    for row in index['entries']:
        if row['layer'] == 'candidate':
            continue
        name = row['source']['path']
        data = (root / name).read_bytes().replace(b'\r\n', b'\n')
        if hashlib.sha256(data).hexdigest() != row['source']['sha256']:
            raise ValueError('release_source_drift:' + name)
        payloads['artifact/sources/' + name] = data
    for name in scope.RUNTIME:
        payloads[name] = (root / 'releases/fs-dashboard/knowledge-layering-20261023/source' / Path(name).name).read_bytes().replace(b'\r\n', b'\n')
    rows = [dict(candidate=n, target=scope.RUNTIME.get(n, scope.PREFIX + n[len('artifact/'):]),
                 sha256=hashlib.sha256(data).hexdigest(), beforeSha256=None, owner='0:0', mode='0o644') for n,data in sorted(payloads.items())]
    # Deliberately non-executable until read-only preflight fills existing baselines/protected hashes.
    manifest = dict(schemaVersion=1, scope=scope.SCOPE, releaseReady=False, sourceCommit=commit,
                    businessWrites=False, timersChanged=False, files=rows, unchangedRequired=[], runtimeRequired={})
    scope.targets(manifest)
    output.mkdir(parents=True)
    for name, data in payloads.items():
        p = output / 'candidate' / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    copies = {
        'release.py': (root / 'releases/fs-dashboard/knowledge-layering-20261023/deploy/release.py').read_bytes().replace(b'\r\n', b'\n'),
        'release_adapter_base.py': git_bytes(root, 'releases/fs-dashboard/fs-business-baseline-20261021/deploy/release.py'),
        'release_navigation_base.py': git_bytes(root, 'releases/fs-dashboard/channel-effects-20261021/deploy/release_navigation_base.py')}
    for name, data in copies.items():
        (output / name).write_bytes(data)
    (output / 'candidate-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return dict(stage=str(output), status='offline_candidate_not_published', release=scope.RELEASE,
                source_commit=commit, payload_count=len(rows), manifest=manifest)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    commit = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    print(json.dumps(prepare(ROOT, a.output, commit), ensure_ascii=False, indent=2))
