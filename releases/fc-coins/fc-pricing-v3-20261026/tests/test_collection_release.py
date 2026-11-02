from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import unittest

DEPLOY = Path(__file__).resolve().parents[1] / 'deploy'
sys.path.insert(0, str(DEPLOY))
import fc_v3_release_adapter as adapter
import target_map


def manifest(scope, mapping):
    return dict(scope=scope, businessWrites=False, timersChanged=False, releaseReady=True,
        files=[dict(candidate=name, target=target, owner='0:0', mode='0o644',
                    beforeSha256='a'*64, sha256='b'*64) for name,target in mapping.items()])


class CollectionRelease(unittest.TestCase):
    def test_collection_scope_is_exactly_three_existing_entry_files(self):
        self.assertEqual(set(target_map.COLLECTION_NAMES), {
            'source/fc_pricing_v3/sources.py', 'source/hermes-copy/fc_pricing_v3/sources.py', 'source/server_quote_job.py'})
        self.assertEqual(adapter.COLLECTION_TARGETS, {
            'source/fc_pricing_v3/sources.py':'/opt/fc27-cloud-browser/fc_pricing_v3/sources.py',
            'source/hermes-copy/fc_pricing_v3/sources.py':'/opt/fs-hermes-fc/fc_pricing_v3/sources.py',
            'source/server_quote_job.py':'/opt/fc27-cloud-browser/server_quote_job.py'})

    def test_collection_manifest_cannot_add_target_writer_or_business_write(self):
        value = manifest(target_map.COLLECTION_SCOPE, adapter.COLLECTION_TARGETS)
        self.assertEqual(adapter.checked_manifest(value), value)
        mutations = []
        added = deepcopy(value); added['files'][0]['beforeSha256'] = None; mutations.append(added)
        writer = deepcopy(value); writer['files'][0].update(candidate='source/price_writer.py', target='/opt/fc27-cloud-browser/price_writer.py'); mutations.append(writer)
        missing = deepcopy(value); missing['files'].pop(); mutations.append(missing)
        for field in ('businessWrites','timersChanged'):
            change=deepcopy(value); change[field]=True; mutations.append(change)
        for changed in mutations:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                adapter.checked_manifest(changed)

    def test_existing_delta_scope_remains_exact_and_accepted(self):
        self.assertEqual(set(target_map.DELTA_NAMES), {'source/fc_pricing_v3/scheduler.py', 'source/hermes-copy/fc_pricing_v3/scheduler.py'})
        value = manifest(target_map.DELTA_SCOPE, adapter.DELTA_TARGETS)
        self.assertEqual(adapter.checked_manifest(value), value)

    def test_existing_manifest_preparer_exposes_collection_as_exclusive_mode(self):
        result = subprocess.run([sys.executable, '-B', str(DEPLOY/'prepare_manifest.py'), '--help'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--collection', result.stdout)


if __name__ == '__main__':
    unittest.main()
