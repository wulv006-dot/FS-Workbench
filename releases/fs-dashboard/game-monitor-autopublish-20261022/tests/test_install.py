import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('install_game_monitor',ROOT/'install_bridge.py')
install=importlib.util.module_from_spec(spec);spec.loader.exec_module(install)

class FakePath:
    parents=()
    def __init__(self,uid=9876,mode=0o40700,linked=False):self.uid=uid;self.mode=mode;self.linked=linked
    def is_symlink(self):return self.linked
    def exists(self):return True
    def is_dir(self):return True
    def stat(self):return SimpleNamespace(st_uid=self.uid,st_mode=self.mode)

class InstallBoundary(unittest.TestCase):
    def test_existing_profile_uid_is_preserved_as_untrusted_input(self):
        install.safe(FakePath(),trusted=False)
    def test_same_profile_ownership_is_not_accepted_for_code(self):
        with self.assertRaisesRegex(AssertionError,'unsafe_install_owner'):install.safe(FakePath())
    def test_code_requires_no_group_or_world_write(self):
        with self.assertRaisesRegex(AssertionError,'unsafe_install_owner'):install.safe(FakePath(uid=0,mode=0o40777))
    def test_profile_and_code_both_reject_symlinks(self):
        for trusted in (True,False):
            with self.subTest(trusted=trusted),self.assertRaisesRegex(AssertionError,'linked_install'):install.safe(FakePath(uid=0,linked=True),trusted=trusted)

if __name__=='__main__':unittest.main()
