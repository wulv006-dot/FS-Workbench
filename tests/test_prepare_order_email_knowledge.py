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


class SharedAdminESOverlayTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.snapshot = Path(temp.name) / 'snapshot'
        self.output = Path(temp.name) / 'stage'
        self.git = {}
        for revision in (builder.SHARED_BASE_COMMIT, COMMIT):
            release = builder.SHARED_BASE_RELEASE if revision == builder.SHARED_BASE_COMMIT else builder.SHARED_ADMIN_ES
            entries = []
            for identity in builder.SHARED_OVERLAYS:
                path = 'canonical/' + identity + '.md'
                data = b'## Anchor\n\n'
                if revision == COMMIT:
                    data += b'D5 shared method.\n\n'
                data += b'Common context.\n\nCanonical method.\n'
                item = row(identity, release, path, data)
                item['knowledge_updated_at'] = '2026-11-13'
                entries.append(item)
                self.git[revision, path] = data
            self.git[revision, 'knowledge/index.json'] = builder.encoded(dict(
                contract='fs-knowledge-index-v1', release=release, release_state='candidate',
                source_commit=None, base_commit=builder.SHARED_BASE_COMMIT, entries=entries))
        baseline = b'Actual active FC rules.\n'
        baseline_digest = builder.sha(baseline)
        write(self.snapshot / 'business-baseline.md', baseline)
        self.git[COMMIT, builder.BASELINE_SOURCE] = baseline
        self.git[COMMIT, builder.BASELINE_SOURCE.replace('.md', '.provenance.json')] = builder.encoded(dict(
            contract='fc-current-baseline-patch-v1', runtime_source=builder.BASELINE_SOURCE,
            after_sha256=baseline_digest, canonical_sha256='b' * 64))
        self.info = dict(captured_at='2026-11-13T05:05:52Z', protected={builder.BASELINE_TARGET: baseline_digest},
                         immutable_directories=[], runtime={n: {'ActiveState': 'active'} for n in
                                                          ('fs-hermes-fc.service', 'fs-business-range.service')})
        routes = []
        for number in range(2):
            prefix = f'knowledge-releases/live-{number}'
            catalog_path = prefix + '/index.json'
            entries = []
            shared = builder.SHARED_OVERLAYS if number == 0 else builder.SHARED_OVERLAYS[:-1]
            current_r2 = (*shared, 'fs.data.sources')
            for identity in (*current_r2, 'fs.learning.methods', 'fc.pricing.v3', builder.EMAIL):
                revision = builder.SHARED_BASE_RELEASE if identity in current_r2 else f'live-{number}'
                prefix_path = 'overlay/' + revision + '/' if identity in current_r2 else 'entries/'
                path = prefix_path + identity + '.md'
                data = (f'## Anchor\n\nCommon context.\n\nOriginal live wording {number}.\n').encode()
                item = row(identity, revision, path, data)
                item['unrelated_metadata'] = number
                entries.append(item)
                self.put_snapshot(prefix + '/sources/' + path, data)
            self.put_snapshot(catalog_path, builder.encoded(dict(
                contract='fs-knowledge-index-v1', release=f'live-{number}', release_state='published',
                source_commit=COMMIT, source_root=prefix + '/sources', entries=entries)))
            routes.append(dict(catalog=catalog_path, sha256=self.info['protected'][builder.FS_RUNTIME_ROOT + catalog_path],
                               owner='original-owner', modules=['FS'],
                               entry_ids=[e['id'] for e in entries],
                               baseline_compatibility={'mode': 'retain_full_baseline', 'sha256': baseline_digest}))
        self.policy = dict(contract='fs-knowledge-load-policy-v1', requests={'first': routes[0]},
                           task_routes={'routes': [routes[1]]})
        self.write_preflight()
        patch = mock.patch.object(builder, 'git_bytes', side_effect=self.git_blob)
        patch.start()
        self.addCleanup(patch.stop)

    def git_blob(self, root, commit, name):
        if (commit, name) in self.git:
            return self.git[commit, name]
        return (Path(root) / name).read_bytes()

    def put_snapshot(self, name, data):
        write(self.snapshot / name, data)
        self.info['protected'][builder.FS_RUNTIME_ROOT + name] = builder.sha(data)

    def write_preflight(self):
        write(self.snapshot / 'policy.json', builder.encoded(self.policy))
        write(self.snapshot / 'preflight.json', builder.encoded(self.info))

    def prepare(self):
        return builder.prepare(ROOT, self.snapshot, self.output, COMMIT, shared_admin_es=True)

    def test_only_existing_shared_sections_overlay_and_live_baseline_stays_bound(self):
        value = self.prepare()
        manifest = value['manifest']
        self.assertFalse(manifest['releaseReady'])
        self.assertEqual(value['release'], builder.SHARED_ADMIN_ES + '-' + COMMIT)
        self.assertIn(dict(path=builder.BASELINE_TARGET, sha256=self.info['protected'][builder.BASELINE_TARGET]),
                      manifest['unchangedRequired'])
        runtime = [r for r in manifest['files'] if r['candidate'].startswith('runtime/')]
        self.assertEqual([r['candidate'] for r in runtime], ['runtime/knowledge-load-policy.json'])
        self.assertEqual(runtime[0]['beforeSha256'], builder.sha((self.snapshot / 'policy.json').read_bytes()))
        self.assertTrue(all(r['beforeSha256'] is None for r in manifest['files'] if r not in runtime))
        staged = self.output / 'candidate'
        policy = json.loads((staged / 'runtime/knowledge-load-policy.json').read_bytes())
        for number, (before, after) in enumerate(zip(builder.routes(self.policy), builder.routes(policy))):
            self.assertEqual({k: v for k, v in before.items() if k not in ('catalog', 'sha256')},
                             {k: v for k, v in after.items() if k not in ('catalog', 'sha256')})
            index = json.loads((staged / 'artifact' / '/'.join(after['catalog'].split('/')[2:])).read_bytes())
            old = json.loads((self.snapshot / before['catalog']).read_bytes())
            self.assertEqual([item['id'] for item in index['entries']], [item['id'] for item in old['entries']])
            for previous, item in zip(old['entries'], index['entries']):
                identity = item['id']
                if identity not in {'fc.marketing.attribution', 'fc.reporting.data'}:
                    self.assertEqual(item, previous)
                    if identity == 'fs.data.sources':
                        self.assertEqual(item['revision'], 'fs-fc-admin-es-shared-20261113-r2')
                    continue
                self.assertEqual(item['revision'], builder.SHARED_ADMIN_ES)
                self.assertEqual(item['unrelated_metadata'], number)
                self.assertEqual(item['modules'], previous['modules'])
                source = '/'.join(index['source_root'].split('/')[2:])
                self.assertNotEqual(item['source']['path'], previous['source']['path'])
                self.assertEqual((staged / 'artifact' / source / previous['source']['path']).read_bytes(),
                                 f'## Anchor\n\nCommon context.\n\nOriginal live wording {number}.\n'.encode())
                self.assertEqual((staged / 'artifact' / source / item['source']['path']).read_bytes(),
                                 f'## Anchor\n\nD5 shared method.\n\nCommon context.\n\nOriginal live wording {number}.\n'.encode())
            self.assertEqual('fc.reporting.data' in [r['id'] for r in index['entries']], number == 0)
        proof = json.loads((self.output / 'retained-baseline-provenance.json').read_bytes())
        self.assertEqual(proof['retained_sha256'], proof['existing_provenance']['after_sha256'])
        self.assertEqual([item['id'] for item in proof['overlays']],
                         ['fc.marketing.attribution', 'fc.reporting.data', 'fc.marketing.attribution'])
        self.assertEqual({item['previous_revision'] for item in proof['overlays']},
                         {'fs-fc-admin-es-shared-20261113-r2'})

    def test_missing_merge_context_refuses_candidate(self):
        name = self.policy['requests']['first']['catalog']
        index = json.loads((self.snapshot / name).read_bytes())
        row = index['entries'][0]
        data = b'Diverged live context.\n'
        row['source']['sha256'] = builder.sha(data)
        self.put_snapshot(index['source_root'] + '/' + row['source']['path'], data)
        self.put_snapshot(name, builder.encoded(index))
        self.policy['requests']['first']['sha256'] = self.info['protected'][builder.FS_RUNTIME_ROOT + name]
        self.write_preflight()
        with self.assertRaisesRegex(ValueError, 'shared_admin_es_snapshot_merge_conflict:fc.marketing.attribution'):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_affected_live_entry_must_be_at_r2(self):
        route = self.policy['requests']['first']
        name = route['catalog']
        index = json.loads((self.snapshot / name).read_bytes())
        index['entries'][0]['revision'] = 'fs-fc-admin-es-shared-20261113-r1'
        self.put_snapshot(name, builder.encoded(index))
        route['sha256'] = self.info['protected'][builder.FS_RUNTIME_ROOT + name]
        self.write_preflight()
        with self.assertRaisesRegex(ValueError, 'shared_admin_es_snapshot_revision_invalid:fc.marketing.attribution'):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_live_baseline_provenance_and_policy_binding_must_match(self):
        self.policy['requests']['first']['baseline_compatibility']['sha256'] = '0' * 64
        self.write_preflight()
        with self.assertRaisesRegex(ValueError, 'shared_admin_es_baseline_binding_drift'):
            self.prepare()
        write(self.snapshot / 'business-baseline.md', b'Different active FC rules.\n')
        with self.assertRaisesRegex(ValueError, 'shared_admin_es_retained_baseline_provenance_invalid'):
            self.prepare()
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
