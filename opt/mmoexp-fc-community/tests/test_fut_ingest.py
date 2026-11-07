import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from community import CommunityError, CommunityStore
from fut_ingest import ingest_batch


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = CommunityStore(Path(self.tmp.name) / 'db.sqlite', {'owner'})
        self.sources = {'sheriff': {'enabled': True, 'transport': 'harness',
                                   'allowed_hosts': ['x.com'], 'allowed_path_prefix': '/FutSheriff/',
                                   'category': 'leak', 'auto_publish': False}}
        self.record = {'source_id': 'sheriff', 'external_id': '42', 'title': 'Title',
                       'summary': 'Summary', 'url': 'https://x.com/FutSheriff/status/42',
                       'season': 27, 'published_at': 900}

    def ingest(self, records, actor='owner'):
        return ingest_batch(self.store, actor, records, self.sources, 1000)

    def test_draft_metadata_and_duplicate(self):
        self.assertEqual(self.ingest([self.record])[0]['code'], 'draft')
        self.assertEqual(self.ingest([self.record])[0]['code'], 'duplicate')
        with self.store.db() as db:
            row = db.execute('SELECT * FROM content').fetchone()
            meta = db.execute('SELECT * FROM fut_ingest_metadata').fetchone()
        self.assertEqual((row['status'], row['kind'], row['source']),
                         ('draft', 'leak', self.record['url']))
        self.assertEqual((meta['source_id'], meta['external_id'], meta['published_at'], meta['fetched_at']),
                         ('sheriff', '42', 900, 1000))
        self.assertEqual(meta['content_id'], row['id'])

    def test_auto_publish_only_when_explicitly_enabled(self):
        self.sources['sheriff']['auto_publish'] = True
        self.assertEqual(self.ingest([self.record])[0]['code'], 'approved')
        row = self.store.latest()[0]
        self.assertEqual(self.store.get(row['id'])['reviewer'], 'owner')

    def test_disabled_and_unknown_sources_are_rejected(self):
        self.sources['sheriff']['enabled'] = False
        self.assertEqual(self.ingest([self.record])[0]['code'], 'source_disabled')
        self.assertEqual(self.ingest([dict(self.record, source_id='other')])[0]['code'], 'unknown_source')
        self.assertEqual(self.store.latest(), [])

    def test_untrusted_urls_and_account_paths_are_rejected(self):
        for url in ('http://x.com/FutSheriff/status/42', 'https://x.com.evil/FutSheriff/status/42',
                    'https://user@x.com/FutSheriff/status/42', 'https://x.com/Other/status/42',
                    'https://x.com/FutSheriffOther/status/42',
                    'https://x.com/FutSheriff/../Other/status/42',
                    'https://x.com/FutSheriff/%2e%2e/Other/status/42'):
            with self.subTest(url=url):
                self.assertEqual(self.ingest([dict(self.record, url=url)])[0]['code'], 'invalid_url')

    def test_rejects_bad_records_independently_without_content_in_results(self):
        records = [dict(self.record, title='secret' * 20), dict(self.record, published_at=1301),
                   dict(self.record, published_at=None), dict(self.record, season=True), self.record]
        result = self.ingest(records)
        self.assertEqual([r['code'] for r in result],
                         ['invalid_record', 'invalid_record', 'invalid_record', 'invalid_record', 'draft'])
        self.assertNotIn('secret', str(result))

    def test_actor_and_batch_limit(self):
        with self.assertRaises(CommunityError):
            self.ingest([self.record], actor='outsider')
        with self.assertRaises(ValueError):
            self.ingest([self.record] * 101)

    def test_malformed_source_does_not_abort_following_record(self):
        self.sources['broken'] = dict(self.sources['sheriff'], category=[])
        result = self.ingest([dict(self.record, source_id='broken'), self.record])
        self.assertEqual([r['code'] for r in result], ['invalid_source', 'draft'])

    def test_unrepresentable_publication_time_is_rejected(self):
        result = ingest_batch(self.store, 'owner', [dict(self.record, published_at=2**63)],
                              self.sources, 2**63 - 1)
        self.assertEqual(result[0]['code'], 'invalid_record')

    def test_invalid_unicode_does_not_abort_following_record(self):
        result = self.ingest([dict(self.record, title='\ud800'), self.record])
        self.assertEqual([r['code'] for r in result], ['invalid_record', 'draft'])

    def test_cli_imports_local_json_and_enforces_owner(self):
        root = Path(self.tmp.name)
        config, batch, db = root / 'sources.json', root / 'batch.json', root / 'cli.sqlite'
        config.write_text(json.dumps({'sources': self.sources}), encoding='utf-8')
        batch.write_text(json.dumps([self.record]), encoding='utf-8')
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'fut_ingest.py'),
                   '--config', str(config), '--input', str(batch), '--database', str(db),
                   '--actor', 'owner', '--owner', 'owner']
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)[0]['code'], 'draft')
        command[-1] = 'someone-else'
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_concurrent_duplicate_creates_one_content_row(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.ingest([self.record])[0]['code'], range(2)))
        self.assertEqual(sorted(results), ['draft', 'duplicate'])
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM content').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM fut_ingest_metadata').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
