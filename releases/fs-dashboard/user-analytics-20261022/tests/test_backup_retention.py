"""Recovery-point retirement contracts using invented, disposable SQLite fixtures only."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path.insert(0, str(SOURCE))
from user_contract import stamp
import user_backup_retention as retention
import user_jobs as jobs
from user_store import Store

NOW = stamp('2026-10-30T00:03:11+08:00')


class BackupRetention(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = json.loads((SOURCE / 'user_config.json').read_text('utf-8'))
        self.config['backup_retention'] = dict(enabled=False, keep_verified=2, protected_dates=[])
        self.store = Store(Path(self.tmp.name) / 'private', b'x' * 32, self.config)
        row = dict(id=1, order_no='retention-fixture-1', paytime='2026-10-21 12:00:00',
                   email='fixture@example.test', gid='1327', uid=0, site_id='266', pay_status=1, status='11')
        self.store.replace_window('266', '2026-10-21', '2026-10-22', [row], NOW.isoformat())
        cid = self.store.read()[1][0]['customer_id']
        self.private = dict(records={cid: dict(customer_id=cid)}, members=dict(known_pool=[cid]), events=[])
        self.public = self.store.save_snapshot(dict(fixture='retention'),
            dict(data_version=self.store.revision(), metrics=dict(known_pool=dict(value=1))), self.private)

    def folder(self, day):
        return self.store.root / 'backups' / day

    def backup(self, day, legacy=False):
        value = jobs.backup(self.store, stamp(day + 'T00:03:11+08:00'))
        if legacy:
            value.pop('recovery')
            value['contract'] = 'fs-users-private-backup-v1'
            retention.write(self.folder(day) / 'manifest.json', value)
        return value

    def enabled(self, keep=2, protected=()):
        self.config['backup_retention'] = dict(enabled=True, keep_verified=keep, protected_dates=list(protected))

    def three_points(self):
        for day in ('2026-10-26', '2026-10-29', '2026-10-30'):
            self.backup(day)
        self.enabled()
        return retention.plan(self.store, NOW)

    def signatures(self, folder):
        return {p.name: retention.signature(p) for p in folder.iterdir()}

    def manifest(self, day):
        return retention.read_json(self.folder(day) / 'manifest.json')[0]

    def rewrite_manifest(self, day, change):
        value = self.manifest(day)
        change(value)
        retention.write(self.folder(day) / 'manifest.json', value)

    def protected(self):
        return {p['name']: p['reason'] for p in retention.plan(self.store, NOW)['protected']}

    def test_v2_backup_restores_facts_and_frozen_private_snapshot(self):
        value = self.backup('2026-10-30')
        self.assertEqual(value['contract'], 'fs-users-private-backup-v2')
        check = value['recovery']
        self.assertEqual(check['status'], 'passed')
        self.assertEqual(check['sqlite_integrity'], 'ok')
        self.assertEqual(check['counts'], dict(orders=1, identities=1, snapshots=1))
        self.assertEqual(check['frozen_snapshot_id'], self.public['snapshot_id'])
        self.assertEqual(check['private_records'], 1)
        self.assertEqual(check['data_version'], self.store.revision())
        self.assertEqual((check['source_calls'], check['database_writes']), (0, 0))

    def test_recovery_reader_changes_no_file_and_rejects_sql_write(self):
        self.backup('2026-10-30')
        folder = self.folder('2026-10-30')
        before = self.signatures(folder)
        check = retention.restore_check(folder)
        restored = Store(folder, self.store.key, json.loads((folder / 'config.json').read_text('utf-8')), read_only=True)
        self.assertEqual(restored.snapshot(self.public['snapshot_id'])[2], self.private)
        with self.assertRaises(sqlite3.OperationalError):
            with restored.db() as db:
                db.execute("UPDATE meta SET value='999' WHERE key='revision'")
        self.assertEqual(check['data_version'], self.store.revision())
        self.assertEqual(self.signatures(folder), before)

    def test_empty_new_installation_still_has_valid_recovery_point(self):
        empty = Store(Path(self.tmp.name) / 'empty', b'y' * 32, self.config)
        check = jobs.backup(empty, NOW)['recovery']
        self.assertEqual(check['counts'], dict(orders=0, identities=0, snapshots=0))
        self.assertEqual(check['status'], 'passed')
        self.assertIsNone(check['frozen_snapshot_id'])

    def test_enabled_retirement_keeps_two_verified_points_and_durable_receipt(self):
        approved = self.three_points()
        kept = {day: self.signatures(self.folder(day)) for day in ('2026-10-29', '2026-10-30')}
        self.assertEqual([p['day'] for p in approved['candidates']], ['2026-10-26'])
        result = retention.apply(self.store, NOW, approved)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['removed_bytes'], approved['candidate_bytes'])
        self.assertFalse(self.folder('2026-10-26').exists())
        for day, signatures in kept.items():
            self.assertEqual(self.signatures(self.folder(day)), signatures)
        audit = retention.read_json(self.store.root / 'backup-retention-audit' / result['audit'])[0]
        self.assertEqual(audit['status'], 'complete')
        self.assertEqual(len(audit['removed']), 4)
        self.assertNotIn('intent', audit)

    def test_policy_can_keep_more_than_two_points(self):
        self.three_points()
        self.backup('2026-10-25')
        self.enabled(keep=3)
        plan = retention.plan(self.store, NOW)
        self.assertEqual([p['day'] for p in plan['keep']], ['2026-10-30', '2026-10-29', '2026-10-26'])
        self.assertEqual([p['day'] for p in plan['candidates']], ['2026-10-25'])

    def test_policy_rejects_fewer_than_two_verified_points(self):
        self.enabled(keep=1)
        with self.assertRaisesRegex(ValueError, 'backup_retention_policy'):
            retention.plan(self.store, NOW)

    def test_disabled_policy_never_deletes(self):
        self.three_points()
        self.config['backup_retention']['enabled'] = False
        before = self.signatures(self.folder('2026-10-26'))
        with self.assertRaisesRegex(ValueError, 'backup_retention_not_enabled'):
            retention.apply(self.store, NOW, retention.plan(self.store, NOW))
        self.assertEqual(self.signatures(self.folder('2026-10-26')), before)
        self.assertFalse((self.store.root / 'backup-retention-audit').exists())

    def test_no_retirement_without_current_day_success(self):
        for day in ('2026-10-25', '2026-10-26', '2026-10-29'):
            self.backup(day)
        self.enabled()
        plan = retention.plan(self.store, NOW)
        self.assertEqual(plan['status'], 'waiting_for_current_verified_recovery_point')
        self.assertEqual(plan['candidates'], [])
        self.assertEqual(retention.apply(self.store, NOW, plan)['removed_bytes'], 0)

    def test_one_verified_point_does_not_count_unverified_legacy_as_second(self):
        self.backup('2026-10-29', legacy=True)
        self.backup('2026-10-30')
        self.enabled()
        plan = retention.plan(self.store, NOW)
        self.assertEqual(plan['status'], 'waiting_for_current_verified_recovery_point')
        self.assertEqual(len(plan['keep']), 1)
        self.assertEqual(self.protected()['2026-10-29'], 'restore_not_verified')

    def test_legacy_point_requires_streamed_hashes_and_semantic_restore_receipt(self):
        self.backup('2026-10-26', legacy=True)
        self.backup('2026-10-29')
        self.backup('2026-10-30')
        self.enabled()
        self.assertEqual(retention.plan(self.store, NOW)['candidates'], [])
        before = self.signatures(self.folder('2026-10-26'))
        with patch.object(jobs, 'file_sha256', wraps=jobs.file_sha256) as streamed:
            check = retention.verify_existing(self.store, '2026-10-26')
        self.assertEqual({call.args[0].name for call in streamed.call_args_list}, set(retention.FILES) - {'manifest.json'})
        self.assertEqual(streamed.call_count, 3)
        self.assertEqual(check['recovery']['counts']['orders'], 1)
        self.assertEqual(check['recovery']['private_records'], 1)
        self.assertEqual(check['recovery']['database_writes'], 0)
        self.assertEqual({name: retention.signature(self.folder('2026-10-26') / name) for name in before}, before)
        self.assertEqual([p['day'] for p in retention.plan(self.store, NOW)['candidates']], ['2026-10-26'])

    def test_verifying_existing_legacy_point_is_idempotent(self):
        self.backup('2026-10-26', legacy=True)
        first = retention.verify_existing(self.store, '2026-10-26')
        before = self.signatures(self.folder('2026-10-26'))
        self.assertEqual(retention.verify_existing(self.store, '2026-10-26'), first)
        self.assertEqual(self.signatures(self.folder('2026-10-26')), before)

    def test_partial_unknown_and_missing_manifest_directories_are_protected(self):
        self.three_points()
        partial = self.folder('2026-10-24'); partial.mkdir(mode=0o700)
        (partial / 'customers.sqlite3').write_bytes(b'incomplete fixture')
        self.backup('2026-10-25')
        (self.folder('2026-10-25') / 'operator-note.txt').write_text('hold fixture', encoding='utf-8')
        self.backup('2026-10-23')
        (self.folder('2026-10-23') / 'manifest.json').unlink()
        protected = self.protected()
        for day in ('2026-10-24', '2026-10-25', '2026-10-23'):
            self.assertEqual(protected[day], 'partial_or_unknown_backup_files')
        retention.apply(self.store, NOW, retention.plan(self.store, NOW))
        for day in protected:
            self.assertTrue(self.folder(day).exists())

    def test_special_recovery_material_and_fixed_date_are_preserved(self):
        self.three_points()
        special = self.folder('January-special'); special.mkdir(mode=0o700)
        (special / 'evidence').write_bytes(b'invented special material')
        self.enabled(protected=['2026-10-26'])
        protected = self.protected()
        self.assertEqual(protected['January-special'], 'special_or_unknown_recovery_material')
        self.assertEqual(protected['2026-10-26'], 'explicitly_protected_recovery_point')
        self.assertEqual(retention.plan(self.store, NOW)['candidates'], [])

    def test_unknown_manifest_contract_is_never_managed(self):
        self.three_points()
        self.rewrite_manifest('2026-10-26', lambda value: value.update(contract='unrecognized-v99'))
        self.assertEqual(self.protected()['2026-10-26'], 'backup_manifest_contract')
        with self.assertRaisesRegex(ValueError, 'backup_manifest_contract'):
            retention.verify_existing(self.store, '2026-10-26')

    def test_manifest_capture_date_must_match_directory(self):
        self.three_points()
        self.rewrite_manifest('2026-10-26', lambda value: value.update(captured_at=NOW.isoformat()))
        self.assertEqual(self.protected()['2026-10-26'], 'backup_manifest_contract')

    def test_unknown_scope_or_noncanonical_version_is_protected(self):
        self.three_points()
        original=self.manifest('2026-10-26')
        for field,value in (('scope','foreign-recovery'),('data_version','01'),('data_version',1),('data_version','9223372036854775808')):
            with self.subTest(field=field,value=value):
                manifest=dict(original);manifest[field]=value
                retention.write(self.folder('2026-10-26')/'manifest.json',manifest)
                self.assertEqual(self.protected()['2026-10-26'],'backup_manifest_contract')

    def test_future_dated_recovery_point_is_never_managed(self):
        self.three_points();self.backup('2026-10-31')
        self.assertEqual(self.protected()['2026-10-31'],'future_or_misdated_recovery_point')

    def test_retained_anchor_drift_after_intent_prevents_first_unlink(self):
        approved=self.three_points();original=retention.write
        def changed(path,value):
            original(path,value)
            if path.parent.name=='backup-retention-audit' and value.get('status')=='in_progress':
                with (self.folder('2026-10-30')/'config.json').open('ab') as out:out.write(b' ')
        with patch.object(retention,'write',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'retained_recovery_point_drift'):
                retention.apply(self.store,NOW,approved)
        self.assertEqual({p.name for p in self.folder('2026-10-26').iterdir()},set(retention.FILES))

    def test_changed_backup_bytes_fail_independent_verification(self):
        self.backup('2026-10-26', legacy=True)
        with (self.folder('2026-10-26') / 'config.json').open('ab') as stream:
            stream.write(b' ')
        with self.assertRaisesRegex(ValueError, 'backup_readback_mismatch'):
            retention.verify_existing(self.store, '2026-10-26')
        self.assertFalse((self.folder('2026-10-26') / 'restore-check.json').exists())

    def test_tampered_manifest_hash_fails_verification(self):
        self.backup('2026-10-26', legacy=True)
        self.rewrite_manifest('2026-10-26', lambda value: value['sha256'].update({'customers.sqlite3': '0' * 64}))
        with self.assertRaisesRegex(ValueError, 'backup_readback_mismatch'):
            retention.verify_existing(self.store, '2026-10-26')

    def test_malformed_manifest_hash_is_rejected(self):
        self.backup('2026-10-26', legacy=True)
        self.rewrite_manifest('2026-10-26', lambda value: value['sha256'].update({'customers.sqlite3': 'not-a-hash'}))
        with self.assertRaisesRegex(ValueError, 'backup_manifest_files'):
            retention.verify_existing(self.store, '2026-10-26')

    def test_different_existing_restore_receipt_requires_reconciliation(self):
        self.backup('2026-10-26', legacy=True)
        check = retention.verify_existing(self.store, '2026-10-26')
        check['signature']['manifest_sha256'] = '0' * 64
        retention.write(self.folder('2026-10-26') / 'restore-check.json', check)
        self.assertEqual(self.protected()['2026-10-26'], 'restore_not_verified')
        with self.assertRaisesRegex(ValueError, 'existing_restore_check_requires_reconciliation'):
            retention.verify_existing(self.store, '2026-10-26')

    def test_nonobject_recovery_receipt_is_protected(self):
        self.three_points()
        self.rewrite_manifest('2026-10-26', lambda value: value.update(recovery=['invalid']))
        self.assertEqual(self.protected()['2026-10-26'], 'backup_recovery_contract')

    def test_plan_drift_rejects_retirement_before_any_delete(self):
        approved = self.three_points()
        path = self.folder('2026-10-26') / 'customers.sqlite3'
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000000))
        with self.assertRaisesRegex(ValueError, 'backup_retention_plan_drift'):
            retention.apply(self.store, NOW, approved)
        self.assertEqual(set(p.name for p in self.folder('2026-10-26').iterdir()), set(retention.FILES))
        self.assertFalse((self.store.root / 'backup-retention-audit').exists())

    def test_linked_backup_file_is_not_a_retirement_candidate(self):
        self.three_points()
        path = self.folder('2026-10-26') / 'customers.sqlite3'
        os.link(path, self.store.root / 'linked-evidence.sqlite3')
        self.assertEqual(self.protected()['2026-10-26'], 'private_backup_file_metadata')
        self.assertEqual(retention.plan(self.store, NOW)['candidates'], [])

    def test_symlink_recovery_directory_is_protected(self):
        self.three_points()
        self.folder('2026-10-25').symlink_to(self.folder('2026-10-26'), target_is_directory=True)
        self.assertEqual(self.protected()['2026-10-25'], 'private_store_symlink')

    def test_nonprivate_recovery_directory_is_protected(self):
        self.three_points()
        self.folder('2026-10-26').chmod(0o755)
        self.assertEqual(self.protected()['2026-10-26'], 'private_backup_directory_metadata')

    def test_interrupted_delete_keeps_intent_and_blocks_blind_retry(self):
        approved = self.three_points()
        kept = {day: self.signatures(self.folder(day)) for day in ('2026-10-29', '2026-10-30')}
        original = Path.unlink
        calls = []

        def interrupted(path, *args, **kwargs):
            if path.parent == self.folder('2026-10-26'):
                calls.append(path.name)
                if len(calls) == 2:
                    raise OSError('invented interruption')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'unlink', interrupted):
            with self.assertRaisesRegex(OSError, 'invented interruption'):
                retention.apply(self.store, NOW, approved)
        audit_paths = list((self.store.root / 'backup-retention-audit').iterdir())
        self.assertEqual(len(audit_paths), 1)
        audit = retention.read_json(audit_paths[0])[0]
        self.assertEqual(audit['status'], 'in_progress')
        self.assertEqual(len(audit['removed']), 1)
        self.assertEqual(audit['intent'], dict(day='2026-10-26', name=calls[1]))
        remaining = self.signatures(self.folder('2026-10-26'))
        with self.assertRaisesRegex(ValueError, 'backup_retention_requires_reconciliation'):
            retention.apply(self.store, NOW, retention.plan(self.store, NOW))
        self.assertEqual(self.signatures(self.folder('2026-10-26')), remaining)
        for day, signatures in kept.items():
            self.assertEqual(self.signatures(self.folder(day)), signatures)

    def test_failure_before_first_unlink_also_requires_reconciliation(self):
        approved = self.three_points()
        original = Path.unlink

        def interrupted(path, *args, **kwargs):
            if path.parent == self.folder('2026-10-26'):
                raise OSError('invented first unlink failure')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'unlink', interrupted):
            with self.assertRaises(OSError):
                retention.apply(self.store, NOW, approved)
        audit = retention.read_json(next((self.store.root / 'backup-retention-audit').iterdir()))[0]
        self.assertEqual(audit['removed'], [])
        self.assertIn('intent', audit)
        with self.assertRaisesRegex(ValueError, 'backup_retention_requires_reconciliation'):
            retention.apply(self.store, NOW, retention.plan(self.store, NOW))

    def test_failed_new_backup_never_retires_old_recovery_points(self):
        for day in ('2026-10-25', '2026-10-26', '2026-10-29'):
            self.backup(day)
        self.enabled()
        before = {day: self.signatures(self.folder(day)) for day in ('2026-10-25', '2026-10-26', '2026-10-29')}
        with patch.object(self.store, 'backup', side_effect=OSError('invented copy failure')):
            with self.assertRaisesRegex(OSError, 'invented copy failure'):
                jobs.daily_backup_status(self.store, NOW)
        for day, signatures in before.items():
            self.assertEqual(self.signatures(self.folder(day)), signatures)
        self.assertFalse((self.store.root / 'backup-retention-audit').exists())
        self.assertEqual(jobs.daily_backup_status(self.store, NOW)['status'], 'requires_reconciliation')

    def test_partial_current_day_blocks_cleanup_and_is_not_overwritten(self):
        for day in ('2026-10-25', '2026-10-26', '2026-10-29'):
            self.backup(day)
        self.enabled()
        folder = self.folder('2026-10-30'); folder.mkdir(mode=0o700)
        evidence = folder / 'customers.sqlite3'; evidence.write_bytes(b'partial invented input'); evidence.chmod(0o600)
        before = retention.signature(evidence)
        result = jobs.daily_backup_status(self.store, NOW)
        self.assertEqual(result['status'], 'requires_reconciliation')
        self.assertFalse(result['retryable'])
        self.assertEqual(retention.signature(evidence), before)
        self.assertTrue(self.folder('2026-10-25').exists())
        self.assertFalse((self.store.root / 'backup-retention-audit').exists())

    def test_retirement_error_preserves_successful_backup_receipt(self):
        self.backup('2026-10-29')
        self.enabled()
        with patch.object(retention, 'apply', side_effect=OSError('invented retirement failure')):
            result = jobs.daily_backup_status(self.store, NOW)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['receipt']['recovery']['status'], 'passed')
        self.assertEqual(result['retention']['status'], 'requires_reconciliation')
        self.assertFalse(result['retention']['retryable'])
        self.assertEqual(retention.read_json(self.store.root / 'backup-status.json')[0]['status'], 'complete')
        self.assertTrue((self.folder('2026-10-30') / 'manifest.json').is_file())


if __name__ == '__main__':
    unittest.main()
