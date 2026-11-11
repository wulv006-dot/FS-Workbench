"""Isolated offline overlay tests; no network, publisher execution or Git writes."""
import copy
import importlib.util
import json
from pathlib import Path
from unittest import mock
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('email_overlay', ROOT / 'tools/prepare_order_email_knowledge.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
COMMIT = 'a' * 40


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def row(identity, revision, path, data, layer='current', status='effective'):
    return dict(id=identity, revision=revision, layer=layer, status=status, modules=['FS'],
                owner='fixture', effective_at='2026-11-11', authority='git', source_commit='a' * 40,
                supersedes=[], provenance=[{'kind': 'fixture'}],
                source=dict(path=path, sha256=builder.sha(data), hash_basis='utf8_lf'))


class OverlayTest(unittest.TestCase):
    def setUp(self):
        def pinned_fixture(root, commit, name):
            self.assertEqual(commit, COMMIT)
            return (Path(root) / name).read_bytes()
        patch = mock.patch.object(builder, 'git_bytes', side_effect=pinned_fixture)
        patch.start()
        self.addCleanup(patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.snapshot, self.output = self.base / 'snapshot', self.base / 'stage'
        self.old = {}
        task, native = [], []
        for n in range(3):
            prefix = 'knowledge-releases/old-' + str(n)
            sources = prefix + '/sources'
            baseline = ('old baseline ' + str(n) + '\r\n').encode()
            fc = ('independent FC revision ' + str(n)).encode()
            entries = [row('fs.data.sources', 'old-' + str(n), 'baseline.md', baseline.replace(b'\r\n', b'\n')),
                       row('fc.pricing.v3', 'live-fc-' + str(n), 'fc.md', fc),
                       row('fs.data.sources', 'history-' + str(n), 'baseline.md', baseline.replace(b'\r\n', b'\n'), 'archive', 'superseded')]
            index = dict(contract='fs-knowledge-index-v1', release='old-' + str(n), release_state='published',
                         source_commit='a' * 40, source_root=sources, entries=entries)
            raw = builder.encoded(index)
            name = prefix + '/index.json'
            write(self.snapshot / name, raw)
            write(self.snapshot / sources / 'baseline.md', baseline)
            write(self.snapshot / sources / 'fc.md', fc)
            write(self.snapshot / sources / 'unreferenced.txt', b'keep me exactly\r\n')
            self.old[name] = (copy.deepcopy(index), raw)
            route = dict(catalog=name, sha256=builder.sha(raw), modules=['FS'], owner='fixture-' + str(n),
                         baseline_compatibility={'mode': 'retain_full_baseline', 'sha256': 'b' * 64},
                         reviewed_skills={'source': 'approved_current'}, history_entry_ids=['fs.data.sources'])
            if n == 2:
                route.update(platform='desktop', profile_name='default', session_ids=['original-session'])
                native.append(route)
            else:
                route.update(entry_ids=['fs.data.sources', 'fc.pricing.v3'], channel='fs', project='FS',
                             task_types=['conversation'], thread_id=None)
                task.append(route)
        self.policy = dict(contract='fs-knowledge-load-policy-v1', requests={},
                           task_routes={'enabled': True, 'routes': task},
                           native={'enabled': True, 'routes': native, 'readonly_sessions': {'unchanged': ['binding']}})
        write(self.snapshot / 'policy.json', builder.encoded(self.policy))

    def prepare(self):
        return builder.prepare(ROOT, self.snapshot, self.output, COMMIT)

    def test_independent_catalogs_preserved_and_selected(self):
        result = self.prepare()
        self.assertEqual(result['catalog_count'], 3)
        manifest = result['manifest']
        self.assertFalse(manifest['releaseReady'])
        self.assertTrue(manifest['knowledgeOnly'])
        self.assertFalse(manifest['businessWrites'])
        self.assertFalse(manifest['timersChanged'])
        runtime = [r for r in manifest['files'] if r['candidate'].startswith('runtime/')]
        self.assertEqual([r['candidate'] for r in runtime], ['runtime/knowledge-load-policy.json'])
        self.assertTrue(all(r['beforeSha256'] is None for r in manifest['files']))
        policy = json.loads((self.output / 'candidate/runtime/knowledge-load-policy.json').read_bytes())
        self.assertEqual(policy['native']['readonly_sessions'], self.policy['native']['readonly_sessions'])
        module = builder.pinned_module(ROOT, COMMIT, builder.MODULE + '/source/knowledge_catalog.py')
        for before, after in zip(builder.routes(self.policy), builder.routes(policy)):
            before_other = {k: v for k, v in before.items() if k not in ('catalog', 'sha256', 'entry_ids')}
            self.assertEqual(before_other, {k: v for k, v in after.items() if k not in ('catalog', 'sha256', 'entry_ids')})
            if 'entry_ids' in before:
                self.assertEqual(after['entry_ids'], before['entry_ids'] + [builder.EMAIL])
            selected = module.select(self.output / 'validation-fs-root', after['catalog'], after['sha256'], after['modules'], after.get('entry_ids'))
            self.assertEqual(selected['status'], 'available')
            index = json.loads((self.output / 'validation-fs-root' / after['catalog']).read_bytes())
            old, raw = self.old[before['catalog']]
            self.assertEqual([r for r in index['entries'] if r['id'] == 'fc.pricing.v3'], [old['entries'][1]])
            self.assertIn(old['entries'][2], index['entries'])
            tree = self.output / 'validation-fs-root' / index['source_root']
            self.assertEqual((tree / 'baseline.md').read_bytes(), (self.snapshot / old['source_root'] / 'baseline.md').read_bytes())
            self.assertEqual((tree / 'unreferenced.txt').read_bytes(), b'keep me exactly\r\n')
            for r in index['entries']:
                if r['id'] in builder.OVERLAYS and r['layer'] == 'current':
                    self.assertTrue(r['source']['path'].startswith('overlay/'))
                    self.assertEqual((tree / r['source']['path']).read_bytes(), builder.git_bytes(ROOT, COMMIT, r['source']['canonical_path']))
            self.assertIn(raw, [p.read_bytes() for p in (self.output / 'candidate/artifact/originals').rglob('index.json')])
        for r in manifest['files']:
            self.assertEqual(builder.sha((self.output / 'candidate' / r['candidate']).read_bytes()), r['sha256'])
        self.assertEqual((self.output / 'release.py').read_bytes(), builder.git_bytes(ROOT, COMMIT, builder.MODULE + '/deploy/release.py'))

    def test_missing_candidate_retained_without_becoming_current(self):
        name = next(iter(self.old))
        index = copy.deepcopy(self.old[name][0])
        index['entries'].append(row('fs.optional.candidate', 'draft', 'missing.md', b'draft', 'candidate', 'proposed'))
        raw = builder.encoded(index)
        write(self.snapshot / name, raw)
        self.policy['task_routes']['routes'][0]['sha256'] = builder.sha(raw)
        write(self.snapshot / 'policy.json', builder.encoded(self.policy))
        self.prepare()
        current = json.loads((self.output / 'candidate/artifact/index.json').read_bytes())
        self.assertIn(index['entries'][-1], current['entries'])
        self.assertFalse((self.output / 'candidate/artifact/sources/missing.md').exists())

    def test_catalog_drift_rejected(self):
        name = next(iter(self.old))
        write(self.snapshot / name, b'{}')
        with self.assertRaisesRegex(ValueError, 'snapshot_catalog_changed'):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_source_drift_rejected(self):
        old = next(iter(self.old.values()))[0]
        write(self.snapshot / old['source_root'] / 'fc.md', b'wrong')
        with self.assertRaisesRegex(ValueError, 'snapshot_source_changed'):
            self.prepare()

    def test_path_escape_rejected(self):
        self.policy['task_routes']['routes'][0]['catalog'] = '../escape.json'
        write(self.snapshot / 'policy.json', builder.encoded(self.policy))
        with self.assertRaisesRegex(ValueError, 'unsafe_snapshot_path'):
            self.prepare()

    def test_full_commit_and_existing_output_required(self):
        with self.assertRaisesRegex(ValueError, 'full_source_commit_required'):
            builder.prepare(ROOT, self.snapshot, self.output, 'HEAD')
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, 'stage_already_exists'):
            self.prepare()

    def test_repeated_catalog_and_request_bindings(self):
        request = copy.deepcopy(self.policy['task_routes']['routes'][0])
        self.policy['requests']['original-request'] = request
        write(self.snapshot / 'policy.json', builder.encoded(self.policy))
        self.assertEqual(self.prepare()['catalog_count'], 3)
        policy = json.loads((self.output / 'candidate/runtime/knowledge-load-policy.json').read_bytes())
        self.assertEqual(policy['requests']['original-request']['owner'], request['owner'])
        self.assertEqual(policy['requests']['original-request']['catalog'], policy['task_routes']['routes'][0]['catalog'])

    def test_repeated_catalog_hash_conflict_rejected(self):
        request = copy.deepcopy(self.policy['task_routes']['routes'][0])
        request['sha256'] = '0' * 64
        self.policy['requests']['original-request'] = request
        write(self.snapshot / 'policy.json', builder.encoded(self.policy))
        with self.assertRaisesRegex(ValueError, 'snapshot_catalog_changed|snapshot_catalog_hash_conflict'):
            self.prepare()


if __name__ == '__main__':
    unittest.main()
