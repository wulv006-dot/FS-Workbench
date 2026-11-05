import importlib.util
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch

path=Path(__file__).resolve().parents[1]/'retire_legacy.py'
spec=importlib.util.spec_from_file_location('retire_monitor',path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RetireTests(unittest.TestCase):
    def test_removes_only_old_controller_hook(self):
        before=b'import subprocess\ndef main():\n        existing_shared_task()\n'+module.HOOK.encode()+b'        other_shared_task()\n'
        self.assertEqual(module.strip_hook(before),b'import subprocess\ndef main():\n        existing_shared_task()\n        other_shared_task()\n')

    def test_missing_or_duplicate_hook_is_not_silently_changed(self):
        for raw in (b'pass\n',module.HOOK.encode()*2):
            with self.assertRaisesRegex(ValueError,'legacy_bridge_hook_drift'):module.strip_hook(raw)

    def test_targets_exclude_shared_bridge_and_new_collector(self):
        self.assertEqual({p.name for p in module.FILES},{'fs-boss-game-monitor.timer','fs-boss-game-monitor.service','controller.py','game-monitor-publish.conf'})
        self.assertTrue(all('fs-game-monitor-intelligence' not in str(p) for p in module.FILES+module.DIRECTORIES))

    def test_relative_retirement_target_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'retirement_path_boundary'):module.safe(Path('relative'))

    def test_symlink_retirement_target_is_rejected(self):
        with patch.object(Path,'is_symlink',return_value=True):
            with self.assertRaisesRegex(ValueError,'retirement_path_boundary'):module.safe(Path(tempfile.gettempdir())/'linked')


if __name__=='__main__':unittest.main()
