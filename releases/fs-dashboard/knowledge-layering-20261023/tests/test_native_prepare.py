import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('prepare_native', ROOT / 'tools/prepare_native_knowledge_release.py')
prepare = importlib.util.module_from_spec(spec); spec.loader.exec_module(prepare)


class Prepare(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.before, self.after = 'sha256:' + 'a' * 64, 'sha256:' + 'b' * 64
        self.unit = self.root / 'old.service'; self.unit.write_text('[Service]\nExecStart=/usr/bin/docker run ' + self.before + '\n')
        self.policy = self.root / 'policy.json'
        self.policy.write_text(json.dumps({'contract': 'fs-knowledge-load-policy-v1', 'requests': {'original': {'keep': True}}, 'custom': 'preserve'}))
        self.preflight = dict(current_image=self.before, unit_before_path=str(self.unit), policy_before_path=str(self.policy),
            native_sqlite_version=sqlite3.sqlite_version,
            native={'enabled': False}, source_commit='a' * 40, before_hashes={
                '/var/lib/fs-hermes-fc/profile/plugins/fs-readonly/__init__.py': 'c' * 64,
                '/var/lib/fs-hermes-fc/profile/plugins/fs-readonly/knowledge.py': None}, unchangedRequired=[], runtimeRequired={})
        release = prepare.load(ROOT / prepare.DEPLOY / 'native_release.py', 'native_scope_fixture')
        self.preflight['before_hashes'][release.TARGETS['plugin/__init__.py']] = release.original_plugin_sha(
            (ROOT / prepare.NATIVE / 'fs_readonly/__init__.py').read_bytes())
        self.result = dict(image=self.after, tag='offline-test', sources={
            '/opt/hermes/tui_gateway/server.py': 'd' * 64, '/opt/hermes/fs_native_entry.py': 'e' * 64})

    def test_stage_merges_only_native_and_never_activates_or_authorizes(self):
        builder = Mock(return_value=self.result)
        with patch.object(prepare.subprocess, 'run', side_effect=AssertionError('no services or external process in offline preparation')):
            manifest = prepare.prepare(ROOT, self.root / 'stage', self.preflight, 'original-op', builder)
        self.assertFalse(manifest['releaseReady']); builder.assert_called_once()
        policy = json.loads((self.root / 'stage/candidate/policy/knowledge-load-policy.json').read_bytes())
        self.assertEqual(policy['requests'], {'original': {'keep': True}}); self.assertEqual(policy['custom'], 'preserve')
        new_unit = (self.root / 'stage/candidate/native/desktop.service').read_bytes()
        self.assertEqual(new_unit.replace(self.after.encode(), self.before.encode()), self.unit.read_bytes())
        state = json.loads((self.root / 'stage/native-image-state.json').read_bytes())
        self.assertEqual(state['operation_id'], 'original-op')
        self.assertEqual(state['status'], 'image_built_and_verified_not_activated')
        self.assertEqual(hashlib.sha256((self.root / 'stage/release_adapter_base.py').read_bytes()).hexdigest(),
                         'd2ab05e0d3efa8003cebb43d75f44c51cd58f1b624c09388322de36e5ce78d58')
        self.assertEqual(hashlib.sha256((self.root / 'stage/release_navigation_base.py').read_bytes()).hexdigest(),
                         '1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de')
        (self.root / 'stage/approved-manifest.json').write_text(json.dumps(manifest))
        release = prepare.load(ROOT / prepare.DEPLOY / 'native_release.py', 'native_staged_load')
        with patch.object(release, 'HERE', self.root / 'stage'):
            self.assertEqual(release.load_base().apply.__module__, 'frozen_hermes_v2_publisher')

    def test_repeat_and_unknown_build_do_not_run_builder_again(self):
        output = self.root / 'stage'; builder = Mock(side_effect=TimeoutError('outcome unknown'))
        with self.assertRaises(TimeoutError): prepare.prepare(ROOT, output, self.preflight, 'original-op', builder)
        self.assertEqual(json.loads((output / 'native-image-state.json').read_bytes())['status'], 'unknown-needs-reconcile')
        with self.assertRaisesRegex(ValueError, 'reconcile_original_operation'):
            prepare.prepare(ROOT, output, self.preflight, 'original-op', builder)
        self.assertEqual(builder.call_count, 1)
        with self.assertRaisesRegex(ValueError, 'verified_build_receipt_required'):
            prepare.finish_candidate(ROOT, output, self.preflight)

    def test_plugin_update_reads_existing_image_and_preserves_exact_policy_unit_and_registration(self):
        release=prepare.load(ROOT/prepare.DEPLOY/'native_release.py','plugin_update_fixture')
        original=json.loads(self.policy.read_bytes());original['native']=self.preflight['native']
        self.policy.write_text(json.dumps(original,separators=(',',':')))
        self.preflight['before_hashes'][release.TARGETS['plugin/__init__.py']]=hashlib.sha256(prepare.source_bytes(ROOT/prepare.NATIVE/'fs_readonly/__init__.py')).hexdigest()
        self.preflight['before_hashes'][release.TARGETS['plugin/knowledge.py']]='f'*64
        rows=''.join(v+'  '+k+'\n' for k,v in release.PATCHED_NATIVE_SOURCES.items())
        with patch.object(prepare.subprocess,'check_output',side_effect=[self.before,rows]),patch.object(prepare.subprocess,'run',side_effect=AssertionError('no build or service operations')):
            result=prepare.prepare_plugin_update(ROOT,self.root/'plugin-stage',self.preflight,'plugin-op')
        self.assertTrue(result['nativePluginOnly'])
        self.assertEqual(result['nativeImageBefore'],result['nativeImageAfter'])
        self.assertEqual((self.root/'plugin-stage/candidate/policy/knowledge-load-policy.json').read_bytes(),self.policy.read_bytes())
        self.assertEqual((self.root/'plugin-stage/candidate/native/desktop.service').read_bytes(),self.unit.read_bytes())
        changed=[r['candidate'] for r in result['files'] if r['sha256']!=r['beforeSha256']]
        self.assertEqual(changed,['plugin/knowledge.py'])
        with self.assertRaisesRegex(ValueError,'reconcile_original_operation'):
            prepare.prepare_plugin_update(ROOT,self.root/'plugin-stage',self.preflight,'plugin-op')

    def test_plugin_update_wrong_runtime_denied_before_staging(self):
        with patch.object(prepare.subprocess,'check_output',return_value='sha256:'+'f'*64):
            with self.assertRaisesRegex(ValueError,'baseline_drift'):
                prepare.prepare_plugin_update(ROOT,self.root/'plugin-stage',self.preflight,'plugin-op')
        self.assertFalse((self.root/'plugin-stage').exists())

    def test_builder_uses_checked_existing_tag_and_verifies_base_layers_and_sources(self):
        context = self.root / 'context'; context.mkdir(); (context / 'fs_native_entry.py').write_bytes(b'entry')
        (context / 'Dockerfile.native').write_bytes(prepare.source_bytes(ROOT / prepare.NATIVE / 'Dockerfile.native'))
        patcher = Mock(); patcher.patch_source.return_value = b'patched'
        lifecycle = Mock(); lifecycle.image_id.side_effect = [self.before, self.before, self.after, self.before]
        layers = ['layer-a', 'layer-b']
        child_layers = layers + ['copy-entry', 'copy-patched-factory']
        expected = {'/opt/hermes/tui_gateway/server.py': hashlib.sha256(b'patched').hexdigest(),
                    '/opt/hermes/fs_native_entry.py': hashlib.sha256(b'entry').hexdigest()}
        replies = [json.dumps(layers), '"hermes"', b'original', json.dumps(child_layers), '"hermes"', ''.join(v + '  ' + k + '\n' for k, v in expected.items())]
        with patch.object(prepare, 'load', side_effect=[patcher, lifecycle]), patch.object(prepare.subprocess, 'check_output', side_effect=replies), patch.object(prepare.subprocess, 'run') as run:
            result = prepare.build_image(ROOT, context, self.before, 'original-op')
        self.assertEqual(result['sources'], expected)
        command = run.call_args.args[0]
        self.assertIn('NATIVE_BASE=' + prepare.BASE_TAG, command)
        self.assertIn('--pull=false', command); self.assertEqual(command[command.index('--network') + 1], 'none')
        lifecycle.image_id.side_effect = [self.before, self.before, self.after, self.before]
        with patch.object(prepare, 'load', side_effect=[patcher, lifecycle]), patch.object(prepare.subprocess, 'check_output', side_effect=[json.dumps(layers), '"hermes"', b'original', json.dumps(['wrong-base'] + child_layers[1:])]), patch.object(prepare.subprocess, 'run'):
            with self.assertRaisesRegex(ValueError, 'base_layers_differ'):
                prepare.build_image(ROOT, context, self.before, 'original-op')
        lifecycle.image_id.side_effect = [self.before, self.before, self.after, self.before]
        with patch.object(prepare, 'load', side_effect=[patcher, lifecycle]), patch.object(prepare.subprocess, 'check_output', side_effect=[json.dumps(layers), '"hermes"', b'original', json.dumps(child_layers), '"root"']), patch.object(prepare.subprocess, 'run'):
            with self.assertRaisesRegex(ValueError, 'runtime_user_changed'):
                prepare.build_image(ROOT, context, self.before, 'original-op')

    def test_incompatible_or_missing_runtime_refused_before_stage_or_build(self):
        builder = Mock()
        for version in ('3.7.17', None, '3.999.0'):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'native_sqlite_'):
                prepare.prepare(ROOT, self.root / 'stage', dict(self.preflight, native_sqlite_version=version), 'original-op', builder)
            self.assertFalse((self.root / 'stage').exists())
        builder.assert_not_called()

    def test_unit_or_missing_policy_contract_refused_before_build(self):
        self.unit.write_text('unrecognized launcher')
        builder = Mock()
        with self.assertRaisesRegex(ValueError, 'unit_image_not_exact'):
            prepare.prepare(ROOT, self.root / 'stage', self.preflight, 'original-op', builder)
        builder.assert_not_called()
        self.unit.write_text('[Service]\nExecStart=/usr/bin/docker run ' + self.before + '\n')
        self.preflight['before_hashes']['/var/lib/fs-hermes-fc/profile/plugins/fs-readonly/__init__.py'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'original_tools_source_drift'):
            prepare.prepare(ROOT, self.root / 'stage', self.preflight, 'original-op', builder)
        builder.assert_not_called()


if __name__ == '__main__': unittest.main()
