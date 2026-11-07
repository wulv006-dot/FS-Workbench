import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class PluginTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).parent / 'fs_codegraph' / '__init__.py'
        self.assertTrue(source.is_file(), 'CodeGraph native plugin has not been implemented')
        spec = importlib.util.spec_from_file_location('codegraph_plugin_test', source)
        self.plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.plugin)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plugin.ROOT = self.root / 'cache'
        self.plugin.REPOSITORY = self.root / 'repository'
        self.project = self.plugin.ROOT / 'sources' / 'example'
        (self.project / '.codegraph').mkdir(parents=True)
        (self.project / '.codegraph/codegraph.db').touch()
        self.plugin.MANIFEST = self.plugin.ROOT / 'projects.json'
        self.plugin.MANIFEST.write_text(json.dumps({'captured_at': '2026-11-07T00:00:00Z', 'projects': {
            'example': {'path': str(self.project), 'source_kind': 'production_snapshot', 'source_path': '/opt/example'}}}))

    def test_inventory_keeps_snapshot_provenance(self):
        result = self.plugin.call('codegraph_projects', {})
        self.assertEqual(result['projects']['example']['source_kind'], 'production_snapshot')
        self.assertEqual(result['captured_at'], '2026-11-07T00:00:00Z')

    def test_sync_before_query_and_no_shell_interpolation(self):
        query = 'save_policy; $(touch /tmp/unwanted)'
        with patch.object(self.plugin.subprocess, 'run', side_effect=[
            subprocess.CompletedProcess([], 0, '', ''),
            subprocess.CompletedProcess([], 0, 'def save_policy(value):\n    return value', '')]) as run:
            result = self.plugin.call('codegraph_explore', {'workspace': 'example', 'query': query})
        self.assertEqual(result['status'], 'ok')
        self.assertIn('def save_policy', result['content'])
        self.assertEqual(run.call_args_list[0].args[0][1:3], ['sync', '--quiet'])
        self.assertEqual(run.call_args_list[1].args[0][-2:], ['--', query])
        self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_sync_failure_does_not_serve_stale_results(self):
        with patch.object(self.plugin.subprocess, 'run', return_value=subprocess.CompletedProcess([], 2, '', 'writer busy')) as run:
            result = self.plugin.call('codegraph_explore', {'workspace': 'example', 'query': 'save_policy'})
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['step'], 'sync')
        self.assertEqual(run.call_count, 1)

    def test_missing_index_does_not_initialize_arbitrary_sources(self):
        (self.project / '.codegraph/codegraph.db').unlink()
        with patch.object(self.plugin.subprocess, 'run') as run:
            result = self.plugin.call('codegraph_explore', {'workspace': 'example', 'query': 'save_policy'})
        self.assertEqual(result['status'], 'not_indexed')
        run.assert_not_called()

    def test_inputs_and_unknown_workspaces_are_rejected(self):
        invalid = [
            {'workspace': '../example', 'query': 'x'},
            {'workspace': 'example', 'query': ''},
            {'workspace': 'example', 'query': 'x', 'maxFiles': True},
            {'workspace': 'example', 'query': 'x', 'maxFiles': 0},
            {'workspace': 'example', 'query': 'x', 'command': 'rm'},
        ]
        with patch.object(self.plugin.subprocess, 'run') as run:
            for args in invalid:
                with self.subTest(args=args), self.assertRaises(ValueError):
                    self.plugin.call('codegraph_explore', args)
        run.assert_not_called()

    def test_manifest_cannot_redirect_queries_to_production(self):
        data = json.loads(self.plugin.MANIFEST.read_text())
        data['projects']['example']['path'] = '/fs-source'
        self.plugin.MANIFEST.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.plugin.call('codegraph_explore', {'workspace': 'example', 'query': 'x'})

    def test_symlinks_cannot_escape_analysis_roots(self):
        outside = self.root / 'production'
        outside.mkdir()
        link = self.plugin.ROOT / 'outside'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Creating symlinks requires privileges on this platform')
        data = json.loads(self.plugin.MANIFEST.read_text())
        data['projects']['example']['path'] = str(link)
        self.plugin.MANIFEST.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.plugin.call('codegraph_explore', {'workspace': 'example', 'query': 'x'})


if __name__ == '__main__':
    unittest.main()
