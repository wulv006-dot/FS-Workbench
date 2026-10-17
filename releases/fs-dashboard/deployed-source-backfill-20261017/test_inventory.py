import hashlib,json,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
class FrozenLiveSources(unittest.TestCase):
    def test_fourteen_sources_keep_frozen_live_bytes(self):
        rows=json.loads((HERE/'SOURCE-MAP.json').read_text(encoding='utf8'))['files']
        self.assertEqual(len(rows),14)
        self.assertEqual(len({r['source'] for r in rows}),14)
        for row in rows:
            with self.subTest(source=row['source']):
                self.assertTrue((ROOT/row['source']).resolve().is_relative_to(ROOT))
                self.assertEqual(hashlib.sha256((ROOT/row['source']).read_bytes()).hexdigest(),row['sha256'])
    def test_players_cloud10_manifest_keeps_complete_sources(self):
        base=ROOT/'fc27_players_cloud'
        manifest=json.loads((base/'source_manifest.json').read_text(encoding='utf8'))
        self.assertEqual(manifest['version'],'2026.10.08-cloud.10')
        self.assertEqual(len(manifest['files']),45)
        for name,digest in manifest['files'].items():
            with self.subTest(source=name):
                self.assertEqual(hashlib.sha256((base/name).read_bytes()).hexdigest(),digest)
if __name__=='__main__':unittest.main()
