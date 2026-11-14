import json
import datetime
import os
import tempfile
import unittest

from matchday_snapshot_worker import read_latest


class SnapshotWorkerTests(unittest.TestCase):
    def test_only_latest_snapshot_with_fixed_request(self):
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, 'snapshots')
            os.mkdir(folder)
            payload = {'schema_version': 1, 'checked_at_utc': '2026-11-14T14:00:00+00:00',
                       'sources': {'openligadb': {}, 'espn': {}}}
            with open(os.path.join(folder, '20261114.json'), 'w', encoding='utf-8') as stream:
                json.dump(payload, stream)
            self.assertEqual(json.loads(read_latest(root, b'{"action":"latest"}')), payload)
            with self.assertRaises(ValueError):
                read_latest(root, b'{"action":"../../etc/passwd"}')

    def test_includes_only_fresh_live_overlay(self):
        now = datetime.datetime(2026, 11, 21, 13, tzinfo=datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, 'snapshots')
            os.mkdir(folder)
            payload = {'schema_version': 1, 'checked_at_utc': now.isoformat(), 'sources': {}}
            with open(os.path.join(folder, 'base.json'), 'w', encoding='utf-8') as out:
                json.dump(payload, out)
            live = {'schema_version': 1, 'checked_at_utc': now.isoformat(), 'fixtures': [{'openliga_id': '86635'}]}
            with open(os.path.join(root, 'live.json'), 'w', encoding='utf-8') as out:
                json.dump(live, out)
            self.assertEqual(json.loads(read_latest(root, b'{"action":"latest"}', now))['live'], live)
            later = now + datetime.timedelta(minutes=3)
            self.assertNotIn('live', json.loads(read_latest(root, b'{"action":"latest"}', later)))


if __name__ == '__main__':
    unittest.main()
