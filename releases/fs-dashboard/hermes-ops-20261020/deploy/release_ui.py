"""Single-page repair through the existing locked, journaled UI publisher."""
from pathlib import Path
import hashlib
import importlib.util

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'release_navigation_base.py'
if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != '5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357':
    raise ValueError('frozen_publisher_drift')
spec = importlib.util.spec_from_file_location('_brain_ui_base', SOURCE)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
SCOPE = 'hermes-brain-theme-recovery-20261020'
TARGET = '/var/www/dashboard/fs-home/brain/index.html'
validate = base.validate

def exact_validate(manifest, stage):
    if manifest.get('scope') != SCOPE or manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False:
        raise ValueError('static_repair_only')
    if len(manifest.get('files', [])) != 1 or not manifest['files'][0].get('beforeSha256'):
        raise ValueError('single_existing_page_required')
    return validate(manifest, stage)

base.expected_files = lambda manifest: {'ui/brain-index.html'} if manifest.get('scope') == SCOPE else set()
base.target_for = lambda rel: TARGET if rel == 'ui/brain-index.html' else None
base.validate = exact_validate
if __name__ == '__main__':
    base.main()
