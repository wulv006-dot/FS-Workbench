import sqlite3
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from binding import BindingStore, BindingError


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'binding.sqlite3'
        self.store = BindingStore(self.path, 'test-guild', {'staff'})

    def request(self, user='player', member='266:123', now=100):
        return self.store.request('test-guild', user, member, now)

    def approve(self, request, staff='staff', evidence='ticket-123', now=101):
        return self.store.approve('test-guild', request, staff, evidence, now)

    def test_match_alone_does_not_bind(self):
        self.request()
        self.assertIsNone(self.store.member_for('test-guild', 'player'))

    def test_verified_binding_survives_restart_and_replay(self):
        request = self.request()
        self.assertEqual(self.approve(request), '266:123')
        self.assertEqual(self.approve(request), '266:123')
        reopened = BindingStore(self.path, 'test-guild', {'staff'})
        self.assertEqual(reopened.member_for('test-guild', 'player'), '266:123')
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM approvals').fetchone()[0], 1)

    def test_production_guild_is_rejected(self):
        with self.assertRaises(BindingError):
            self.store.request('1041923524601851914', 'player', '266:123', 100)
        request = self.request()
        with self.assertRaises(BindingError):
            self.store.approve('1041923524601851914', request, 'staff', 'ticket-123', 101)
        with self.assertRaises(BindingError):
            self.store.member_for('1041923524601851914', 'player')

    def test_unauthorized_self_and_empty_evidence_rejected(self):
        request = self.request()
        for staff, evidence in [('player', 'ticket-123'), ('outsider', 'ticket-123'), ('staff', '')]:
            with self.subTest(staff=staff, evidence=evidence), self.assertRaises(BindingError):
                self.approve(request, staff, evidence)
        own = self.request(user='staff', member='266:456')
        with self.assertRaises(BindingError):
            self.approve(own)
        self.assertIsNone(self.store.member_for('test-guild', 'player'))

    def test_expired_request_cannot_bind(self):
        request = self.request()
        with self.assertRaises(BindingError):
            self.approve(request, now=100 + 86400)

    def test_new_request_invalidates_older_request(self):
        old = self.request()
        new = self.request(member='266:456', now=110)
        with self.assertRaises(BindingError):
            self.approve(old, now=111)
        self.assertEqual(self.approve(new, now=111), '266:456')

    def test_duplicate_member_cannot_be_claimed_by_other_user(self):
        a = self.request()
        b = self.request(user='other')
        self.approve(a)
        with self.assertRaises(BindingError):
            self.approve(b)
        self.assertIsNone(self.store.member_for('test-guild', 'other'))

    def test_bound_user_cannot_silently_switch_member(self):
        self.approve(self.request())
        with self.assertRaises(BindingError):
            self.request(member='266:456')
        self.assertEqual(self.store.member_for('test-guild', 'player'), '266:123')

    def test_noncanonical_member_ids_cannot_bypass_uniqueness(self):
        for member in ['0266:123', '266:00123', '123', '266:0']:
            with self.subTest(member=member), self.assertRaises(BindingError):
                self.request(member=member)

    def test_audit_failure_rolls_back_binding_and_request(self):
        request = self.request()
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON approvals "
                         "BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.approve(request)
        self.assertIsNone(self.store.member_for('test-guild', 'player'))
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute('SELECT status FROM requests WHERE id=?',
                                          (request,)).fetchone()[0], 'pending')

    def test_clock_boundaries_and_approved_replay_after_expiry(self):
        request = self.request()
        with self.assertRaises(BindingError):
            self.approve(request, now=99)
        self.assertEqual(self.approve(request, now=86499), '266:123')
        self.assertEqual(self.approve(request, now=90000), '266:123')

    def test_simultaneous_approvals_keep_single_binding_and_audit(self):
        a = self.request()
        b = self.request(user='other')

        def approve_separately(request):
            store = BindingStore(self.path, 'test-guild', {'staff'})
            try:
                return store.approve('test-guild', request, 'staff', 'ticket-123', 101)
            except BindingError:
                return 'conflict'

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(approve_separately, [a, b]))
        self.assertEqual(sorted(results), ['266:123', 'conflict'])
        winner = a if results[0] == '266:123' else b
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(approve_separately, [winner, winner])),
                             ['266:123', '266:123'])
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM approvals').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
