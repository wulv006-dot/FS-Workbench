"""Exact archive scope over the existing locked CAS/backup/rollback publisher."""
from pathlib import Path
import subprocess
import release

SCOPE='fs-daily-archive-20261021'
TARGETS={
 'runtime/daily_archive.py':'/opt/fs-exact-range-20261001/daily_archive.py',
 'hermes/daily_archive.py':'/opt/fs-hermes-fc/daily_archive.py',
 'marketing/daily_archive.py':'/opt/mmoexp-marketing/custom-range/daily_archive.py',
 'runtime/archive_jobs.py':'/opt/fs-exact-range-20261001/archive_jobs.py',
 'runtime/live_summary.py':'/opt/fs-exact-range-20261001/live_summary.py',
 'runtime/range_api.py':'/opt/fs-exact-range-20261001/range_api.py',
 'runtime/profit_queries.py':'/opt/fs-exact-range-20261001/profit_queries.py',
 'hermes/source_snapshots.py':'/opt/fs-hermes-fc/source_snapshots.py',
 'hermes/business_context.py':'/opt/fs-hermes-fc/business_context.py',
 'marketing/range_api.py':'/opt/mmoexp-marketing/custom-range/range_api.py',
 'channel/channel_effects.py':'/opt/fs-hermes-fc/channel_effects.py',
 'channel/channel_cache.py':'/opt/fs-hermes-fc/channel_cache.py',
 'skills/data-archive-first/SKILL.md':'/var/lib/fs-hermes-fc/profile/skills/data-archive-first/SKILL.md',
 'units/fs-data-archive.service':'/etc/systemd/system/fs-data-archive.service',
 'units/fs-data-archive.timer':'/etc/systemd/system/fs-data-archive.timer'}
SOURCES={key:('skills/data-archive-first/SKILL.md' if key.startswith('skills/') else
    'deploy/'+key.split('/')[-1] if key.startswith('units/') else
    'source/marketing_range_api.py' if key=='marketing/range_api.py' else
    'source/'+key.split('/')[-1]) for key in TARGETS}
NEW=frozenset(k for k in TARGETS if k.endswith('/daily_archive.py') or k.startswith(('skills/','units/')) or k=='runtime/archive_jobs.py')
UNITS=frozenset(v for k,v in TARGETS.items() if k.startswith('units/'))


def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,NEW
    release.AUTHORIZED_TIMERS=UNITS
    base=release.load_base();restart=base.restart_for;quiescent=base.hermes_quiescent
    def idle(root):
        quiescent(root)
        if str(root)!='/':return
        for unit in ('fs-business-range.service','fs-marketing-range.service'):
            pid=subprocess.check_output(['systemctl','show',unit,'--property=MainPID'],text=True,timeout=10).strip().split('=',1)[-1]
            if not pid.isdigit() or pid=='0':raise ValueError('archive_runtime_not_mapped')
            if any(p.read_text().strip() for p in Path('/proc',pid,'task').glob('*/children')):
                raise ValueError('active_native_or_marketing_read')
    base.hermes_quiescent=idle
    def restart_archive(manifest,admission_fence=None):
        restart(manifest,admission_fence)
        if manifest.get('scope')!=SCOPE:return
        subprocess.run(['systemctl','restart','fs-marketing-range.service'],check=True,timeout=40)
        if all(Path(p).is_file() for p in UNITS):
            if 'Asia/Shanghai' not in subprocess.check_output(['timedatectl','status'],text=True,timeout=10):raise ValueError('archive_requires_shanghai_server_timezone')
            subprocess.run(['systemd-analyze','verify',*sorted(UNITS)],check=True,timeout=30)
            subprocess.run(['systemctl','daemon-reload'],check=True,timeout=30)
            subprocess.run(['systemctl','enable','--now','fs-data-archive.timer'],check=True,timeout=30)
        else:
            subprocess.run(['systemctl','disable','--now','fs-data-archive.timer'],check=False,timeout=30)
            subprocess.run(['systemctl','daemon-reload'],check=True,timeout=30)
            if subprocess.run(['systemctl','is-active','--quiet','fs-data-archive.timer'],timeout=10).returncode==0:raise ValueError('archive_timer_rollback_still_active')
    base.restart_for=restart_archive
    return base


if __name__=='__main__':load_base().main()
