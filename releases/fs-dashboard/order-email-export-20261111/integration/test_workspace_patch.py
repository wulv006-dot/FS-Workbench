import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
import workspace_patch as subject


class WorkspacePatchTests(unittest.TestCase):
    def test_only_lifecycle_block_changes(self):
        source = (Path(__file__).parent / 'fixtures/data-workspace.js').read_bytes()
        result = subject.prepare_workspace(source)
        self.assertEqual(result.replace(subject.REPLACEMENT, subject.ANCHOR, 1), source)
        for preserved in ('折扣码推广渠道', '已满观察期新客', 'coupon_mapping_version'):
            self.assertIn(preserved.encode('utf8'), result)
        self.assertIn(b'mountOrderEmailExcelExport', result)
        result.decode('utf8')
        self.assertNotEqual(hashlib.sha256(result).hexdigest(), subject.EXPECTED_SHA256)

    def test_changed_baseline_and_duplicate_anchor_refused(self):
        source = (Path(__file__).parent / 'fixtures/data-workspace.js').read_bytes()
        with self.assertRaisesRegex(ValueError, 'baseline_changed'):
            subject.prepare_workspace(source + b'\n')
        changed = source + subject.ANCHOR
        with patch.object(subject, 'EXPECTED_SHA256', hashlib.sha256(changed).hexdigest()):
            with self.assertRaisesRegex(ValueError, 'anchor_changed'):
                subject.prepare_workspace(changed)


if __name__ == '__main__':
    unittest.main()
