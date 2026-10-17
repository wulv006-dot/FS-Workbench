"""Bounded FC27 official news evidence; no model, credentials, cache or writes."""
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from functools import lru_cache
from html import unescape
from html.parser import HTMLParser
import json
import re
import urllib.error
from urllib.parse import urljoin, urlsplit

INDEX = 'https://www.ea.com/games/ea-sports-fc/fc-27/news'
PREFIX = '/games/ea-sports-fc/fc-27/news/'
MAX_ARTICLES = 6
MAX_TEXT = 6000
MAX_BYTES = 750000


def checked_query(args):
    if not isinstance(args, dict) or set(args) != {'profile', 'start', 'end'} or args.get('profile') != 'FC27':
        raise ValueError('official_query_not_allowed')
    for field in ('start', 'end'):
        if not isinstance(args[field], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', args[field]):
            raise ValueError('official_date_required')
    start, end = date.fromisoformat(args['start']), date.fromisoformat(args['end'])
    if not 0 <= (end - start).days < 93:
        raise ValueError('official_period_not_allowed')
    return dict(profile='FC27', start=start.isoformat(), end=end.isoformat())


def _url(value, index=False):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.netloc != 'www.ea.com' or
            parsed.query or parsed.fragment or any(ord(char) < 32 for char in value)):
        raise ValueError('official_url_not_allowed')
    allowed = parsed.path.rstrip('/') == PREFIX.rstrip('/') if index else bool(
        re.fullmatch(re.escape(PREFIX) + r'[a-z0-9][a-z0-9-]*/?', parsed.path))
    if not allowed:
        raise ValueError('official_path_not_allowed')
    return value


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.parts, self.main_parts, self.title_parts = [], [], [], []
        self.skip = self.main = self.in_title = 0
        self.published = self.meta_title = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style', 'noscript', 'svg', 'nav', 'header', 'footer', 'form'):
            self.skip += 1
        if tag in ('main', 'article'):
            self.main += 1
        if tag == 'title':
            self.in_title += 1
        if tag == 'a' and not self.skip and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag == 'meta':
            key = attrs.get('property') or attrs.get('name')
            if key in ('article:published_time', 'og:published_time', 'datePublished'):
                self.published = attrs.get('content')
            if key == 'og:title':
                self.meta_title = attrs.get('content')
        if tag == 'time' and not self.skip and attrs.get('datetime') and not self.published:
            self.published = attrs['datetime']

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg', 'nav', 'header', 'footer', 'form'):
            self.skip = max(0, self.skip - 1)
        if tag in ('main', 'article'):
            self.main = max(0, self.main - 1)
        if tag == 'title':
            self.in_title = max(0, self.in_title - 1)

    def handle_data(self, value):
        if not self.skip:
            if self.in_title:
                self.title_parts.append(value)
            else:
                self.parts.append(value)
                if self.main:
                    self.main_parts.append(value)


def _clean(value):
    return re.sub(r'\s+', ' ', unescape(value)).strip()


def _published(value):
    if not value:
        return None
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return date.fromisoformat(value).isoformat()
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.isoformat() if parsed.utcoffset() is not None else None
    except (ValueError, TypeError):
        return None


def _publication_hints(html):
    # EA's rendered Next page places publishingDate immediately before its slug.
    return {slug: _published(stamp) for stamp, slug in re.findall(
        r'"publishingDate"\s*:\s*"([^"<>]{1,80})"\s*,\s*"slug"\s*:\s*"([a-z0-9-]+)"', html)}


@lru_cache(maxsize=1)
def _collector():
    # The FS host reuses the deployed collector without widening its import path.
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location('fs_fc_official_collector', '/opt/fs-boss-workspaces/backend/game_intelligence.py')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.fetch


def _default_fetch(url, hosts, deadline_at):
    return _collector()(url, hosts, deadline_at=deadline_at)


class OfficialReader:
    def __init__(self, fetcher=None, clock=None):
        self.fetcher = fetcher or _default_fetch
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _read(self, url, deadline, index=False):
        _url(url, index)
        data, mime, final_url = self.fetcher(url, ['www.ea.com'], deadline_at=deadline)
        _url(final_url, index)
        if mime != 'text/html' or not isinstance(data, bytes) or len(data) > MAX_BYTES:
            raise ValueError('official_response_contract')
        html = data.decode('utf-8-sig', 'strict')
        page = _Page()
        page.feed(html)
        text = _clean(' '.join(page.main_parts or page.parts))
        if len(text) < 80 or re.search(r'just a moment|access denied|enable javascript|verify you are human|checking your browser', text, re.I):
            raise ValueError('official_page_unreadable')
        return html, page, text, final_url, sha256(data).hexdigest()

    def __call__(self, args):
        query = checked_query(args)
        observed = self.clock()
        if observed.utcoffset() is None:
            raise ValueError('official_aware_clock_required')
        captured = observed.astimezone(timezone.utc).isoformat()
        deadline = datetime.now(timezone.utc) + timedelta(seconds=35)
        documents, failures, selected, links = [], [], [], []
        index_ok = False
        index_sha = None
        try:
            html, page, _, _, index_sha = self._read(INDEX, deadline, index=True)
            index_ok = True
            hints = _publication_hints(html)
            for href in page.links:
                candidate = urljoin(INDEX + '/', href)
                try:
                    _url(candidate)
                except ValueError:
                    continue
                if candidate not in links:
                    links.append(candidate)
            selected = links[:MAX_ARTICLES]

            def article(url):
                html, page, body, final_url, raw_sha = self._read(url, deadline)
                title = _clean(page.meta_title or ' '.join(page.title_parts))[:240]
                if re.search(r'\bFC\s*26\b', title, re.I) and not re.search(r'\bFC\s*27\b', title, re.I):
                    raise ValueError('fc26_article_excluded')
                slug = urlsplit(final_url).path.rstrip('/').rsplit('/', 1)[-1]
                published = _published(page.published) or _publication_hints(html).get(slug) or hints.get(slug)
                in_window = query['start'] <= published[:10] <= query['end'] if published else None
                text = body[:MAX_TEXT]
                return dict(source_url=final_url, title=title or slug, text=text,
                            published_at=published, observed_at=captured, event_date=None,
                            publication_in_window=in_window, text_truncated=len(body) > MAX_TEXT,
                            body_scope='main_or_article' if page.main_parts else 'page_text',
                            sha256=sha256(text.encode('utf-8')).hexdigest(), content_sha256=raw_sha)

            executor = ThreadPoolExecutor(max_workers=3)
            pending = {executor.submit(article, url): url for url in selected}
            try:
                for future in as_completed(pending, timeout=max(0.01, (deadline - datetime.now(timezone.utc)).total_seconds())):
                    url = pending[future]
                    try:
                        documents.append(future.result())
                    except (OSError, ValueError, TypeError) as error:
                        failures.append(_failure(url, error))
            except FuturesTimeout:
                completed = {item['source_url'] for item in documents} | {item['source_url'] for item in failures}
                for future, url in pending.items():
                    if url not in completed:
                        future.cancel()
                        failures.append(dict(source_url=url, reason='deadline_exceeded'))
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        except (OSError, ValueError, TypeError) as error:
            failures.append(_failure(INDEX, error))

        documents.sort(key=lambda item: selected.index(item['source_url']) if item['source_url'] in selected else len(selected))
        status = ('partial' if failures or len(links) > len(selected) else 'available') if documents else ('empty' if index_ok and not failures else 'not_available')
        result = dict(http_status=200 if documents or index_ok and not failures else 503,
                      status=status, captured_at=captured, query=query, documents=documents,
                      coverage=dict(index_url=INDEX, index_read=index_ok, index_sha256=index_sha,
                                    discovered_articles=len(links), selected_articles=len(selected),
                                    returned_articles=len(documents), omitted_articles=max(0, len(links) - len(selected)),
                                    exhaustive=False, period_basis='publication_date_only',
                                    event_dates='unknown_read_article_body',
                                    limitation='Bounded current news index; outside-window articles are context. No match does not establish no activity.'),
                      failures=failures)
        result['source_snapshot_id'] = 'official_' + sha256(json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
        return result


def _failure(url, error):
    if isinstance(error, urllib.error.HTTPError):
        reason = 'http_' + str(error.code)
    elif isinstance(error, TimeoutError):
        reason = 'deadline_or_timeout'
    elif isinstance(error, ValueError) and str(error) in (
            'official_url_not_allowed', 'official_path_not_allowed', 'official_response_contract',
            'official_page_unreadable', 'fc26_article_excluded'):
        reason = str(error)
    else:
        reason = 'fetch_or_parse_failed'
    return dict(source_url=url, reason=reason)
