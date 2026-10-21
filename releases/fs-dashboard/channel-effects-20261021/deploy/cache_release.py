"""Controlled cache/accounting release; only the new channel schedules are admitted."""
import subprocess
from pathlib import Path
import release
SCOPE='fs-channel-cache-20261021'
TARGETS={'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf', 'ui/index.html': '/var/lib/fs-navigation-formal-static/channel-effects-46232953bcbf/index.html', 'ui/channel.js': '/var/lib/fs-navigation-formal-static/channel-effects-46232953bcbf/channel.js', 'ui/channel.css': '/var/lib/fs-navigation-formal-static/channel-effects-46232953bcbf/channel.css', 'runtime/channel_effects.py': '/opt/fs-hermes-fc/channel_effects.py', 'runtime/channel_source.py': '/opt/fs-hermes-fc/channel_source.py', 'runtime/channel_cache.py': '/opt/fs-hermes-fc/channel_cache.py', 'units/fs-channel-cache.service': '/etc/systemd/system/fs-channel-cache.service', 'units/fs-channel-cache.timer': '/etc/systemd/system/fs-channel-cache.timer', 'units/fs-channel-backfill.service': '/etc/systemd/system/fs-channel-backfill.service', 'units/fs-channel-backfill.timer': '/etc/systemd/system/fs-channel-backfill.timer'}
OLD='channel-effects-4145afae60e8'
NEW='channel-effects-46232953bcbf'
UNITS=frozenset(v for k,v in TARGETS.items() if k.startswith('units/'))
TIMERS=('fs-channel-cache.timer','fs-channel-backfill.timer')
def candidate(before):
    needle=('alias /var/lib/fs-navigation-formal-static/'+OLD+'/').encode()
    if before.count(needle)!=3:raise ValueError('exact_channel_ui_bindings_required')
    return before.replace(needle,('alias /var/lib/fs-navigation-formal-static/'+NEW+'/').encode())
def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset(k for k in TARGETS if k.startswith(('ui/','units/')) or k=='runtime/channel_cache.py')
    release.AUTHORIZED_TIMERS=UNITS
    base=release.load_base();restart=base.restart_for
    def restart_cache(manifest,admission_fence=None):
        restart(manifest,admission_fence)
        if manifest.get('scope')!=SCOPE:return
        if all(Path(p).is_file() for p in UNITS):
            subprocess.run(['systemd-analyze','verify',*sorted(UNITS)],check=True,timeout=30)
            subprocess.run(['systemctl','daemon-reload'],check=True,timeout=30)
            subprocess.run(['systemctl','enable','--now',*TIMERS],check=True,timeout=30)
        else:
            # On rollback these newly introduced units have been removed.
            subprocess.run(['systemctl','disable','--now',*TIMERS],check=False,timeout=30)
            subprocess.run(['systemctl','daemon-reload'],check=True,timeout=30)
            for unit in TIMERS:
                if subprocess.run(['systemctl','is-active','--quiet',unit],timeout=10).returncode==0:
                    raise ValueError('channel_timer_rollback_still_active')
    base.restart_for=restart_cache
    return base
if __name__=='__main__':load_base().main()
