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
            self.assertEqual(len(list((core.root/'backups').glob('backup-*'))),2)
            self.assertTrue(retention.verify_backup(Path(result['path'])))
            self.assertFalse((core.root/'seo-ai').exists())

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


if __name__=='__main__':unittest.main()
