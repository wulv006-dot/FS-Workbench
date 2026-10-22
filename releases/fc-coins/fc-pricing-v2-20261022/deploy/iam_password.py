"""Single static IAM form fix through the existing locked CAS publisher."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('existing_fc_publisher', HERE / 'fc_v2_release_adapter.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
adapter.HERE = HERE
adapter.SCOPE = 'fs-iam-password-contract-20261022'
adapter.TARGETS = {'source/app.js': '/opt/fs-access-policy/web/app.js'}
adapter.NEW = frozenset()
adapter.RESTART_FC = False


def load_base():
    base = adapter.load_base()
    # The portal reads this static file per request; no service reload is needed.
    base.restart_for = lambda manifest, admission_fence=None: None
    return base


if __name__ == '__main__':
    load_base().main()
