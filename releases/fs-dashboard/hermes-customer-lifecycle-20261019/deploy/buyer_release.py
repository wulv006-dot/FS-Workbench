"""Bind the existing navigation publisher to the active Buyer ID tracking files."""
import hashlib
import json
import os
import re
import sqlite3
import stat
import types
from contextlib import closing
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCOPE = 'customer-buyer-tracking-20261110'
BASE_SHA = '1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de'
TARGETS = {
    'source/tracking_source.py': '/opt/fs-hermes-fc/tracking_source.py',
    'source/customer_tracking.py': '/opt/fs-hermes-fc/customer_tracking.py',
    'source/page.js': '/var/lib/fs-navigation-formal-static/workspace-native-20261006-346f59eea565/page.js',
    'source/index.html': '/var/lib/fs-navigation-formal-static/workspace-native-20261006-346f59eea565/index.html',
}
BEFORE = {
    'source/tracking_source.py': '4544704459ab3681b0dd9ff2df692bfeb255ca66f4b15b4b71522c72ebc181db',
    'source/customer_tracking.py': 'a9ec5f24eae2e369aa6d0c05567e0db76cf349bfed7a44fabba87f8b27864094',
    'source/page.js': 'ba7cc477f63aa096685c8e85adc9f6721d9eac373e49ab96cccff2f96525a93a',
    'source/index.html': 'bcf5a1c906d1ab2075c96b5c09e158a2831858b64bf60727564637ce68cc4e8f',
}
AFTER = {
    'source/tracking_source.py': 'a811cb4a059eb5ca1cdf309925c2c9323b47f1cf24e1c86f4997e36bc2e79033',
    'source/customer_tracking.py': '9cd1feffda0bfcb85eb39adb2ff6783f3fa1d81fedc738cc0d0360612f764006',
    'source/page.js': 'dd2763ee5c34bb9e3349eaeb90718bed2e6e4458c33db04705ad6ef3c2ef38df',
    'source/index.html': '7c92e176c1ee8f7946bda98c510f72590db52854c52baefdf4e0f205ca1a9ce4',
}
OLD = Path('/opt/fs-release-stage/customer-pool-lifecycle-20261019/approved-manifest.json')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def prepare(stage, source_commit):
    if os.name != 'posix' or not re.fullmatch('[a-f0-9]{40}', source_commit):
        raise ValueError('linux_stage_and_source_commit_required')
    old = json.loads(OLD.read_text('utf-8'))
    rows = []
    for name, target in TARGETS.items():
        if sha(Path(target)) != BEFORE[name] or sha(stage/'candidate'/name) != AFTER[name]:
            raise ValueError('buyer_target_or_candidate_drift: '+name)
        info = Path(target).stat()
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (0, 0, 0o644):
            raise ValueError('buyer_target_owner_mode_drift: '+name)
        rows.append(dict(candidate=name, target=target, beforeSha256=BEFORE[name],
                         sha256=AFTER[name], owner='0:0', mode='0o644'))
    old_paths = {row['path'] for row in old['unchangedRequired']} | {row['target'] for row in old['files']}
    protected = [dict(path=path, sha256=sha(Path(path))) for path in sorted(old_paths-set(TARGETS.values()))
                 if Path(path).is_file()]
    old.update(scope=SCOPE, sourceCommit=source_commit, files=rows, unchangedRequired=protected,
               runtimeRequired={'fs-hermes-fc.service': {'ActiveState': 'active'},
                                'fs-business-range.service': {'ActiveState': 'active'}},
               businessWrites=False, timersChanged=False)
    payload=json.dumps(old, ensure_ascii=False, indent=2).encode()
    (stage/'approved-manifest.json').write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def load_base(stage=HERE):
    raw=(stage/'release_navigation_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=BASE_SHA:raise ValueError('frozen_publisher_drift')
    source=raw.decode('utf-8')
    anchor="HERMES_HISTORY_SCOPE='hermes-fc-history-pagination-20261014'"
    if source.count(anchor)!=1:raise ValueError('frozen_scope_anchor_drift')
    source=source.replace(anchor,"HERMES_HISTORY_SCOPE='"+SCOPE+"'")
    base=types.ModuleType('buyer_frozen_publisher')
    base.__file__=str(stage/'release_navigation_base.py')
    exec(compile(source,base.__file__,'exec'),base.__dict__)
    base.HERMES_HISTORY_TARGETS=TARGETS
    original_target=base.target_for
    base.target_for=lambda name: TARGETS[name] if name in TARGETS else original_target(name)
    base.expected_files=lambda manifest: set(TARGETS) if manifest.get('scope')==SCOPE else (_ for _ in ()).throw(ValueError('buyer_scope_only'))
    approved=json.loads((stage/'approved-manifest.json').read_text('utf-8'))
    original_validate=base.validate
    def validate(manifest,candidate_stage):
        if manifest!=approved or manifest.get('scope')!=SCOPE or {row['candidate']:row['target'] for row in manifest['files']}!=TARGETS:
            raise ValueError('exact_buyer_manifest_required')
        if any(row.get('beforeSha256')!=BEFORE[row['candidate']] or row.get('sha256')!=AFTER[row['candidate']]
               for row in manifest['files']):raise ValueError('buyer_file_hashes_changed')
        if manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False:
            raise ValueError('buyer_readonly_scope_required')
        return original_validate(manifest,candidate_stage)
    base.validate=validate
    original_quiescent=base.hermes_quiescent
    def quiescent(root):
        original_quiescent(root)
        path=base.rooted(root,'/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db')
        base.no_target_link(path)
        if path.is_file():
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
                if db.execute("SELECT count(*) FROM scan_jobs WHERE state='pending'").fetchone()[0]:
                    raise ValueError('tracking_scan_in_flight')
                if db.execute("SELECT count(*) FROM milestones WHERE state IN ('claimed','creating','dispatch_unknown','queued','running')").fetchone()[0]:
                    raise ValueError('tracking_milestone_in_flight')
    base.hermes_quiescent=quiescent
    return base


if __name__=='__main__':
    import sys
    if len(sys.argv)==3 and sys.argv[1]=='prepare':
        print(prepare(HERE,sys.argv[2]))
    else:
        load_base().main()
