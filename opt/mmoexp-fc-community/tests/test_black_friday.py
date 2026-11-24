import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from black_friday import ClaimStore, reward_tier

NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)
START = '2026-10-01T00:00:00+08:00'

def order(i, status='complete', paid=True, game=1327, date=START, site=266):
    return dict(id=i, status=status, paid=paid, game=game, paid_at=date, site=site)

class BlackFridayTest(unittest.TestCase):
    def test_tiers(self):
        self.assertEqual(reward_tier([], NOW), 'one')
        self.assertEqual(reward_tier([order(1, 'open', game=99)], NOW), 'two')
        four = [order(i, game=200+i) for i in range(1,5)]
        self.assertEqual(reward_tier(four+[order(5,'open'),four[0]], NOW), 'two')
        self.assertEqual(reward_tier(four+[order(5)], NOW), 'bonus')

    def test_period_and_status(self):
        rows = [order(1,date='2026-09-30T15:59:59Z'),order(2,site=777),
                order(3,status='cancelled'),order(4,status='refunded'),
                order(5,paid=False),order(6,date='2026-12-01T00:00:00Z')]
        self.assertEqual(reward_tier(rows, NOW), 'one')
        with self.assertRaises(ValueError):
            reward_tier([order(1,status='unexpected')], NOW)

    def test_persistent_once_for_both_accounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, 'test.db')
            store = ClaimStore(db)
            with ThreadPoolExecutor(4) as pool:
                results = list(pool.map(lambda _: store.claim(1, 8, 'bonus'), range(8)))
            self.assertEqual(results.count(('bonus', True)), 1)
            self.assertEqual(ClaimStore(db).claim(1, 8, 'one'), ('bonus',False))
            for discord_id, member_id in ((2,8),(1,9)):
                with self.assertRaises(ValueError):
                    store.claim(discord_id, member_id, 'one')
