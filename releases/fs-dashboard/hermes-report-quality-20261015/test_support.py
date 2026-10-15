"""Assemble a temporary test import root from existing canonical sources.

The release carries only the ten changed production files. Existing dependencies
and licensed skill snapshots stay in their original release paths.
"""
import atexit
from pathlib import Path
import shutil
import tempfile

HERE = Path(__file__).resolve().parent
_temporary = tempfile.TemporaryDirectory(prefix='hermes-report-quality-')
atexit.register(_temporary.cleanup)
SOURCE_ROOT = Path(_temporary.name)
repository = next((p for p in HERE.parents if (p/'releases/fs-dashboard/hermes-fc-pilot-20261013').is_dir()), None)
if repository:
    original = repository/'releases/fs-dashboard/hermes-fc-pilot-20261013'
    for source in original.glob('*.py'):
        shutil.copyfile(source, SOURCE_ROOT/source.name)
    shutil.copytree(original/'skills', SOURCE_ROOT/'skills')
    shutil.copytree(original/'assets', SOURCE_ROOT/'assets')
    shutil.copytree(original/'admin_order_capabilities_20261014', SOURCE_ROOT/'admin_order_capabilities_20261014')
    revision = repository/'releases/fs-dashboard/fs-revision-20261015/ai/candidate'
    shutil.copyfile(revision/'report.template.html', SOURCE_ROOT/'report.template.html')
    desktop = repository/'releases/fs-dashboard/hermes-desktop-20261015/release/candidate/hermes/runtime'
    for name in ('controller.py','business_context.py'):
        if (desktop/name).exists():shutil.copyfile(desktop/name,SOURCE_ROOT/name)
else:
    for directory in ('baseline', 'qa_dependencies'):
        for source in (HERE/directory).rglob('*'):
            if source.is_file():
                target = SOURCE_ROOT/source.relative_to(HERE/directory)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
    if (HERE/'qa_dependencies/current_controller.py').exists():
        shutil.copyfile(HERE/'qa_dependencies/current_controller.py',SOURCE_ROOT/'controller.py')
for source in (HERE/'candidate').rglob('*'):
    if source.is_file():
        if source.suffix=='.py' and source.name not in ('boss_projection.py','boss_renderer.py','report_artifacts.py','report_delivery.py','report_semantics.py','skill_bundle.py','research.py'):
            continue
        target = SOURCE_ROOT/source.relative_to(HERE/'candidate')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
