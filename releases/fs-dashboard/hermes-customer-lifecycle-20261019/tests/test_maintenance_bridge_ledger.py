"""Run the native Node response fixture through dispatch and the SQLite ledger."""
import json
import shutil
import subprocess
import unittest

from test_maintenance_dispatch import Bridge, Dispatcher, NOW, ROOT, ledger_test, TEMPLATE
from maintenance_reconcile import reconcile


class BridgeLedgerTest(unittest.TestCase):
    setUp = ledger_test.LedgerTest.setUp
    connection = ledger_test.LedgerTest.connection

    def rule(self, rule, quota=1):
        self.ledger.save_rule(rule, 0, dict(enabled=True, priority=1, template=TEMPLATE,
                                           daily_quota=quota), 'admin', NOW)

    def test_native_admin_receipts_route_for_job_reconciliation_or_manual_review(self):
        node = shutil.which('node')
        self.assertIsNotNone(node)
        fixture = ROOT / 'tests' / 'test_maintenance_coupon_bridge.cjs'

        class NativeBridge(Bridge):
            def grant(self, coupon, email, batch):
                arguments = dict(coupon_id=coupon, email=email, batch=batch)
                if email == 'known@example.net':
                    arguments['job'] = 'admin-77'
                elif email == 'inconclusive@example.net':
                    arguments.update(job=88, overrides=dict(processed=0))
                elif email == 'foreign@example.net':
                    arguments.update(job='foreign-77', overrides=dict(
                        mode='async', rows=[dict(email='other@example.net')]))
                script = ('const {submit} = require(process.argv[1]);'
                          'submit(JSON.parse(process.argv[2])).then(v => console.log(JSON.stringify(v)))'
                          '.catch(e => { console.error(e); process.exitCode = 1; });')
                output = subprocess.check_output([node, '-e', script, str(fixture), json.dumps(arguments)], timeout=10)
                return json.loads(output)

        runner = Dispatcher(self.ledger, NativeBridge(), lambda row, at: lambda db, fresh: None, lambda: NOW)
        entries = []
        scenarios = [('known', 'pending_register'), ('missing', 'pending_register'),
                     ('inconclusive', 'unknown'), ('foreign', 'unknown')]
        for case, state in scenarios:
            self.rule(case)
            entry = self.ledger.enqueue(case, case, case + '@example.net', case, NOW)
            self.ledger.commit_review(entry, dict(digest='proof', decision='pass'), 'proof', NOW)
            self.ledger.decide(entry, 'confirmed', 'admin', NOW)
            runner.once(entry)
            self.assertEqual(state, self.ledger.entry(entry)['state'])
            entries.append(entry)
        self.assertEqual([(entries[0], 'admin-77'), (entries[2], '88')],
                         [(row['id'], row['job_id']) for row in self.ledger.reconcile_queue()])
        self.assertCountEqual([entries[1], entries[3]], [row['id'] for row in self.ledger.manual_queue()])


    def test_reconciliation_releases_quotas_only_for_a_matching_rejection(self):
        node = shutil.which('node')
        self.assertIsNotNone(node)
        fixture = ROOT / 'tests' / 'test_maintenance_coupon_bridge.cjs'
        scenarios = [
            ('batch', 'grant_batch_no', {'grant_batch_no': 'FCSM_' + 'B' * 32}),
            ('recipient', 'rows.email', {'rows': [{'email': 'other@example.net'}]}),
            ('job', 'job_id', {'job_id': 'other-job'}),
            ('matched', None, {}),
        ]
        for case, conflict, overrides in scenarios:
            with self.subTest(case=case):
                self.rule(case)
                email = case + '@example.net'
                entry = self.ledger.enqueue(case, case, email, case, NOW)
                self.ledger.commit_review(entry, dict(digest='proof', decision='pass'), 'proof', NOW)
                self.ledger.decide(entry, 'confirmed', 'admin', NOW)
                original = self.ledger.claim(entry, NOW)
                job = 'admin-' + case
                self.ledger.result(entry, 'dispatching', dict(state='pending_register', job_id=job), NOW)

                def lookup(job_id, recipient, batch):
                    self.assertEqual((job, email, original['batch']), (job_id, recipient, batch))
                    args = dict(job=job_id, email=recipient, batch=batch, overrides=overrides)
                    script = ('const {readReceipt} = require(process.argv[1]);'
                              'readReceipt(JSON.parse(process.argv[2])).then(v => console.log(JSON.stringify(v)))'
                              '.catch(e => { console.error(e); process.exitCode = 1; });')
                    return json.loads(subprocess.check_output(
                        [node, '-e', script, str(fixture), json.dumps(args)], timeout=10))

                reconcile(self.ledger, lambda: NOW, lookup)
                actual = self.ledger.entry(entry)
                self.assertEqual((job, original['batch']), (actual['job_id'], actual['batch']))
                self.assertEqual('unknown' if conflict else 'rejected', actual['state'])
                manual_ids = [row['id'] for row in self.ledger.manual_queue()]
                self.assertEqual(bool(conflict), entry in manual_ids)
                self.assertNotIn(entry, [row['id'] for row in self.ledger.reconcile_queue()])
                if conflict:
                    self.assertEqual([conflict], actual['result']['identity_conflicts'])
                self.rule(case + '-other')
                for event, customer, rule, blocked in [
                    ('customer', case, case + '-other', 'customer_quota'),
                    ('rule', case + '-other', case, 'daily_quota'),
                ]:
                    successor = self.ledger.enqueue(case + event, customer, email, rule, NOW)
                    self.ledger.commit_review(successor, dict(digest='proof', decision='pass'), 'proof', NOW)
                    self.ledger.decide(successor, 'confirmed', 'admin', NOW)
                    self.assertEqual(not conflict, self.ledger.claim(successor, NOW) is not None)
                    if conflict:
                        self.assertEqual(blocked, self.ledger.entry(successor)['result']['reason'])
                if conflict:
                    self.assertFalse(self.ledger.result(entry, 'unknown', dict(state='rejected'), NOW,
                                                        reconciled=True))
                    self.assertTrue(self.ledger.manual_result(entry, 'manually_closed', 'admin', NOW,
                                                              '核对了原批次和原 job'))


if __name__ == '__main__':
    unittest.main()
