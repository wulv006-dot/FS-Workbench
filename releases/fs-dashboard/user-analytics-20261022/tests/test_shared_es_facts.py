"""Shared closed-day publication and indexed scope reads against the existing Store."""
from contextlib import closing
from hashlib import sha256
from pathlib import Path
import sqlite3
import sys
import tempfile
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
import shared_es_facts as facts
import user_weekly as weekly
from user_contract import digest, stamp
from user_store import Store

D1, D2, D3 = '2026-11-10', '2026-11-11', '2026-11-12'


def order(number, day, site='266', gid='1327'):
    return dict(id=1, order_no=number, site_id=site, gid=gid, paytime=day + ' 13:15:14',
                pay_status=1, status_format='已完成', amount_usd_format='5.42',
                site={'full_title': site + '.example.test'}, email='private@example.test')


def line(number, day, product='gold'):
    return {'订单号': sha256(number.encode()).hexdigest(), '付款时间': day + ' 13:15:14',
            '_signature': digest([number, day, product]), '产品类型': product,
            'marketing_attribution': {'channel': 'SEO', 'status': 'available'}}


def archive(*lines):
    return dict(_private_dataset=True, revision_selection='published_pins',
                status='available', hashes=['a' * 64], failed_files=0, parse_failures=0, rows=list(lines))


def scope(start=D1, end=D1, site='266', gid='1327'):
    return dict(start=start, end=end, site_id=site, gid=gid)


def publication(cutoff, suffix='a'):
    value = dict(contract=weekly.CONTRACT, cutoff=stamp(cutoff).isoformat(),
                 published_at=stamp(cutoff + 'T04:22:00+08:00').isoformat(), captured_at=None,
                 cadence='daily', data_version='1', config={'sites': {'266': {}}}, jobs=[],
                 flag_manifests=[{'name': suffix * 64 + '.json', 'sha256': suffix * 64}],
                 refresh_health={}, coverage_context={}, source_status_rule_versions=[])
    value['publication_id'] = 'uw_' + digest(value)[:32]
    return value


class SharedFacts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store.__new__(Store)
        self.store.root = Path(tmp.name)
        self.store.path = Path(tmp.name) / 'customers.sqlite3'
        self.store.read_only = False
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
            db.execute("INSERT INTO meta VALUES('revision','1')")

    def stage(self, day, dataset, *orders, ref='test', tracking=None):
        return facts.stage_day(self.store, day, ref, dataset, orders, tracking or {},
                               day + 'T14:00:00+08:00')

    def read(self, query=None, ident=None):
        return facts.read(query or scope(), db=self.store.path, publication_id=ident)

    def test_scoped_read_retains_multiline_and_cross_site_identity_but_no_private_fields(self):
        rev1 = self.stage(D1, archive(line('same', D1), line('same', D1, 'item'),
                                      line('only-d4', D1)), order('same', D1),
                          order('only-d4', D1, gid='456'),
                          tracking={('266', 'same'): {'coupons': []}})
        rev2 = self.stage(D2, archive(line('same', D2)), order('same', D2, site='300', gid='456'))
        self.assertEqual(self.read()['status'], 'unavailable')
        pub = publication(D3)
        weekly.write_publication(self.store, pub, None, shared_revisions={D1: rev1, D2: rev2})
        result = self.read(scope(D1, D2))
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['rows'][0]['tracking'], {'coupons': []})
        self.assertNotIn('email', result['rows'][0])
        self.assertEqual({row['产品类型'] for row in result['dataset']['rows']}, {'gold', 'item'})
        self.assertEqual({row['site_id'] for row in result['identity_catalog']['rows']}, {'266', '300'})
        self.assertEqual(result['coverage']['source_revision'],
                         self.read(scope(D1, D2, gid='456'))['coverage']['source_revision'])

    def test_update_reuses_previous_days_and_keeps_fixed_publication(self):
        old_rev = self.stage(D1, archive(line('old', D1)), order('old', D1))
        first = publication(D2)
        weekly.write_publication(self.store, first, None, shared_revisions={D1: old_rev})
        new_rev = self.stage(D1, archive(line('corrected', D1)), order('corrected', D1), ref='new')
        next_day = self.stage(D2, archive())
        next_pub = publication(D3, 'b')
        weekly.write_publication(self.store, next_pub, first['publication_id'],
                                 shared_revisions={D1: new_rev, D2: next_day})
        self.assertEqual(self.read()['rows'][0]['order_no'], 'corrected')
        self.assertEqual(self.read(ident=first['publication_id'])['rows'][0]['order_no'], 'old')
        self.assertEqual(self.read(scope(D2, D2))['status'], 'available')
        self.assertEqual(self.read(scope(D1, D3))['coverage']['missing_days'], [D3])
        self.assertEqual(self.read(scope(D3, D3))['status'], 'unavailable')

    def test_bad_stage_rolls_back_whole_publication(self):
        rev = self.stage(D1, archive(line('old', D1)), order('old', D1))
        first = publication(D2)
        weekly.write_publication(self.store, first, None, shared_revisions={D1: rev})
        second = publication(D3, 'b')
        with self.assertRaisesRegex(ValueError, 'shared_es_publication_stage_mismatch'):
            weekly.write_publication(self.store, second, first['publication_id'],
                                     shared_revisions={D1: rev, D2: 'missing'})
        self.assertEqual(self.read()['coverage']['publication_id'], first['publication_id'])
        self.assertEqual(self.read(ident=second['publication_id'])['status'], 'unavailable')

    def test_prepare_resumes_existing_day_without_second_native_pull(self):
        pub = publication(D3)
        reader = Mock(side_effect=[([order('one', D1)], {}), ([order('two', D2)], {})])
        workbooks = Mock(return_value=archive(line('one', D1), line('two', D2)))
        self.assertIsNone(facts.prepare_publication(self.store, pub, D1, D2, reader=reader,
                                                   archive=workbooks,
                                                   checkpoint=Mock(side_effect=[False, True])))
        revisions = facts.prepare_publication(self.store, pub, D1, D2, reader=reader, archive=workbooks)
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(set(revisions), {D1, D2})
        self.assertEqual(facts.prepare_publication(self.store, pub, D1, D2, reader=reader,
                                                   archive=workbooks), revisions)
        self.assertEqual(workbooks.call_count, 2)

    def test_current_month_review_rule_keeps_old_inflight_bounds(self):
        cutoff = stamp('2026-11-16')
        self.assertEqual(weekly.calendar_review_start(cutoff, weekly.REVIEW_POLICY), stamp('2026-09-01'))
        self.assertEqual(weekly.calendar_review_start(cutoff, weekly.CURRENT_MONTH_POLICY), stamp('2026-11-01'))

    def test_seed_uses_existing_files_and_leaves_user_publication_unchanged(self):
        first = publication(D2)
        weekly.write_publication(self.store, first, None)
        root = self.store.path.parent
        manifest = root / ('a' * 64 + '.json')
        manifest.write_text('{"query":{"profile":"ALL","status":"all","start":"2026-11-10","end":"2026-11-10"},'
                            '"captured_at":"2026-11-11T05:00:00+08:00","file_sha256":["source"],'
                            '"file_set":{"failed_files":0,"declared_files":1}}', encoding='utf-8')
        # Manifest selection already has private file mode/owner coverage in its own tests.
        pin = dict(name=manifest.name, sha256=sha256(manifest.read_bytes()).hexdigest())
        reader = Mock(return_value=([order('one', D1)], {}))
        workbook = Mock(return_value=archive(line('one', D1)))
        with patch('user_customer_types.manifest_inventory', return_value=[pin]):
            opts = dict(now='2026-11-13T04:00:00+08:00', archive_root=root, reader=reader, archive=workbook)
            preview = facts.seed(self.store, D1, D2, **opts)
            self.assertEqual(preview['missing_es_days'], [D2])
            self.assertEqual(preview['needs_native_identity_days'], [D1])
            reader.assert_not_called()
            applied = facts.seed(self.store, D1, D2, apply=True, **opts)
            reused = facts.seed(self.store, D1, D2, apply=True, **opts)
        self.assertEqual(applied['status'], 'partial')
        self.assertTrue(applied['publication_id'].startswith('se_'))
        self.assertEqual(reused['already_indexed'], [D1])
        reader.assert_called_once_with(D1)
        self.assertEqual(weekly.stored_publication(self.store), first)
        self.assertEqual(self.read()['coverage']['publication_id'], applied['publication_id'])

    def test_daily_publication_survives_independent_shared_mapping_failure(self):
        pub = publication(D2)
        weekly.write_publication(self.store, pub, None, shared_window=(D1, D2, None))
        with patch('shared_es_facts.prepare_publication', side_effect=OSError('fixture')):
            result = weekly.retry_shared_es(self.store, lambda: False)
        self.assertEqual(result[pub['publication_id']], {'status': 'pending', 'reason': 'OSError', 'retryable': True})
        self.assertEqual(weekly.stored_publication(self.store), pub)
        self.assertEqual(self.read()['status'], 'unavailable')

    def test_shared_publish_resume_after_commit_does_not_move_newer_active_pin(self):
        rev = self.stage(D1, archive(line('first', D1)), order('first', D1))
        first = publication(D2)
        weekly.write_publication(self.store, first, None, shared_window=(D1, D2, None))
        with self.store.db() as db:
            facts.bind_publication(db, first, None, {D1: rev})
        with patch('shared_es_facts.prepare_publication', side_effect=AssertionError('shared day already committed')):
            result = weekly.retry_shared_es(self.store, lambda: False)
            self.assertEqual(result[first['publication_id']]['status'], 'complete')
            self.assertEqual(weekly.retry_shared_es(self.store, lambda: False), {})
        later = publication(D3, 'b')
        with self.store.db() as db:
            facts.bind_publication(db, later, None, {})
            facts.bind_publication(db, first, None, {D1: rev})
            with self.assertRaisesRegex(ValueError, 'shared_es_publication_replay_conflict'):
                facts.bind_publication(db, first, None, {D1: 'different'})
            with self.assertRaisesRegex(ValueError, 'shared_es_publication_replay_conflict'):
                facts.bind_publication(db, dict(first, data_version='2'), None, {D1: rev})
        self.assertEqual(facts.latest_publication(db=self.store.path)['publication_id'], later['publication_id'])
        self.assertEqual(self.read(ident=first['publication_id'])['rows'][0]['order_no'], 'first')

    def test_cross_month_failed_days_keep_pins_and_catch_up_after_new_publication(self):
        old_day, start, cutoff = '2026-10-31', '2026-11-01', '2026-11-02'
        old = publication(start)
        new = publication(cutoff, 'b')
        weekly.write_publication(self.store, old, None, shared_window=(old_day, start, None))
        old_rev = self.stage(old_day, archive(line('old', old_day)), order('old', old_day))
        new_rev = self.stage(start, archive(line('new', start)), order('new', start))

        def failed_old(store, value, start_day, end_day, **_):
            if start_day == old_day:
                self.assertEqual(value['flag_manifests'], old['flag_manifests'])
                raise OSError('fixture')
            self.assertEqual(value['flag_manifests'], new['flag_manifests'])
            return {start: new_rev}

        with patch('shared_es_facts.prepare_publication', side_effect=failed_old):
            weekly.retry_shared_es(self.store, lambda: False)
            weekly.write_publication(self.store, new, old['publication_id'], shared_window=(start, cutoff, None))
            weekly.retry_shared_es(self.store, lambda: False)
        self.assertEqual(weekly.stored_publication(self.store), new)
        self.assertEqual(self.read(scope(old_day, start))['coverage']['missing_days'], [old_day])
        self.assertEqual([pending['pin']['publication_id'] for pending in facts.pending_publications(self.store)],
                         [old['publication_id']])
        from user_customer_types import archive_reference_state
        refs = archive_reference_state(self.store, self.store.root)
        self.assertEqual(set(refs['manifests']), {old['flag_manifests'][0]['name'], new['flag_manifests'][0]['name']})
        with patch('shared_es_facts.prepare_publication', return_value={old_day: old_rev}):
            weekly.retry_shared_es(self.store, lambda: False)
        current = self.read(scope(old_day, start))
        self.assertEqual(current['status'], 'available')
        self.assertEqual(current['coverage']['data_revision'], new['data_version'])
        self.assertEqual(self.read(scope(old_day, start), ident=new['publication_id'])['coverage']['missing_days'], [old_day])
        self.assertEqual(facts.pending_publications(self.store), [])

    def test_multi_day_run_prepares_all_missing_dates_from_publication_start(self):
        cutoff = '2026-11-13'
        old = publication(D1)
        candidate = publication(cutoff, 'b')
        weekly.write_publication(self.store, old, None)
        state = dict(contract='fs-users-weekly-work-v1', phase='publish', cadence='daily',
                     start=stamp(D1).isoformat(), cutoff=stamp(cutoff).isoformat(), base_publication=old['publication_id'])
        revisions = {day: self.stage(day, archive(line(day, day)), order(day, day)) for day in (D1, D2, D3)}
        self.store.config = {'sites': {'266': {}}}
        with patch.dict(sys.modules, user_jobs=Mock()), \
                patch.object(self.store, 'coverage', return_value=[]), patch('user_lifecycle.covered', return_value=True), \
                patch.object(weekly, 'snapshot_candidate', return_value=(candidate, {})), \
                patch('shared_es_facts.prepare_publication', return_value=revisions) as prepare:
            result = weekly.run(self.store, state, old, stamp(cutoff + 'T04:18:00+08:00'), lambda: 0, shared_es=True)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(prepare.call_args.args[2:4], (D1, D3))
        self.assertEqual(self.read(scope(D1, D3))['coverage']['missing_days'], [])

    def test_closed_day_old_archive_receipt_uses_one_original_fresh_cycle(self):
        from user_customer_types import closed_period_bundle
        root = self.store.root
        index, attempt, legacy = (root / name for name in ('old.json', 'orig.attempt', 'legacy.attempt'))
        index.touch()
        snapshot = dict(value=dict(captured_at=D1 + 'T15:48:00+08:00', quality=dict(source_origin='private_archive_reuse')))
        es = SimpleNamespace(checked_query=lambda q: q, SERVER_LOCK=RLock(),
                             _receipt_paths=Mock(return_value=(index, attempt, legacy)),
                             _read_receipt=Mock(return_value=(dict(value=dict(status='available', snapshots=[snapshot])), 'fixture')),
                             _server_bundle=Mock(), server_bundle_after=Mock(return_value={'status': 'pending'}))
        query, cutoff = dict(start=D1, end=D1), stamp(D2)
        with patch.dict(sys.modules, es_order_structure=es):
            closed_period_bundle(query, cutoff, root)
            first = es.server_bundle_after.call_args
            closed_period_bundle(query, cutoff, root)
            self.assertEqual(es.server_bundle_after.call_args, first)
            es._server_bundle.assert_not_called()
            attempt.touch()
            closed_period_bundle(query, cutoff, root)
        self.assertEqual(es.server_bundle_after.call_count, 2)
        es._server_bundle.assert_called_once()

