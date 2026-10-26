"""Prepare the V3 immutable knowledge artifact offline from the merged Git sources."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

from release import PREFIX, RELEASE


def lf(path):
    return path.read_bytes().replace(b'\r\n', b'\n')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def build(checkout, source_commit, output):
    checkout = Path(checkout).resolve()
    if not re.fullmatch('[a-f0-9]{40}', source_commit):
        raise ValueError('merged_source_commit_required')
    raw_index = lf(checkout / 'knowledge/index.json')
    index = json.loads(raw_index)
    if index.get('contract') != 'fs-knowledge-index-v1' or index.get('release_state') != 'candidate' or \
            index.get('source_commit') is not None or len(index.get('entries', [])) != 25:
        raise ValueError('exact_v3_candidate_index_required')
    current = {row['id'] for row in index['entries'] if row['layer'] == 'current' and row['status'] == 'effective'}
    if len(current) != 14 or 'fc.pricing.v3' not in current or 'fc.pricing.reference-weighting' in current:
        raise ValueError('v3_current_knowledge_selection_invalid')
    published = copy.deepcopy(index)
    published.update(release=RELEASE, release_state='published', source_commit=source_commit,
                     source_root='knowledge-releases/' + RELEASE + '/sources')
    payloads = {}
    for row in published['entries']:
        if row.get('source_commit') is None:
            row['source_commit'] = source_commit
        if row['layer'] == 'candidate':
            continue
        relative = row['source']['path']
        if Path(relative).is_absolute() or '..' in Path(relative).parts or '\\' in relative:
            raise ValueError('source_path_escaped_git_root')
        data = lf(checkout / relative)
        if sha(data) != row['source']['sha256']:
            raise ValueError('source_sha_mismatch:' + relative)
        payloads['artifact/sources/' + relative] = data
    index_bytes = (json.dumps(published, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    payloads['artifact/index.json'] = index_bytes
    baseline = lf(checkout / 'docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md')
    if sha(baseline) != '7b3ca86691a3671c55b7a6095d6bd77253fed4125a6885caddd08a1c5933331e':
        raise ValueError('approved_full_baseline_sha_mismatch')
    payloads['runtime/business-baseline.md'] = baseline
    with tempfile.TemporaryDirectory(prefix='fc-v3-knowledge-') as temporary:
        stage = Path(temporary) / RELEASE
        for name, data in payloads.items():
            path = stage / 'candidate' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        deployment = stage / 'deploy'
        deployment.mkdir()
        for name in ('release.py', 'prepare_manifest.py', 'release_navigation_base.py'):
            shutil.copyfile(Path(__file__).parent / name, deployment / name)
        manifest = dict(sourceCommit=source_commit, catalogSha256=sha(index_bytes),
                        payloadSha256={name: sha(data) for name, data in sorted(payloads.items())})
        (stage / 'source-manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        output = Path(output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output, 'w:gz') as bundle:
            bundle.add(stage, arcname=stage.name)
    return dict(archive=str(output), sha256=sha(output.read_bytes()), release=RELEASE,
                sourceCommit=source_commit, catalogSha256=sha(index_bytes), files=len(payloads))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('checkout')
    parser.add_argument('source_commit')
    parser.add_argument('output')
    args = parser.parse_args()
    print(json.dumps(build(args.checkout, args.source_commit, args.output), sort_keys=True))
