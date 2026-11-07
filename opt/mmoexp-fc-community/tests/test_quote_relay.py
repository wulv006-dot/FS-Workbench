import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from quote_relay import RelayStore


AUTHOR = 1167033335256731658


def message(mid, *, channel=12, guild=11, author=AUTHOR, bot=True, created=1000, **extra):
    values = dict(id=mid, guild=SimpleNamespace(id=guild), channel=SimpleNamespace(id=channel),
                  author=SimpleNamespace(id=author, bot=bot),
                  created_at=datetime.fromtimestamp(created, timezone.utc), type=0,
                  interaction=None, interaction_metadata=None, webhook_id=None)
    values.update(extra)
    return SimpleNamespace(**values)


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'relay.sqlite')
        self.store = RelayStore(self.path, {12: 'sbc', 13: 'packs', 14: 'gallery'}, 11, self_id=15)

    def tearDown(self):
        self.tmp.cleanup()

    def test_accepts_only_recent_whitelisted_bot_noninteraction_messages(self):
        bad = [message(1, guild=99), message(2, channel=99), message(3, author=15),
               message(4, bot=False), message(5, author=16), message(6, created=699),
               message(7, created=1031), message(8, type=1),
               message(9, interaction=object()), message(10, interaction_metadata=object()),
               message(11, webhook_id=44)]
        for item in bad:
            with self.subTest(mid=item.id):
                self.assertFalse(self.store.accept(item, 1000))
        self.assertTrue(self.store.accept(message(12), 1000))
        self.assertEqual(self.store.due(1029), [])
        self.assertEqual(self.store.due(1030), [{'channel_id': 12, 'kind': 'sbc', 'message_id': 12}])

    def test_coalesces_updates_and_respects_cooldown(self):
        self.assertTrue(self.store.accept(message(100), 1000))
        self.assertTrue(self.store.accept(message(101, created=1010), 1010))
        self.assertEqual(self.store.claim(12, 1029), None)
        self.assertEqual(self.store.claim(12, 1030)['message_id'], 101)
        self.assertEqual(self.store.claim(12, 1030), None)
        self.assertTrue(self.store.accept(message(102, created=1040), 1040))
        self.store.complete(12, 101, 1041)
        self.assertEqual(self.store.due(1640), [])
        self.assertEqual(self.store.claim(12, 1641)['message_id'], 102)

    def test_restart_does_not_replay_or_resend_claimed_message(self):
        self.assertTrue(self.store.accept(message(100), 1000))
        self.assertEqual(self.store.claim(12, 1030)['message_id'], 100)
        restarted = RelayStore(self.path, {12: 'sbc', 13: 'packs', 14: 'gallery'}, 11)
        self.assertFalse(restarted.accept(message(100), 1030))
        self.assertEqual(restarted.due(1030), [])
        self.assertTrue(restarted.accept(message(101, created=1040), 1040))
        self.assertEqual(restarted.claim(12, 1629), None)
        self.assertEqual(restarted.claim(12, 1630)['message_id'], 101)

    def test_failure_and_mismatched_completion_cannot_replay(self):
        self.store.accept(message(100), 1000)
        self.store.claim(12, 1030)
        with self.assertRaises(ValueError):
            self.store.complete(12, 99, 1031)
        self.store.fail(12, 100, 1031)
        self.assertEqual(self.store.due(2000), [])
        self.assertFalse(self.store.accept(message(100, created=1999), 2000))

    def test_channels_and_mapping_are_isolated(self):
        self.store.accept(message(100), 1000)
        self.store.accept(message(50, channel=13), 1000)
        self.assertEqual({x['kind'] for x in self.store.due(1030)}, {'sbc', 'packs'})
        changed = RelayStore(self.path, {12: 'gallery', 13: 'packs'}, 11)
        self.assertEqual(changed.due(1030), [{'channel_id': 13, 'kind': 'packs', 'message_id': 50}])
        self.assertTrue(changed.accept(message(101), 1000))
        self.assertEqual(changed.claim(12, 1030)['kind'], 'gallery')

    def test_simultaneous_claims_only_return_one_batch(self):
        self.store.accept(message(100), 1000)
        barrier = threading.Barrier(2)

        def claim():
            barrier.wait()
            return self.store.claim(12, 1030)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)


if __name__ == '__main__':
    unittest.main()

class ExtendedRelayTests(unittest.TestCase):
    def test_only_five_distinct_supported_relay_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'relay.sqlite')
            routes = {12: 'sbc', 13: 'packs', 14: 'gallery', 15: 'evolutions', 16: 'boosting'}
            store = RelayStore(path, routes, 11)
            self.assertTrue(store.accept(message(77, channel=15), 1000))
            self.assertTrue(store.accept(message(78, channel=16), 1000))
            self.assertEqual({row['kind'] for row in store.due(1030)}, {'evolutions', 'boosting'})
            for bad in ({12: 'coins'}, dict(routes, **{'17': 'sbc'}), {12: 'sbc', 13: 'sbc'}):
                with self.assertRaises(ValueError):
                    RelayStore(path, bad, 11)
