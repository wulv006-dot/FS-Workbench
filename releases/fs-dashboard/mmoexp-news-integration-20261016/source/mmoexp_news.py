"""One bounded night collection; the monitor and Hermes only read its shared result."""
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

INDEX = 'https://www.mmoexp.com/new_sitemap.xml'  # Published by the site's robots.txt.
ROOT = Path('/var/lib/fs-boss-workspaces/public')
CONTRACT = 'mmoexp-seo-news-v1'
LABEL = 'MMOEXP News／主站SEO资讯'
MAX_ARTICLES = 12
MAX_BYTES = 750000
MAX_SNAPSHOT_BYTES = 160000
ALIASES = {
 'ea-sports-fc': r'\b(?:ea\s*)?(?:sports\s*)?(?:fc|fifa)[ -]?(?:26|27)\b',
 'mlb-the-show-26': r'\bmlb(?: the show)?[ -]?26\b', 'nba-2k': r'\bnba[ -]?2k(?:26|27)?\b',
 'madden-nfl': r'\b(?:madden|nfl)[ -]?(?:26|27)?\b',
 'college-football-27': r'\b(?:college football|cfb)[ -]?27\b',
 'college-football-26': r'\b(?:college football|cfb)[ -]?26\b',
 'diablo4': r'\bdiablo[ -]?(?:4|iv)\b', 'diablo-2-resurrected': r'\bdiablo[ -]?(?:2|ii)\b',
 'poe2': r'\b(?:poe|path of exile)[ -]?2\b',
 'poe1': r'\b(?:poe|path of exile)(?![ -]?2\b)\b', 'aion2': r'\baion[ -]?2\b',
 'dark-and-darker': r'\bdark and darker\b', 'skull-and-bones': r'\bskull and bones\b',
 'arena-breakout-infinite': r'\barena breakout(?: infinite)?\b', 'odin-valhalla-rising': r'\bodin\b',
 'arc-raiders': r'\barc raiders\b', 'runescape': r'\b(?:runescape|osrs|rs3)\b',
 'black-ops-7': r'\b(?:black ops[ -]?7|cod bo7)\b', 'dune-awakening': r'\bdune awakening\b',
 'elden-ring': r'\belden ring\b', 'helldivers-2': r'\bhelldivers[ -]?2\b',
 'legend-of-ymir': r'\b(?:legend of ymir|ymir)\b', 'mistfall-hunter': r'\bmistfall hunter\b',
 'raven-2': r'\braven[ -]?2\b', 'wow-classic-20': r'\b(?:wow|world of warcraft).*20th\b',
 'wow-tbc-classic-anniversary': r'\b(?:tbc|burning crusade).*anniversary\b',
 'wow-forever': r'\b(?:wow|world of warcraft)[ -]+forever\b', 'maplestory': r'\bmaplestory\b',
 'gta6': r'\b(?:gta|grand theft auto)[ -]?(?:6|vi)\b', 'dreadmyst': r'\bdreadmyst\b',
}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def checked_url(url, index=False):
    if not isinstance(url,str) or any(ord(c)<32 or ord(c)==127 for c in url):
        raise ValueError('news_url_not_allowed')
    p = urlsplit(url)
    if p.scheme != 'https' or p.netloc != 'www.mmoexp.com' or p.query or p.fragment:
        raise ValueError('news_url_not_allowed')
    if index and url != INDEX or not index and not re.fullmatch(r'/News/[a-z0-9][a-z0-9-]*\.html', p.path):
        raise ValueError('news_path_not_allowed')
    return url


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl, index=req.full_url == INDEX)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, deadline):
    checked_url(url, index=url == INDEX)
    remaining = deadline-time.monotonic()
    if remaining <= 0:
        raise TimeoutError('news_deadline')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirects())
    request = urllib.request.Request(url, headers={'User-Agent':'FS-GameMonitor/1.0', 'Accept-Encoding':'identity'})
    with opener.open(request, timeout=min(10, remaining)) as response:
        checked_url(response.url, index=url == INDEX)
        if response.headers.get('Content-Encoding','identity') != 'identity':
            raise ValueError('news_encoding')
        data = bytearray()
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError('news_deadline')
            block = response.read(min(16384, MAX_BYTES+1-len(data)))
            if not block:
                break
            data.extend(block)
            if len(data) > MAX_BYTES:
                raise ValueError('news_response_too_large')
        return bytes(data)


def games(title):
    normalized = re.sub(r'[-_:]+', ' ', title)
    return [key for key, pattern in ALIASES.items() if re.search(pattern, normalized, re.I)]


def index_rows(raw):
    ns = {'s':'http://www.sitemaps.org/schemas/sitemap/0.9', 'n':'http://www.google.com/schemas/sitemap-news/0.9'}
    if len(raw) > MAX_BYTES or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('news_index_contract')
    root = ET.fromstring(raw)
    if len(root) > 2000:
        raise ValueError('news_index_contract')
    rows, seen = [], set()
    for item in root:
        url = item.findtext('s:loc', namespaces=ns)
        title = item.findtext('n:news/n:title', namespaces=ns)
        published = item.findtext('n:news/n:publication_date', namespaces=ns)
        try:
            checked_url(url)
            day = date.fromisoformat(published[:10]).isoformat()
        except (ValueError, TypeError):
            continue
        if not title or url in seen:
            continue
        seen.add(url)
        keys = games(title+' '+urlsplit(url).path.rsplit('/',1)[-1])
        if keys:
            rows.append(dict(source_url=url, title=title[:240], published_at=day, game_keys=keys))
    return sorted(rows, key=lambda r:r['published_at'], reverse=True)


class Article(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = self.article = self.heading = self.skipping = 0
        self.parts, self.title = [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script','style','noscript','svg','nav','header','footer','aside','form'):
            self.skipping += 1
        if tag == 'h1':
            self.heading += 1
        if tag == 'div':
            self.depth += 1
            if 'article-body' in attrs.get('class','').split():
                self.article = self.depth

    def handle_endtag(self, tag):
        if tag in ('script','style','noscript','svg','nav','header','footer','aside','form'):
            self.skipping = max(0,self.skipping-1)
        if tag == 'h1':
            self.heading = max(0,self.heading-1)
        if tag == 'div':
            if self.depth == self.article:
                self.article = 0
            self.depth = max(0,self.depth-1)

    def handle_data(self, value):
        if not self.skipping:
            if self.heading:
                self.title.append(value)
            if self.article:
                self.parts.append(value)


def article(row, raw, captured):
    page = Article();page.feed(raw.decode('utf-8-sig'))
    text = re.sub(r'\s+', ' ', ' '.join(page.parts)).strip()
    title = re.sub(r'\s+', ' ', ' '.join(page.title)).strip()
    if len(text) < 80 or not title or re.search(r'access denied|verify you are human|just a moment', text, re.I):
        raise ValueError('news_article_unreadable')
    # The article body, not navigation/categories, establishes the game's identity.
    keys = games(title)
    if not keys or not set(keys)&set(row['game_keys']):
        raise ValueError('news_article_game_mismatch')
    profiles = [p for p in ('FC27','FC26') if re.search(r'\b(?:fc|fifa)[ -]?'+p[2:]+r'\b', title, re.I)]
    return dict(row, title=title[:240], game_keys=keys, profiles=profiles, text=text[:5000],
                summary=text[:360], text_truncated=len(text)>5000, source_kind='mmoexp_seo', source_label=LABEL,
                observed_at=captured, event_date=None, event_time=None, timezone=None,
                document_id=sha256(row['source_url'].encode()).hexdigest()[:24],
                content_sha256=sha256(raw).hexdigest(), text_sha256=sha256(text[:5000].encode()).hexdigest())


def collect(at=None, *, fetcher=fetch, deadline_at=None):
    at = at or datetime.now(timezone.utc)
    if at.utcoffset() is None:
        raise ValueError('news_aware_clock_required')
    seconds = min(45, max(0, (deadline_at-datetime.now(timezone.utc)).total_seconds())) if deadline_at else 45
    deadline = time.monotonic()+seconds
    raw = fetcher(INDEX, deadline)
    candidates = [r for r in index_rows(raw) if at.date()-timedelta(days=90) <= date.fromisoformat(r['published_at']) <= at.date()+timedelta(days=1)]
    selected, represented = [], set()
    for row in candidates:
        if set(row['game_keys'])-represented:
            selected.append(row);represented.update(row['game_keys'])
            if len(selected) == MAX_ARTICLES:
                break
    for row in candidates:
        if len(selected) == MAX_ARTICLES:
            break
        if row not in selected:
            selected.append(row)
    documents, failures = [], []
    executor = ThreadPoolExecutor(max_workers=3)
    pending = {executor.submit(lambda r:article(r,fetcher(r['source_url'],deadline),at.isoformat()),row):row for row in selected}
    try:
        for future in as_completed(pending, timeout=max(.01,deadline-time.monotonic())):
            row = pending[future]
            try:
                documents.append(future.result())
            except (OSError,ValueError,TypeError):
                failures.append({'source_url':row['source_url'],'reason':'article_fetch_or_parse_failed'})
    except FuturesTimeout:
        for future,row in pending.items():
            if not future.done():
                future.cancel();failures.append({'source_url':row['source_url'],'reason':'deadline'})
    finally:
        executor.shutdown(wait=False,cancel_futures=True)
    order = {r['source_url']:i for i,r in enumerate(selected)}
    documents.sort(key=lambda r:order[r['source_url']])
    value = dict(schema_version=1, contract=CONTRACT, source_kind='mmoexp_seo', source_label=LABEL,
                 status='partial' if failures else 'available' if documents else 'empty', collected_at=at.isoformat(),
                 stale_after=(at+timedelta(hours=30)).isoformat(), documents=documents, failures=failures,
                 coverage={'index_url':INDEX,'index_sha256':sha256(raw).hexdigest(),'discovered_articles':len(candidates),
                           'selected_articles':len(selected),'returned_articles':len(documents),'exhaustive':False,
                           'game_keys':sorted({k for r in documents for k in r['game_keys']}),
                           'policy':'SEO editorial source; article publication is not event time; no official confirmation or countdown implied.'})
    # Reserve the version field so every collected snapshot fits its reader.
    while documents and len(encoded(value))>MAX_SNAPSHOT_BYTES-64:
        documents.pop()
        value['status']='partial'
        value['coverage'].update(returned_articles=len(documents),
                                 source_documents_omitted=len(selected)-len(failures)-len(documents),
                                 game_keys=sorted({k for r in documents for k in r['game_keys']}))
    value['version'] = 'mmoexp-news-'+sha256(encoded(value)).hexdigest()[:20]
    return value


def atomic(path, value):
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('news_snapshot_boundary')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp = tempfile.mkstemp(prefix='.seo-news-', dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as stream:
            if os.name=='posix':os.fchmod(stream.fileno(),0o644)
            stream.write(encoded(value));stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
        if os.name=='posix':
            directory=os.open(str(path.parent),os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def refresh(at=None, *, root=ROOT, fetcher=fetch, deadline_at=None):
    # A failed SEO source must not replace the last good result or stop official collection.
    try:
        value = collect(at,fetcher=fetcher,deadline_at=deadline_at)
        if value['documents']:
            atomic(Path(root)/'seo-news.json',value)
        atomic(Path(root)/'seo-news.status.json',{'status':value['status'],'collected_at':value['collected_at'],'version':value['version']})
        return value
    except (OSError,ValueError,TypeError,ET.ParseError):
        failed={'status':'unavailable','reason':'news_fetch_or_parse_failed','last_success_preserved':True}
        atomic(Path(root)/'seo-news.status.json',failed)
        return failed


def read_snapshot(root=ROOT, *, now=None):
    p=Path(root)/'seo-news.json'
    if not p.exists():
        return {'status':'not_available','reason':'nightly_news_snapshot_missing','documents':[]}
    if p.is_symlink() or any(x.is_symlink() for x in p.parents):
        raise ValueError('news_snapshot_boundary')
    info=p.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>MAX_SNAPSHOT_BYTES or (os.name=='posix' and (info.st_uid!=os.geteuid() or info.st_mode&0o022)):
        raise ValueError('news_snapshot_owner_or_size')
    value=json.loads(p.read_bytes());identity=dict(value);version=identity.pop('version',None)
    if value.get('contract')!=CONTRACT or value.get('source_kind')!='mmoexp_seo' or version!='mmoexp-news-'+sha256(encoded(identity)).hexdigest()[:20] or len(value.get('documents',[]))>MAX_ARTICLES:
        raise ValueError('news_snapshot_contract')
    for row in value['documents']:
        checked_url(row['source_url'])
        if row.get('source_kind')!='mmoexp_seo' or row.get('source_label')!=LABEL or row.get('event_date') is not None or row.get('event_time') is not None or row.get('timezone') is not None:
            raise ValueError('news_snapshot_label_or_time')
    clock=now or datetime.now(timezone.utc)
    if clock>datetime.fromisoformat(value['stale_after']):
        value=dict(value,status='stale',last_success_status=value['status'])
    return value


def read_shared(args):
    if not isinstance(args,dict) or set(args)!={'profile','start','end'} or args.get('profile')!='FC27':
        raise ValueError('news_query_not_allowed')
    start,end=(date.fromisoformat(args[k]) for k in ('start','end'))
    if start.isoformat()!=args['start'] or end.isoformat()!=args['end'] or not 0<=(end-start).days<93:
        raise ValueError('news_period_not_allowed')
    try:
        value=read_snapshot()
    except (OSError,ValueError,KeyError,TypeError):
        return {'status':'not_available','reason':'shared_news_snapshot_invalid','documents':[]}
    docs=[dict(r,publication_in_window=args['start']<=r['published_at'][:10]<=args['end']) for r in value['documents'] if 'FC27' in r.get('profiles',[])]
    return dict(value,http_status=200 if value.get('version') else 503,documents=docs,query=args,shared_snapshot_id=value.get('version'),network_requests=0,
                captured_at=value.get('collected_at'),source_kind='mmoexp_seo',source_label=LABEL)
