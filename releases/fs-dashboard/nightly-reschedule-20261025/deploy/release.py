"""Narrow time/queue update through the unchanged original nightly publisher."""
import hashlib,json,types
from pathlib import Path
HERE=Path(__file__).resolve().parent
LEGACY=HERE.parents[1]/'nightly-pipeline-20261023/deploy/release.py'
LEGACY_SHA='9a49a8b19ddb0a76807d7239f3947ccdb06ac91bf85c115d7c278d0711eb568c'
SCOPE='nightly-reschedule-20261025'
TARGETS={
    'source/nightly.py':'/opt/fs-hermes-fc/nightly.py',
    'source/nightly_data.py':'/opt/fs-hermes-fc/nightly_data.py',
    'source/nightly_recovery_job.py':'/opt/fs-hermes-fc/nightly_recovery_job.py',
    'source/controller.py':'/opt/fs-hermes-fc/controller.py',
    'source/nightly_ops.py':'/opt/fs-hermes-ops/nightly_ops.py',
    'source/data-archive-first.md':'/opt/fs-hermes-fc/data-archive-first.md',
}

def load_base():
    raw=LEGACY.read_bytes().replace(b'\r\n',b'\n')
    if hashlib.sha256(raw).hexdigest()!=LEGACY_SHA:raise ValueError('original_nightly_publisher_changed')
    source=raw.decode('utf-8')
    anchor="HERE / 'release_navigation_base.py'"
    if source.count(anchor)!=2:raise ValueError('original_nightly_publisher_anchor_changed')
    source=source.replace(anchor,'FROZEN_BASE')
    read_anchor='raw = (FROZEN_BASE).read_bytes()'
    if source.count(read_anchor)!=1:raise ValueError('original_publisher_read_anchor_changed')
    source=source.replace(read_anchor,'raw = FROZEN_BYTES')
    old=types.ModuleType('original_nightly_publisher');old.__file__=str(LEGACY)
    old.FROZEN_BASE=LEGACY.with_name('release_navigation_base.py')
    # Restore the exact approved CRLF bytes after Git transport; the original SHA check stays intact.
    old.FROZEN_BYTES=old.FROZEN_BASE.read_bytes().replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
    exec(compile(source,str(LEGACY),'exec'),old.__dict__)
    old.HERE=HERE;old.SCOPE=SCOPE;old.TARGETS=TARGETS;old.NEW=set()
    return old.load_base()

if __name__=='__main__':load_base().main()
