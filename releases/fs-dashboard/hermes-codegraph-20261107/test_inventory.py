import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('inventory', Path(__file__).with_name('inventory_187.py'))
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


class InventoryTests(unittest.TestCase):
    def test_head_metadata_can_be_read_without_installing_git(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'.git/refs/heads').mkdir(parents=True)
            (root/'.git/HEAD').write_text('ref: refs/heads/main\n')
            revision = 'a'*40
            (root/'.git/refs/heads/main').write_text(revision+'\n')
            self.assertEqual(inventory.checkout_revision(root), revision)

    def test_timer_inspection_does_not_request_service_only_properties(self):
        fields = inventory.unit_properties('d4follow-collect.timer')
        self.assertIn('Triggers', fields)
        self.assertTrue(set(fields).isdisjoint({'MainPID', 'WorkingDirectory', 'ExecStart'}))

    def test_source_capture_omits_sensitive_configuration_and_keeps_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = Path(temporary)/'source', Path(temporary)/'snapshot'
            source.mkdir()
            (source/'main.py').write_text('def main():\n    return 1\n')
            (source/'runtime_config.py').write_text('setting = 1\n')
            (source/'password.py').write_text('password = "actual-private-value"\n')
            (source/'credentials.env').write_text('PASSWORD=private')
            result = inventory.copy_sources(source, target)
            self.assertEqual([row['path'] for row in result['files']], ['main.py'])
            self.assertEqual(len(result['omitted']), 2)
            self.assertTrue(result['partial_snapshot'])
            self.assertEqual((target/'main.py').read_bytes(), (source/'main.py').read_bytes())
            self.assertFalse((target/'credentials.env').exists())
            (source/'main.py').write_text('def main():\n    return 2\n')
            with self.assertRaises(RuntimeError):
                inventory.copy_sources(source, target)

    @unittest.skipIf(__import__('os').name == 'nt', 'Production paths use POSIX semantics')
    def test_runtime_roots_are_not_misclassified_by_double_slashes(self):
        self.assertEqual(inventory.deployment_root('/opt/fc27-cloud-browser/worker.py'), '/opt/fc27-cloud-browser')
        self.assertEqual(inventory.deployment_root('/var/www/dashboard/index.html'), '/var/www/dashboard')


if __name__ == '__main__':
    unittest.main()
