"""Fixed-source FC27 news and administrator-selected X links; no customer data."""
import re
import json
import uuid
import os
import sqlite3
import time
import urllib.request
from contextlib import closing
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

SOURCE_URL = 'https://www.mmoexp.com/News/game/fc-27.html'
POLL_SECONDS = 21600
MAX_RESPONSE = 2 * 1024 * 1024
EA_SOURCE_URL = 'https://www.ea.com/games/ea-sports-fc/fc-27/news'
SOURCE_URLS = {'ea': EA_SOURCE_URL, 'mmoexp': SOURCE_URL}


def canonical_x_url(value):
    if not isinstance(value, str) or len(value) > 400:
        raise ValueError('Use a public X status URL.')
    match = re.fullmatch(r'https://(?:www\.)?(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})/status/([1-9][0-9]{0,24})(?:\?[A-Za-z0-9_=&%-]*)?', value)
    if not match:
        raise ValueError('Use https://x.com/account/status/numeric-id.')
    return 'https://x.com/%s/status/%s' % (match[1], match[2])


def validate_config(value, guild_id=None):
    if (not isinstance(value, dict) or not {'guild_id', 'channel_id', 'enabled', 'poll_seconds'} <= set(value)
            or set(value) - {'guild_id', 'channel_id', 'enabled', 'poll_seconds', 'collector', 'ea_enabled'}
            or type(value.get('ea_enabled', True)) is not bool
            or value.get('collector', '187') not in ('187', '183', 'auto')
            or type(value['guild_id']) is not int or value['guild_id'] <= 0
            or (guild_id is not None and value['guild_id'] != guild_id)
            or not isinstance(value['channel_id'], str)
            or not re.fullmatch(r'[1-9][0-9]{16,19}', value['channel_id'])
            or type(value['enabled']) is not bool or type(value['poll_seconds']) is not int
            or not 900 <= value['poll_seconds'] <= 86400):
        raise ValueError('Invalid news publishing configuration.')
    return dict(value)


def _article_url(value, manual=False):
    value = urljoin(SOURCE_URL, value)
    u = urlsplit(value)
    valid = ((u.netloc == 'www.mmoexp.com' and re.fullmatch(r'/News/[a-z0-9-]*fc-27[a-z0-9-]*\.html', u.path))
             or (manual and u.netloc == 'www.mmoexp.com' and re.fullmatch(r'/events/[A-Za-z0-9][A-Za-z0-9_-]*\.html', u.path))
             or (u.netloc == 'www.ea.com' and re.fullmatch(r'/games/ea-sports-fc/fc-27/news/[a-z0-9-]+', u.path)))
    if u.scheme != 'https' or u.query or u.fragment or not valid:
        raise ValueError('Invalid article URL.')
    return value


def _cover_url(value):
    u = urlsplit(value)
    if (u.scheme == 'https' and u.netloc == 'drop-assets.ea.com'
            and re.fullmatch(r'/images/[A-Za-z0-9/_-]+\.(?:png|jpg|jpeg|webp)', u.path)):
        return 'https://drop-assets.ea.com' + u.path
    if (u.scheme == 'https' and u.netloc == 'assets.mmoexp.com'
            and re.fullmatch(r'/images/[A-Za-z0-9/_-]+\.(?:png|jpg|jpeg|webp)', u.path)
            and not u.query and not u.fragment):
        return value
    return ''


class _Listing(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections = []
        self.row = None
        self.capture = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = a.get('class', '').split()
        if tag == 'section':
            self.sections.append('news-blog' in classes)
        if tag == 'li' and any(self.sections):
            self.row = {'title': '', 'summary': '', 'published_date': '', 'url': '', 'cover_url': ''}
        if self.row is None:
            return
        if tag == 'a' and 'imgbox' in classes:
            self.row['url'] = a.get('href', '')
        if tag == 'img':
            self.row['cover_url'] = _cover_url(a.get('data-original', ''))
        key = ('title' if tag == 'h3' and 'title' in classes else
               'summary' if tag == 'div' and 'text' in classes else
               'published_date' if tag == 'span' and 'time' in classes else None)
        if key:
            self.capture.append((tag, key))

    def handle_data(self, data):
        if self.row is not None and self.capture:
            self.row[self.capture[-1][1]] += data

    def handle_endtag(self, tag):
        if self.capture and self.capture[-1][0] == tag:
            self.capture.pop()
        if tag == 'li' and self.row is not None:
            self.rows.append(self.row)
            self.row, self.capture = None, []
        if tag == 'section' and self.sections:
            self.sections.pop()


def parse_listing(html):
    parser = _Listing()
    parser.feed(html)
    records = {}
    for row in parser.rows:
        try:
            row['url'] = _article_url(row['url'])
            row['published_date'] = ' '.join(row['published_date'].split())
            row['published_at'] = int(datetime.strptime(row['published_date'], '%b %d, %Y').replace(tzinfo=timezone.utc).timestamp())
            row['title'] = ' '.join(row['title'].split())[:240]
            row['summary'] = ' '.join(row['summary'].split())[:350]
            if not row['title'] or not row['summary']:
                continue
            row['source'] = 'MMOEXP FC27'
            records.setdefault(row['url'], row)
        except (ValueError, TypeError):
            continue
    if not records:
        raise ValueError('FC27 listing format not recognized; nothing queued.')
    return sorted(records.values(), key=lambda r: -r['published_at'])


def parse_ea_listing(html):
    match = re.search(r'<script\b[^>]*\bid=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.S)
    if not match:
        raise ValueError('EA news structure not recognized.')
    try:
        data = json.loads(match[1])['props']['pageProps']['initialNewsData']
        candidates = data['items'] + ([data['featured']] if data.get('featured') else [])
    except (ValueError, KeyError, TypeError):
        raise ValueError('EA news structure not recognized.')
    records = {}
    for item in candidates:
        try:
            title = ' '.join(item['title'].split())
            # Shared EA feeds contain Mobile/FC26 articles even on the FC27 page.
            if (not any(link.get('slug') == 'fc-27' for link in item.get('linkedTo', []))
                    or re.search(r'\bFC\s*[™®]?\s*(?:2[0-6]|Mobile)\b', title, re.I)
                    or not re.search(r'(?:FC\s*[™®]?\s*27|Ultimate Team\s*[™®]?\s*27)', title, re.I)):
                continue
            url = _article_url(EA_SOURCE_URL + '/' + item['slug'])
            date = datetime.fromisoformat(item['publishingDate'].replace('Z', '+00:00'))
            if date.tzinfo is None:
                continue
            records[url] = dict(kind='ea', source='EA SPORTS FC27', title=title[:240],
                summary=' '.join(item.get('summary', '').split())[:350], url=url,
                published_at=int(date.timestamp()), published_date=date.strftime('%b %d, %Y'),
                cover_url=_cover_url((item.get('image') or {}).get('ar16X9', '')))
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    if not records:
        raise ValueError('No verified FC27 articles in EA listing.')
    return sorted(records.values(), key=lambda row: -row['published_at'])


def parse_source(source_id, html):
    if source_id == 'ea':
        return parse_ea_listing(html)
    if source_id == 'mmoexp':
        return parse_listing(html)
    raise ValueError('Unknown news source.')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('News redirects are disabled.')


def fetch_listing(source_id='mmoexp'):
    # No caller-supplied URL, pagination, article fetch, proxy override or redirect.
    url = SOURCE_URLS[source_id]
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 MMOEXP-FC27-News/1.0'})
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=25) as response:
        if response.geturl() != url:
            raise ValueError('Unexpected source URL.')
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError('News listing too large.')
    return parse_source(source_id, raw.decode('utf-8'))


class NewsStore:
    def __init__(self, path):
        self.path = str(path)
        with self.db() as db, db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS news_items (
                id INTEGER PRIMARY KEY, external_id TEXT UNIQUE NOT NULL,
                kind TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL,
                url TEXT NOT NULL, cover_url TEXT NOT NULL, source TEXT NOT NULL,
                published_at INTEGER, published_date TEXT NOT NULL,
                created_at INTEGER NOT NULL, actor TEXT NOT NULL,
                status TEXT NOT NULL, channel_id TEXT, message_id TEXT,
                attempted_at INTEGER, completed_at INTEGER, error_code TEXT);
              CREATE TABLE IF NOT EXISTS news_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS news_batches (
                id INTEGER PRIMARY KEY, started_at INTEGER NOT NULL,
                state TEXT NOT NULL, claimed INTEGER NOT NULL DEFAULT 0);
            ''')
            columns = {r[1] for r in db.execute('PRAGMA table_info(news_items)')}
            for name, definition in [('delivery_mode', "TEXT NOT NULL DEFAULT 'auto'"),
                                     ('batch_id', 'INTEGER'), ('last_seen_at', 'INTEGER')]:
                if name not in columns:
                    db.execute('ALTER TABLE news_items ADD COLUMN ' + name + ' ' + definition)
            db.execute("UPDATE news_items SET delivery_mode='manual' WHERE kind='x'")
            db.execute('UPDATE news_items SET last_seen_at=created_at WHERE last_seen_at IS NULL')

    def db(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return closing(connection)

    def begin_cycle(self, interval, now=None):
        now = int(time.time() if now is None else now)
        with self.db() as db, db:
            db.execute('BEGIN IMMEDIATE')
            last = db.execute('SELECT started_at FROM news_batches ORDER BY id DESC LIMIT 1').fetchone()
            if last and now < last[0] + interval:
                return None
            db.execute("UPDATE news_batches SET state='closed' WHERE state IN ('collecting','ready')")
            cur = db.execute("INSERT INTO news_batches(started_at,state) VALUES(?,'collecting')", (now,))
            db.execute("INSERT OR REPLACE INTO news_meta(key,value) VALUES('last_attempt_at',?)", (str(now),))
            return cur.lastrowid

    def finish_cycle(self, batch_id, outcomes, now=None):
        now = int(time.time() if now is None else now)
        failed = sum(not value.get('ok') for value in outcomes.values())
        error = ('all_sources_failed' if outcomes and failed == len(outcomes) else 'partial_failure') if failed else ''
        with self.db() as db, db:
            # Atomically expose the round and its status only after every source attempt.
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE news_batches SET state='ready' WHERE id=? AND state='collecting'", (batch_id,))
            db.execute("INSERT OR REPLACE INTO news_meta(key,value) VALUES('collector_status',?)", (json.dumps(outcomes),))
            db.execute("INSERT OR REPLACE INTO news_meta(key,value) VALUES('last_poll_error',?)", (error,))
            if not outcomes or failed < len(outcomes):
                db.execute("INSERT OR REPLACE INTO news_meta(key,value) VALUES('last_poll_at',?)", (str(now),))

    def ingest(self, rows, now=None, batch_id=None):
        now = int(time.time() if now is None else now)
        if not rows:
            raise ValueError('Empty listing cannot initialize baseline.')
        rows = sorted(rows, key=lambda row: -row['published_at'])
        source_id = rows[0].get('kind', 'mmoexp')
        if source_id not in SOURCE_URLS or any(r.get('kind', 'mmoexp') != source_id for r in rows):
            raise ValueError('Ingest one verified source at a time.')
        added = 0
        with self.db() as db, db:
            db.execute('BEGIN IMMEDIATE')
            key = 'latest_date' if source_id == 'mmoexp' else 'latest_date_ea'
            prior = db.execute('SELECT value FROM news_meta WHERE key=?', (key,)).fetchone()
            latest = rows[0]['published_at']
            for index, row in enumerate(rows):
                url = _article_url(row['url'])
                status = 'pending' if (prior and row['published_at'] >= int(prior[0])) or (not prior and index == 0) else 'baseline'
                expected = 'ea' if url.startswith('https://www.ea.com/') else 'mmoexp'
                if expected != source_id:
                    raise ValueError('Article source mismatch.')
                cur = db.execute('INSERT OR IGNORE INTO news_items(external_id,kind,title,summary,url,cover_url,source,published_at,published_date,created_at,actor,status,delivery_mode,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (url, source_id, row['title'][:240], row['summary'][:350], url, _cover_url(row.get('cover_url', '')), 'EA SPORTS FC27' if source_id == 'ea' else 'MMOEXP FC27', row['published_at'], row['published_date'], now, 'official-source', status, 'auto', now))
                added += cur.rowcount if status == 'pending' else 0
                db.execute("UPDATE news_items SET last_seen_at=? WHERE external_id=? AND delivery_mode='auto'", (now, url))
            highwater = max(latest, int(prior[0]) if prior else latest)
            db.execute('INSERT OR REPLACE INTO news_meta(key,value) VALUES(?,?)', (key,str(highwater)))
            # Compatibility for explicit standalone ingestion; service passes a durable cycle.
            if batch_id is None and not db.execute('SELECT 1 FROM news_batches LIMIT 1').fetchone():
                db.execute("INSERT INTO news_batches(started_at,state) VALUES(?,'ready')", (now,))
        return added

    def enqueue_x(self, url, summary='', actor='admin', now=None):
        url = canonical_x_url(url)
        if (not isinstance(summary, str) or len(summary) > 600 or any(ord(c) < 32 and c not in '\n\t' for c in summary)):
            raise ValueError('Summary must be at most 600 characters.')
        # Every deliberate manual submission is a new publication, including repeated URLs.
        external_id = 'manual:' + uuid.uuid4().hex
        with self.db() as db, db:
            db.execute('INSERT INTO news_items(external_id,kind,title,summary,url,cover_url,source,published_date,created_at,actor,status,delivery_mode) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (external_id, 'x', 'FC27 · Selected X post', summary.strip(), url, '', 'X · administrator selection', '', int(time.time() if now is None else now), str(actor), 'pending','manual'))
            row = db.execute('SELECT * FROM news_items WHERE external_id=?', (external_id,)).fetchone()
            return dict(row)

    def enqueue_article(self, url, title='', summary='', actor='admin', now=None):
        url = _article_url(url, manual=True)
        kind = 'ea' if url.startswith('https://www.ea.com/') else 'mmoexp'
        title = title or ('EA SPORTS FC27 · Selected news' if kind == 'ea' else 'MMOEXP FC27 · Selected news')
        item = dict(kind=kind, title=title, summary=summary, source='EA SPORTS FC27' if kind == 'ea' else 'MMOEXP FC27',
                    url=url, cover_url='', published_date='', delivery_mode='manual')
        validate_item(item)
        external_id = 'manual:' + uuid.uuid4().hex
        with self.db() as db, db:
            db.execute('INSERT INTO news_items(external_id,kind,title,summary,url,cover_url,source,published_date,created_at,actor,status,delivery_mode) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (external_id,kind,title,summary,url,'',item['source'],'',int(time.time() if now is None else now),str(actor),'pending','manual'))
            return dict(db.execute('SELECT * FROM news_items WHERE external_id=?',(external_id,)).fetchone())

    def items(self, limit=50):
        with self.db() as db:
            return [dict(row) for row in db.execute('SELECT * FROM news_items ORDER BY id DESC LIMIT ?', (max(1, min(int(limit), 100)),))]

    def recover_sending(self):
        """Call once at bot startup, never from a web request or each poll."""
        with self.db() as db, db:
            db.execute("UPDATE news_items SET status='uncertain',error_code='process_interrupted' WHERE status='sending'")

    def claim(self, channel_id, now=None, auto_enabled=True, ea_enabled=True):
        if not re.fullmatch(r'[1-9][0-9]{16,19}', str(channel_id)):
            raise ValueError('Invalid channel.')
        with self.db() as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM news_items WHERE status='pending' AND delivery_mode='manual' ORDER BY id LIMIT 1").fetchone()
            batch = None
            if row is None and auto_enabled:
                batch = db.execute("SELECT * FROM news_batches WHERE state='ready' AND claimed<6 ORDER BY id DESC LIMIT 1").fetchone()
                if batch:
                    # A manual publication may already have covered an automatically collected URL.
                    db.execute("""UPDATE news_items SET status='duplicate' WHERE status='pending' AND delivery_mode='auto'
                        AND EXISTS (SELECT 1 FROM news_items other WHERE other.id!=news_items.id
                          AND other.url=news_items.url AND other.status IN ('published','sending','uncertain'))""")
                    row = db.execute("""SELECT * FROM news_items WHERE status='pending' AND delivery_mode='auto'
                        AND (kind!='ea' OR ?) ORDER BY CASE kind WHEN 'ea' THEN 0 ELSE 1 END,
                        published_at DESC,id DESC LIMIT 1""", (ea_enabled,)).fetchone()
            if row is None:
                return None
            if row['delivery_mode'] == 'auto':
                db.execute('UPDATE news_batches SET claimed=claimed+1 WHERE id=?', (batch['id'],))
            db.execute("UPDATE news_items SET status='sending',channel_id=?,attempted_at=?,batch_id=? WHERE id=?", (str(channel_id), int(time.time() if now is None else now), batch['id'] if row['delivery_mode']=='auto' else None, row['id']))
            return dict(row)

    def complete(self, item_id, status, message_id=None, error_code=None):
        if status not in ('published', 'uncertain', 'failed'):
            raise ValueError('Invalid outcome.')
        with self.db() as db, db:
            if not db.execute("UPDATE news_items SET status=?,message_id=?,completed_at=?,error_code=? WHERE id=? AND status='sending'", (status, str(message_id) if message_id else None, int(time.time()), error_code, item_id)).rowcount:
                raise ValueError('Claim no longer active.')


class DefinitelyNotSent(Exception):
    """Adapter may use only when it knows Discord did not accept a message."""


def enqueue_article(path, url, title='', summary='', actor='admin'):
    return NewsStore(path).enqueue_article(url, title, summary, actor)


def collect_cycle(store, config, now=None):
    """Collection is one durable round; failover never allocates a second allowance."""
    from collector_router import collect, fetch_remote_html, CollectionError
    batch = store.begin_cycle(config['poll_seconds'], now)
    if batch is None:
        return None
    outcomes = {}
    def remote(source):
        key = os.environ.get('FC27_NEWS_SSH_KEY')
        hosts = os.environ.get('FC27_NEWS_KNOWN_HOSTS')
        if not key or not hosts:
            raise FileNotFoundError('Remote collector is not configured.')
        return parse_source(source, fetch_remote_html(source,key_path=key,known_hosts=hosts))
    for source in ('ea','mmoexp'):
        if source == 'ea' and not config.get('ea_enabled', True):
            continue
        try:
            rows, metadata = collect(source, config.get('collector','187'), fetch_listing, remote)
            store.ingest(rows, now, batch_id=batch)
            outcomes[source] = dict(metadata, ok=True)
        except CollectionError as exc:
            outcomes[source] = dict(ok=False,error='collection_failed',attempts=exc.attempts,checked_at=int(time.time()))
        except Exception:
            outcomes[source] = dict(ok=False,error='ingest_failed',attempts=[],checked_at=int(time.time()))
    store.finish_cycle(batch,outcomes,now)
    return outcomes


def validate_item(item):
    """Validate persisted content again before crossing the Discord boundary."""
    if not isinstance(item, dict) or item.get('kind') not in ('mmoexp', 'ea', 'x'):
        raise ValueError('Invalid news kind.')
    for key, maximum in (('title', 240), ('summary', 600 if item['kind'] == 'x' else 350),
                         ('source', 100), ('published_date', 60)):
        value = item.get(key)
        if (not isinstance(value, str) or len(value) > maximum
                or (key in ('title', 'source') and not value.strip())
                or any(ord(c) < 32 and c not in '\n\t' for c in value)):
            raise ValueError('Invalid news text.')
    url = item.get('url')
    canonical = canonical_x_url(url) if item['kind'] == 'x' else _article_url(url, manual=item.get('delivery_mode') == 'manual')
    if canonical != url:
        raise ValueError('Stored source URL is not canonical.')
    if item['kind'] != 'x' and (url.startswith('https://www.ea.com/') != (item['kind']=='ea')):
        raise ValueError('Source does not match article URL.')
    cover = item.get('cover_url')
    if not isinstance(cover, str) or (cover and (_cover_url(cover) != cover or item['kind'] == 'x')):
        raise ValueError('Invalid cover URL.')
    return item


async def publish_pending(store, channel_id, sender, limit=3, auto_enabled=True, ea_enabled=True):
    """sender(item, channel_id) returns Discord message ID; exceptions never retry."""
    count = 0
    for _ in range(limit):
        item = store.claim(channel_id, auto_enabled=auto_enabled, ea_enabled=ea_enabled)
        if item is None:
            break
        try:
            try:
                validate_item(item)
            except (ValueError, TypeError, KeyError):
                raise DefinitelyNotSent('Invalid persisted item')
            message_id = await sender(item, int(channel_id))
            if not message_id:
                raise RuntimeError('Missing Discord acknowledgement')
        except DefinitelyNotSent as error:
            store.complete(item['id'], 'failed', error_code=type(error).__name__)
        except Exception as error:
            store.complete(item['id'], 'uncertain', error_code=type(error).__name__[:80])
        else:
            store.complete(item['id'], 'published', message_id)
            count += 1
    return count


def news_embed(item):
    import discord
    validate_item(item)
    safe = lambda value: discord.utils.escape_markdown(discord.utils.escape_mentions(value))
    embed = discord.Embed(title=safe(item['title'])[:256], description=safe(item['summary']) or 'Open the original post below.', url=item['url'], color=0x23A85D)
    embed.set_author(name=item['source'])
    if item.get('cover_url'):
        embed.set_image(url=item['cover_url'])
    embed.set_footer(text=('Published ' + item['published_date'] + ' · ' if item.get('published_date') else '') + 'MMOEXP FC27 · Original source')
    return embed
