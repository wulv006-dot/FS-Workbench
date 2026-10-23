import copy
import hashlib
import importlib.util
import json
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load(ROOT / 'tools/prepare_learning_release.py', 'prepare_learning_candidate')
scope = load(Path(__file__).parent / 'deploy/release.py', 'learning_candidate_scope')


def fixture_root(path):
    index = json.loads(prepare.raw(ROOT, 'knowledge/index.json'))
    names = set(prepare.SOURCES.values()) | {Path('knowledge/index.json'), prepare.MODULE/'deploy/release.py',
                                           prepare.KNOWLEDGE/'source/knowledge_catalog.py'}
    names.update(source for source, sha in prepare.PUBLISHERS.values())
    names.update(Path(row['source']['path']) for row in index['entries'] if row['layer'] != 'candidate')
    for name in names:
        target = path/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT/name).read_bytes())
    return path


class Candidate(unittest.TestCase):
    def test_uncommitted_candidate_cannot_claim_published_source_or_reuse_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / 'stage'
            with patch('subprocess.check_output', side_effect=AssertionError('offline only')):
                value = prepare.prepare(ROOT, stage)
            manifest = value['manifest']
            self.assertFalse(manifest['releaseReady'])
            self.assertIsNone(manifest['sourceCommit'])
            index = json.loads((stage / 'candidate/artifact/index.json').read_bytes())
            self.assertEqual(index['release_state'], 'candidate')
            self.assertIsNone(index['source_commit'])
            self.assertNotEqual(scope.RELEASE, 'knowledge-layering-20261023-1')
            for row in manifest['files']:
                self.assertEqual(hashlib.sha256((stage / 'candidate' / row['candidate']).read_bytes()).hexdigest(), row['sha256'])
            self.assertEqual((stage / 'candidate/runtime/reviewed_skills.py').read_bytes(),
                             (stage / 'candidate/approval/reviewed_skills.py').read_bytes())
            with self.assertRaisesRegex(ValueError, 'reconcile_original'):
                prepare.prepare(ROOT, stage)

    def test_commit_must_contain_exact_candidate_bytes(self):
        with tempfile.TemporaryDirectory() as tmp, patch('subprocess.check_output', return_value=b'old content'):
            with self.assertRaisesRegex(ValueError, 'commit_source_drift'):
                prepare.prepare(ROOT, Path(tmp) / 'stage', commit='a' * 40)
            self.assertFalse((Path(tmp) / 'stage').exists())

    def test_scope_rejects_policy_configuration_schedule_and_other_targets(self):
        value = dict(businessWrites=False, timersChanged=False,
                     files=[dict(candidate=name, target=target) for name, target in scope.RUNTIME.items()]
                     + [dict(candidate='artifact/index.json', target=scope.PREFIX + 'index.json')])
        scope.targets(value)
        for target in ('/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json',
                       '/var/lib/fs-hermes-fc/profile/config.yaml', '/etc/systemd/system/anything.timer',
                       '/opt/fs-hermes-fc/hermes_worker.py'):
            bad = copy.deepcopy(value)
            bad['files'].append(dict(candidate='artifact/escape', target=target))
            with self.assertRaisesRegex(ValueError, 'boundary'):
                scope.targets(bad)
        for key in ('businessWrites', 'timersChanged'):
            with self.assertRaisesRegex(ValueError, 'schedule_writes'):
                scope.targets(dict(value, **{key: True}))

    def test_scope_rejects_immutable_path_aliases_and_duplicate_targets(self):
        value = dict(businessWrites=False, timersChanged=False,
                     files=[dict(candidate=name, target=target) for name, target in scope.RUNTIME.items()]
                     + [dict(candidate='artifact/index.json', target=scope.PREFIX+'index.json')])
        for name in ('artifact//index.json', 'artifact/./other.md', 'artifact/sources/../other.md'):
            bad = copy.deepcopy(value)
            bad['files'].append(dict(candidate=name, target=scope.PREFIX+name[len('artifact/'):]))
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'boundary'):
                scope.targets(bad)
        bad = copy.deepcopy(value)
        bad['files'].append(dict(candidate='artifact/alias.json', target=scope.PREFIX+'index.json'))
        with self.assertRaisesRegex(ValueError, 'duplicate_targets'):
            scope.targets(bad)

    def test_archived_source_cannot_read_outside_the_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(Path(tmp)/'root')
            index = json.loads(prepare.raw(root, 'knowledge/index.json'))
            row = next(r for r in index['entries'] if r['layer']=='archive')
            (root.parent/'outside.md').write_bytes(b'outside repository')
            row['source'].update(path='../outside.md', sha256=hashlib.sha256(b'outside repository').hexdigest(), selector=None)
            (root/'knowledge/index.json').write_text(json.dumps(index, ensure_ascii=False), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'path_boundary'):
                prepare.prepare(root, Path(tmp)/'stage')
            self.assertFalse((Path(tmp)/'stage').exists())

    def test_frozen_publisher_drift_fails_before_creating_the_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(Path(tmp)/'root')
            path, sha = prepare.PUBLISHERS['release_adapter_base.py']
            (root/path).write_bytes((root/path).read_bytes()+b'\n# drift\n')
            with self.assertRaisesRegex(ValueError, 'frozen_publisher_drift'):
                prepare.prepare(root, Path(tmp)/'stage')
            self.assertFalse((Path(tmp)/'stage').exists())

    def test_existing_publisher_still_requires_all_existing_baselines(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / 'stage'
            value = prepare.prepare(ROOT, stage)['manifest']
            (stage / 'approved-manifest.json').write_text(json.dumps(value), encoding='utf-8')
            with patch.object(scope, 'HERE', stage):
                with self.assertRaisesRegex(ValueError, 'exact_new_existing_boundary'):
                    scope.load_base()

    def test_complete_fixture_uses_existing_validator_and_restart_fence(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / 'stage'
            before = {target: 'a' * 64 for name, target in scope.RUNTIME.items() if name not in scope.NEW_RUNTIME}
            value = prepare.prepare(ROOT, stage, before)['manifest']
            original = load(stage / 'release_navigation_base.py', 'learning_original_publisher_fixture')
            protected = set(original.HERMES_TARGETS.values()) | {
                '/opt/fs-exact-range-20261001/' + name for name in
                ('boss_insights.py', 'fc_deep_model.py', 'fc_daily.py', 'fc_daily_model.py',
                 'fc_detail.py', 'fc_detail_model.py', 'fc_detail_reader.py', 'fc_detail_config.json',
                 'fc_deep_sources.py', 'summary_bridge.py')}
            protected.update(('/var/www/dashboard/index.html', '/var/www/dashboard/fs-home/index.html',
                              '/var/www/dashboard/fs-home/navigation.js', '/opt/fs-access-policy/access_policy.py'))
            protected -= set(scope.targets(value).values())
            value['unchangedRequired'] = [dict(path=path, sha256='f' * 64) for path in sorted(protected)]
            value['runtimeRequired'] = {name: {'ActiveState': 'active'} for name in
                                        ('fs-hermes-fc.service', 'fs-business-range.service')}
            value['imageId'] = 'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544'
            (stage / 'approved-manifest.json').write_text(json.dumps(value), encoding='utf-8')
            with patch.object(scope, 'HERE', stage):
                publisher = scope.load_base()
            self.assertEqual(len(publisher.validate(value, stage)), len(value['files']))
            with self.assertRaisesRegex(ValueError, 'existing_admission_fence'):
                publisher.restart_for(value)
            unchanged = copy.deepcopy(value)
            for row in unchanged['files']:
                row['beforeSha256'] = row['sha256']
            with patch('subprocess.run') as service:
                publisher.restart_for(unchanged)
                service.assert_not_called()
            events = []
            class Fence:
                root = Path(tmp)/'host'
                def stop_then_unlock_database(self):
                    events.append('fence_stop_range')
            fence = Fence()
            key = fence.root/'run/fs-hermes-fc/api-key'
            key.parent.mkdir(parents=True)
            key.write_text('offline-fixture-only', encoding='ascii')
            with patch('subprocess.run', side_effect=lambda command, **kwargs: events.append(command)), \
                    patch('urllib.request.urlopen', side_effect=lambda *args, **kwargs: BytesIO(b'{"ok":true}')):
                publisher.restart_for(value, fence)
            self.assertEqual(events, ['fence_stop_range',
                ['systemctl','restart','fs-hermes-fc.service'],
                ['systemctl','is-active','--quiet','fs-hermes-fc.service'],
                ['systemctl','restart','fs-business-range.service'],
                ['systemctl','is-active','--quiet','fs-business-range.service']])


if __name__ == '__main__':
    unittest.main()
