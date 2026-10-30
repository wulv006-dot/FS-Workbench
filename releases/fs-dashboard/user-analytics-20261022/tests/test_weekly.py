"""Weekly business epochs: invented facts, actual SQLite, no live Admin or services."""
from contextlib import ExitStack, nullcontext
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE/'source'))
from user_contract import checked_query, stamp
from user_query import Service
from user_store import Store
from user_http import get
import user_weekly as weekly
import user_customer_types as types
import user_jobs as jobs

FRIDAY = stamp('2026-10-30T21:18:00+08:00')
MONDAY = stamp('2026-11-02T04:18:00+08:00')
OLD = stamp('2026-10-26')


def row(n, day='2026-10-21', paid='1'):
    return dict(id=n, order_no='weekly-fixture-'+str(n), paytime=day, email='p%s@example.test'%n,
                uid=0, gid='1327', site_id='266', pay_status=paid, status='11')


class Dates(unittest.TestCase):
    def test_monday_and_shared_timer_window_use_beijing_time(self):
        self.assertEqual(weekly.monday(stamp('2026-11-01T23:59:59+08:00')), OLD)
        self.assertEqual(weekly.monday(MONDAY), stamp('2026-11-02'))
        for time, expected in [('04:17', False), ('04:18', True), ('04:48', True), ('05:00', False)]:
            self.assertEqual(weekly.window(stamp('2026-11-02T'+time+':00+08:00')), expected)

    def test_weekly_cutoff_rejects_newer_end_and_does_not_drift_current_observation(self):
        config = json.loads((BASE/'source/user_config.json').read_text('utf-8'))
        config['weekly_data_cutoff'] = OLD.isoformat()
        query = checked_query(dict(start='2026-10-19'), config, FRIDAY)
        self.assertEqual(query['end_exclusive'], OLD.isoformat())
        current = checked_query(dict(start='2026-10-19', end_exclusive=OLD.isoformat(), state_basis='current'), config, FRIDAY)
        self.assertEqual(stamp(current['as_of']).date().isoformat(), '2026-10-25')
        with self.assertRaisesRegex(ValueError, 'period_after_published_data'):
            checked_query(dict(start='2026-10-19', end_exclusive='2026-10-30', state_basis='period_end'), config, FRIDAY)



class WeeklyFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.config = json.loads((BASE/'source/user_config.json').read_text('utf-8'))
        self.config.update(snapshot_storage='recipe-v1', update_cadence='weekly-v1')
        self.store = Store(Path(self.tmp.name)/'private', b'x'*32, self.config)
        self.rows = [row(1), row(2, '2026-10-24')]
        self.store.replace_window('266', '2026-01-01', '2026-10-30', self.rows, FRIDAY.isoformat())
        self.flags = {hashlib.sha256(r['order_no'].encode()).hexdigest(): 'new' for r in self.rows}
        self.flag_info = dict(status='complete', source='fixture ES', sourceVersion='fixture-v1', files=1)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(types, 'read_pinned_flags', side_effect=lambda *a, **k: (dict(self.flags), dict(self.flag_info))))
        self.stack.enter_context(patch.object(types, 'manifest_inventory', return_value=[]))
        legacy = Service(self.store, lambda *_: True, clock=lambda: OLD,
                         customer_type_reader=lambda q: (dict(self.flags), dict(self.flag_info)), weekly_publication=False)
        public = legacy.query(dict(start='2026-10-19'), 'admin')
        self.publication = weekly.from_snapshot(self.store, public['snapshot_id'], OLD, [], FRIDAY.isoformat())
        weekly.write_publication(self.store, self.publication, None)
        weekly.record_state(self.store, dict(contract='fs-users-weekly-work-v1', cutoff=OLD.isoformat(), phase='complete'))
        self.allowed = True
        self.service = Service(self.store, lambda u, q, p: self.allowed and (u == 'admin' or u == 'reader' and not p), clock=lambda: FRIDAY)
        self.addCleanup(lambda: self.service.private_cache_timer.cancel() if self.service.private_cache_timer else None)


class PublishedQueries(WeeklyFixture):
    def test_default_previous_complete_week_and_daily_start_choice(self):
        value = self.service.query({}, 'admin')
        self.assertEqual(value['query']['start'], '2026-10-19T00:00:00+08:00')
        self.assertEqual(value['query']['end_exclusive'], OLD.isoformat())
        self.assertEqual(value['observation_date'], '2026-10-25')
        chosen = self.service.query(dict(start='2026-10-22'), 'admin')
        self.assertEqual(chosen['metrics']['purchasers']['value'], 1)
        self.assertEqual(chosen['weekly_update']['data_through'], '2026-10-25')

    def test_clock_and_unpublished_fact_changes_do_not_change_week(self):
        before = self.service.query({}, 'admin')
        self.store.replace_window('266', '2026-01-01', '2026-10-30', [row(1, paid='2'), *self.rows[1:], row(3, '2026-10-23')], FRIDAY.isoformat())
        self.service.clock = lambda: stamp('2026-11-01T23:59:59+08:00'); self.service.cache.clear()
        after = self.service.query({}, 'admin')
        self.assertEqual(after, before)
        self.assertEqual(self.service.members(dict(snapshot_id=before['snapshot_id'], group='purchasers'), 'admin')['total'], 2)

    def test_cache_hit_does_not_replay_or_parse_exports_again(self):
        with patch.object(self.store, 'read_at', wraps=self.store.read_at) as replay, patch.object(types, 'read_pinned_flags', return_value=(self.flags, self.flag_info)) as flags:
            a = self.service.query({}, 'admin'); b = self.service.query({}, 'admin')
            self.assertEqual(a, b); self.assertEqual(replay.call_count, 1); self.assertEqual(flags.call_count, 1)

    def test_temporary_pinned_export_failure_recovers_without_clearing_week_cache(self):
        with patch.object(types, 'read_pinned_flags', side_effect=OSError('fixture temporary read failure')) as reader:
            failed = self.service.query({}, 'admin')
            self.assertEqual(failed['customer_type_source']['status'], 'unavailable')
            self.assertEqual(reader.call_count, 1)
        self.assertEqual(len(self.service.cache), 0)
        with patch.object(types, 'read_pinned_flags', return_value=(self.flags, self.flag_info)) as reader:
            recovered = self.service.query({}, 'admin')
            self.assertEqual(recovered['customer_type_source']['status'], 'complete')
            self.assertEqual(self.service.query({}, 'admin'), recovered)
            self.assertEqual(reader.call_count, 1)
        self.assertNotEqual(recovered['snapshot_id'], failed['snapshot_id'])
        self.assertEqual(self.service.query(dict(snapshot_id=failed['snapshot_id']), 'admin'), failed)

    def test_partial_pinned_export_is_rechecked_until_complete(self):
        partial = dict(self.flag_info, status='partial')
        with patch.object(types, 'read_pinned_flags', side_effect=[({}, partial), (self.flags, self.flag_info)]) as reader:
            self.assertEqual(self.service.query({}, 'admin')['customer_type_source']['status'], 'partial')
            self.assertEqual(self.service.query({}, 'admin')['customer_type_source']['status'], 'complete')
            self.assertEqual(reader.call_count, 2)

    def test_permission_rechecked_before_warm_cache_or_fact_replay(self):
        self.service.query({}, 'admin'); self.allowed = False
        with patch.object(self.store, 'read_at', wraps=self.store.read_at) as replay:
            with self.assertRaises(PermissionError):self.service.query({}, 'admin')
            replay.assert_not_called()

    def test_all_history_current_state_is_frozen_to_same_observation_date(self):
        value = self.service.query(dict(start='2026-10-01', end_exclusive=OLD.isoformat(), state_basis='current'), 'admin')
        self.assertEqual(value['observation_date'], '2026-10-25')
        self.service.clock = lambda: stamp('2026-11-01')
        self.assertEqual(self.service.query(dict(start='2026-10-01', end_exclusive=OLD.isoformat(), state_basis='current'), 'admin'), value)

    def test_old_snapshot_id_bypasses_new_week_date_defaults(self):
        old = Service(self.store, lambda *_: True, clock=lambda: FRIDAY, weekly_publication=False).query(dict(start='2026-10-01'), 'admin')
        self.assertEqual(self.service.query(dict(snapshot_id=old['snapshot_id']), 'admin'), old)

    def test_failed_cycle_catalog_exposes_gap_without_replacing_success(self):
        weekly.record_state(self.store, dict(contract='fs-users-weekly-work-v1', cutoff='2026-11-02T00:00:00+08:00', phase='windows', error='fixture_failure', retryable=False))
        info = self.service.catalog('admin')['weekly_update']
        self.assertEqual(info['data_through'], '2026-10-25'); self.assertFalse(info['pending']['retryable'])
        from user_tools import invoke
        value = invoke(self.service, 'admin', {})
        self.assertEqual(value['weekly_refresh_status']['error'], 'fixture_failure')
        self.assertEqual(value['weekly_update']['data_through'], '2026-10-25')

    def test_publication_corruption_and_stale_cas_refuse(self):
        with self.assertRaisesRegex(ValueError, 'weekly_publication_cas'):
            weekly.write_publication(self.store, self.publication, None)
        changed = deepcopy(self.publication); changed['data_version'] = '99999'
        with self.store.db() as db:db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(changed), weekly.META))
        with self.assertRaisesRegex(ValueError, 'weekly_publication_integrity'):self.service.query({}, 'admin')


class Worker(WeeklyFixture):
    def setUp(self):
        super().setUp(); self.synced = []
        def sync(store, site, start, end):
            self.synced.append((site, start, end))
            store.replace_window(site, start, end, [], MONDAY.isoformat())
            return dict(status='complete')
        self.sync = self.stack.enter_context(patch.object(jobs, 'synchronize_day', side_effect=sync))
        self.targeted = self.stack.enter_context(patch.object(jobs, 'targeted_refresh', return_value=dict(status='complete')))
        self.ensure = self.stack.enter_context(patch.object(types, 'ensure_period', return_value=dict(status='complete')))

    def wake(self, now=MONDAY, **kwargs):
        return weekly.wake(self.store.root, lambda: self.store, now, clock=lambda: 0, **kwargs)

    def test_weekday_idle_does_not_open_store_collect_compute_or_backup(self):
        loader = Mock(side_effect=AssertionError('weekday opened store'))
        value = weekly.wake(self.store.root, loader, FRIDAY)
        self.assertEqual(value['reason'], 'weekly_idle'); loader.assert_not_called(); self.sync.assert_not_called()

    def test_success_enumerates_all_seven_days_and_one_backup_then_reuses(self):
        value = self.wake(); self.assertEqual(value['status'], 'complete')
        week = [(a, b) for _, a, b in self.synced if a >= OLD.isoformat()]
        self.assertEqual(len(week), 7); self.assertEqual(week[0][0], OLD.isoformat()); self.assertEqual(week[-1][1], '2026-11-02T00:00:00+08:00')
        self.targeted.assert_called_once(); self.ensure.assert_called_once()
        folder = self.store.root/'backups/2026-11-02'
        self.assertTrue((folder/'manifest.json').is_file())
        count = self.sync.call_count
        with patch.object(jobs, 'backup', side_effect=AssertionError('duplicate backup')):
            self.assertEqual(self.wake(stamp('2026-11-02T04:33:00+08:00'))['status'], 'reused')
        self.assertEqual(self.sync.call_count, count)

    def test_failed_day_keeps_old_publication_and_resume_reconciles_committed_day(self):
        original = self.sync.side_effect
        def interrupted(*args):
            result = original(*args)
            if len(self.synced) == 2:raise TimeoutError('fixture interruption after commit')
            return result
        self.sync.side_effect = interrupted
        self.assertEqual(self.wake()['status'], 'deferred')
        self.assertEqual(weekly.stored_publication(self.store), self.publication)
        committed = self.synced[1]
        self.sync.side_effect = original
        self.assertEqual(self.wake(stamp('2026-11-02T04:33:00+08:00'))['status'], 'complete')
        self.assertEqual(self.synced.count(committed), 1)

    def test_contract_failure_does_not_automatically_retry(self):
        self.sync.side_effect = ValueError('source_order_sort_or_identity')
        self.assertEqual(self.wake()['status'], 'requires_reconciliation')
        count = self.sync.call_count; self.wake(stamp('2026-11-02T04:33:00+08:00'))
        self.assertEqual(self.sync.call_count, count)

    def test_partial_targeted_read_keeps_previous_week_and_missing_records(self):
        self.targeted.return_value = dict(status='partial', requested_rows=2, returned_rows=1, missing_rows=1)
        self.assertEqual(self.wake()['status'], 'requires_reconciliation')
        self.assertEqual(weekly.stored_publication(self.store), self.publication)
        self.assertFalse(weekly.small_state(self.store.root)['retryable'])

    def test_backup_failure_retries_same_cycle_on_another_day_without_recollection(self):
        actual = jobs.backup
        with patch.object(jobs, 'backup', side_effect=OSError('fixture unavailable')):
            self.assertEqual(self.wake()['status'], 'deferred')
        self.assertEqual(weekly.stored_publication(self.store)['cutoff'], '2026-11-02T00:00:00+08:00')
        count = self.sync.call_count
        with patch.object(jobs, 'backup', wraps=actual) as backup:
            self.assertEqual(self.wake(stamp('2026-11-03T04:18:00+08:00'))['status'], 'complete')
            self.assertEqual(backup.call_args.kwargs['day'], '2026-11-03')
        self.assertEqual(self.sync.call_count, count)
        self.assertFalse((self.store.root/'backups/2026-11-02').exists())
        self.assertTrue((self.store.root/'backups/2026-11-03/manifest.json').is_file())
        from user_backup_retention import verify_existing
        self.assertEqual(verify_existing(self.store, '2026-11-03')['recovery']['status'], 'passed')

    def test_complete_backup_with_lost_ack_is_reused_across_day(self):
        actual = jobs.backup
        def interrupted(*args, **kwargs):
            actual(*args, **kwargs)
            raise OSError('fixture lost acknowledgement')
        with patch.object(jobs, 'backup', side_effect=interrupted):
            self.assertEqual(self.wake()['status'], 'deferred')
        with patch.object(self.store, 'backup', side_effect=AssertionError('must not copy a second time')):
            self.assertEqual(self.wake(stamp('2026-11-03T04:18:00+08:00'))['status'], 'complete')
        self.assertFalse((self.store.root/'backups/2026-11-03').exists())

    def test_lost_work_file_reconciles_existing_weekly_backup_before_any_copy(self):
        self.wake(); (self.store.root/weekly.WORK).unlink()
        with patch.object(self.store, 'backup', side_effect=AssertionError('must not duplicate after lost work file')), \
                patch.object(jobs, 'synchronize_day', side_effect=AssertionError('must not recollect')):
            self.assertEqual(self.wake(stamp('2026-11-03T04:18:00+08:00'))['status'], 'complete')
        self.assertEqual(sorted(p.name for p in (self.store.root/'backups').iterdir()), ['2026-11-02'])

    def test_delayed_old_week_backup_occupies_monday_and_new_week_resumes_tuesday(self):
        with patch.object(jobs, 'backup', side_effect=OSError('fixture unavailable')):
            self.assertEqual(self.wake()['status'], 'deferred')
        monday = stamp('2026-11-09T04:18:00+08:00')
        self.assertEqual(self.wake(monday)['status'], 'complete')
        old_folder = self.store.root/'backups/2026-11-09'
        before = jobs.backup_signature(old_folder)
        pending = self.wake(stamp('2026-11-09T04:33:00+08:00'))
        self.assertEqual(pending['status'], 'deferred')
        self.assertEqual(pending['reason'], 'weekly_backup_date_busy')
        self.assertTrue(weekly.small_state(self.store.root)['retryable'])
        calls = self.sync.call_count
        with patch.object(self.store, 'backup', side_effect=AssertionError('must not overwrite older cycle')):
            self.assertEqual(self.wake(stamp('2026-11-09T04:48:00+08:00'))['status'], 'deferred')
        self.assertEqual(self.wake(stamp('2026-11-10T04:18:00+08:00'))['status'], 'complete')
        self.assertEqual(self.sync.call_count, calls)
        self.assertEqual(jobs.backup_signature(old_folder), before)
        new_folder = self.store.root/'backups/2026-11-10'
        old = json.loads((old_folder/'manifest.json').read_text())
        new = json.loads((new_folder/'manifest.json').read_text())
        self.assertEqual(old['weekly_cutoff'], MONDAY.replace(hour=0, minute=0).isoformat())
        self.assertEqual(new['weekly_cutoff'], monday.replace(hour=0, minute=0).isoformat())
        self.assertEqual(sorted(p.name for p in old_folder.parent.iterdir()), ['2026-11-09', '2026-11-10'])
        from user_backup_retention import verify_existing
        self.assertEqual(verify_existing(self.store, '2026-11-10')['recovery']['status'], 'passed')

    def test_changed_other_week_backup_is_unknown_and_never_skipped(self):
        with patch.object(jobs, 'backup', side_effect=OSError('fixture unavailable')):self.wake()
        self.wake(stamp('2026-11-09T04:18:00+08:00'))
        path = self.store.root/'backups/2026-11-09/config.json'
        path.write_text(path.read_text()+' ')
        value = self.wake(stamp('2026-11-09T04:33:00+08:00'))
        self.assertEqual(value['status'], 'requires_reconciliation')
        self.assertEqual(value['reason'], 'weekly_backup_unknown_directory')
        self.assertFalse(weekly.small_state(self.store.root)['retryable'])
        self.assertFalse((self.store.root/'backups/2026-11-10').exists())

    def test_unknown_partial_backup_never_gets_overwritten_or_duplicated(self):
        folder = self.store.root/'backups/2026-11-02'; folder.mkdir(parents=True, mode=0o700)
        original = b'fixture unknown partial'; (folder/'customers.sqlite3').write_bytes(original)
        self.assertEqual(self.wake()['status'], 'requires_reconciliation')
        self.assertEqual((folder/'customers.sqlite3').read_bytes(), original)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ['customers.sqlite3'])
        self.ensure.assert_called_once(); self.targeted.assert_called_once()
        self.wake(stamp('2026-11-03T04:18:00+08:00'))
        self.assertFalse((self.store.root/'backups/2026-11-03').exists())

    def test_existing_older_backup_cannot_masquerade_as_current_week(self):
        with patch.object(jobs, 'backup', return_value=dict(data_version='0')):
            value = self.wake()
        self.assertEqual(value['status'], 'requires_reconciliation')
        self.assertEqual(value['reason'], 'weekly_backup_version_requires_reconciliation')

    def test_cross_week_resume_finishes_original_cycle_before_new_one(self):
        self.sync.side_effect = TimeoutError('fixture network timeout')
        self.wake(); self.assertEqual(weekly.small_state(self.store.root)['cutoff'], '2026-11-02T00:00:00+08:00')
        def recovered(store, site, start, end):
            store.replace_window(site, start, end, [], '2026-11-09T04:18:00+08:00'); return dict(status='complete')
        self.sync.side_effect = recovered
        self.assertEqual(self.wake(stamp('2026-11-09T04:18:00+08:00'))['cutoff'], '2026-11-02T00:00:00+08:00')

    def test_first_adoption_freezes_existing_daily_recipe_without_new_backup(self):
        with self.store.db() as db:db.execute('DELETE FROM meta WHERE key=?', (weekly.META,))
        (self.store.root/weekly.WORK).unlink()
        legacy = Service(self.store, lambda *_: True, clock=lambda: FRIDAY, weekly_publication=False)
        value = legacy.query(dict(start='2026-10-01', end_exclusive='2026-10-30', state_basis='period_end'), 'admin')
        jobs.atomic(self.store.root/'daily-state.json', dict(snapshot_id=value['snapshot_id'], executed_at=FRIDAY.isoformat()))
        with patch.object(jobs, 'backup', side_effect=AssertionError('adoption backup')):
            self.assertEqual(self.wake(FRIDAY)['reason'], 'weekly_outside_window')
        self.assertEqual(weekly.stored_publication(self.store)['cutoff'], OLD.isoformat())
        self.sync.assert_not_called()

    def test_time_budget_preserves_checkpoint_and_old_view_until_resume(self):
        calls = [0]
        def clock():
            calls[0] += 1
            return 0 if calls[0] == 1 else 400
        value = weekly.wake(self.store.root, lambda:self.store, MONDAY, clock=clock)
        self.assertEqual(value['status'], 'continuing'); self.assertEqual(len(self.synced), 1)
        self.assertEqual(weekly.stored_publication(self.store), self.publication)
        first = self.synced[0]
        self.assertEqual(self.wake(stamp('2026-11-02T04:33:00+08:00'))['status'], 'complete')
        self.assertEqual(self.synced.count(first), 1)

    def test_publication_commit_without_checkpoint_resumes_backup_only(self):
        self.wake()
        state = weekly.small_state(self.store.root); state['phase']='publish'; weekly.record_state(self.store,state)
        with patch.object(jobs,'synchronize_day',side_effect=AssertionError('recollection after committed publication')):
            self.assertEqual(self.wake(stamp('2026-11-02T04:33:00+08:00'))['status'], 'complete')

    def test_first_installation_collects_before_publishing_any_zero(self):
        store = Store(Path(self.tmp.name)/'empty', b'y'*32, self.config)
        self.assertIsNone(weekly.stored_publication(store))
        self.assertEqual(weekly.wake(store.root, lambda:store, MONDAY, clock=lambda:0)['status'], 'complete')
        self.assertEqual(weekly.stored_publication(store)['cutoff'], '2026-11-02T00:00:00+08:00')


class FlagPeriods(unittest.TestCase):
    def test_cross_month_ensures_both_portions_then_reuses(self):
        periods = []
        def reader(query):
            periods.append(query); return {}, dict(status='complete')
        with patch.object(types, 'read_flags', side_effect=reader):
            value = types.ensure_period('2026-10-26', '2026-11-02', MONDAY)
        self.assertEqual(value['status'], 'complete')
        self.assertEqual([v['end_exclusive'] for v in periods], ['2026-11-01T00:00:00+08:00', '2026-11-02T00:00:00+08:00'])

    def test_missing_month_uses_existing_export_and_reports_pending(self):
        export = Mock(return_value=dict(status='pending'))
        with patch.object(types, 'read_flags', return_value=({}, dict(status='partial'))), patch.dict(sys.modules, {'es_order_structure': Mock(server_bundle=export)}):
            value = types.ensure_period('2026-10-26', '2026-11-02', MONDAY)
        self.assertEqual(value['status'], 'pending')
        self.assertEqual(export.call_args.args[0]['end'], '2026-10-31')

    def test_export_permission_error_is_not_automatically_polled(self):
        export = Mock(return_value=dict(status='failed',reason='permission_denied'))
        with patch.object(types,'read_flags',return_value=({},dict(status='partial'))),patch.dict(sys.modules,{'es_order_structure':Mock(server_bundle=export)}):
            with self.assertRaisesRegex(ValueError,'weekly_customer_type_source_contract'):
                types.ensure_period('2026-10-26','2026-11-02',MONDAY)

    def test_uninitialized_week_is_unavailable_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            config = json.loads((BASE/'source/user_config.json').read_text('utf-8')); config['update_cadence']='weekly-v1'
            store = Store(Path(directory)/'private', b'x'*32, config)
            status, value = get(Service(store, lambda *_: True), '/users', {}, 'admin')
            self.assertEqual(status, 503); self.assertEqual(value['error'], 'weekly_initial_publication_pending')


class PinnedFlags(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'archive'; self.root.mkdir(mode=0o700)
        self.order = hashlib.sha256(b'pinned-fixture-order').hexdigest()
        from types import SimpleNamespace
        def parse(files):
            return [row for data in files for row in json.loads(data)], [hashlib.sha256(data).hexdigest() for data in files], 0
        es = SimpleNamespace(MAX_FILE=32*1024*1024, archive_access=lambda root:nullcontext(),
                             excel_path=lambda root, ident:root/(ident+'.xlsx'), parse_files=parse,
                             make_dataset=lambda rows, *args:dict(rows=rows),
                             archived_dataset=Mock(side_effect=AssertionError('newest export must not be selected')),
                             COLUMNS=dict(time='time', order='order', new_customer='new'))
        self.patch = patch.dict(sys.modules, {'es_order_structure':es}); self.patch.start(); self.addCleanup(self.patch.stop)
        self.es = es
        self.add_manifest('\u662f', '2026-11-01T02:00:00+08:00')
        self.inventory = types.manifest_inventory(self.root)

    def add_manifest(self, label, captured, declared=1):
        raw = json.dumps([dict(order=self.order, time='2026-10-21', new=label)]).encode()
        ident = hashlib.sha256(raw).hexdigest(); path = self.root/(ident+'.xlsx'); path.write_bytes(raw); path.chmod(0o600)
        value = dict(query=dict(profile='ALL', start='2026-10-01', end='2026-10-31'), captured_at=captured,
                     file_sha256=[ident], file_set=dict(declared_files=declared, failed_files=0))
        raw = json.dumps(value).encode(); name = hashlib.sha256(raw).hexdigest()+'.json'
        path = self.root/name; path.write_bytes(raw); path.chmod(0o600)
        return path

    def test_later_export_does_not_change_frozen_customer_types(self):
        self.add_manifest('\u5426', '2026-11-02T02:00:00+08:00')
        query = dict(start='2026-10-19', end_exclusive='2026-10-26')
        flags, info = types.read_pinned_flags(query, self.inventory, self.root)
        self.assertEqual(flags[self.order], 'new'); self.assertEqual(info['status'], 'complete')
        fresh, _ = types.read_pinned_flags(query, types.manifest_inventory(self.root), self.root)
        self.assertEqual(fresh[self.order], 'old'); self.es.archived_dataset.assert_not_called()

    def test_manifest_or_workbook_corruption_refuses(self):
        name = self.inventory[0]['name']; path = self.root/name; original = path.read_bytes()
        path.write_bytes(original+b' ')
        with self.assertRaisesRegex(ValueError, 'manifest_changed'):
            types.read_pinned_flags(dict(start='2026-10-19', end_exclusive='2026-10-26'), self.inventory, self.root)
        path.write_bytes(original)
        workbook = next(self.root.glob('*.xlsx')); workbook.write_bytes(b'changed fixture')
        with self.assertRaisesRegex(ValueError, 'file_changed'):
            types.read_pinned_flags(dict(start='2026-10-19', end_exclusive='2026-10-26'), self.inventory, self.root)

    def test_incomplete_file_set_remains_partial_and_path_escape_refuses(self):
        self.add_manifest('\u662f', '2026-11-03T02:00:00+08:00', declared=2)
        _, info = types.read_pinned_flags(dict(start='2026-10-19', end_exclusive='2026-10-26'), types.manifest_inventory(self.root), self.root)
        self.assertEqual(info['status'], 'partial')
        with self.assertRaisesRegex(ValueError, 'frozen_customer_type_manifest'):
            types.read_pinned_flags(dict(start='2026-10-19', end_exclusive='2026-10-26'), [dict(name='../private.json', sha256='a'*64)], self.root)


if __name__ == '__main__':
    unittest.main()
