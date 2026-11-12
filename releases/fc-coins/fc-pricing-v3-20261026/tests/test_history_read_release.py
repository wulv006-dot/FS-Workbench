"""The history repair reuses V3 admission, with one existing file only."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest

DEPLOY = Path(__file__).resolve().parents[1] / 'deploy'
sys.path.insert(0, str(DEPLOY))
spec = importlib.util.spec_from_file_location('history_read_adapter_test', DEPLOY / 'fc_v3_release_adapter.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class HistoryReadRelease(unittest.TestCase):
    def manifest(self):
        return dict(scope=adapter.HISTORY_READ_SCOPE, releaseReady=True,
                    businessWrites=False, timersChanged=False,
                    files=[dict(candidate='source/coins_evidence.py',
                                target='/opt/fs-hermes-fc/coins_evidence.py',
                                beforeSha256='a' * 64, sha256='b' * 64,
                                owner='0:0', mode='0o644')])

    def test_exact_existing_history_file(self):
        m = self.manifest()
        self.assertIs(adapter.checked_manifest(m), m)

    def test_reject_extra_target_or_new_file(self):
        for change in ('extra', 'new', 'target'):
            m = self.manifest()
            if change == 'extra':
                m['files'].append(copy.deepcopy(m['files'][0]))
            elif change == 'new':
                m['files'][0]['beforeSha256'] = None
            else:
                m['files'][0]['target'] = '/opt/fc27-cloud-browser/price_writer.py'
            with self.subTest(change=change), self.assertRaises(ValueError):
                adapter.checked_manifest(m)

    def test_no_business_or_timer_mutation(self):
        for field in ('businessWrites', 'timersChanged'):
            m = self.manifest()
            m[field] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                adapter.checked_manifest(m)


if __name__ == '__main__':
    unittest.main()
