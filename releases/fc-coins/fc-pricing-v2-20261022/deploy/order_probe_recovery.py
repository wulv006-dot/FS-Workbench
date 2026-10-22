"""Publish one shared Order probe fix through the existing CAS/rollback publisher."""
import importlib.util
import json
from pathlib import Path
import subprocess
import time
import urllib.request

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('fc_v2_existing_publisher', HERE / 'fc_v2_release_adapter.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
adapter.HERE = HERE
adapter.SCOPE = 'fc-order-probe-recovery-20261022'
adapter.TARGETS = {'source/order_session_service.py': '/opt/fs-order-session/service.py'}
adapter.NEW = frozenset()
adapter.RESTART_FC = False


def load_base():
    base = adapter.load_base()
    original = base.restart_for

    def restart(manifest, admission_fence=None):
        original(manifest, admission_fence)
        subprocess.run(['systemctl', 'restart', 'fs-order-session.service'], check=True, timeout=15)
        # The browser owns authentication; restarting this broker never logs in or resets it.
        for _ in range(40):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8768/health', timeout=2) as response:
                    if json.load(response).get('ready') is True:
                        return
            except (OSError, ValueError):
                pass
            time.sleep(1)
        raise RuntimeError('shared_order_probe_not_ready_after_restart')

    base.restart_for = restart
    return base


if __name__ == '__main__':
    load_base().main()
