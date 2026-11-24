"""Offline knowledgeOnly overlay for order email, shared Admin/ES or FC V6.1.

Input: snapshot/policy.json (raw deployed policy) and its complete catalog and
source_root trees mirrored relative to /var/lib/fs-hermes-fc/fs. Every referenced
catalog must be beneath knowledge-releases/, with an explicit source_root there.
Output must not exist. Sources/adapters come from --commit, never working files.
The caller verifies merged-main/CI and snapshot freshness separately; the manifest
always remains releaseReady=false until the lead's original-publisher preflight.
--shared-admin-es additionally takes the retained business-baseline.md and
preflight.json with captured_at, protected file hashes, service states and
existing immutable D5 release names. It performs no publish or service action.
--fc-v61 uses the same retained-baseline preflight and preserves route selections.
The 100K revision also updates the existing parameter and learning rule entries.
--fc-baseline-identity adds the explicit FC version to the direct baseline and preserves every selected catalog entry.
--fc-v61-reporting overlays the three report entries and the shared data-source
section against their previous Git bodies, retaining the current V6 pricing entries.
--email-only refreshes existing email entries and retains route selections and baseline.
"""
import argparse
import copy
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import types

ROOT = Path(__file__).resolve().parents[1]
MODULE = 'releases/fs-dashboard/knowledge-layering-20261023'
EMAIL = 'fs.orders.email_export'
OVERLAYS = (EMAIL, 'fs.data.sources')
SHARED_ADMIN_ES = 'fs-fc-admin-es-shared-20261113-r3'
SHARED_BASE_RELEASE = 'fs-fc-admin-es-shared-20261113-r2'
SHARED_BASE_COMMIT = '3110c1530ebc56a8cc51bcf56e3c2cb7d219ec49'
SHARED_OVERLAYS = ('fc.marketing.attribution', 'fc.reporting.data')
FC_V61 = 'fc-v61-average-discount-20261113-r1'
FC_V61_OVERLAYS = ('fc.pricing.constraints', 'fc.pricing.v3')
FC_V61_DISCOUNT_REVISION = 'fc_v6_d8_d2_amount_weighted_discount_v1'
FC_V61_TWO_BAND_REVISION = 'fc_v61_native_all_two_band_20261113'
FC_V61_100K_MARKET_REVISION = 'fc_v61_100k_market_two_band_20261113'
FC_V61_ADMIN_ONLY_REVISION = 'fc_v61_admin_only_two_band_20261113'
FC_V61_MARKET_ANCHOR_REVISION = 'fc_v61_market_anchor_20261117'
FC_V61_WEEKLY_REVISION = 'fc_v61_market_anchor_weekly_20261117'
FC_V61_INSURANCE_REVISION = 'fc_v61_insurance_15_40_20261117'
FC_V61_MARGIN_BAND_REVISION = 'fc_v61_margin_band_20261118'
FC_V61_MARGIN_BAND_BASE = 'b12cb55f9dc346dfb27980d53028f79579891bb4'
FC_V61_HOURLY_REVISION = 'fc_v61_margin_band_hourly_20261119'
FC_V61_HOURLY_BASE = '27fe0962a8b51fcfb64a415603101ece8097dff8'
FC_V61_CARNIVAL_REVISION = 'fc_v61_carnival_discount_20261119'
FC_V61_CARNIVAL_BASE = '9295063b2c1ee4bfb15c175ecba19253d808e99a'
MARKET_PREDECESSOR_MANIFEST_SHA = 'baad7565b53098d636eaf0901b0682800a048919face91aa5212cca6cc5f5d89'
FC_V61_MARKET_PACKAGES_REVISION = 'fc_v61_market_packages_observers_20261124'
FC_BASELINE_IDENTITY_LINE = '当前基准版本为 `business-baseline-fc-v6-20261124`。\n'.encode('utf-8')
FC_V61_PARAMETER_ID = 'fs.pricing.parameter-identity'
FC_V61_LEARNING_ID = 'fs.learning.methods'
FC_V61_MARGIN_BAND_IDS = (*FC_V61_OVERLAYS, FC_V61_PARAMETER_ID, FC_V61_LEARNING_ID,
                          'fc.reporting.business', 'fc.reporting.data')
FC_V61_HOURLY_IDS = (FC_V61_OVERLAYS[0], FC_V61_PARAMETER_ID)
FC_V61_MARGIN_BAND_SCOPES = {
    FC_V61_MARGIN_BAND_REVISION: (FC_V61_MARGIN_BAND_IDS, FC_V61_MARGIN_BAND_BASE),
    FC_V61_HOURLY_REVISION: (FC_V61_HOURLY_IDS, FC_V61_HOURLY_BASE),
    FC_V61_CARNIVAL_REVISION: ((FC_V61_OVERLAYS[0],), FC_V61_CARNIVAL_BASE),
    FC_V61_MARKET_PACKAGES_REVISION: ((*FC_V61_OVERLAYS, FC_V61_PARAMETER_ID, 'fc.reporting.business'),
                                      'e6981b3cb3916e944b007008bbb547d9d2d78e33'),
}
FC_V61_REPORTING_BASE_COMMIT = 'c51bb4f494523f19e6979cf5c85565dac94a4257'
FC_V61_REPORTING_REVISIONS = {
    'fc.reporting.business': '20261113-v61-reporting-business',
    'fc.reporting.data': '20261113-v61-reporting-data',
    'fc.reporting.methods': '20261113-v61-reporting-entry',
    'fs.data.sources': '20261113-v61-reporting-sources',
}
FS_RUNTIME_ROOT = '/var/lib/fs-hermes-fc/fs/'
BASELINE_TARGET = '/opt/fs-hermes-fc/business-baseline.md'
BASELINE_SOURCE = 'releases/fs-dashboard/fs-business-baseline-20261021/source/hermes/business-baseline.md'
PUBLISHER_IMAGE = 'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def relative(name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/'))):
        raise ValueError('unsafe_snapshot_path:' + str(name))
    return PurePosixPath(name)


def bound(root, name):
    path = root.joinpath(*relative(name).parts)
    for item in (path, *path.parents):
        info = item.lstat()
        if item.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('snapshot_link:' + str(item))
        if item == root:
            return path
    raise ValueError('snapshot_boundary')


def git_bytes(root, commit, name):
    return subprocess.check_output(['git', 'show', commit + ':' + name], cwd=root)


def pinned_module(root, commit, name):
    module = types.ModuleType(name)
    module.__file__ = str(root / name)
    exec(compile(git_bytes(root, commit, name), name, 'exec'), module.__dict__)
    return module


def routes(policy):
    yield from policy.get('requests', {}).values()
    yield from policy.get('task_routes', {}).get('routes', [])
    yield from policy.get('native', {}).get('routes', [])


def normalized(data, source):
    return data.replace(b'\r\n', b'\n') if source.get('hash_basis') == 'utf8_lf' else data


def contextual_changes(previous, current):
    old, new = (text.splitlines(keepends=True) for text in (previous, current))
    return [
        (''.join(old[group[0][1]:group[-1][2]]), ''.join(new[group[0][3]:group[-1][4]]))
        for group in difflib.SequenceMatcher(None, old, new, autojunk=False).get_grouped_opcodes(1)
    ]


def shared_changes(root, commit, catalog, canonical, current):
    if (canonical.get('release') != SHARED_ADMIN_ES or canonical.get('release_state') != 'candidate'
            or canonical.get('source_commit') is not None or canonical.get('base_commit') != SHARED_BASE_COMMIT):
        raise ValueError('exact_shared_admin_es_candidate_required')
    prior = json.loads(git_bytes(root, SHARED_BASE_COMMIT, 'knowledge/index.json'))
    if prior['release'] != SHARED_BASE_RELEASE:
        raise ValueError('shared_admin_es_base_release_invalid')
    changes = {}
    for identity, row in current.items():
        if row['revision'] != SHARED_ADMIN_ES:
            raise ValueError('shared_admin_es_revision_invalid:' + identity)
        previous = next(r for r in prior['entries'] if r['id'] == identity and r['layer'] == 'current')
        if previous['revision'] != SHARED_BASE_RELEASE:
            raise ValueError('shared_admin_es_base_revision_invalid:' + identity)
        selected = []
        for revision, template in ((SHARED_BASE_COMMIT, previous), (commit, row)):
            source = template['source']
            data = normalized(git_bytes(root, revision, source['path']), source)
            if sha(data) != source['sha256']:
                raise ValueError('canonical_source_changed:' + identity)
            selected.append(catalog.extract(data.decode('utf-8-sig'), source.get('selector')))
        changes[identity] = contextual_changes(*selected)
        if not changes[identity]:
            raise ValueError('shared_admin_es_delta_missing:' + identity)
    return changes


def merge_shared_entry(identity, template, row, content, changes):
    for old, new in changes[identity]:
        if content.count(old) != 1:
            raise ValueError('shared_admin_es_snapshot_merge_conflict:' + identity)
        content = content.replace(old, new, 1)
    data = (content.rstrip('\n') + '\n').encode('utf-8')
    source = template['source']
    row.update(revision=template['revision'], knowledge_updated_at=template.get('knowledge_updated_at', template['effective_at']),
               source=dict(path='overlay/' + template['revision'] + '/' + identity + '.md',
                           sha256=sha(data), hash_basis='utf8_lf',
                           canonical_path=source['path'], canonical_sha256=source['sha256']),
               provenance=row['provenance'] + template['provenance'],
               supersedes=list(dict.fromkeys(row['supersedes'] + template['supersedes'])))
    return data


def reporting_entry(identity, existing, template, previous, live_body, previous_body, current_body):
    if existing['revision'] != previous['revision'] or live_body.strip() != previous_body.strip():
        raise ValueError('fc_v61_reporting_snapshot_source_changed:' + identity)
    source = copy.deepcopy(template['source'])
    canonical_path = source['path']
    data = (current_body.rstrip('\n') + '\n').encode('utf-8')
    if source.pop('selector', None):
        source['canonical_sha256'] = source['sha256']
    source.update(sha256=sha(data), hash_basis='utf8_lf')
    source.update(path='overlay/' + template['revision'] + '/' + canonical_path,
                  canonical_path=canonical_path)
    return dict(existing, revision=template['revision'], effective_at=template['effective_at'],
                knowledge_updated_at=template.get('knowledge_updated_at'), source=source,
                provenance=existing['provenance'] + [ref for ref in template['provenance']
                                                     if ref not in existing['provenance']],
                supersedes=list(dict.fromkeys(existing['supersedes'] + template['supersedes']))), data


def shared_preflight(root, snapshot, commit, release, *, allow_baseline_patch=False, revision=None, retain_baseline=False):
    info = json.loads(bound(snapshot, 'preflight.json').read_bytes())
    if release in info['immutable_directories']:
        raise ValueError('shared_admin_es_release_already_exists_reconcile')
    baseline = bound(snapshot, 'business-baseline.md').read_bytes()
    digest = sha(baseline)
    units = {'fs-hermes-fc.service', 'fs-business-range.service'}
    if info['runtime'] != {name: {'ActiveState': 'active'} for name in units}:
        raise ValueError('shared_admin_es_active_services_required')
    if retain_baseline:
        if digest != info['protected'][BASELINE_TARGET]:
            raise ValueError('overlay_retained_baseline_hash')
        return info, {'retained_source_sha256': digest}
    proof = json.loads(git_bytes(root, commit, BASELINE_SOURCE.replace('.md', '.provenance.json')))
    candidate = git_bytes(root, commit, BASELINE_SOURCE)
    current_git = revision == FC_V61_MARKET_ANCHOR_REVISION and baseline == candidate
    retained = (digest == proof['after_sha256'] or current_git) and baseline == candidate
    patch = (allow_baseline_patch and digest == proof.get('before_sha256')
             and sha(candidate) == proof['after_sha256'] and candidate != baseline)
    if (digest != info['protected'][BASELINE_TARGET] or not (retained or patch)
            or proof['contract'] != 'fc-current-baseline-patch-v1' or proof['runtime_source'] != BASELINE_SOURCE
            or not re.fullmatch('[a-f0-9]{64}', proof['canonical_sha256'])):
        raise ValueError('shared_admin_es_retained_baseline_provenance_invalid')
    if current_git:
        proof = dict(proof, retained_current_git=True, retained_source_commit=commit, retained_source_sha256=digest)
    return info, proof


def reconcile_preceding_market_release(snapshot, preflight, policy_hash, baseline_proof):
    # This one predecessor installed the direct baseline while its policy kept the old binding.
    manifest_raw = bound(snapshot, 'previous-release/approved-manifest.json').read_bytes()
    manifest_hash = sha(manifest_raw)
    if manifest_hash != MARKET_PREDECESSOR_MANIFEST_SHA:
        raise ValueError('market_predecessor_manifest_changed')
    manifest = json.loads(manifest_raw)
    journal = json.loads(bound(snapshot, 'previous-release/journal.json').read_bytes())
    if (journal['approvedManifestSha256'] != manifest_hash or journal['manifest'] != manifest
            or journal['status'] != 'applied-awaiting-actual-http-role-acceptance'):
        raise ValueError('market_predecessor_journal_changed')
    expected = {row['target']: row['sha256'] for row in manifest['files']}
    written = {row['target']: row['sha256'] for row in journal['files'] if row.get('written') is True}
    observed = dict(preflight['protected'])
    observed[FS_RUNTIME_ROOT + 'knowledge-load-policy.json'] = policy_hash
    if (len(journal['files']) != len(expected) or written != expected
            or any(observed.get(path) != digest for path, digest in expected.items())):
        raise ValueError('market_predecessor_target_drift')
    patch = manifest['baselinePatch']
    previous = baseline_proof['previous_provenance']
    if (patch['after_sha256'] != expected[BASELINE_TARGET] or baseline_proof['before_sha256'] != patch['after_sha256']
            or (previous['before_sha256'], previous['after_sha256']) != (patch['before_sha256'], patch['after_sha256'])):
        raise ValueError('market_predecessor_baseline_drift')
    return {'mode': 'retain_full_baseline', 'sha256': patch['before_sha256']}


def verify_routes(catalog, mirror, snapshot, checks, shared_admin_es, current):
    for before, route in checks:
        selected = catalog.select(mirror, route['catalog'], route['sha256'], route['modules'], route.get('entry_ids'))
        if selected['status'] != 'available':
            raise ValueError('overlay_selection_unavailable')
        if shared_admin_es:
            original = catalog.select(snapshot, before['catalog'], before['sha256'], before['modules'],
                                      before.get('entry_ids'))
            old_entries = {r['id']: r for r in original['entries']}
            if original['status'] != 'available' or set(old_entries) != {r['id'] for r in selected['entries']}:
                raise ValueError('shared_admin_es_route_selection_changed')
            for row in selected['entries']:
                if row['id'] not in current:
                    old = old_entries[row['id']]
                    if (row['revision'], row['content_sha256']) != (old['revision'], old['content_sha256']):
                        raise ValueError('shared_admin_es_unrelated_selection_changed:' + row['id'])
        elif EMAIL not in [r['id'] for r in selected['entries']]:
            raise ValueError('overlay_selection_unavailable')


def write_payloads(root, payloads):
    for name, data in payloads.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def prepare(root, snapshot, output, commit, *, shared_admin_es=False, fc_v61=False,
            fc_v61_reporting=False, email_only=False, fc_baseline_identity=False):
    if sum((shared_admin_es, fc_v61, fc_v61_reporting, email_only, fc_baseline_identity)) > 1:
        raise ValueError('one_knowledge_overlay_scope_required')
    fc_overlay = fc_v61 or fc_v61_reporting or fc_baseline_identity
    preserve_routes = shared_admin_es or fc_overlay or email_only
    root, snapshot, output = Path(root).absolute(), Path(snapshot).absolute(), Path(output).absolute()
    if not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('full_source_commit_required')
    if output.exists() or output.is_symlink():
        raise ValueError('stage_already_exists_reconcile_original')
    if snapshot == output or snapshot in output.parents or output in snapshot.parents:
        raise ValueError('snapshot_output_overlap')
    catalog = pinned_module(root, commit, MODULE + '/source/knowledge_catalog.py')
    publisher = pinned_module(root, commit, MODULE + '/deploy/release.py')
    canonical = json.loads(git_bytes(root, commit, 'knowledge/index.json'))
    if fc_overlay and (canonical.get('release') != FC_V61 or canonical.get('release_state') != 'candidate'):
        raise ValueError('exact_fc_v61_candidate_required')
    current = {}
    overlay_ids = FC_V61_OVERLAYS if fc_v61 else SHARED_OVERLAYS if shared_admin_es else OVERLAYS
    if fc_baseline_identity:
        overlay_ids = ()
    if email_only:
        overlay_ids = (EMAIL,)
    if fc_v61_reporting:
        overlay_ids = tuple(FC_V61_REPORTING_REVISIONS)
    if fc_v61 and any(r['id'] == 'fc.pricing.v3' and r['revision'] == FC_V61_100K_MARKET_REVISION
                      for r in canonical['entries']):
        overlay_ids = (*FC_V61_OVERLAYS, FC_V61_PARAMETER_ID, FC_V61_LEARNING_ID)
    if fc_v61 and any(r['id'] == 'fc.pricing.v3' and r['revision'] in (FC_V61_WEEKLY_REVISION, FC_V61_INSURANCE_REVISION)
                      for r in canonical['entries']):
        overlay_ids = (*FC_V61_OVERLAYS, FC_V61_PARAMETER_ID, 'fs.procurement.inputs')
    constraints_revision = next((r['revision'] for r in canonical['entries']
                                 if r['id'] == FC_V61_OVERLAYS[0] and r['layer'] == 'current'
                                 and r['status'] == 'effective'), None)
    margin_band_scope = FC_V61_MARGIN_BAND_SCOPES.get(constraints_revision) if fc_v61 else None
    if margin_band_scope:
        overlay_ids, prior_commit = margin_band_scope
        prior_index = json.loads(git_bytes(root, prior_commit, 'knowledge/index.json'))
        margin_band_prior = {r['id']: r for r in prior_index['entries']
                             if r['id'] in overlay_ids and r['layer'] == 'current' and r['status'] == 'effective'}
        if set(margin_band_prior) != set(overlay_ids):
            raise ValueError('exact_margin_band_prior_entries_required')
        prior_bodies = {}
        for identity, prior in margin_band_prior.items():
            source = prior['source']
            data = normalized(git_bytes(root, prior_commit, source['path']), source)
            if sha(data) != source['sha256']:
                raise ValueError('margin_band_prior_source_changed:' + identity)
            prior_bodies[identity] = catalog.extract(data.decode('utf-8-sig'), source.get('selector'))
    for identity in overlay_ids:
        found = [r for r in canonical['entries'] if r['id'] == identity
                 and r['layer'] == 'current' and r['status'] == 'effective']
        if len(found) != 1:
            raise ValueError('canonical_current_required:' + identity)
        current[identity] = found[0]
    if margin_band_scope:
        if any(row['revision'] != constraints_revision for row in current.values()):
            raise ValueError('exact_margin_band_revisions_required')
    elif fc_v61:
        revision, full_revision = (current[identity]['revision'] for identity in FC_V61_OVERLAYS)
        revisions = (FC_V61_DISCOUNT_REVISION, FC_V61_TWO_BAND_REVISION,
                     FC_V61_100K_MARKET_REVISION, FC_V61_ADMIN_ONLY_REVISION, FC_V61_MARKET_ANCHOR_REVISION,
                     FC_V61_WEEKLY_REVISION, FC_V61_INSURANCE_REVISION)
        if revision not in revisions or full_revision != revision:
            raise ValueError('exact_fc_v61_revision_required')
        if any(identity in current and current[identity]['revision'] != revision
               for identity in (FC_V61_PARAMETER_ID, FC_V61_LEARNING_ID)):
            raise ValueError('exact_fc_v61_parameter_revision_required')
    if fc_v61_reporting:
        if {identity: row['revision'] for identity, row in current.items()} != FC_V61_REPORTING_REVISIONS:
            raise ValueError('exact_fc_v61_reporting_revisions_required')
        prior_index = json.loads(git_bytes(root, FC_V61_REPORTING_BASE_COMMIT, 'knowledge/index.json'))
        reporting_prior = {row['id']: row for row in prior_index['entries']
                           if row['id'] in overlay_ids and row['layer'] == 'current' and row['status'] == 'effective'}
        if set(reporting_prior) != set(overlay_ids):
            raise ValueError('exact_fc_v61_reporting_prior_required')
        previous_bodies = {}
        for identity, row in reporting_prior.items():
            source = row['source']
            data = normalized(git_bytes(root, FC_V61_REPORTING_BASE_COMMIT, source['path']), source)
            if sha(data) != source['sha256']:
                raise ValueError('fc_v61_reporting_prior_source_changed:' + identity)
            previous_bodies[identity] = catalog.extract(data.decode('utf-8-sig'), source.get('selector'))
    policy_raw = bound(snapshot, 'policy.json').read_bytes()
    policy = json.loads(policy_raw)
    if policy.get('contract') != 'fs-knowledge-load-policy-v1':
        raise ValueError('knowledge_policy_contract')
    all_routes = list(routes(policy))
    if not all_routes:
        raise ValueError('snapshot_routes_required')
    release = (FC_V61 + '-' + commit if fc_overlay else SHARED_ADMIN_ES + '-' + commit
               if shared_admin_es else 'fc-reporting-knowledge-20261105-' + commit[:8])
    if shared_admin_es:
        changes = shared_changes(root, commit, catalog, canonical, current)
    carnival = fc_v61 and constraints_revision == FC_V61_CARNIVAL_REVISION
    retain_baseline = email_only or carnival
    if preserve_routes:
        preflight, baseline_proof = shared_preflight(root, snapshot, commit, release,
            allow_baseline_patch=fc_baseline_identity or fc_v61 and FC_V61_PARAMETER_ID in current,
            revision=constraints_revision if fc_v61 else None, retain_baseline=retain_baseline)
        if fc_baseline_identity:
            before = bound(snapshot, 'business-baseline.md').read_bytes()
            heading, separator, body = before.partition(b'\n')
            candidate = git_bytes(root, commit, BASELINE_SOURCE)
            if (not separator or FC_BASELINE_IDENTITY_LINE in before
                    or heading + b'\n\n' + FC_BASELINE_IDENTITY_LINE + body != candidate):
                raise ValueError('fc_baseline_identity_content_changed')
        compatibility = {'mode': 'retain_full_baseline', 'sha256': preflight['protected'][BASELINE_TARGET]}
        if any(r.get('baseline_compatibility', compatibility) != compatibility for r in all_routes):
            if fc_v61 and constraints_revision == FC_V61_MARKET_PACKAGES_REVISION:
                preceding = reconcile_preceding_market_release(snapshot, preflight, sha(policy_raw), baseline_proof)
                if any(r.get('baseline_compatibility', compatibility) not in (preceding, compatibility) for r in all_routes):
                    raise ValueError('shared_admin_es_baseline_binding_drift')
                baseline_proof['reconciled_previous_manifest_sha256'] = MARKET_PREDECESSOR_MANIFEST_SHA
            elif not (fc_v61 and baseline_proof.get('retained_current_git') and all(
                    r.get('baseline_compatibility', compatibility).get('mode') == 'retain_full_baseline'
                    and re.fullmatch('[a-f0-9]{64}', r.get('baseline_compatibility', compatibility).get('sha256', ''))
                    for r in all_routes)):
                raise ValueError('shared_admin_es_baseline_binding_drift')
            baseline_proof['previous_route_baselines'] = [copy.deepcopy(r.get('baseline_compatibility')) for r in all_routes]
            for route in all_routes:
                if 'baseline_compatibility' in route:
                    route['baseline_compatibility'] = copy.deepcopy(compatibility)
    release_root = 'knowledge-releases/' + release
    payloads, remap, checks = {}, {}, []
    shared_rows = []
    for route in all_routes:
        old_name = route['catalog']
        relative(old_name)
        if not old_name.startswith('knowledge-releases/'):
            raise ValueError('snapshot_release_boundary')
        if old_name in remap:
            if route['sha256'] != remap[old_name][2]:
                raise ValueError('snapshot_catalog_hash_conflict')
            continue
        raw = bound(snapshot, old_name).read_bytes()
        if sha(raw) != route['sha256']:
            raise ValueError('snapshot_catalog_changed:' + old_name)
        index = catalog.validate(json.loads(raw))
        if preserve_routes and (index['release_state'] != 'published'
                or preflight['protected'].get(FS_RUNTIME_ROOT + old_name) != sha(raw)):
            raise ValueError('shared_admin_es_catalog_cas_invalid:' + old_name)
        source_root = index.get('source_root', '')
        relative(source_root)
        if not source_root.startswith('knowledge-releases/'):
            raise ValueError('snapshot_source_root_boundary')
        # Preserve each catalog independently: FC patches need not match each other.
        slot = '' if not remap else 'catalog-' + str(len(remap)) + '/'
        new_name = slot + 'index.json'
        sources = slot + 'sources/'
        old_tree = bound(snapshot, source_root)
        if not old_tree.is_dir():
            raise ValueError('snapshot_source_tree_required')
        for directory, dirs, files in os.walk(old_tree, followlinks=False):
            for name in dirs + files:
                item = Path(directory) / name
                rel = item.relative_to(snapshot).as_posix()
                safe = bound(snapshot, rel)
                if safe.is_file():
                    data = safe.read_bytes()
                    if preserve_routes and preflight['protected'].get(FS_RUNTIME_ROOT + rel) != sha(data):
                        raise ValueError('shared_admin_es_source_cas_invalid:' + rel)
                    payloads['artifact/' + sources + item.relative_to(old_tree).as_posix()] = data
        for row in index['entries']:
            # Deployed candidate rows may have no artifact; they are never selected.
            if row['layer'] == 'candidate':
                continue
            source = row['source']
            data = bound(snapshot, source_root + '/' + source['path']).read_bytes()
            source_data = normalized(data, source)
            if sha(source_data) != source['sha256']:
                raise ValueError('snapshot_source_changed:' + row['id'])
            catalog.extract(source_data.decode('utf-8-sig'), source.get('selector'))
        payloads['artifact/originals/' + (slot or 'root/') + 'index.json'] = raw
        for identity, template in current.items():
            existing = [r for r in index['entries'] if r['id'] == identity and r['layer'] == 'current']
            if len(existing) > 1 or any(r['status'] != 'effective' for r in existing):
                raise ValueError('snapshot_current_conflict:' + identity)
            if (fc_overlay or email_only) and not existing:
                continue
            if margin_band_scope:
                live = existing[0]
                source = live['source']
                data = normalized(payloads['artifact/' + sources + source['path']], source)
                live_body = catalog.extract(data.decode('utf-8-sig'), source.get('selector'))
                package_constraint = (constraints_revision == FC_V61_MARKET_PACKAGES_REVISION
                                      and identity == 'fc.pricing.constraints' and live_body != prior_bodies[identity])
                if (live['revision'] != margin_band_prior[identity]['revision']
                        or not (carnival or package_constraint) and live_body != prior_bodies[identity]):
                    raise ValueError('margin_band_live_entry_changed:' + identity)
            if shared_admin_es:
                if not existing:
                    continue
                if existing[0]['revision'] != SHARED_BASE_RELEASE:
                    raise ValueError('shared_admin_es_snapshot_revision_invalid:' + identity)
                row = copy.deepcopy(existing[0])
                original_source = existing[0]['source']
                body = payloads['artifact/' + sources + original_source['path']]
                content = catalog.extract(normalized(body, original_source).decode('utf-8-sig'),
                                          original_source.get('selector'))
                data = merge_shared_entry(identity, template, row, content, changes)
                shared_rows.append(dict(catalog=old_name, id=identity, previous_revision=existing[0]['revision'],
                                        previous_source_sha256=original_source['sha256'], revision=row['revision'],
                                        source_sha256=row['source']['sha256']))
            else:
                row = copy.deepcopy(template)
                source = row['source']
                canonical_path = source['path']
                data = git_bytes(root, commit, canonical_path)
                source_data = normalized(data, source)
                if sha(source_data) != source['sha256']:
                    raise ValueError('canonical_source_changed:' + identity)
                content = catalog.extract(source_data.decode('utf-8-sig'), source.get('selector'))
                overlay_root = 'overlay/'
                if email_only:
                    overlay_root += row['revision'] + '/'
                if fc_v61 and (margin_band_scope or row['revision'] in (
                        FC_V61_TWO_BAND_REVISION, FC_V61_100K_MARKET_REVISION, FC_V61_ADMIN_ONLY_REVISION,
                        FC_V61_MARKET_ANCHOR_REVISION, FC_V61_WEEKLY_REVISION, FC_V61_INSURANCE_REVISION)):
                    # Retain the preceding snapshot's source at its original path.
                    overlay_root += row['revision'] + '/'
                if carnival or margin_band_scope and package_constraint:
                    delta = contextual_changes(prior_bodies[identity], content)
                    if carnival and (len(delta) != 1 or not delta[0][0] or 'margin_band.promotion_guard' not in delta[0][1]):
                        raise ValueError('carnival_constraints_delta_invalid')
                    row = copy.deepcopy(existing[0])
                    row['effective_at'] = template['effective_at']
                    data = merge_shared_entry(identity, template, row, live_body, {identity: delta})
                elif fc_v61_reporting:
                    previous_source = existing[0]['source']
                    previous_data = payloads['artifact/' + sources + previous_source['path']]
                    live_body = catalog.extract(normalized(previous_data, previous_source).decode('utf-8-sig'),
                                                previous_source.get('selector'))
                    row, data = reporting_entry(identity, existing[0], template, reporting_prior[identity],
                                                live_body, previous_bodies[identity], content)
                else:
                    source.update(path=overlay_root + canonical_path, canonical_path=canonical_path)
                if fc_overlay or email_only:
                    shared_rows.append(dict(catalog=old_name, id=identity, previous_revision=existing[0]['revision'],
                                            previous_source_sha256=existing[0]['source']['sha256'],
                                            revision=row['revision'], source_sha256=row['source']['sha256']))
            key = 'artifact/' + sources + row['source']['path']
            if key in payloads and payloads[key] != data:
                raise ValueError('overlay_path_collision')
            payloads[key] = data
            row['source_commit'] = commit
            if existing:
                row['supersedes'] = list(dict.fromkeys(row['supersedes'] + [identity + '@' + existing[0]['revision']]))
                index['entries'][index['entries'].index(existing[0])] = row
            else:
                index['entries'].append(row)
        index.update(release=release, release_state='published', source_commit=commit,
                     source_root=release_root + '/' + sources.rstrip('/'))
        catalog.validate(index)
        data = encoded(index)
        payloads['artifact/' + new_name] = data
        remap[old_name] = (release_root + '/' + new_name, sha(data), route['sha256'])
    for route in all_routes:
        before = copy.deepcopy(route)
        route['catalog'], route['sha256'], _ = remap[route['catalog']]
        if not preserve_routes and 'entry_ids' in route and EMAIL not in route['entry_ids']:
            route['entry_ids'].append(EMAIL)
        checks.append((before, copy.deepcopy(route)))
    payloads['runtime/knowledge-load-policy.json'] = encoded(policy)
    payloads['artifact/originals/policy.json'] = policy_raw
    baseline_patch = None
    if (preserve_routes and not retain_baseline and not baseline_proof.get('retained_current_git')
            and baseline_proof['after_sha256'] != preflight['protected'][BASELINE_TARGET]):
        before_digest = preflight['protected'][BASELINE_TARGET]
        baseline_patch = dict(contract='fc-v61-current-baseline-patch-v1',
                              before_sha256=before_digest, after_sha256=baseline_proof['after_sha256'])
        payloads['runtime/business-baseline.md'] = git_bytes(root, commit, BASELINE_SOURCE)
        payloads['artifact/originals/business-baseline.md'] = bound(snapshot, 'business-baseline.md').read_bytes()
        for route in all_routes:
            if 'baseline_compatibility' in route:
                route['baseline_compatibility']['sha256'] = baseline_proof['after_sha256']
        payloads['runtime/knowledge-load-policy.json'] = encoded(policy)
    prefix = '/var/lib/fs-hermes-fc/fs/' + release_root + '/'
    manifest = dict(schemaVersion=1, scope=publisher.SCOPE, knowledgeOnly=True,
                    knowledgeRelease=release, sourceCommit=commit, releaseReady=False,
                    businessWrites=False, timersChanged=False, unchangedRequired=[], runtimeRequired={},
                    files=[dict(candidate=name, target=(BASELINE_TARGET if name == 'runtime/business-baseline.md'
                           else '/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json'
                           if name.startswith('runtime/') else prefix + name[len('artifact/'):]),
                           sha256=sha(data), beforeSha256=None, owner='0:0', mode='0o644')
                           for name, data in sorted(payloads.items())])
    if baseline_patch:
        manifest['baselinePatch'] = baseline_patch
        next(r for r in manifest['files'] if r['candidate'] == 'runtime/business-baseline.md')['beforeSha256'] = baseline_patch['before_sha256']
    if preserve_routes:
        if shared_admin_es and {row['id'] for row in shared_rows} != set(SHARED_OVERLAYS):
            raise ValueError('shared_admin_es_overlay_inventory_invalid')
        if fc_overlay and {row['id'] for row in shared_rows} != set(overlay_ids):
            raise ValueError('fc_v61_existing_overlay_inventory_required')
        if email_only and not shared_rows:
            raise ValueError('email_overlay_existing_entry_required')
        policy_row = next(row for row in manifest['files'] if row['candidate'] == 'runtime/knowledge-load-policy.json')
        policy_row['beforeSha256'] = sha(policy_raw)
        manifest.update(imageId=PUBLISHER_IMAGE, runtimeRequired=preflight['runtime'],
                        unchangedRequired=[dict(path=path, sha256=digest)
                                           for path, digest in sorted(preflight['protected'].items())
                                           if not (baseline_patch and path == BASELINE_TARGET)])
    publisher.targets(manifest)
    adapters = {'release.py': MODULE + '/deploy/release.py',
                'release_adapter_base.py': 'releases/fs-dashboard/fs-business-baseline-20261021/deploy/release.py',
                'release_navigation_base.py': 'releases/fs-dashboard/channel-effects-20261021/deploy/release_navigation_base.py'}
    copies = {name: git_bytes(root, commit, path) for name, path in adapters.items()}
    # select() resolves source_root from the fs root, NOT from the catalog directory.
    # Use a separate local validation mirror with the exact deployed relative paths.
    mirror_payloads = {release_root + '/' + name[len('artifact/'):]: data for name, data in payloads.items()
                       if name.startswith('artifact/')}
    with tempfile.TemporaryDirectory(prefix='kl-') as folder:
        mirror = Path(folder)
        write_payloads(mirror, mirror_payloads)
        verify_routes(catalog, mirror, snapshot, checks, preserve_routes, current)
    output.mkdir(parents=True)
    write_payloads(output / 'candidate', payloads)
    if not preserve_routes:
        write_payloads(output / 'validation-fs-root', mirror_payloads)
    for name, data in copies.items():
        (output / name).write_bytes(data)
    (output / 'candidate-manifest.json').write_bytes(encoded(manifest))
    if preserve_routes:
        (output / 'retained-baseline-provenance.json').write_bytes(encoded(dict(
            observed_at=preflight['captured_at'], target=BASELINE_TARGET,
            retained_sha256=preflight['protected'][BASELINE_TARGET], existing_provenance=baseline_proof,
            overlays=shared_rows)))
    return dict(status='offline_candidate_not_published', release=release, stage=str(output),
                catalog_count=len(remap), manifest=manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--commit', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--shared-admin-es', action='store_true')
    mode.add_argument('--fc-v61', action='store_true')
    mode.add_argument('--fc-v61-reporting', action='store_true')
    mode.add_argument('--email-only', action='store_true')
    mode.add_argument('--fc-baseline-identity', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(ROOT, args.snapshot, args.output, args.commit,
                             shared_admin_es=args.shared_admin_es, fc_v61=args.fc_v61,
                             fc_v61_reporting=args.fc_v61_reporting, email_only=args.email_only,
                             fc_baseline_identity=args.fc_baseline_identity),
                     ensure_ascii=False, indent=2))
