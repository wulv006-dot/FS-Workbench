import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
from save_local_token import save_token


class TokenSaveTests(unittest.TestCase):
    def test_invalid_input_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'secret'
            with self.assertRaises(ValueError):
                save_token(directory, 'bad\ninput')
            self.assertFalse(directory.exists())

    def test_synthetic_token_saved_and_replaced_without_printing(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'secret'
            save_token(directory, 'SYNTHETIC_TEST_VALUE_' + 'a' * 40)
            save_token(directory, 'SYNTHETIC_TEST_VALUE_' + 'b' * 40)
            data = (directory / 'discord.env').read_text(encoding='utf-8')
            self.assertEqual(data, 'FC_ENABLE_LIVE=1\nDISCORD_BOT_TOKEN=SYNTHETIC_TEST_VALUE_' + 'b' * 40 + '\n')


if __name__ == '__main__':
    unittest.main()
