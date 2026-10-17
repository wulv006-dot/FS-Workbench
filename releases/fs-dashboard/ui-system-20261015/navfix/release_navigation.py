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
UI_SYSTEM_SCOPE='fs-ui-navfix-20261015'
UI_SYSTEM_TARGETS={'ui/hubnav.js':'/var/www/hub/hubnav.js'}

original_expected=base.expected_files
original_target=base.target_for
original_guards=base.guards
def expected_files(manifest):
    return set(UI_SYSTEM_TARGETS) if manifest.get('scope')==UI_SYSTEM_SCOPE else original_expected(manifest)
def target_for(rel):
    return UI_SYSTEM_TARGETS[rel] if rel in UI_SYSTEM_TARGETS else original_target(rel)
def guards(manifest,root):
    if manifest.get('scope')==UI_SYSTEM_SCOPE:
        for target in UI_SYSTEM_TARGETS.values():
            path=base.rooted(root,target);base.no_target_link(path)
            for item in (path,*path.parents):
                if item.exists() and (item.stat().st_uid!=0 or item.stat().st_gid!=0 or item.stat().st_mode&0o022):raise ValueError('unsafe UI boundary')
                if item==root:break
    return original_guards(manifest,root)
base.expected_files=expected_files
base.target_for=target_for
base.guards=guards
def __getattr__(name):return getattr(base,name)
if __name__=='__main__':base.main()
