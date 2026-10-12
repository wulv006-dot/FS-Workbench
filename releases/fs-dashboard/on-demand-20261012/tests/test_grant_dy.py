import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'deploy'))
from grant_dy import grant_all


class GrantTests(unittest.TestCase):
    def setUp(self):
        self.data = {'schemaVersion': 1, 'clients': [
            {'id': 'dy-all-projects', 'owner': 'DY', 'enabled': True,
             'projects': ['FC27'], 'includeProfit': True, 'expiresAtEpoch': 100,
             'tokenSha256': 'a'*64, 'futureSetting': 'retain'},
            {'id': 'limited', 'projects': ['D4'], 'enabled': False}]}

    def test_only_projects_changes_and_original_is_unchanged(self):
        before = copy.deepcopy(self.data)
        result = grant_all(self.data, now=1)
        self.assertEqual(self.data, before)
        self.assertEqual(result['clients'][0]['projects'], ['*'])
        result['clients'][0]['projects'] = ['FC27']
        self.assertEqual(result, before)

    def test_idempotent(self):
        once = grant_all(self.data, now=1)
        self.assertEqual(grant_all(once, now=1), once)

    def test_revoked_expired_wrong_owner_or_bad_hash_rejected(self):
        for field, value in [('enabled', False), ('expiresAtEpoch', 0),
                             ('owner', 'other'), ('tokenSha256', 'bad'), ('includeProfit', False)]:
            data = copy.deepcopy(self.data); data['clients'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                grant_all(data, now=1)

    def test_missing_or_duplicate_dy_rejected(self):
        for clients in [[], [self.data['clients'][0]]*2]:
            with self.assertRaises(ValueError):
                grant_all({'clients': clients}, now=1)


if __name__ == '__main__':
    unittest.main()
