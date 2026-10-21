"""Fixed business history and five-day traffic correction, without schedule changes."""
from pathlib import Path
import subprocess
import release
SCOPE='fs-data-maturity-20261022'
TARGETS={
 'runtime/live_summary.py':'/opt/fs-exact-range-20261001/live_summary.py',
 'runtime/range_api.py':'/opt/fs-exact-range-20261001/range_api.py',
 'runtime/profit_queries.py':'/opt/fs-exact-range-20261001/profit_queries.py',
 'runtime/archive_jobs.py':'/opt/fs-exact-range-20261001/archive_jobs.py',
 'marketing/range_api.py':'/opt/mmoexp-marketing/custom-range/range_api.py',
 'channel/channel_effects.py':'/opt/fs-hermes-fc/channel_effects.py',
 'channel/channel_cache.py':'/opt/fs-hermes-fc/channel_cache.py',
 'skills/data-archive-first/SKILL.md':'/opt/fs-hermes-fc/data-archive-first.md'}
SOURCES={k:('skills/data-archive-first/SKILL.md' if k.startswith('skills/') else 'source/marketing_range_api.py' if k=='marketing/range_api.py' else 'source/'+Path(k).name) for k in TARGETS}


def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset()
    release.AUTHORIZED_TIMERS=frozenset()
    base=release.load_base();restart=base.restart_for;quiescent=base.hermes_quiescent
    def idle(root):
        quiescent(root)
        if str(root)!='/':return
        for unit in ('fs-business-range.service','fs-marketing-range.service'):
            pid=subprocess.check_output(['systemctl','show',unit,'--property=MainPID'],text=True,timeout=10).strip().split('=',1)[-1]
            if not pid.isdigit() or pid=='0':raise ValueError('archive_runtime_not_mapped')
            if any(p.read_text().strip() for p in Path('/proc',pid,'task').glob('*/children')):raise ValueError('active_native_or_marketing_read')
    base.hermes_quiescent=idle
    def reload_readers(manifest,admission_fence=None):
        restart(manifest,admission_fence)
        if manifest.get('scope')==SCOPE:subprocess.run(['systemctl','restart','fs-marketing-range.service'],check=True,timeout=40)
    base.restart_for=reload_readers
    return base


if __name__=='__main__':load_base().main()
