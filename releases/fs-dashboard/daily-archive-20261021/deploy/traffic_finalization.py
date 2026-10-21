"""Traffic finalization read and next scheduler invocation; keep business reader running."""
from pathlib import Path
import subprocess
import release
SCOPE='fs-traffic-finalization-20261022'
TARGETS={'runtime/archive_jobs.py':'/opt/fs-exact-range-20261001/archive_jobs.py',
 'marketing/range_api.py':'/opt/mmoexp-marketing/custom-range/range_api.py',
 'skills/data-archive-first/SKILL.md':'/opt/fs-hermes-fc/data-archive-first.md'}
SOURCES={'runtime/archive_jobs.py':'source/archive_jobs.py','marketing/range_api.py':'source/marketing_range_api.py','skills/data-archive-first/SKILL.md':'skills/data-archive-first/SKILL.md'}


def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset()
    release.AUTHORIZED_TIMERS=frozenset()
    base=release.load_base();quiescent=base.hermes_quiescent
    def idle(root):
        quiescent(root)
        if str(root)!='/':return
        pid=subprocess.check_output(['systemctl','show','fs-marketing-range.service','--property=MainPID'],text=True,timeout=10).strip().split('=',1)[-1]
        if not pid.isdigit() or pid=='0':raise ValueError('marketing_runtime_not_mapped')
        if any(p.read_text().strip() for p in Path('/proc',pid,'task').glob('*/children')):raise ValueError('active_marketing_range_read')
    base.hermes_quiescent=idle
    def marketing_only(manifest,admission_fence=None):
        if admission_fence is None:raise ValueError('archive admission fence required')
        subprocess.run(['systemctl','restart','fs-marketing-range.service'],check=True,timeout=40)
    base.restart_for=marketing_only
    return base


if __name__=='__main__':load_base().main()
