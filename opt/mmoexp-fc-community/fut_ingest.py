"""Import trusted local harness output; this module does not fetch content."""
import argparse
import json
import sqlite3
import time
from urllib.parse import urlsplit

from community import CommunityStore


KINDS = {'news', 'leak', 'review', 'squad', 'sbc', 'topic', 'collection', 'guide',
         'evolutions', 'objectives', 'store'}


def _valid_text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        return False
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def _valid_url(value, source):
    if not _valid_text(value, 400) or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        return False
    try:
        url = urlsplit(value)
        hosts = source.get('allowed_hosts')
        if (not isinstance(hosts, list) or not hosts or
                any(not isinstance(host, str) or not host or '*' in host for host in hosts)):
            return False
        if (url.scheme != 'https' or not url.hostname or url.username is not None or
                url.password is not None or url.hostname not in hosts or url.port not in (None, 443)):
            return False
        prefix = source.get('allowed_path_prefix')
        if prefix is not None:
            if (not isinstance(prefix, str) or not prefix.startswith('/') or
                    '%' in prefix or '\\' in prefix or
                    any(part in ('.', '..') for part in prefix.split('/')) or
                    '%' in url.path or '\\' in url.path or
                    any(part in ('.', '..') for part in url.path.split('/'))):
                return False
            base = prefix.rstrip('/')
            if not base or not (url.path == base or url.path.startswith(base + '/')):
                return False
        return True
    except ValueError:
        return False


def ingest_batch(store, actor, records, sources, now):
    """Return a code per record, without returning untrusted content."""
    store.staff(actor)
    if (not isinstance(records, list) or len(records) > 100 or not isinstance(sources, dict) or
            type(now) is not int or not 0 <= now <= 2**63 - 1):
        raise ValueError('Invalid batch, sources, or time.')
    with store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS fut_ingest_metadata ('
                   'content_id INTEGER NOT NULL REFERENCES content(id), '
                   'source_id TEXT NOT NULL, external_id TEXT NOT NULL, '
                   'published_at INTEGER NOT NULL, fetched_at INTEGER NOT NULL, '
                   'PRIMARY KEY(source_id, external_id), UNIQUE(content_id))')
    results = []
    for index, record in enumerate(records):
        code = _ingest_one(store, actor, record, sources, now)
        results.append({'index': index, 'code': code})
    return results


def _ingest_one(store, actor, record, sources, now):
    if not isinstance(record, dict) or not _valid_text(record.get('source_id'), 100):
        return 'invalid_record'
    source_id = record['source_id']
    source = sources.get(source_id)
    if source is None:
        return 'unknown_source'
    if not isinstance(source, dict) or source.get('enabled') is not True:
        return 'source_disabled'
    if (source.get('transport') != 'harness' or not isinstance(source.get('category'), str) or
            source['category'] not in KINDS or
            type(source.get('auto_publish')) is not bool):
        return 'invalid_source'
    if (not _valid_text(record.get('external_id'), 200) or
            not _valid_text(record.get('title'), 100) or
            not _valid_text(record.get('summary'), 1500) or
            type(record.get('season')) is not int or record['season'] != 27 or
            type(record.get('published_at')) is not int or
            not 0 <= record['published_at'] <= min(now + 300, 2**63 - 1)):
        return 'invalid_record'
    if not _valid_url(record.get('url'), source):
        return 'invalid_url'
    try:
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM fut_ingest_metadata WHERE source_id=? AND external_id=?',
                          (source_id, record['external_id'])).fetchone():
                return 'duplicate'
            approved = source['auto_publish']
            status = 'approved' if approved else 'draft'
            cur = db.execute('INSERT INTO content(title,kind,body,source,season,author,created,'
                             'reviewer,reviewed,status) VALUES(?,?,?,?,?,?,?,?,?,?)',
                             (record['title'].strip(), source['category'], record['summary'].strip(),
                              record['url'], 27, str(actor), now, str(actor) if approved else None,
                              now if approved else None, status))
            db.execute('INSERT INTO fut_ingest_metadata '
                       '(content_id,source_id,external_id,published_at,fetched_at) VALUES(?,?,?,?,?)',
                       (cur.lastrowid, source_id, record['external_id'], record['published_at'], now))
            return status
    except sqlite3.Error:
        return 'storage_error'


def main():
    parser = argparse.ArgumentParser(description='Import a local JSON batch into the community database.')
    parser.add_argument('--config', required=True)
    parser.add_argument('--input', required=True)
    parser.add_argument('--database', required=True)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--owner', required=True, help='Trusted local staff ID')
    args = parser.parse_args()
    try:
        with open(args.config, encoding='utf-8') as f:
            config = json.load(f)
        with open(args.input, encoding='utf-8') as f:
            records = json.load(f)
        store = CommunityStore(args.database, {args.owner})
        results = ingest_batch(store, args.actor, records, config['sources'], int(time.time()))
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        parser.exit(1, 'Import failed: invalid input, configuration, or database.\n')
    except Exception:
        parser.exit(1, 'Import failed: access denied or unexpected error.\n')
    print(json.dumps(results))
    return 1 if any(result['code'] not in ('draft', 'approved', 'duplicate') for result in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
