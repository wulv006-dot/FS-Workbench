"""Approved public-page observations. No crawling, cookies, browser or model."""
import datetime as dt
import hashlib
import http.client
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .contracts import game, make_daily_context
from .sources import path_expression, SourceError


def approved_url(scope, url):
    game(scope)
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.netloc != 'www.mmoexp.com' or parts.query or parts.fragment or
            not re.search(path_expression(scope), url) or
            re.search(r'/(?:checkout|cart|payment|pay|login|logout|account)(?:[/.]|$)', parts.path, re.I)):
        raise ValueError('UNAPPROVED_SEO_PAGE')
    return url


class HeadFacts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = dict(title='', h1='', robots=None, canonical=None, hreflang=[])
        self.current = None

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag in ('title', 'h1') and not self.values[tag]:
            self.current = tag
        if tag == 'meta' and str(data.get('name', '')).lower() == 'robots':
            self.values['robots'] = str(data.get('content') or '')[:1000]
        if tag == 'link' and 'canonical' in str(data.get('rel', '')).lower().split():
            self.values['canonical'] = str(data.get('href') or '')[:2000]
        if tag == 'link' and data.get('hreflang') and len(self.values['hreflang']) < 100:
            self.values['hreflang'].append(dict(language=str(data['hreflang'])[:50], href=str(data.get('href') or '')[:2000]))

    def handle_endtag(self, tag):
        if tag == self.current:
            self.current = None

    def handle_data(self, data):
        if self.current:
            self.values[self.current] = (self.values[self.current] + data)[:1000]

    def facts(self):
        return dict(self.values, title=self.values['title'].strip(), h1=self.values['h1'].strip())


def read_page(url, *, connect_seconds, idle_seconds, response_emergency_bytes,
              clock=lambda: dt.datetime.now(dt.timezone.utc)):
    if min(connect_seconds, idle_seconds, response_emergency_bytes) <= 0:
        raise ValueError('PAGE_RESOURCE_CONFIG_REQUIRED')
    parts = urlsplit(url)
    connection = http.client.HTTPSConnection('www.mmoexp.com', timeout=connect_seconds)
    try:
        connection.connect()
        connection.sock.settimeout(idle_seconds)
        connection.request('GET', parts.path, headers={'User-Agent':'FS-SEO-Daily/1.0', 'Accept':'text/html', 'Accept-Encoding':'identity'})
        response = connection.getresponse()
        parser, content_hash, size = HeadFacts(), hashlib.sha256(), 0
        import codecs
        decoder = codecs.getincrementaldecoder(response.headers.get_content_charset() or 'utf-8')(errors='replace')
        while True:
            if not make_daily_context(clock()).collection_allowed:
                raise SourceError('NIGHT_DEADLINE')
            data = response.read(65536)
            if not data:
                break
            size += len(data)
            if size > response_emergency_bytes:
                raise SourceError('PAGE_EMERGENCY_SIZE')
            content_hash.update(data)
            parser.feed(decoder.decode(data))
        parser.feed(decoder.decode(b'', final=True));parser.close()
        return dict(parser.facts(), status_code=response.status, redirect=response.getheader('Location'),
                    content_hash=content_hash.hexdigest(), response_bytes=size)
    finally:
        connection.close()


class PageSource:
    name = 'pages'
    timezone = 'Asia/Shanghai'
    is_observation = True

    def __init__(self, urls, *, fetch=None, http=None, clock=lambda: dt.datetime.now(dt.timezone.utc)):
        self.urls = {game(scope):tuple(approved_url(scope, u) for u in values) for scope,values in urls.items()}
        self.clock = clock
        self.fetch = fetch or (lambda url: read_page(url, clock=clock, **http))

    def pages(self, scope, day, cursor=0):
        context = make_daily_context(self.clock())
        if not context.collection_allowed or day != context.publication_date:
            raise SourceError('PAGE_OBSERVATION_TIME_REQUIRED')
        urls = self.urls.get(game(scope), ())
        if not urls:
            yield dict(rows=[], next_cursor=None, source_timezone=self.timezone, status='not_configured', quality={})
        for index in range(cursor, len(urls)):
            observed = self.clock().astimezone(dt.timezone.utc).isoformat()
            if not make_daily_context(self.clock()).collection_allowed:
                raise SourceError('NIGHT_DEADLINE')
            row = dict(self.fetch(urls[index]), key=urls[index], url=urls[index], observed_at=observed)
            yield dict(rows=[row], next_cursor=index+1 if index+1 < len(urls) else None,
                       source_timezone=self.timezone, status='available', quality=dict(sample_kind='point_observation'))
