"""Prepare one approved baseline digest update; preserve all policy bytes and bindings."""
import json
import re


def candidate(raw, old_hash, new_hash):
    if not all(re.fullmatch('[a-f0-9]{64}', value) for value in (old_hash, new_hash)) or old_hash == new_hash:
        raise ValueError('baseline_digest_delta_invalid')
    policy = json.loads(raw)
    routes = policy.get('task_routes', {}).get('routes', [])
    matching = [r for r in routes if r.get('baseline_compatibility', {}).get('sha256') == old_hash]
    if (policy.get('contract') != 'fs-knowledge-load-policy-v1' or len(matching) != 1
            or matching[0].get('owner') != 'wulv' or matching[0].get('project') != 'FS'
            or matching[0].get('channel') != 'fs'
            or matching[0]['baseline_compatibility'].get('mode') != 'retain_full_baseline'
            or raw.count(old_hash.encode()) != 1):
        raise ValueError('exact_existing_fs_baseline_binding_required')
    result = raw.replace(old_hash.encode(), new_hash.encode(), 1)
    expected = json.loads(raw)
    selected = next(r for r in expected['task_routes']['routes'] if r.get('baseline_compatibility', {}).get('sha256') == old_hash)
    selected['baseline_compatibility']['sha256'] = new_hash
    if json.loads(result) != expected:
        raise ValueError('baseline_policy_unrelated_delta')
    return result
