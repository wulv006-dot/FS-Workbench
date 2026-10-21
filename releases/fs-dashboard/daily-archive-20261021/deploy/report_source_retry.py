"""Retry/report policy over the original locked publisher; no timer or pricing changes."""
from pathlib import Path
import subprocess
import release
SCOPE='fs-report-source-retry-20261022'
TARGETS={'runtime/archive_jobs.py':'/opt/fs-exact-range-20261001/archive_jobs.py',
 'hermes/source_snapshots.py':'/opt/fs-hermes-fc/source_snapshots.py',
 'hermes/nightly.py':'/opt/fs-hermes-fc/nightly.py',
 'skills/data-archive-first/SKILL.md':'/opt/fs-hermes-fc/data-archive-first.md'}
SOURCES={k:'skills/data-archive-first/SKILL.md' if k.startswith('skills/') else 'source/'+Path(k).name for k in TARGETS}

def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset()
    release.AUTHORIZED_TIMERS=frozenset()
    base=release.load_base();quiescent=base.hermes_quiescent;restart=base.restart_for
    def idle(root):
        quiescent(root)
        if str(root)!='/':return
        pid=subprocess.check_output(['systemctl','show','fs-business-range.service','--property=MainPID'],text=True,timeout=10).strip().split('=',1)[-1]
        if not pid.isdigit() or pid=='0':raise ValueError('business_runtime_not_mapped')
        if any(p.read_text().strip() for p in Path('/proc',pid,'task').glob('*/children')):raise ValueError('active_business_read')
    base.hermes_quiescent=idle
    def business_only(manifest,admission_fence=None):
        if admission_fence is None:raise ValueError('report source admission fence required')
        admission_fence.stop_then_unlock_database()
        restart(dict(manifest,scope=base.DEEP_SCOPE))
    base.restart_for=business_only
    return base

if __name__=='__main__':load_base().main()
