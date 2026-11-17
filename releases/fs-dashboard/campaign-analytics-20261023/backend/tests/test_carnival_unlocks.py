import unittest

from campaign_backend.core import ContractError
from campaign_backend.discount_revenue import carnival_unlocks, read_carnival_unlocks


def log(coupon_id, uid, status=1, use_time='2026-11-20 10:00:00', site_id=266):
    return dict(site_id=site_id, coupon_id=coupon_id, status=status, use_time=use_time, member={'uid': uid, 'usname': 'a***'})


class Reader:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def pages(self, resource, filters=(), **_):
        self.calls.append((resource, list(filters)))
        return self.rows


class CarnivalUnlocks(unittest.TestCase):
    def test_paid_uses_map_to_their_coupon_set_in_utc(self):
        out = carnival_unlocks([log(1427, 42), log(1405, '7', use_time='2026-11-21 08:30:00'), log(1433, 42, status=0)])
        self.assertEqual(out['uses'], [
            dict(uid='42', set='poe', used_at='2026-11-20T02:00:00Z'),
            dict(uid='7', set='fc27', used_at='2026-11-21T00:30:00Z'),
        ])

    def test_duplicates_collapse_and_rows_without_member_are_skipped(self):
        out = carnival_unlocks([log(1401, 5), log(1403, 5), log(1401, None)])
        self.assertEqual(len(out['uses']), 1)

    def test_scope_and_state_are_enforced(self):
        with self.assertRaises(ContractError):
            carnival_unlocks([log(1395, 1)])
        with self.assertRaises(ContractError):
            carnival_unlocks([log(1401, 1, site_id=1)])
        with self.assertRaises(ContractError):
            carnival_unlocks([log(1401, 1, status=3)])

    def test_reader_asks_for_the_eighteen_mystery_coupons_in_the_window(self):
        reader = Reader([log(1411, 9)])
        out = read_carnival_unlocks(reader, {'action': 'carnival_unlocks'})
        self.assertEqual(out['uses'][0]['set'], 'aion2')
        resource, filters = reader.calls[0]
        self.assertEqual(resource, 'coupon_logs')
        self.assertEqual(len(filters[1][2].split(',')), 18)
        self.assertEqual(filters[2], ('use_time', 'RANGE', '2026-11-19 13:00:00,2026-12-02 12:59:59'))
        with self.assertRaises(ContractError):
            read_carnival_unlocks(reader, {'action': 'carnival_unlocks', 'uid': '1'})


if __name__ == '__main__':
    unittest.main()
