"""Offline rejection checks for a live migration; never contacts a service."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import migrate


class MigrationChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.old, self.main = root/'old', root/'main'
        self.unit, self.bridge = root/'gateway.service', root/'host.py'
        self.job = {'id': migrate.JOB, 'enabled': True, 'no_agent': True,
                    'schedule': {'expr': '0 0,15,18,21 * * *'}, 'last_status': 'ok',
                    'script': '/profile/scripts/fs-ops-watchdog/watch.py',
                    'repeat': {'completed': 12}, 'next_run_at': '2026-10-21T18:00:00+00:00'}
        for base, jobs in [(self.old, [self.job]), (self.main, [{'id':'keep'}])]:
            for rel in ['memories', 'business-context', 'cron']:
                (base/rel).mkdir(parents=True)
            (base/'memories/MEMORY.md').write_text('keep learned memory')
            (base/'business-context/current.md').write_text('approved context')
            (base/'AGENTS.md').write_text('current instructions')
            (base/'.env').write_text('dummy test configuration')
            (base/'cron/jobs.json').write_text(json.dumps({'jobs': jobs}))
            c=sqlite3.connect(base/'cron/executions.db')
            c.execute('CREATE TABLE executions(status TEXT)')
            c.close()
        self.unit.write_text('--name hermes-dingtalk --mount type=bind,source='+str(self.old)+',target=/profile')
        self.bridge.write_text("PROFILE = Path('"+str(self.old/'ops-watchdog')+"')")
        self.mock = patch.multiple(migrate, OLD=self.old, MAIN=self.main, UNIT=self.unit, BRIDGE=self.bridge)
        self.mock.start()
        self.addCleanup(self.mock.stop)
        def active_count(container, code):
            base=self.old if container=='hermes-dingtalk' else self.main
            c=sqlite3.connect(base/'cron/executions.db')
            try:return str(c.execute("SELECT count(*) FROM executions WHERE status IN ('claimed','running','queued')").fetchone()[0])
            finally:c.close()
        native_patch=patch.object(migrate, 'native', side_effect=active_count)
        native_patch.start()
        self.addCleanup(native_patch.stop)

    def test_preview_preserves_existing_job_and_memory(self):
        plan, job=migrate.preflight()
        self.assertEqual(plan['target_existing_jobs'], 1)
        self.assertEqual(job, self.job)
        self.assertFalse((self.main/'ops-watchdog').exists())

    def test_reject_changed_memory(self):
        (self.main/'memories/MEMORY.md').write_text('new learning must survive')
        with self.assertRaises(AssertionError): migrate.preflight()

    def test_reject_active_execution(self):
        c=sqlite3.connect(self.old/'cron/executions.db')
        c.execute("INSERT INTO executions VALUES ('running')")
        c.commit();c.close()
        with self.assertRaises(AssertionError): migrate.preflight()

    def test_reject_existing_destination(self):
        (self.main/'ops-watchdog').mkdir()
        with self.assertRaises(AssertionError): migrate.preflight()

    def test_gateway_shares_existing_server_namespace(self):
        self.assertIn('docker exec --env HERMES_ALLOW_ROOT_GATEWAY=1 fs-hermes-desktop',migrate.SERVICE)
        self.assertNotIn('docker run',migrate.SERVICE)
        self.assertNotIn('--force',migrate.SERVICE)

    def test_finish_branch_completes_without_migration_locals(self):
        backup=Path(self.temp.name)/'backup'
        backup.mkdir()
        (backup/'receipt.json').write_text(json.dumps({'stage':'started_readback_required','after_hashes':{}}))
        expected=migrate.sha(self.unit.read_bytes())
        with patch.object(migrate,'BACKUP',backup), patch.object(migrate,'stop_existing_main_gateway') as stop:
            with patch.object(migrate,'run') as run, patch('sys.argv',['migrate.py','--finish-gateway','--expected-unit',expected]), patch('builtins.print'):
                migrate.main()
        stop.assert_called_once()
        self.assertEqual(self.unit.read_text(),migrate.SERVICE)
        self.assertTrue((backup/'container-start-refused.service').exists())
        self.assertEqual(run.call_count,2)


if __name__ == '__main__':
    unittest.main()
