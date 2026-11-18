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

    def test_email_only_refresh_keeps_route_ids_live_entries_and_baseline(self):
        catalog_name = next(iter(self.old))
        index, _ = self.old[catalog_name]
        email = b'old published email policy'
        index['entries'].append(row(builder.EMAIL, 'old-email', 'email.md', email))
        write(self.snapshot / index['source_root'] / 'email.md', email)
        raw = builder.encoded(index)
        write(self.snapshot / catalog_name, raw)
        route = self.policy['task_routes']['routes'][0]
        route['entry_ids'].append(builder.EMAIL)
        route['sha256'] = builder.sha(raw)
        policy_raw = builder.encoded(self.policy)
        write(self.snapshot / 'policy.json', policy_raw)
        baseline = b'live production baseline'
        write(self.snapshot / 'business-baseline.md', baseline)
        for route in builder.routes(self.policy):
            route['baseline_compatibility']['sha256'] = builder.sha(baseline)
        policy_raw = builder.encoded(self.policy)
        write(self.snapshot / 'policy.json', policy_raw)
        protected = {builder.FS_RUNTIME_ROOT + p.relative_to(self.snapshot).as_posix(): builder.sha(p.read_bytes())
                     for p in (self.snapshot / 'knowledge-releases').rglob('*') if p.is_file()}
        protected[builder.BASELINE_TARGET] = builder.sha(baseline)
        write(self.snapshot / 'preflight.json', builder.encoded(dict(captured_at='2026-11-18', protected=protected,
              immutable_directories=[], runtime={u: {'ActiveState': 'active'} for u in
                  ('fs-hermes-fc.service', 'fs-business-range.service')})))
        manifest = builder.prepare(ROOT, self.snapshot, self.output, COMMIT, email_only=True)['manifest']
        runtime = [r for r in manifest['files'] if r['candidate'].startswith('runtime/')]
        self.assertEqual(len(runtime), 1)
        self.assertEqual(runtime[0]['beforeSha256'], builder.sha(policy_raw))
        final = json.loads((self.output / 'candidate' / runtime[0]['candidate']).read_bytes())
        self.assertEqual([r.get('entry_ids') for r in builder.routes(final)],
                         [r.get('entry_ids') for r in builder.routes(self.policy)])
        updated = json.loads((self.output / 'candidate/artifact/index.json').read_bytes())
        self.assertEqual([r for r in updated['entries'] if r['id'] != builder.EMAIL],
                         [r for r in index['entries'] if r['id'] != builder.EMAIL])
        email_row = next(r for r in updated['entries'] if r['id'] == builder.EMAIL)
        self.assertIn(builder.EMAIL + '@old-email', email_row['supersedes'])

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

    def test_fc_v61_replaces_only_existing_ids_and_preserves_route_scope(self):
        templates=[]
        for identity in builder.FC_V61_OVERLAYS:
            path='canonical/'+identity+'.md'
            data=b'V6 average discount and native ALL propagation.\n'
            self.git[COMMIT,path]=data
            templates.append(row(identity,'fc_v6_d8_d2_amount_weighted_discount_v1',path,data))
        self.git[COMMIT,'knowledge/index.json']=builder.encoded(dict(
            contract='fs-knowledge-index-v1',release=builder.FC_V61,release_state='candidate',
            source_commit=None,entries=templates))
        first=self.policy['requests']['first']
        index=json.loads((self.snapshot/first['catalog']).read_bytes())
        data=b'Legacy margin scope.\n'
        item=row('fc.pricing.constraints','legacy-v4','entries/margin.md',data)
        index['entries'].append(item)
        self.put_snapshot(index['source_root']+'/entries/margin.md',data)
        self.put_snapshot(first['catalog'],builder.encoded(index))
        first['sha256']=self.info['protected'][builder.FS_RUNTIME_ROOT+first['catalog']]
        first['entry_ids'].append(item['id'])
        self.write_preflight()
        before=copy.deepcopy(list(builder.routes(self.policy)))
        result=builder.prepare(ROOT,self.snapshot,self.output,COMMIT,fc_v61=True)
        after=list(builder.routes(json.loads((self.output/'candidate/runtime/knowledge-load-policy.json').read_bytes())))
        self.assertEqual(result['release'],builder.FC_V61+'-'+COMMIT)
        for old,new in zip(before,after):
            self.assertEqual(old['entry_ids'],new['entry_ids'])
            self.assertEqual(old['owner'],new['owner'])
            slot=new['catalog'].split(result['release']+'/',1)[1]
            published=json.loads((self.output/'candidate/artifact'/slot).read_bytes())
            entries={r['id']:r for r in published['entries']}
            self.assertEqual(set(entries),set(old['entry_ids']))
            self.assertEqual(entries['fc.pricing.v3']['revision'],'fc_v6_d8_d2_amount_weighted_discount_v1')
            self.assertEqual(entries['fs.learning.methods']['unrelated_metadata'],
                             0 if old is before[0] else 1)
        self.assertEqual((self.output/'candidate/artifact/originals/policy.json').read_bytes(),
                         (self.snapshot/'policy.json').read_bytes())

    def set_fc_v61_candidate(self, revisions, data):
        path = 'canonical/HERMES-V61-CONTRACT.md'
        self.git[COMMIT, path] = data
        entries = [row(identity, revision, path, data)
                   for identity, revision in zip(builder.FC_V61_OVERLAYS, revisions)]
        if revisions == (builder.FC_V61_100K_MARKET_REVISION,) * 2:
            entries.append(row(builder.FC_V61_PARAMETER_ID, revisions[0], path, data))
            entries.append(row(builder.FC_V61_LEARNING_ID, revisions[0], path, data))
        if revisions in ((builder.FC_V61_WEEKLY_REVISION,) * 2, (builder.FC_V61_INSURANCE_REVISION,) * 2):
            entries.append(row(builder.FC_V61_PARAMETER_ID, revisions[0], path, data))
            entries.append(row('fs.procurement.inputs', revisions[0], path, data))
        if revisions == (builder.FC_V61_MARGIN_BAND_REVISION,) * 2:
            entries = [row(identity, revisions[0], path, data) for identity in builder.FC_V61_MARGIN_BAND_IDS]
        self.git[COMMIT, 'knowledge/index.json'] = builder.encoded(dict(
            contract='fs-knowledge-index-v1', release=builder.FC_V61, release_state='candidate',
            source_commit=None, entries=entries))
        return path

    def test_fc_v61_two_band_replaces_previous_rules_and_keeps_their_artifact(self):
        self.assert_fc_revision_migration('fc_v6_d8_d2_amount_weighted_discount_v1',
                                          'fc_v61_native_all_two_band_20261113')

    def test_fc_v61_100k_market_keeps_previous_two_band_artifact(self):
        self.assert_fc_revision_migration('fc_v61_native_all_two_band_20261113',
                                          'fc_v61_100k_market_two_band_20261113')

    def test_fc_v61_admin_only_updates_pricing_and_retains_prior_market_contract(self):
        self.assert_fc_revision_migration(builder.FC_V61_100K_MARKET_REVISION,
                                          'fc_v61_admin_only_two_band_20261113')

    def test_fc_v61_baseline_patch_preserves_original_and_updates_only_existing_binding(self):
        self.assert_fc_revision_migration('fc_v61_native_all_two_band_20261113',
                                          'fc_v61_100k_market_two_band_20261113', baseline_patch=True)

    def test_weekly_closeout_updates_four_existing_ids_and_baseline_without_expanding_routes(self):
        self.assert_fc_revision_migration(builder.FC_V61_MARKET_ANCHOR_REVISION,
                                          builder.FC_V61_WEEKLY_REVISION, baseline_patch=True)

    def test_insurance_limits_replace_previous_active_revision_and_preserve_routes(self):
        self.assert_fc_revision_migration(builder.FC_V61_WEEKLY_REVISION,
                                          builder.FC_V61_INSURANCE_REVISION, baseline_patch=True)

    def test_margin_band_updates_existing_pricing_learning_and_reporting_ids(self):
        self.assert_fc_revision_migration(builder.FC_V61_INSURANCE_REVISION,
                                          builder.FC_V61_MARGIN_BAND_REVISION, baseline_patch=True)

    def test_margin_band_refuses_to_overwrite_newer_live_reporting(self):
        self.assert_fc_revision_migration(builder.FC_V61_INSURANCE_REVISION,
                                          builder.FC_V61_MARGIN_BAND_REVISION, drift_reporting=True)

    def assert_fc_revision_migration(self, old_revision, new_revision, baseline_patch=False, drift_reporting=False):
        old_data = b'Original amount-weighted discount and ALL propagation.\n'
        new_data = b'Two native price bands and main catalogue readback.\n'
        canonical_path = self.set_fc_v61_candidate((new_revision, new_revision), new_data)
        overlay_ids = set(builder.FC_V61_OVERLAYS)
        if new_revision == builder.FC_V61_100K_MARKET_REVISION:
            overlay_ids.update((builder.FC_V61_PARAMETER_ID, builder.FC_V61_LEARNING_ID))
        if new_revision in (builder.FC_V61_WEEKLY_REVISION, builder.FC_V61_INSURANCE_REVISION):
            overlay_ids.update((builder.FC_V61_PARAMETER_ID, 'fs.procurement.inputs'))
        margin_band = new_revision == builder.FC_V61_MARGIN_BAND_REVISION
        if margin_band:
            overlay_ids = set(builder.FC_V61_MARGIN_BAND_IDS)
            base = builder.FC_V61_MARGIN_BAND_BASE
            self.git[base, canonical_path] = old_data
            self.git[base, 'knowledge/index.json'] = builder.encoded(dict(
                entries=[row(identity, old_revision, canonical_path, old_data) for identity in sorted(overlay_ids)]))
        old_path = 'overlay/' + canonical_path
        before = list(builder.routes(self.policy))
        for number, route in enumerate(before):
            index = json.loads((self.snapshot / route['catalog']).read_bytes())
            entries = index['entries']
            previous = next(r for r in entries if r['id'] == 'fc.pricing.v3')
            entries[entries.index(previous)] = row(previous['id'], old_revision, old_path, old_data)
            if builder.FC_V61_LEARNING_ID in overlay_ids:
                previous = next(r for r in entries if r['id'] == builder.FC_V61_LEARNING_ID)
                entries[entries.index(previous)] = row(previous['id'], old_revision, old_path, old_data)
            if number == 0:
                identity = 'fc.pricing.constraints'
                entries.append(row(identity, old_revision, old_path, old_data))
                route['entry_ids'].append(identity)
                if builder.FC_V61_PARAMETER_ID in overlay_ids:
                    identity = builder.FC_V61_PARAMETER_ID
                    entries.append(row(identity, old_revision, old_path, old_data))
                    route['entry_ids'].append(identity)
                if 'fs.procurement.inputs' in overlay_ids:
                    identity = 'fs.procurement.inputs'
                    entries.append(row(identity, old_revision, old_path, old_data))
                    route['entry_ids'].append(identity)
                if margin_band:
                    for identity in ('fc.reporting.business', 'fc.reporting.data'):
                        rev = 'newer-reporting' if drift_reporting else old_revision
                        updated = row(identity, rev, old_path, old_data)
                        if identity in route['entry_ids']:
                            position = next(i for i, r in enumerate(entries) if r['id'] == identity)
                            entries[position] = updated
                        else:
                            entries.append(updated)
                            route['entry_ids'].append(identity)
            self.put_snapshot(index['source_root'] + '/' + old_path, old_data)
            self.put_snapshot(route['catalog'], builder.encoded(index))
            route['sha256'] = self.info['protected'][builder.FS_RUNTIME_ROOT + route['catalog']]
        self.write_preflight()
        if baseline_patch:
            candidate = b'Current V6 rules; legacy scalar receipts retain their old protocol.\n'
            self.git[COMMIT, builder.BASELINE_SOURCE] = candidate
            proof_path = builder.BASELINE_SOURCE.replace('.md', '.provenance.json')
            proof = json.loads(self.git[COMMIT, proof_path])
            proof.update(before_sha256=proof['after_sha256'], after_sha256=builder.sha(candidate))
            self.git[COMMIT, proof_path] = builder.encoded(proof)
            del self.policy['task_routes']['routes'][0]['baseline_compatibility']
            self.write_preflight()
            before = copy.deepcopy(list(builder.routes(self.policy)))

        if drift_reporting:
            with self.assertRaisesRegex(ValueError, 'margin_band_live_entry_changed:fc.reporting'):
                builder.prepare(ROOT, self.snapshot, self.output, COMMIT, fc_v61=True)
            self.assertFalse(self.output.exists())
            return
        result = builder.prepare(ROOT, self.snapshot, self.output, COMMIT, fc_v61=True)
        self.assertEqual(result['release'], builder.FC_V61 + '-' + COMMIT)
        self.assertFalse(result['manifest']['releaseReady'])
        policy = json.loads((self.output / 'candidate/runtime/knowledge-load-policy.json').read_bytes())
        if baseline_patch:
            manifest = result['manifest']
            self.assertEqual(manifest['baselinePatch']['before_sha256'], proof['before_sha256'])
            self.assertEqual((self.output/'candidate/runtime/business-baseline.md').read_bytes(), candidate)
            self.assertEqual((self.output/'candidate/artifact/originals/business-baseline.md').read_bytes(),
                             (self.snapshot/'business-baseline.md').read_bytes())
            self.assertNotIn(builder.BASELINE_TARGET, [r['path'] for r in manifest['unchangedRequired']])
        for old, new in zip(before, builder.routes(policy)):
            expected = copy.deepcopy(old)
            if baseline_patch and 'baseline_compatibility' in expected:
                expected['baseline_compatibility']['sha256'] = proof['after_sha256']
            self.assertEqual({k: v for k, v in expected.items() if k not in ('catalog', 'sha256')},
                             {k: v for k, v in new.items() if k not in ('catalog', 'sha256')})
            slot = new['catalog'].split(result['release'] + '/', 1)[1]
            artifact = self.output / 'candidate/artifact'
            index = json.loads((artifact / slot).read_bytes())
            sources = artifact / index['source_root'].split(result['release'] + '/', 1)[1]
            self.assertEqual((sources / old_path).read_bytes(), old_data)
            selected = {r['id']: r for r in index['entries'] if r['id'] in overlay_ids}
            self.assertEqual(set(selected), set(old['entry_ids']) & overlay_ids)
            for identity, item in selected.items():
                self.assertEqual(item['revision'], new_revision)
                self.assertIn(identity + '@' + old_revision, item['supersedes'])
                self.assertEqual(item['source']['canonical_path'], canonical_path)
                self.assertEqual(item['source']['sha256'], builder.sha(new_data))
                self.assertNotEqual(item['source']['path'], old_path)
                self.assertEqual((sources / item['source']['path']).read_bytes(), new_data)

    def test_fc_v61_rejects_mixed_or_unregistered_revisions(self):
        old_revision = 'fc_v6_d8_d2_amount_weighted_discount_v1'
        new_revision = 'fc_v61_native_all_two_band_20261113'
        for revisions in ((old_revision, new_revision), ('unregistered', 'unregistered')):
            with self.subTest(revisions=revisions):
                self.set_fc_v61_candidate(revisions, b'Candidate.\n')
                with self.assertRaisesRegex(ValueError, 'exact_fc_v61_revision_required'):
                    builder.prepare(ROOT, self.snapshot, self.output, COMMIT, fc_v61=True)
                self.assertFalse(self.output.exists())

    def add_reporting_candidate(self):
        prior_commit = 'c51bb4f494523f19e6979cf5c85565dac94a4257'
        revisions = {
            'fc.reporting.business': ('20261110-three-platform-100k', '20261113-v61-reporting-business'),
            'fc.reporting.data': ('fs-fc-admin-es-shared-20261113-r4', '20261113-v61-reporting-data'),
            'fc.reporting.methods': ('20261105-2', '20261113-v61-reporting-entry'),
            'fs.data.sources': ('fs-fc-admin-es-shared-20261113-r2', '20261113-v61-reporting-sources'),
        }
        first = self.policy['requests']['first']
        second = self.policy['task_routes']['routes'][0]
        index = json.loads((self.snapshot / first['catalog']).read_bytes())
        other = json.loads((self.snapshot / second['catalog']).read_bytes())
        index['entries'] = [item for item in index['entries'] if item['id'] not in revisions]
        first['entry_ids'] = [identity for identity in first['entry_ids'] if identity not in revisions]
        prior, current = [], []
        for identity, (old_revision, revision) in revisions.items():
            path = 'canonical/' + identity + '.md'
            old_data, new_data = b'Original report source.\n', b'V6 report source.\n'
            selector = None
            if identity == 'fs.data.sources':
                selector = dict(start='## Selected', end='## End')
                old_data = b'## Selected\n\n' + old_data
                new_data = b'## Selected\n\n' + new_data
            self.git[prior_commit, path] = old_data
            self.git[COMMIT, path] = new_data
            prior.append(row(identity, old_revision, path, old_data))
            item = row(identity, revision, path, new_data)
            if selector:
                for commit, template, section in ((prior_commit, prior[-1], old_data), (COMMIT, item, new_data)):
                    full = b'Unrelated shared rules.\n\n' + section + b'\n## End\n'
                    self.git[commit, path] = full
                    template['source'].update(selector=selector, sha256=builder.sha(full))
            item['supersedes'] = [identity + '@' + old_revision]
            current.append(item)
            saved_path = 'entries/' + identity + '.md'
            saved = dict(row(identity, old_revision, saved_path, old_data), unrelated_metadata='original')
            index['entries'].append(saved)
            self.put_snapshot(index['source_root'] + '/' + saved_path, old_data)
            first['entry_ids'].append(identity)
            if selector:
                other['entries'] = [entry for entry in other['entries'] if entry['id'] != identity] + [copy.deepcopy(saved)]
                self.put_snapshot(other['source_root'] + '/' + saved_path, old_data)
        self.git[prior_commit, 'knowledge/index.json'] = builder.encoded({'entries': prior})
        self.git[COMMIT, 'knowledge/index.json'] = builder.encoded(dict(
            contract='fs-knowledge-index-v1', release=builder.FC_V61, release_state='candidate',
            source_commit=None, entries=current))
        self.put_snapshot(first['catalog'], builder.encoded(index))
        first['sha256'] = self.info['protected'][builder.FS_RUNTIME_ROOT + first['catalog']]
        self.put_snapshot(second['catalog'], builder.encoded(other))
        second['sha256'] = self.info['protected'][builder.FS_RUNTIME_ROOT + second['catalog']]
        self.write_preflight()
        return revisions, index

    def test_fc_v61_reporting_changes_three_reports_and_shared_source_section(self):
        revisions, original = self.add_reporting_candidate()
        result = builder.prepare(ROOT, self.snapshot, self.output, COMMIT, fc_v61_reporting=True)
        manifest = result['manifest']
        self.assertFalse(manifest['releaseReady'])
        self.assertNotIn('baselinePatch', manifest)
        self.assertEqual([r['candidate'] for r in manifest['files'] if r['candidate'].startswith('runtime/')],
                         ['runtime/knowledge-load-policy.json'])
        artifact = self.output / 'candidate/artifact'
        catalog = json.loads((artifact / 'index.json').read_bytes())
        self.assertEqual([item['id'] for item in catalog['entries']], [item['id'] for item in original['entries']])
        for before, after in zip(original['entries'], catalog['entries']):
            identity = before['id']
            if identity not in revisions:
                self.assertEqual(after, before)
                continue
            self.assertEqual(after['revision'], revisions[identity][1])
            self.assertEqual(after['unrelated_metadata'], 'original')
            heading = b'## Selected\n\n' if identity == 'fs.data.sources' else b''
            self.assertEqual((artifact / 'sources' / before['source']['path']).read_bytes(), heading + b'Original report source.\n')
            self.assertEqual((artifact / 'sources' / after['source']['path']).read_bytes(), heading + b'V6 report source.\n')
            self.assertNotIn('selector', after['source'])
        second = json.loads((artifact / 'catalog-1/index.json').read_bytes())
        second_entries = {item['id']: item for item in second['entries']}
        self.assertEqual(set(revisions) & set(second_entries), {'fs.data.sources'})
        self.assertEqual(second_entries['fs.data.sources']['revision'], revisions['fs.data.sources'][1])

    def test_fc_v61_reporting_refuses_unreviewed_live_content_even_at_the_expected_revision(self):
        _, original = self.add_reporting_candidate()
        route = self.policy['requests']['first']
        item = next(row for row in original['entries'] if row['id'] == 'fc.reporting.data')
        data = b'Extra active report guidance.\n'
        item['source']['sha256'] = builder.sha(data)
        self.put_snapshot(original['source_root'] + '/' + item['source']['path'], data)
        self.put_snapshot(route['catalog'], builder.encoded(original))
        route['sha256'] = self.info['protected'][builder.FS_RUNTIME_ROOT + route['catalog']]
        self.write_preflight()
        with self.assertRaisesRegex(ValueError, 'fc_v61_reporting_snapshot_source_changed:fc.reporting.data'):
            builder.prepare(ROOT, self.snapshot, self.output, COMMIT, fc_v61_reporting=True)
        self.assertFalse(self.output.exists())

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
