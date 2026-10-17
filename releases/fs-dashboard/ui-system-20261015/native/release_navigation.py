"""Reuse the already-reviewed repository publisher; never duplicate unrelated scopes."""
from pathlib import Path
import importlib.util, hashlib
baseline = Path(__file__).resolve().parents[2] / 'menu-cache-20261015/native/release_navigation.py'
if not baseline.is_file():
    baseline = Path(__file__).resolve().parents[1] / 'native/release_navigation_base.py'
if hashlib.sha256(baseline.read_bytes()).hexdigest()!='5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357':raise ValueError('reviewed baseline publisher differs')
spec=importlib.util.spec_from_file_location('_fs_ui_publisher_base',baseline)
base=importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
atomic=base.atomic
digest=base.digest
locks=base.locks
directory_sync=base.directory_sync
retirement=base.retirement
