"""Apply the verified Cards mapping through the existing locked, backed-up publisher."""
import contextlib
import os
from pathlib import Path
import subprocess
import release

SCOPE = 'fs-fc-cards-mapping-20261105'
TARGETS = {
    'data/game_mapping_20261019.json': '/opt/mmoexp-marketing/details/game_mapping_20261019.json',
    'data/game_dimensions.py': '/opt/mmoexp-marketing/details/game_dimensions.py',
    'runtime/channel_effects.py': '/opt/fs-hermes-fc/channel_effects.py',
    'runtime/es_order_structure.py': '/opt/fs-hermes-fc/es_order_structure.py',
}


def load_base():
    release.SCOPE, release.TARGETS, release.NEW = SCOPE, TARGETS, frozenset()
    base = release.load_base()
    original_locks, original_restart = base.locks, base.restart_for

    @contextlib.contextmanager
    def locks(root):
        import fcntl
        with original_locks(root):
            path = base.rooted(root, '/opt/mmoexp-marketing/data/verified-readonly/collector.lock')
            base.no_target_link(path)
            fd = os.open(str(path), os.O_RDWR | os.O_NOFOLLOW)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                for proc in Path('/proc').glob('[0-9]*/cmdline'):
                    try: args = proc.read_bytes().split(b'\0')
                    except (OSError, ProcessLookupError): continue
                    if any(arg.endswith((b'/custom_range.py', b'/collect_details.py')) for arg in args):
                        raise ValueError('source reader busy; defer release')
                yield
            finally:
                os.close(fd)

    def restart(manifest, admission_fence=None):
        original_restart(manifest, admission_fence)
        subprocess.run(['systemctl', 'restart', 'fs-marketing-range.service'], check=True, timeout=30)
        subprocess.run(['systemctl', 'is-active', '--quiet', 'fs-marketing-range.service'], check=True, timeout=10)

    base.locks, base.restart_for = locks, restart
    return base


if __name__ == '__main__':
    load_base().main()
