"""Run the native Node response fixture through dispatch and the SQLite ledger."""
import json
import shutil
import subprocess
import unittest

from test_maintenance_dispatch import Bridge, Dispatcher, NOW, ROOT, ledger_test, TEMPLATE


class BridgeLedgerTest(unittest.TestCase):
    setUp = ledger_test.LedgerTest.setUp
    connection = ledger_test.LedgerTest.connection

    def rule(self, rule, quota=1):
        self.ledger.save_rule(rule, 0, dict(enabled=True, priority=1, template=TEMPLATE,
                                           daily_quota=quota), 'admin', NOW)

    def test_native_admin_pending_registration_routes_by_original_job(self):
        node = shutil.which('node')
        self.assertIsNotNone(node)
        fixture = ROOT / 'tests' / 'test_maintenance_coupon_bridge.cjs'

        class NativeBridge(Bridge):
            def grant(self, coupon, email, batch):
                arguments = dict(coupon_id=coupon, email=email, batch=batch)
                if email == 'known@example.net':
                    arguments['job'] = 'admin-77'
                script = ('const {submit} = require(process.argv[1]);'
                          'submit(JSON.parse(process.argv[2])).then(v => console.log(JSON.stringify(v)))'
                          '.catch(e => { console.error(e); process.exitCode = 1; });')
                output = subprocess.check_output([node, '-e', script, str(fixture), json.dumps(arguments)], timeout=10)
                return json.loads(output)

        runner = Dispatcher(self.ledger, NativeBridge(), lambda row, at: lambda db, fresh: None, lambda: NOW)
        entries = []
        for case, rule in (('known', 'r1'), ('missing', 'r2')):
            entry = self.ledger.enqueue(case, case, case + '@example.net', rule, NOW)
            self.ledger.commit_review(entry, dict(digest='proof', decision='pass'), 'proof', NOW)
            self.ledger.decide(entry, 'confirmed', 'admin', NOW)
            runner.once(entry)
            self.assertEqual('pending_register', self.ledger.entry(entry)['state'])
            entries.append(entry)
        self.assertEqual([(entries[0], 'admin-77')], [(r['id'], r['job_id']) for r in self.ledger.reconcile_queue()])
        self.assertEqual([entries[1]], [r['id'] for r in self.ledger.manual_queue()])


if __name__ == '__main__':
    unittest.main()
