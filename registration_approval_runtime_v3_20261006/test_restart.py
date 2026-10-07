"""Real separate Python process tests, synthetic storage and signed tokens only."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import runtime as r
from process_probe import portal


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fs-registration-restart-')
        self.root = Path(self.temp.name)
        self.probe = Path(__file__).parent / 'process_probe.py'

    def tearDown(self): self.temp.cleanup()

    def remove_synthetic_directory(self, name):
        target = (self.root / name).resolve()
        root = self.root.resolve()
        if target.parent != root or Path(tempfile.gettempdir()).resolve() not in root.parents:
            raise ValueError('fixture deletion outside dedicated temp root rejected')
        shutil.rmtree(target)

    def run_process(self, phase, expected=0):
        result = subprocess.run([sys.executable, str(self.probe), phase, str(self.root)], capture_output=True, text=True)
        self.assertEqual(expected, result.returncode, result.stderr)
        return result.stdout.strip()

    def prepare_logout(self):
        self.assertEqual('PREPARED', self.run_process('prepare'))
        self.assertEqual('LOGGED_OUT', self.run_process('logout'))
        self.assertEqual('TOKEN_DENIED', self.run_process('verify'))

    def test_true_process_logout_restart_then_missing_db(self):
        self.prepare_logout()
        db = self.root / 'registration-approval/registration.sqlite3'
        db.unlink()
        self.assertEqual('BOOT_DENIED', self.run_process('verify'))
        self.assertFalse(db.exists())
        with self.assertRaises(FileNotFoundError): r.build(self.root, portal(self.root), 'https://synthetic.invalid', isolated=True)

    def test_registration_directory_loss_rejects_reinit(self):
        self.prepare_logout()
        self.remove_synthetic_directory('registration-approval')
        self.assertEqual('BOOT_DENIED', self.run_process('verify'))
        self.assertFalse((self.root / 'registration-approval').exists())
        with self.assertRaises(ValueError): r.RuntimeStore.initialize_fresh(self.root, portal(self.root), isolated=True)

    def test_old_backup_cannot_restore_logged_out_token(self):
        self.prepare_logout()
        db = self.root / 'registration-approval/registration.sqlite3'
        shutil.copyfile(self.root / 'old-backup.sqlite3', db)
        before = db.read_bytes()
        self.assertEqual('BOOT_DENIED', self.run_process('verify'))
        self.assertEqual(before, db.read_bytes())

    def test_corruption_rejects_without_rebuild(self):
        self.prepare_logout()
        db = self.root / 'registration-approval/registration.sqlite3'
        db.write_bytes(b'Synthetic corrupted database')
        self.assertEqual('BOOT_DENIED', self.run_process('verify'))
        self.assertEqual(b'Synthetic corrupted database', db.read_bytes())

    def test_registered_revocation_cannot_rollback_epoch(self):
        self.assertEqual('PREPARED',self.run_process('prepare-registered'))
        self.assertEqual('TOKEN_ACCEPTED',self.run_process('verify'))
        self.assertEqual('REVOKED',self.run_process('revoke-registered'))
        self.assertEqual('TOKEN_DENIED',self.run_process('verify'))
        db=self.root/'registration-approval/registration.sqlite3'
        shutil.copyfile(self.root/'old-backup.sqlite3',db)
        self.assertEqual('BOOT_DENIED',self.run_process('verify'))

    def test_uninitialized_build_does_not_create_storage(self):
        self.assertEqual('BOOT_DENIED', self.run_process('verify'))
        self.assertFalse((self.root / 'registration-approval').exists())
        self.assertFalse((self.root / '.registration-checkpoint').exists())

    def test_repeated_init_never_overwrites_existing_ledger(self):
        self.prepare_logout()
        db = self.root / 'registration-approval/registration.sqlite3'
        before = db.read_bytes()
        with self.assertRaises(ValueError): r.RuntimeStore.initialize_fresh(self.root, portal(self.root), isolated=True)
        self.assertEqual(before, db.read_bytes())
        self.assertEqual('TOKEN_DENIED', self.run_process('verify'))

    def test_pending_and_committed_crash_restarts_fail_closed(self):
        for phase, status in (('pending-crash', 73), ('committed-crash', 74)):
            with self.subTest(phase=phase):
                if (self.root / 'registration-approval').exists():
                    # Delete only synthetic fixtures between independent scenarios.
                    self.remove_synthetic_directory('registration-approval')
                    self.remove_synthetic_directory('.registration-checkpoint')
                self.assertEqual('PREPARED', self.run_process('prepare'))
                self.run_process(phase, expected=status)
                self.assertEqual('BOOT_DENIED', self.run_process('verify'))
                self.assertEqual('pending', json.loads((self.root / '.registration-checkpoint/state.json').read_text())['status'])

    def test_first_initialization_crash_cannot_auto_retry(self):
        self.run_process('init-crash', expected=75)
        self.assertEqual('BOOT_DENIED', self.run_process('verify'))
        with self.assertRaises(ValueError): r.RuntimeStore.initialize_fresh(self.root, portal(self.root), isolated=True)

    def test_https_insecure_binding_rejected_before_storage_write(self):
        native = portal(self.root); native.CFG['secure'] = False
        with self.assertRaises(ValueError): r.build(self.root, native, 'https://synthetic.invalid', isolated=True)
        self.assertFalse((self.root / 'registration-approval').exists())
        self.assertEqual(False, native.CFG['secure'])


if __name__ == '__main__': unittest.main()
