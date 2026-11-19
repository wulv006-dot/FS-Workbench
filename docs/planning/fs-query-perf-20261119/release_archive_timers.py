"""Apply or restore only the two archive timers through the FS publisher's locks and atomic writes."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import release_navigation_base as release


HERE = Path(__file__).resolve().parent
BACKUPS = Path('/var/backups/fs-navigation-20261006')
UNITS = {
    'fs-user-analytics.timer': ('b6d36324326a72a4e648f1c87073decc53c7fcd77a9446bdca440722717e3c6d',
                                '88dd35c984d9366cf7540ecb0f482e58edb6a94b37a8cdf4f9cc5a16f11b73bd'),
    'fs-channel-cache.timer': ('a4752f63808da79788bc076fc4eec1001bc9ee26c497253c23dd36b690a34b69',
                               '1db34a04905ec6bc876a2cffd60fd7f692517861cbd453c83179d3740073e474'),
}


def reload_timers():
    subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
    subprocess.run(['systemctl', 'restart', *UNITS], check=True, timeout=30)
    subprocess.run(['systemctl', 'is-active', '--quiet', *UNITS], check=True, timeout=10)


def install(action, backup=None):
    if Path('/etc/localtime').read_bytes() != Path('/usr/share/zoneinfo/Asia/Shanghai').read_bytes():
        raise ValueError('server_timezone_changed')
    paths = {name: Path('/etc/systemd/system') / name for name in UNITS}
    with release.locks(Path('/')):
        for path in paths.values():
            release.no_target_link(path)
            if path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
                raise ValueError('unsafe_timer:' + path.name)
        subprocess.run(['systemctl', 'is-enabled', '--quiet', *UNITS], check=True, timeout=10)
        subprocess.run(['systemctl', 'is-active', '--quiet', *UNITS], check=True, timeout=10)
        if action == 'rollback':
            if backup is None or backup.resolve().parent != BACKUPS or not backup.name.startswith('archive-timers-'):
                raise ValueError('original_timer_backup_required')
            source, from_index, to_index = backup, 1, 0
        else:
            source, from_index, to_index = HERE, 0, 1
        for name, path in paths.items():
            if release.digest(path) != UNITS[name][from_index] or release.digest(source/name) != UNITS[name][to_index]:
                raise ValueError('archive_timer_cas:' + name)
        if action == 'inspect':
            return dict(status='checked', units=list(UNITS))
        if action == 'apply':
            backup = BACKUPS / datetime.now(timezone.utc).strftime('archive-timers-%Y%m%dT%H%M%SZ')
            backup.mkdir(mode=0o700)
            for name, path in paths.items():
                release.atomic(backup/name, path.read_bytes(), 0o600)
        changed = []
        try:
            for name, path in paths.items():
                if release.digest(path) != UNITS[name][from_index]:
                    raise ValueError('archive_timer_drift:' + name)
                release.atomic(path, (source/name).read_bytes(), 0o644)
                changed.append(name)
            reload_timers()
            if any(release.digest(path) != UNITS[name][to_index] for name, path in paths.items()):
                raise ValueError('archive_timer_readback')
        except Exception:
            restore = backup if action == 'apply' else HERE
            for name in reversed(changed):
                if release.digest(paths[name]) == UNITS[name][to_index]:
                    release.atomic(paths[name], (restore/name).read_bytes(), 0o644)
            reload_timers()
            raise
        return dict(status=action, backup=str(backup), units=list(UNITS))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['inspect','apply','rollback'])
    parser.add_argument('--backup',type=Path)
    args = parser.parse_args()
    print(json.dumps(install(args.action, args.backup)))
