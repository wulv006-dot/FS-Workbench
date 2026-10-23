"""Offline exact build/publication preparation. Docker and systemd are mocked."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zlib
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('learning_prepare', ROOT / 'tools/prepare_learning_native_release.py')
prepare = importlib.util.module_from_spec(spec); spec.loader.exec_module(prepare)
release = prepare.load(ROOT / prepare.DEPLOY / 'native_release.py', 'learning_native_scope_fixture')


class GitlessBinding(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.path = Path('nested/entry.py')
        (self.root / 'nested').mkdir(); (self.root / self.path).write_bytes(b'approved source\n')
        self.blob = self.object('blob', b'approved source\n')
        tree = self.object('tree', b'100644 entry.py\0' + bytes.fromhex(self.blob))
        root_tree = self.object('tree', b'40000 nested\0' + bytes.fromhex(tree))
        self.commit = self.object('commit', ('tree ' + root_tree + '\n\nSynthetic QA commit\n').encode())

    def object(self, kind, content):
        raw = (kind + ' ' + str(len(content))).encode() + b'\0' + content
        sha = hashlib.sha1(raw).hexdigest(); path = self.root / '.git/objects' / sha[:2] / sha[2:]
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(zlib.compress(raw))
        return sha

    def verify(self):
        with patch.object(prepare, 'COMMIT_INPUTS', (self.path,)), \
                patch.object(prepare.subprocess, 'check_output', side_effect=FileNotFoundError('git')):
            prepare.verify_commit(self.root, self.commit)

    def test_original_commit_tree_and_blob_chain_works_without_git(self):
        self.verify()

    def test_working_bytes_must_still_match_original_commit(self):
        (self.root / self.path).write_bytes(b'different working source')
        with self.assertRaisesRegex(ValueError, 'commit_source_differs'): self.verify()

    def test_corrupt_object_and_missing_object_are_never_accepted(self):
        path = self.root / '.git/objects' / self.blob[:2] / self.blob[2:]
        path.write_bytes(zlib.compress(b'blob 7\0changed'))
        with self.assertRaisesRegex(ValueError, 'git_object_changed'): self.verify()
        path.unlink()
        with self.assertRaises(FileNotFoundError): self.verify()

    def test_git_symlink_entry_and_object_link_are_refused(self):
        tree = self.object('tree', b'120000 entry.py\0' + bytes.fromhex(self.blob))
        root = self.object('tree', b'40000 nested\0' + bytes.fromhex(tree))
        self.commit = self.object('commit', ('tree ' + root + '\n\nSymlink fixture\n').encode())
        with self.assertRaisesRegex(ValueError, 'git_source_mode'): self.verify()
        with patch.object(Path, 'is_symlink', return_value=True), self.assertRaisesRegex(ValueError, 'git_object_link'):
            self.verify()

    def test_git_errors_do_not_fall_back_to_unrelated_loose_objects(self):
        with patch.object(prepare, 'COMMIT_INPUTS', (self.path,)), \
                patch.object(prepare.subprocess, 'check_output', side_effect=prepare.subprocess.CalledProcessError(1, 'git')), \
                patch.object(prepare, 'loose_source') as fallback, self.assertRaisesRegex(ValueError, 'source_unavailable'):
            prepare.verify_commit(self.root, self.commit)
        fallback.assert_not_called()


class NativeRelease(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name)
        self.output = self.root / 'stage'; self.after = 'sha256:' + 'a' * 64
        self.unit = self.root / 'before.service'
        self.unit.write_text('[Service]\nExecStart=/usr/bin/docker run --name fs-hermes-desktop ' + release.CURRENT_IMAGE + '\n')
        self.policy = self.root / 'before-policy.json'
        self.prior = dict(contract='fs-knowledge-load-policy-v1', requests={}, native=dict(enabled=True,
            readonly_sessions={'old-approved-test': dict(task_ids=['old-task'])}), custom='preserve')
        self.policy.write_text(json.dumps(self.prior))
        self.gateway = self.root / 'gateway.py'; self.gateway.write_bytes(b'fixture gateway before')
        self.preflight = dict(current_image=release.CURRENT_IMAGE, native_image_sources=release.BEFORE_SOURCES,
            unit_before_path=str(self.unit), policy_before_path=str(self.policy), gateway_before_path=str(self.gateway),
            native_sqlite_version=sqlite3.sqlite_version, source_commit='a' * 40, unchangedRequired=[], runtimeRequired={},
            before_hashes={release.TARGETS['plugin/__init__.py']: prepare.sha(prepare.source_bytes(ROOT / prepare.NATIVE / 'fs_readonly/__init__.py')),
                           release.TARGETS['plugin/knowledge.py']: 'b' * 64})
        self.original_load = prepare.load
        self.patcher = Mock(); self.patcher.patch_gateway.return_value = b'fixture gateway patched'
        self.load_patch = patch.object(prepare, 'load', side_effect=lambda path, name:
            self.patcher if Path(path).name == 'patch_factory.py' else self.original_load(path, name))
        self.load_patch.start(); self.addCleanup(self.load_patch.stop)

    def builder(self, root, context, before, operation_id, **source_binding):
        self.assertEqual({p.name for p in context.iterdir()}, {'Dockerfile.native', *release.IMAGE_PAYLOADS})
        sources = {target: prepare.sha((context / name).read_bytes()) for name, target in release.IMAGE_PAYLOADS.items()}
        sources['/opt/hermes/tui_gateway/server.py'] = release.BEFORE_SOURCES['/opt/hermes/tui_gateway/server.py']
        return dict(image=self.after, tag='offline-mock', sources=sources)

    def prepare(self, builder=None):
        return prepare.prepare(ROOT, self.output, self.preflight, 'original-learning-op', builder)

    def test_default_only_prepares_exact_context_and_blocked_preview(self):
        with patch.object(prepare.subprocess, 'run', side_effect=AssertionError('no process')), \
             patch.object(prepare.subprocess, 'check_output', side_effect=AssertionError('no Docker')):
            value = self.prepare()
        self.assertFalse(value['releaseReady']); self.assertFalse(value['imageBuilt'])
        self.assertFalse((self.output / 'candidate-manifest.json').exists())
        dockerfile = (self.output / 'native-image-context/Dockerfile.native').read_text()
        self.assertEqual(dockerfile.count('COPY '), 3)
        self.assertIn('COPY native_gateway_factory.py /opt/hermes/gateway/run_turn_runner.py', dockerfile)
        self.assertIn('COPY reviewed_skills.py /opt/hermes/reviewed_skills.py', dockerfile)
        self.assertNotIn('COPY native_factory.py', dockerfile)
        with self.assertRaisesRegex(ValueError, 'verified_build_receipt'):
            prepare.finish_candidate(ROOT, self.output, self.preflight)

    def test_context_only_needs_no_unit_policy_or_runtime_and_cannot_be_published(self):
        with patch.object(prepare.subprocess, 'check_output', side_effect=AssertionError('no external read')):
            value = prepare.prepare_context(ROOT, self.output, self.gateway.read_bytes(), 'context-only-op')
        self.assertFalse(value['releaseReady']); self.assertEqual(value['status'], 'context_only_needs_preflight')
        self.assertEqual(len(value['exactContextFiles']), 4)
        self.assertFalse((self.output / 'candidate-manifest.json').exists())
        self.assertFalse((self.output / 'native-image-state.json').exists())
        self.assertTrue(any('systemd unit' in reason for reason in value['blocked']))

    def test_mock_built_candidate_preserves_policy_and_exact_mount_only(self):
        with patch.object(prepare.subprocess, 'run', side_effect=AssertionError('no service operation')):
            manifest = self.prepare(self.builder)
        self.assertFalse(manifest['releaseReady']); self.assertFalse(manifest['ordinaryKnowledgeRoutesEnabled'])
        self.assertEqual(manifest['nativeImageBeforeSources'], release.BEFORE_SOURCES)
        self.assertEqual((self.output / 'candidate/policy/knowledge-load-policy.json').read_bytes(), self.policy.read_bytes())
        candidate_unit = (self.output / 'candidate/native/desktop.service').read_bytes()
        self.assertEqual(candidate_unit.replace((release.MOUNT + ' ' + self.after).encode(), release.CURRENT_IMAGE.encode()), self.unit.read_bytes())
        self.assertIn('published-skills,dst=/approved-skills,readonly', release.MOUNT)
        self.assertNotIn('src=/var/lib/fs-hermes-memory-approval,dst=', release.MOUNT)
        release.checked(manifest, self.output)
        (self.output / 'approved-manifest.json').write_text(json.dumps(manifest))
        with patch.object(release, 'HERE', self.output):
            base = release.load_base()
        self.assertEqual(base.apply.__module__, 'frozen_hermes_v2_publisher')
        self.assertEqual(base.rollback_journal.__name__, 'restore_native')
        self.assertEqual(base.hermes_admission_fence.__name__, 'fence')

    def test_builder_pins_original_sources_and_checks_three_layers_user_and_image_paths(self):
        self.prepare(); context = self.output / 'native-image-context'
        expected = self.builder(ROOT, context, release.CURRENT_IMAGE, 'original-learning-op')['sources']
        lines = lambda rows: ''.join(sha + '  ' + path + '\n' for path, sha in rows.items())
        replies = [json.dumps(['base']), '"hermes"', lines(release.BEFORE_SOURCES), self.gateway.read_bytes(), self.after,
            json.dumps(['base', 'copy-entry', 'copy-gateway', 'copy-helper']), '"hermes"', lines(expected)]
        with patch.object(prepare, 'verify_commit') as commit, patch.object(prepare.subprocess, 'check_output', side_effect=replies), patch.object(prepare.subprocess, 'run') as run:
            result = prepare.build_image(ROOT, context, release.CURRENT_IMAGE, 'original-learning-op', source_commit='a' * 40)
        commit.assert_called_once_with(ROOT, 'a' * 40)
        self.assertEqual(result['sources'], expected)
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ['docker', 'build', '--network', 'none'])
        self.assertIn('NATIVE_BASE=' + release.CURRENT_IMAGE, command); self.assertIn('--pull=false', command)
        self.assertNotIn('systemctl', command)
        bad = list(replies); bad[2] = lines(dict(release.BEFORE_SOURCES, **{'/opt/hermes/fs_native_entry.py': 'f' * 64}))
        with patch.object(prepare, 'verify_commit'), patch.object(prepare.subprocess, 'check_output', side_effect=bad), patch.object(prepare.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'existing_image_source_drift'):
                prepare.build_image(ROOT, context, release.CURRENT_IMAGE, 'original-learning-op', source_commit='a' * 40)
            run.assert_not_called()
        for index, value, error in ((5, json.dumps(['wrong-base', 'copy-entry', 'copy-gateway', 'copy-helper']), 'layers_differ'),
                                    (6, '"root"', 'runtime_user_changed'), (7, lines({**expected, '/unexpected.py': 'f' * 64}), 'built_sources_differ')):
            wrong = list(replies); wrong[index] = value
            with self.subTest(error=error), patch.object(prepare, 'verify_commit'), patch.object(prepare.subprocess, 'check_output', side_effect=wrong), \
                    patch.object(prepare.subprocess, 'run'), self.assertRaisesRegex(ValueError, error):
                prepare.build_image(ROOT, context, release.CURRENT_IMAGE, 'original-learning-op', source_commit='a' * 40)

    def test_real_builder_rejects_unbound_commit_before_any_docker_action(self):
        self.prepare(); context = self.output / 'native-image-context'
        with patch.object(prepare.subprocess, 'check_output', return_value=b'older committed source') as read, \
                patch.object(prepare.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'commit_source_differs'):
                prepare.build_image(ROOT, context, release.CURRENT_IMAGE, 'original-learning-op', source_commit='a' * 40)
        self.assertEqual(read.call_args.args[0][0], 'git'); run.assert_not_called()
        for source_commit in (None, '', 'a' * 39):
            with self.assertRaisesRegex(ValueError, 'committed_source_required'):
                prepare.verify_commit(ROOT, source_commit)

    def test_commit_binding_checks_every_repository_input_against_exact_lf_bytes(self):
        def committed(command, **kwargs):
            self.assertEqual(command[:4], ['git', '-C', str(ROOT), 'show'])
            source_commit, relative = command[4].split(':', 1)
            self.assertEqual(source_commit, 'a' * 40)
            return prepare.source_bytes(ROOT / relative)
        with patch.object(prepare.subprocess, 'check_output', side_effect=committed) as read:
            prepare.verify_commit(ROOT, 'a' * 40)
        self.assertEqual(read.call_count, len(prepare.COMMIT_INPUTS))

    def test_unknown_and_repeat_build_never_blind_retry(self):
        builder = Mock(side_effect=TimeoutError('outcome unknown'))
        with self.assertRaises(TimeoutError): self.prepare(builder)
        self.assertEqual(json.loads((self.output / 'native-image-state.json').read_bytes())['status'], 'unknown-needs-reconcile')
        with self.assertRaisesRegex(ValueError, 'reconcile_original_operation'): self.prepare(builder)
        self.assertEqual(builder.call_count, 1)
        with self.assertRaisesRegex(ValueError, 'verified_build_receipt'):
            prepare.finish_candidate(ROOT, self.output, self.preflight)
        with self.assertRaisesRegex(ValueError, 'reconcile_original'):
            prepare.build_prepared(ROOT, self.output, self.preflight, 'original-learning-op', builder)
        self.assertEqual(builder.call_count, 1)

    def test_known_preview_builds_under_same_operation_once_and_requires_original_baseline(self):
        self.prepare()
        builder = Mock(side_effect=self.builder)
        manifest = prepare.build_prepared(ROOT, self.output, self.preflight, 'original-learning-op', builder)
        self.assertFalse(manifest['releaseReady']); self.assertEqual(builder.call_count, 1)
        with self.assertRaisesRegex(ValueError, 'reconcile_original'):
            prepare.build_prepared(ROOT, self.output, self.preflight, 'replacement-id', builder)

    def test_changed_policy_after_preview_never_builds(self):
        self.prepare(); self.policy.write_text(self.policy.read_text() + '\n')
        builder = Mock(side_effect=self.builder)
        with self.assertRaisesRegex(ValueError, 'prepared_baseline_drift'):
            prepare.build_prepared(ROOT, self.output, self.preflight, 'original-learning-op', builder)
        builder.assert_not_called()

    def test_manifest_cannot_enable_routes_expand_mount_or_rewrite_registration(self):
        manifest = self.prepare(self.builder)
        for field, value in (('ordinaryKnowledgeRoutesEnabled', True), ('reviewedSkillsMount', '--mount src=/var/lib,dst=/approved-skills,readonly')):
            wrong = dict(manifest, **{field: value})
            with self.assertRaisesRegex(ValueError, 'exact_scope'):
                release.checked(wrong, self.output)
        wrong = copy.deepcopy(manifest); wrong['files'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'existing_registration_policy'):
            release.checked(wrong, self.output)
        wrong = copy.deepcopy(manifest); wrong['nativeExtraSources']['/opt/fs-hermes-fc/reviewed_skills.py'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'exact_source_dependencies'):
            release.checked(wrong, self.output)
        wrong = dict(manifest, releaseReady=True)
        with self.assertRaisesRegex(ValueError, 'complete_protection'):
            release.checked(wrong, self.output)

    def test_enabled_policy_or_wrong_baseline_fail_before_creating_stage(self):
        self.prior['task_routes'] = dict(enabled=True, routes=[]); self.policy.write_text(json.dumps(self.prior))
        with self.assertRaisesRegex(ValueError, 'disabled_routes'): self.prepare(self.builder)
        self.assertFalse(self.output.exists())
        self.preflight['current_image'] = 'sha256:' + 'f' * 64
        with self.assertRaisesRegex(ValueError, 'preflight_image_source'): self.prepare(self.builder)


if __name__ == '__main__': unittest.main()
