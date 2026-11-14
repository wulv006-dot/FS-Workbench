import json
import os
import tempfile
import unittest

from matchday_espn_probe import write_snapshot


class ESPNProbeTests(unittest.TestCase):
    def test_persists_normalized_snapshot_without_partial_temp_file(self):
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, 'snapshots')
            payload = {'provider': 'ESPN', 'day': '20261121',
                       'fixtures_by_league': {'pl': [{'fixture_id': '401879233'}]}}
            path = write_snapshot(folder, payload)
            with open(path, encoding='utf-8') as stream:
                self.assertEqual(json.load(stream), payload)
            self.assertEqual(os.listdir(folder), [os.path.basename(path)])


if __name__ == '__main__':
    unittest.main()
