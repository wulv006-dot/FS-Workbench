from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

from _paths import ROOT, RELEASE
from customer_reports import CustomerReports, anonymous_evidence, report_prompt
from customer_tracking import Store
from conversation_store import ConversationStore


class Conversation:
    def __init__(self, root):
        self.store = ConversationStore(root)
        self.calls = 0
        self.unknown = False
        self.completed = False
        self.last_text = None
    def create(self, user):
        return self.store.create(user)
    def submit(self, user, cid, text, request_id):
        self.calls += 1
        self.last_text = text
        result = self.store.reserve_turn(user, cid, text, request_id)
        if self.unknown:
            raise TimeoutError('simulated lost response')
        return result
    def detail(self, user, cid):
        value = self.store.detail(user, cid)
        if self.completed:
            for turn in value['turns']:
                turn.update(state='completed', artifacts=[{'artifact_id': 'f' * 32, 'mime': 'text/html'}])
        return value


class ReportsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'tracking')
        self.now = datetime.now(timezone.utc)
        self.start = self.now - timedelta(minutes=10)
        source = {'order_no': 'PRIVATE-ORDER', 'email': 'guest@example.invalid', 'uid': 0,
                  'identity_status': 'verified', 'profile': 'FC27', 'gid': 1327, 'site_id': 266,
                  'paid_at': (self.start - timedelta(days=1)).isoformat(), 'pay_status': 1,
                  'order_usd': '929.80', 'discount_usd': '0.99', 'current_status': '已完成',
                  'selected_game': True, 'customer_flag': 'old'}
        candidate = self.store.save_candidates(self.now.date().isoformat(), [source])['items'][0]
        self.track = self.store.track(candidate['candidate_id'], 'a' * 32, now=self.start, owner='admin')
        self.tid = self.track['tracking_id']
        self.store.observe(self.tid, [source], self.now.isoformat(), {'complete': True})
        self.conversation = Conversation(Path(self.temp.name) / 'conversations')
        self.reports = CustomerReports(self.conversation, self.store, 'admin')
    def tearDown(self):
        self.temp.cleanup()

    def test_no_identity_or_unpaid_orders_and_mature_cutoff(self):
        detail = self.store.detail(self.tid)
        detail['orders'] += [dict(detail['orders'][0], order_no='UNPAID', pay_status=0),
                             dict(detail['orders'][0], order_no='AFTER', paid_at=(self.start + timedelta(days=8)).isoformat())]
        result = anonymous_evidence(detail, 7, self.start + timedelta(days=9))
        wire = json.dumps(result)
        self.assertNotIn('guest@example.invalid', wire)
        self.assertNotIn('PRIVATE-ORDER', wire)
        self.assertNotIn('uid', wire)
        self.assertEqual(sum(row['orders'] for row in result['paid_order_groups']), 1)
        self.assertEqual(result['non_paid_orders_excluded'], 1)
        with self.assertRaises(ValueError):
            anonymous_evidence(detail, 14, self.start + timedelta(days=9))

    def test_initial_report_private_html_and_idempotent_recovery(self):
        self.reports.tick()
        self.assertEqual(self.conversation.calls, 1)
        self.assertIn('guest@example.invalid', self.conversation.last_text)
        self.assertIn(self.tid, self.conversation.last_text)
        self.assertIn('首次维护建议', self.conversation.last_text)
        self.conversation.completed = True
        self.reports.tick()
        self.reports.tick()
        self.assertEqual(self.conversation.calls, 1)
        first = self.store.detail(self.tid)['milestones'][0]
        self.assertEqual(first['state'], 'completed')
        self.assertEqual(first['artifact_id'], 'f' * 32)

    def test_unknown_submission_finds_original_turn_without_resubmission(self):
        self.conversation.unknown = True
        self.reports.tick()
        self.assertEqual(self.store.detail(self.tid)['milestones'][0]['state'], 'dispatch_unknown')
        self.conversation.completed = True
        self.reports.tick()
        self.assertEqual(self.conversation.calls, 1)
        self.assertEqual(self.store.detail(self.tid)['milestones'][0]['state'], 'completed')

    def test_no_history_snapshot_does_not_start_model(self):
        with self.store.db() as db:
            db.execute('DELETE FROM history_coverage')
        self.reports.tick()
        self.assertEqual(self.conversation.calls, 0)

    def test_unknown_conversation_creation_is_visible_and_never_recreated(self):
        calls = []
        def lost_create(user):
            calls.append(user)
            self.conversation.store.create(user)
            raise TimeoutError('lost local create result')
        self.conversation.create = lost_create
        self.reports.tick()
        self.reports.tick()
        self.assertEqual(calls, ['admin'])
        self.assertEqual(self.conversation.calls, 0)
        self.assertEqual(self.store.detail(self.tid)['milestones'][0]['state'], 'needs_review')

    def test_overdue_nodes_share_one_conversation_without_parallel_submission(self):
        start = self.now - timedelta(days=31)
        with self.store.db() as db:
            db.execute('UPDATE tracks SET tracked_at=?', (start.isoformat(),))
            for day in (0, 7, 14, 30):
                db.execute('UPDATE milestones SET due_at=? WHERE days=?', ((start + timedelta(days=day)).isoformat(), day))
        self.reports.tick()
        self.reports.tick()
        self.assertEqual(self.conversation.calls, 1)
        self.conversation.completed = True
        self.reports.tick()
        self.reports.tick()
        self.assertEqual(self.conversation.calls, 2)
        nodes = self.store.detail(self.tid)['milestones']
        self.assertEqual(nodes[0]['conversation_id'], nodes[1]['conversation_id'])

    def test_long_history_is_bounded_without_dropping_old_totals(self):
        detail = self.store.detail(self.tid)
        first = detail['orders'][0]
        detail['orders'] = [dict(first, order_no='ORDER-20261109-'+str(i).zfill(9), paid_at=(self.start - timedelta(days=i + 1)).isoformat()) for i in range(1000)]
        value = anonymous_evidence(detail, 0, self.now)
        self.assertEqual(sum(row['orders'] for row in value['paid_order_groups']), 1000)
        self.assertLess(len(report_prompt(detail, 0)), 12000)


if __name__ == '__main__':
    unittest.main()
