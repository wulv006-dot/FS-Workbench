"""Dedicated observer code via the existing FC/FS publisher, locks and rollback."""
import importlib.util
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('fc_v2_existing_publisher', HERE / 'fc_v2_release_adapter.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
adapter.HERE = HERE
adapter.SCOPE = 'fc-dot-observer-20261022'
adapter.TARGETS = {
    'source/rbac.py': '/opt/fs-access-policy/rbac.py',
    'source/access_policy.py': '/opt/fs-access-policy/access_policy.py',
    'source/fc27_cloud_api.py': '/opt/fc27-cloud-browser/fc27_cloud_api.py',
    'source/fc_observer.py': '/opt/fc27-cloud-browser/fc_observer.py',
}
adapter.NEW = frozenset({'source/fc_observer.py'})
adapter.RESTART_FC = False


def load_base():
    base = adapter.load_base()

    def restart(manifest, admission_fence=None):
        for unit in ('auth-portal.service', 'fc27-cloud-api.service'):
            subprocess.run(['systemctl', 'restart', unit], check=True, timeout=30)
            subprocess.run(['systemctl', 'is-active', '--quiet', unit], check=True, timeout=10)

    base.restart_for = restart
    return base


if __name__ == '__main__':
    load_base().main()
