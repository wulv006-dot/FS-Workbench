import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from community import CommunityStore, CommunityError


class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'community.db'
        self.store = CommunityStore(self.path, {'editor', 'reviewer'})

    def draft(self, **kwargs):
        args = dict(actor='editor', title='SBC checklist', kind='sbc',
                    body='Check card versions and requirements.',
                    source='https://www.ea.com/games/ea-sports-fc', season=27, now=100)
        args.update(kwargs)
        return self.store.draft(**args)

    def event(self, capacity=2):
        return self.store.create_event('editor', 'FC27 squad clinic', capacity, 200, 100)

    def test_only_reviewed_content_is_visible_and_withdrawal_hides_it(self):
        item = self.draft()
        self.assertEqual(self.store.latest(), [])
        with self.assertRaises(CommunityError):
            self.store.get(item)
        self.store.approve('reviewer', item, 101)
        self.assertEqual(self.store.get(item)['title'], 'SBC checklist')
        self.store.withdraw('editor', item)
        self.assertEqual(self.store.latest(), [])

    def test_owner_can_publish_own_draft_but_outsider_cannot(self):
        item = self.draft()
        with self.assertRaises(CommunityError):
            self.store.approve('outsider', item, 101)
        self.store.approve('editor', item, 101)
        self.assertEqual(self.store.get(item)['reviewer'], 'editor')
        with self.assertRaises(CommunityError):
            self.draft(season=26)
        with self.assertRaises(CommunityError):
            self.draft(actor='outsider')

    def test_invalid_source_and_oversize_text_rejected(self):
        for source in ['http://example.com', 'https://user:pass@example.com', 'javascript:alert(1)']:
            with self.subTest(source=source), self.assertRaises(CommunityError):
                self.draft(source=source)
        with self.assertRaises(CommunityError):
            self.draft(body='x' * 1501)

    def test_duplicate_join_preserves_original_channel_and_counts_once(self):
        event = self.event()
        self.store.join(event, 'player', 'channel-a', 101)
        self.store.join(event, 'player', 'channel-b', 102)
        self.assertEqual(self.store.report('editor', event),
                         [{'channel': 'channel-a', 'active': 1, 'cancelled': 0}])
        reopened = CommunityStore(self.path, {'editor', 'reviewer'})
        self.assertEqual(reopened.report('editor', event)[0]['active'], 1)

    def test_concurrent_last_slot_only_one_wins(self):
        event = self.event(capacity=1)
        def join(user):
            try:
                self.store.join(event, user, 'channel-a', 101)
                return 'joined'
            except CommunityError:
                return 'full'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(join, ['a', 'b'])), ['full', 'joined'])

    def test_cancellation_releases_slot_and_rejoin_keeps_first_source(self):
        event = self.event(capacity=1)
        self.store.join(event, 'a', 'first', 101)
        self.store.leave(event, 'a')
        self.store.join(event, 'b', 'second', 102)
        self.store.leave(event, 'b')
        self.store.join(event, 'a', 'third', 103)
        self.assertEqual(self.store.report('editor', event), [
            {'channel': 'first', 'active': 1, 'cancelled': 0},
            {'channel': 'second', 'active': 0, 'cancelled': 1}])

    def test_deadline_and_private_report(self):
        event = self.event()
        with self.assertRaises(CommunityError):
            self.store.join(event, 'a', 'channel', 200)
        with self.assertRaises(CommunityError):
            self.store.report('outsider', event)
        self.assertEqual(self.store.events(200), [])


if __name__ == '__main__':
    unittest.main()
