import unittest, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"deploy"))
from prepare_release import replace_once


class ExactTarget(unittest.TestCase):
    def test_changes_one_target_and_preserves_surrounding_bytes(self):
        self.assertEqual(replace_once('before\r\nOLD\nafter', 'OLD', 'NEW'), 'before\r\nNEW\nafter')

    def test_rejects_missing_or_ambiguous_target(self):
        for value in ('before after', 'OLD before OLD'):
            with self.subTest(value=value), self.assertRaises(AssertionError):
                replace_once(value, 'OLD', 'NEW')


if __name__ == '__main__':
    unittest.main()
