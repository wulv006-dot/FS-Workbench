import datetime as dt
import tempfile
import unittest
from pathlib import Path

from mmoexp_google_data.seo import retention, store


class Resources(unittest.TestCase):
    def test_old_reference_is_warning_and_actual_emergency_stops(self):
        gb=1024**3
        policy=retention.ResourcePolicy(warning_bytes=4*gb, operating_ceiling_bytes=8*gb,
            emergency_stop_bytes=12*gb, host_reserve_bytes=2*gb, measured_basis='isolated test fixture')
        result=policy.admit(used=5*gb, free=20*gb, estimate=gb)
        self.assertTrue(result['allowed'])
        self.assertEqual(result['state'],'warning')
        self.assertFalse(policy.admit(used=11*gb,free=20*gb,estimate=2*gb)['allowed'])
        self.assertFalse(policy.admit(used=gb,free=2*gb,estimate=gb)['allowed'])

    def test_backup_restore_without_ai_and_only_two_verified_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            core=store.Store(Path(tmp)/'seo')
            for n in range(3):
                result=retention.backup_verified(core)
                self.assertTrue(result['verified'])
                self.assertTrue(result['restore_checked'])
            self.assertEqual(len(list((core.root/'backups').glob('backup-*'))),2)
            self.assertTrue(retention.verify_backup(Path(result['path'])))
            self.assertFalse((core.root/'seo-ai').exists())

    def test_restore_can_open_frozen_snapshot_without_ai_or_original_database(self):
        from mmoexp_google_data.seo import daily,snapshot
        from test_daily_snapshot import NIGHT,Source
        with tempfile.TemporaryDirectory() as tmp:
            core=store.Store(Path(tmp)/'seo')
            published=daily.run_daily(core,[Source()],clock=lambda:NIGHT)
            result=retention.backup_verified(core)
            restored=retention.restore_backup(result['path'],Path(tmp)/'restored')
            actual=snapshot.read(restored.root,published['snapshot_id'],'history','FC27')
            self.assertEqual(actual['facts_hash'],published['facts_hash'])
            self.assertEqual(len(actual['rows']),30)
            with self.assertRaises(FileExistsError):retention.restore_backup(result['path'],restored.root)

    def test_cleanup_keeps_35_days_and_other_fs_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            core=store.Store(Path(tmp)/'seo')
            other=Path(tmp)/'main.db';other.write_bytes(b'main database')
            with core.db() as db:
                for day in ('2026-09-30','2026-10-01','2026-11-04'):
                    db.execute('INSERT INTO facts VALUES (?,?,?,?,?)',('gsc','FC27',day,'one','{}'))
            result=retention.cleanup_owned_data(core,dt.date(2026,11,4))
            with core.db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM facts').fetchone()[0],2)
            self.assertEqual(other.read_bytes(),b'main database')
            self.assertIn('physical_bytes_after',result)

    def test_rejects_symlink_from_seo_into_shared_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            core=store.Store(Path(tmp)/'seo')
            shared=Path(tmp)/'shared';shared.mkdir()
            try:(core.root/'snapshots').symlink_to(shared,target_is_directory=True)
            except OSError:return self.assertRaises(ValueError,retention.checked_child,core.root,'../shared')
            with self.assertRaises(ValueError):retention.cleanup_owned_data(core,dt.date(2026,11,4))

    def test_memory_allows_above_old_one_gib_but_stops_for_real_pressure(self):
        gb=1024**3
        policy=dict(warning_bytes=gb,operating_ceiling_bytes=2*gb,emergency_stop_bytes=3*gb,host_reserve_bytes=4*gb)
        self.assertTrue(retention.memory_admission(policy,rss_bytes=int(1.5*gb),available_bytes=8*gb)['allowed'])
        self.assertFalse(retention.memory_admission(policy,rss_bytes=3*gb,available_bytes=8*gb)['allowed'])
        self.assertFalse(retention.memory_admission(policy,rss_bytes=gb,available_bytes=3*gb)['allowed'])

    def test_disabled_ai_artifacts_are_cleaned_locally(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'ai';root.mkdir()
            with sqlite3.connect(str(root/'ai.db')) as db:
                db.execute('CREATE TABLE reports(snapshot_id TEXT,text TEXT)')
                db.executemany('INSERT INTO reports VALUES (?,?)',[('seo-2026-09-01','expired'),('seo-2026-11-04','recent')])
            db.close()
            result=retention.cleanup_ai(root,dt.date(2026,11,5))
            self.assertEqual(result['rows_deleted'],1)

    def test_interrupted_temporary_capacity_is_reclaimed_without_touching_trusted_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            core=store.Store(Path(tmp)/'seo')
            backup=retention.backup_verified(core)
            leftover=core.root/'backups'/'candidate-interrupted';leftover.mkdir();(leftover/'partial').write_bytes(b'x'*4096)
            snapshots=core.root/'snapshots';snapshots.mkdir()
            (snapshots/('seo-2026-11-04.'+'a'*32+'.tmp')).write_bytes(b'x'*4096)
            receipt=retention.cleanup_owned_data(core,dt.date(2026,11,5))
            self.assertFalse(leftover.exists())
            self.assertGreater(receipt['physical_bytes_before'],receipt['physical_bytes_after'])
            self.assertTrue(retention.verify_backup(backup['path']))


if __name__=='__main__':unittest.main()
