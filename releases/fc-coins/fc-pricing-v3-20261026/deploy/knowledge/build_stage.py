"""Prepare the V3 immutable knowledge artifact offline from the merged Git sources."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

from release import release_identity

BASELINE_SOURCE='releases/fs-dashboard/fs-business-baseline-20261021/source/hermes/business-baseline.md'


def blob(checkout, path):
    relative = path.relative_to(checkout).as_posix()
    return subprocess.check_output(['git', 'show', 'HEAD:' + relative], cwd=checkout)


def canonical_source(checkout, path):
    # The catalog pins LF-normalized Markdown, including legacy Git -text files.
    return blob(checkout, path).replace(b'\r\n', b'\n')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def build(checkout, source_commit, output):
    checkout = Path(checkout).resolve()
    if not re.fullmatch('[a-f0-9]{40}', source_commit):
        raise ValueError('merged_source_commit_required')
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout, text=True).strip() != source_commit:
        raise ValueError('source_commit_must_match_checkout')
    release,_=release_identity(source_commit)
    raw_index = blob(checkout, checkout / 'knowledge/index.json')
    index = json.loads(raw_index)
    if index.get('contract') != 'fs-knowledge-index-v1' or index.get('release_state') != 'candidate' or \
            index.get('source_commit') is not None or index.get('release')!='fc-three-platform-100k-20261110' or \
            len([row for row in index.get('entries', []) if row.get('layer')!='candidate']) != 25:
        raise ValueError('exact_v3_candidate_index_required')
    current_rows = [row['id'] for row in index['entries'] if row['layer'] == 'current' and row['status'] == 'effective']
    current = set(current_rows)
    expected_current = {'fs.data.sources','fs.data.currency','fs.customer.identity','fs.finance.procurement',
        'fc.pricing.constraints','fc.marketing.attribution','fs.procurement.inputs','fs.pricing.parameter-identity',
        'fs.product.identity','fs.customer.lifecycle','fs.learning.methods','fs.project.execution',
        'fs.dashboard.shipping-profit','fc.pricing.v3','fc.reporting.methods','fc.reporting.data',
        'fc.reporting.report','fc.reporting.business','fc.reporting.maintenance'}
    if len(current_rows) != len(expected_current) or current != expected_current:
        raise ValueError('v3_current_knowledge_selection_invalid')
    expected_other={'fs.experience.archive-cycle','fc.history.natural-1821','fs.decision.pmax-authority-20261023',
        'fs.decision.aion2-distribution-20261023','fc.pricing.decision.three-platform-100k','fc.pricing.experience.platform-discount'}
    effective=[row['id'] for row in index['entries'] if row['layer']!='candidate']
    if len(effective)!=len(set(effective)) or set(effective)!=expected_current|expected_other:
        raise ValueError('v3_effective_knowledge_selection_invalid')
    revisions={'fc.pricing.constraints':'fc27_dual20_d9_d2_platform_100k_v4',
        'fc.pricing.v3':'20261110-three-platform-100k','fs.pricing.parameter-identity':'20261110-three-platform-100k',
        'fs.learning.methods':'20261110-three-platform-100k','fc.reporting.business':'20261110-three-platform-100k',
        'fc.pricing.decision.three-platform-100k':'20261110-1','fc.pricing.experience.platform-discount':'20261110-1'}
    if any(next(row for row in index['entries'] if row['id']==identity)['revision']!=revision for identity,revision in revisions.items()):
        raise ValueError('v3_current_knowledge_revision_invalid')
    published = copy.deepcopy(index)
    published.update(release=release, release_state='published', source_commit=source_commit,
                     source_root='knowledge-releases/' + release + '/sources')
    payloads = {}
    for row in published['entries']:
        if row.get('source_commit') is None:
            row['source_commit'] = source_commit
        if row['layer'] == 'candidate':
            continue
        relative = row['source']['path']
        if Path(relative).is_absolute() or '..' in Path(relative).parts or '\\' in relative:
            raise ValueError('source_path_escaped_git_root')
        data = canonical_source(checkout, checkout / relative)
        if sha(data) != row['source']['sha256']:
            raise ValueError('source_sha_mismatch:' + relative)
        payloads['artifact/sources/' + relative] = data
    index_bytes = (json.dumps(published, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    payloads['artifact/index.json'] = index_bytes
    canonical = canonical_source(checkout, checkout / 'docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md')
    baseline_hashes = {row['source']['sha256'] for row in published['entries']
                       if row['source']['path'] == 'docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md'}
    if baseline_hashes != {sha(canonical)}:
        raise ValueError('approved_full_baseline_sha_mismatch')
    baseline=blob(checkout,checkout/BASELINE_SOURCE)
    provenance=json.loads(blob(checkout,checkout/BASELINE_SOURCE.replace('.md','.provenance.json')))
    if (provenance.get('contract')!='fc-current-baseline-patch-v1' or
            provenance.get('canonical_sha256')!=sha(canonical) or
            provenance.get('runtime_source')!=BASELINE_SOURCE or provenance.get('after_sha256')!=sha(baseline)):
        raise ValueError('runtime_baseline_patch_provenance_invalid')
    payloads['runtime/business-baseline.md'] = baseline
    with tempfile.TemporaryDirectory(prefix='fc-v3-knowledge-') as temporary:
        stage = Path(temporary) / release
        for name, data in payloads.items():
            path = stage / 'candidate' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        deployment = stage / 'deploy'
        deployment.mkdir()
        for name in ('release.py', 'prepare_manifest.py', 'release_navigation_base.py'):
            (deployment / name).write_bytes(blob(checkout, checkout / 'releases/fc-coins/fc-pricing-v3-20261026/deploy/knowledge' / name))
        (deployment/'release_readiness.py').write_bytes(blob(checkout,checkout/'releases/fc-coins/fc-pricing-v3-20261026/deploy/release_readiness.py'))
        manifest = dict(sourceCommit=source_commit, knowledgeRelease=release,catalogSha256=sha(index_bytes),
                        payloadSha256={name: sha(data) for name, data in sorted(payloads.items())})
        (stage / 'source-manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        output = Path(output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output, 'w:gz') as bundle:
            bundle.add(stage, arcname=stage.name)
    return dict(archive=str(output), sha256=sha(output.read_bytes()), release=release,
                sourceCommit=source_commit, catalogSha256=sha(index_bytes), files=len(payloads))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('checkout')
    parser.add_argument('source_commit')
    parser.add_argument('output')
    args = parser.parse_args()
    print(json.dumps(build(args.checkout, args.source_commit, args.output), sort_keys=True))
