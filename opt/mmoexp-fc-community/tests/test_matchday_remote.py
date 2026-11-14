import datetime
import json
import subprocess
import unittest

from matchday_remote import SnapshotUnavailable, fetch_latest


class MatchdayRemoteTests(unittest.TestCase):
    def test_accepts_fresh_forced_command_snapshot(self):
        now = datetime.datetime(2026, 11, 14, 14, tzinfo=datetime.timezone.utc)
        payload = {'schema_version': 1, 'checked_at_utc': now.isoformat(),
                   'sources': {'openligadb': {}, 'espn': {}}}
        calls = []

        def runner(command, **options):
            calls.append((command, options['input']))
            return subprocess.CompletedProcess(command, 0, json.dumps(payload).encode(), b'')

        self.assertEqual(fetch_latest('/key', '/hosts', runner, now), payload)
        self.assertEqual(calls[0][1], b'{"action":"latest"}\n')
        self.assertIn('fc27-match-fetch@172.18.108.183', calls[0][0])

    def test_rejects_stale_snapshot(self):
        now = datetime.datetime(2026, 11, 14, 14, tzinfo=datetime.timezone.utc)
        payload = {'schema_version': 1, 'checked_at_utc': '2026-11-13T00:00:00+00:00',
                   'sources': {}}
        runner = lambda command, **options: subprocess.CompletedProcess(command, 0, json.dumps(payload).encode(), b'')
        with self.assertRaises(SnapshotUnavailable):
            fetch_latest('/key', '/hosts', runner, now)


if __name__ == '__main__':
    unittest.main()
