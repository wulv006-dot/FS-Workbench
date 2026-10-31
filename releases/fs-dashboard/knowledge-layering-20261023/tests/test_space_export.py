import importlib.util
from pathlib import Path
import unittest
import hashlib
import json
import tempfile

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('export_fs_space', ROOT / 'tools/export_fs_space.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SpaceExportTests(unittest.TestCase):
    def test_source_hash_and_redaction_are_separate(self):
        raw = '历史依据\r\n用户邮箱 user@example.com\r\n'.encode()
        row = module.documents([('docs/example.md', raw)], 'a' * 40, {'docs/example.md'})['documents'][0]
        self.assertEqual(row['classification'], 'contains_current_entries')
        self.assertTrue(row['redacted'])
        self.assertNotIn('user@example.com', row['content'])
        self.assertNotEqual(row['source_sha256'], row['exported_sha256'])
        self.assertEqual(raw, '历史依据\r\n用户邮箱 user@example.com\r\n'.encode())

    def test_credentials_and_key_locations_are_not_exported(self):
        value = 'sk-' + 'x' * 40 + ' /home/example/.ssh/private_key ' + 'C:/local/example.pem'
        cleaned = module.redact(value)
        for secret in ('sk-', '.ssh/', '.pem'):
            self.assertNotIn(secret, cleaned)

    def test_path_and_version_boundaries(self):
        for name in ('../outside.md', '/outside.md', 'docs\\outside.md'):
            with self.assertRaises(ValueError):
                module.documents([(name, b'text')], 'a' * 40)
        with self.assertRaises(ValueError):
            module.documents([('docs/a.md', b'text')], 'main')
        a = module.documents([('docs/b.md', b'b'), ('docs/a.md', b'a')], 'a' * 40)
        b = module.documents([('docs/a.md', b'a'), ('docs/b.md', b'b')], 'a' * 40)
        self.assertEqual(a, b)

    def test_reference_is_readable_only_with_explicit_history(self):
        snapshot = module.documents([('docs/a.md', b'old rule\r\r\nlegacy')], 'a' * 40)
        entries, sources = module.references(snapshot, '2026-10-31')
        loader = importlib.util.spec_from_file_location('export_catalog', ROOT / 'releases/fs-dashboard/knowledge-layering-20261023/source/knowledge_catalog.py')
        catalog = importlib.util.module_from_spec(loader); loader.loader.exec_module(catalog)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, data in sources.items():
                target = root / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
            index = dict(contract=catalog.CONTRACT, release='test', release_state='published', source_commit='a' * 40, entries=entries)
            raw = json.dumps(index).encode(); (root / 'index.json').write_bytes(raw)
            args = (root, 'index.json', hashlib.sha256(raw).hexdigest(), ['FS'], [entries[0]['id']])
            self.assertEqual(catalog.select(*args)['status'], 'missing_or_out_of_scope')
            past = catalog.select(*args, history=True)
            self.assertIn('old rule\nlegacy', past['entries'][0]['content'])
            with self.assertRaisesRegex(ValueError, 'not_current'):
                catalog.context(past)


if __name__ == '__main__':
    unittest.main()
