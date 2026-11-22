"""Actor-scoped receipts for on-demand FC27 public source reads."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urljoin, urlsplit
import json
import re
import subprocess
import sys
import tempfile

RUNTIME = '/opt/fs-hermes-fc-public-research-0.5.1/bin/python3.12'
VERSION = '0.5.1'
SOURCE_LIMIT = 4
EA_NEWS_INDEX = 'https://www.ea.com/games/ea-sports-fc/fc-27/news'
PUBLIC_CONFIG = 'https://www.mmoexp.com/events/api/campaign/config'
STORE_PAGES = {'Player-Trio.html':'fc27-trio','Weekly-Scout.html':'fc27-weekly','Sbc-Companions.html':'fc27-sbc'}
SOURCE_PATTERNS = {
    'www.ea.com': ('ea_news', r'/(?:[a-z]{2}(?:-[a-z]{2})?/)?games/ea-sports-fc/fc-27/news/[a-z0-9-]+/?'),
    'www.futbin.com': ('futbin_card', r'/27/player/[0-9]+/[a-zA-Z0-9-]+/?'),
    'www.fut.gg': ('futgg_card', r'/players/[0-9]+(?:-[a-zA-Z0-9-]+)?/27-[0-9]+/?'),
    'www.mmoexp.com': ('storefront_display', r'/events/(?:Player-Trio|Weekly-Scout|Sbc-Companions)\.html'),
}


def source_kind(url):
    if url == EA_NEWS_INDEX:
        return 'ea_news_index'
    if not isinstance(url, str) or len(url) > 300 or not url.isascii() or re.search(r'[\x00-\x20\x7f\\]', url):
        raise ValueError('campaign_public_source_url')
    parts = urlsplit(url)
    route = SOURCE_PATTERNS.get(parts.netloc)
    if (not route or parts.scheme != 'https' or parts.query or parts.fragment
            or not re.fullmatch(route[1], parts.path) or url != parts.geturl()):
        raise ValueError('campaign_public_source_url')
    return route[0]


def validate_request(body):
    if (type(body) is not dict or set(body) != {'purpose', 'urls'}
            or body['purpose'] not in ('activity', 'pricing_display')
            or type(body['urls']) is not list or not 1 <= len(body['urls']) <= SOURCE_LIMIT):
        raise ValueError('campaign_public_source_request')
    for url in body['urls']:
        kind = source_kind(url)
        if body['purpose'] == 'pricing_display' and kind in ('ea_news', 'ea_news_index'):
            raise ValueError('campaign_public_source_purpose')
    if len(set(body['urls'])) != len(body['urls']):
        raise ValueError('campaign_public_source_request')
    return body


def field(root, name, selectors, fields, limit=240):
    for selector in selectors:
        result = root.css(selector).getall()
        value = ' '.join(re.sub(r'[\x00-\x1f\x7f]', ' ', ' '.join(result)).split())[:limit]
        if value:
            fields[name] = {'value': value, 'selector': selector}
            return


def extract(page, kind, purpose, url):
    fields = {}
    field(page, 'title', ('h1 ::text', 'h1::text', 'head title::text'), fields)
    if kind == 'ea_news_index':
        selector = 'a[href*="/fc-27/news/"]'
        for link in page.css(selector):
            href = urljoin(url, link.attrib['href'])
            try:
                if source_kind(href) != 'ea_news':
                    continue
            except ValueError:
                continue
            label = ' '.join(link.get_all_text(separator=' ',strip=True).split())
            if re.search(r'\bFootball Ultimate Team\b', label, re.I):
                fields['article_url'] = dict(value=href, selector=selector+'::attr(href)')
                break
        return fields, sorted({'title', 'article_url'} - set(fields))
    if kind == 'ea_news':
        field(page, 'published_at', ('meta[property="article:published_time"]::attr(content)', 'time::attr(datetime)'), fields)
        field(page, 'article_summary', ('meta[name="description"]::attr(content)', 'article p ::text', 'main p ::text'), fields, 420)
    else:
        parts = urlsplit(url).path.strip('/').split('/')
        item = parts[-1][3:] if kind == 'futgg_card' else parts[-2]
        if 'title' in fields:
            fields['source_card_id'] = {'value':item,'selector':'URL path'}
            field(page, 'card_summary', ('meta[name="description"]::attr(content)',), fields)
            if purpose=='activity':
                # Only preserve explicitly labelled counts. Generic ratings and descriptions are not usage.
                for selector in ('dl > div', 'tr'):
                    for row in page.css(selector):
                        label = ' '.join(row.get_all_text(separator=' ',strip=True).split())
                        matched = re.fullmatch(r'(Games Played|Usage|Votes)\s*:?\s*([0-9][0-9,]*(?:\.[0-9]+)?%?)',label,re.I)
                        if matched:
                            key = matched[1].casefold().replace(' ', '_')
                            fields[key] = dict(value=matched[2],selector=selector+' / '+matched[1])
    missing = ({'title','published_at','article_summary'} if kind=='ea_news'
               else {'title','source_card_id','card_summary'})
    if purpose == 'pricing_display' and kind in ('futgg_card','futbin_card'):
        missing.add('market_currency_and_display_price')
    return fields, sorted(missing - set(fields))


def storefront_fields(url, fetch, stamp):
    """Read the active public projection. Initial HTML can contain legacy example cards."""
    fields = {}
    try:
        config = fetch(PUBLIC_CONFIG)
        if int(config.status)!=200 or str(config.url)!=PUBLIC_CONFIG or len(config.body)>5_000_000:
            return fields
        data=json.loads(config.body)
    except (OSError,RuntimeError,ValueError,TypeError):
        return fields
    if not isinstance(data,dict):
        return fields
    source_time=stamp()
    release=data.get('release_id')
    if not isinstance(release,str) or not re.fullmatch(r'campaign-preview-[0-9]+',release):
        return fields
    page_id=STORE_PAGES[url.rsplit('/',1)[-1]]
    page=next((row for row in data.get('pages',[]) if row.get('page_id')==page_id),None)
    if not page or page.get('active') is not True:
        return fields
    def add(name,value,selector):
        fields[name]=dict(value=value,selector=selector,source_url=PUBLIC_CONFIG,fetched_at=source_time)
    add('publication',release,'$.release_id')
    add('title',page['title'],'$.pages[page_id].title')
    layout=data.get('fc_layout') or {}
    if page_id=='fc27-sbc':
        core=layout.get('defaultCore')
        selected=layout.get('routes',{}).get(core,{}).get('picks',[])
        add('default_core',core,'$.fc_layout.defaultCore')
    else:
        selected=layout.get(page_id.split('-')[-1],[])
    model_ids={key.rsplit('-',1)[-1] for key in selected}
    keys=set(page.get('product_keys',[]))
    matches=[product for product in data.get('products',[]) if product.get('key') in keys and product.get('product_ref',{}).get('model_id') in model_ids]
    if matches:
        names=list(dict.fromkeys(product['title'] for product in matches))
        add('cards',names,'$.pages[page_id].product_keys -> $.products[product_ref.model_id].title')
    contracts=data.get('seasonal_model_contracts',{})
    references=[]
    at=datetime.fromisoformat(source_time)
    for product in matches:
        model_id=product['product_ref']['model_id']
        contract=contracts.get(model_id,{})
        if contract.get('verified') is not True:continue
        for combo in contract.get('combinations',[]):
            if combo.get('product_key')!=product['key']:continue
            price=combo.get('price') or {}
            if (price.get('source')!='admin_current' or price.get('currency')!='USD'
                    or price.get('minor_unit_scale')!=2 or type(price.get('base_minor')) is not int
                    or price['base_minor']<=0):continue
            try:
                if datetime.fromisoformat(price['expires_at'].replace('Z','+00:00'))<=at:continue
            except (ValueError,TypeError,KeyError):continue
            references.append(dict(title=product['title'],platform=product.get('platform',{}).get('code'),
                                   currency='USD',base_minor=price['base_minor'],expires_at=price['expires_at']))
    if references:
        add('public_reference_prices',references,'$.seasonal_model_contracts[model_id].combinations[product_key].price')
    return fields


def observe(url, purpose, fetch, stamp):
    kind = source_kind(url)
    receipt = {'url':url,'source_kind':kind,'attempted_at':stamp(),'fields':{}}
    try:
        page = fetch(url)
        status = int(page.status)
    except Exception as error:
        return dict(receipt,status='fetch_failed',error_type=type(error).__name__)
    receipt['http_status'] = status
    if not 200 <= status < 300:
        return dict(receipt,status='source_blocked' if status in (401,403,429) else 'http_error')
    receipt['fetched_at'] = stamp()
    if str(page.url).rstrip('/') != url.rstrip('/'):
        return dict(receipt,status='unexpected_source_url')
    body = page.body
    if not body or len(body) > 5_000_000:
        return dict(receipt,status='source_body_unavailable')
    title = ' '.join(page.css('head title::text').getall()).casefold()
    if any(label in title for label in ('just a moment','access denied','captcha','attention required','request blocked')):
        return dict(receipt,status='source_blocked')
    try:
        if kind=='storefront_display':
            fields=storefront_fields(url,fetch,stamp)
            needed={'title','publication','cards'}
            if purpose=='pricing_display':
                needed.add('public_reference_prices')
            missing=sorted(needed-set(fields))
        else:
            fields, missing = extract(page,kind,purpose,url)
    except (TypeError,ValueError,KeyError,AttributeError):
        return dict(receipt,status='fields_missing',content_sha256=sha256(body).hexdigest())
    return dict(receipt,status='observed' if not missing else 'partial' if fields else 'fields_missing',
                fields=fields,missing_fields=missing,content_sha256=sha256(body).hexdigest())


def collect(request, fetch, stamp):
    request = validate_request(request)
    with ThreadPoolExecutor(max_workers=SOURCE_LIMIT) as pool:
        sources = list(pool.map(lambda url:observe(url,request['purpose'],fetch,stamp),request['urls']))
    coverage = ('complete' if all(source['status']=='observed' for source in sources) else
                'partial' if any(source['fields'] for source in sources) else 'unavailable')
    return dict(purpose=request['purpose'],coverage=coverage,sources=sources,
                authority='display_price_corroboration_only' if request['purpose']=='pricing_display' else 'public_evidence_only')


def worker(request):
    payload = json.dumps(request,ensure_ascii=False).encode()
    with tempfile.TemporaryFile() as output:
        completed = subprocess.run([RUNTIME,'-I','-B',str(Path(__file__).resolve()),'--worker'],
            input=payload,stdout=output,stderr=subprocess.DEVNULL,timeout=24,check=False,
            user='nobody',group='nobody',extra_groups=[],env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':'/nonexistent'})
        output.seek(0)
        raw = output.read(64001)
    if completed.returncode or not raw or len(raw)>64000:
        raise RuntimeError('public_source_worker_unavailable')
    return json.loads(raw)


def read_sources(request, read=worker):
    data=read(validate_request(request))
    if (type(data) is not dict or data.get('purpose')!=request['purpose']
            or [source.get('url') for source in data.get('sources',[])]!=request['urls']
            or data.get('coverage') not in ('complete','partial','unavailable')):
        raise ValueError('public_source_worker_contract')
    return data


class PublicSources:
    def __init__(self,tasks,*,worker=worker,clock=lambda:datetime.now(timezone.utc)):
        self.tasks,self.worker,self.clock=tasks,worker,clock
        with tasks.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS campaign_public_sources (operation_id TEXT PRIMARY KEY, owner TEXT NOT NULL, request TEXT NOT NULL, started_at TEXT NOT NULL, result TEXT)')
            # A disrupted worker remains attached to its original id.
            orphaned=db.execute('SELECT operation_id,request,started_at FROM campaign_public_sources WHERE result IS NULL').fetchall()
            for row in orphaned:
                record=self.failure(row['operation_id'],json.loads(row['request']),row['started_at'],'worker_interrupted')
                db.execute('UPDATE campaign_public_sources SET result=? WHERE operation_id=?',(json.dumps(record),row['operation_id']))

    def lookup(self,key,owner):
        with self.tasks.db() as db:
            row=db.execute('SELECT result FROM campaign_public_sources WHERE operation_id=? AND owner=?',(key,owner)).fetchone()
        if row:
            return json.loads(row['result']) if row['result'] else {'status':'pending','kind':'public_sources','operation_id':key}
        return None

    def failure(self,key,request,started,reason):
        return dict(status='failed',kind='public_sources',operation_id=key,engine={'name':'scrapling','version':VERSION},
                    purpose=request['purpose'],coverage='unavailable',error=reason,started_at=started,
                    completed_at=self.clock().isoformat(),sources=[])

    def submit(self,key,owner,request):
        validate_request(request)
        encoded=json.dumps(request,ensure_ascii=False,sort_keys=True)
        started=self.clock().isoformat()
        with self.tasks.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT owner,request FROM campaign_public_sources WHERE operation_id=?',(key,)).fetchone()
            if row:
                if row['owner']!=owner:
                    raise PermissionError('campaign_source_owner')
                if row['request']!=encoded:
                    raise ValueError('campaign_request_conflict')
            else:
                db.execute('INSERT INTO campaign_public_sources VALUES(?,?,?,?,NULL)',(key,owner,encoded,started))
        if row:
            return self.lookup(key,owner)
        try:
            data=read_sources(request,self.worker)
            result=dict(data,status='completed',kind='public_sources',operation_id=key,
                        engine={'name':'scrapling','version':VERSION},started_at=started,completed_at=self.clock().isoformat())
        except (OSError,RuntimeError,ValueError,TypeError,subprocess.TimeoutExpired):
            result=self.failure(key,request,started,'public_source_worker_unavailable')
        with self.tasks.db() as db:
            db.execute('UPDATE campaign_public_sources SET result=? WHERE operation_id=? AND owner=?',
                       (json.dumps(result,ensure_ascii=False),key,owner))
        return result


if __name__=='__main__' and sys.argv[1:]==['--worker']:
    from importlib.metadata import version
    from scrapling.fetchers import Fetcher
    if version('scrapling')!=VERSION:
        raise RuntimeError('unexpected_scrapling_version')
    def get(url):
        return Fetcher.get(url,timeout=8,retries=0,follow_redirects=False,stealthy_headers=False,
                           headers={'User-Agent':'MMOEXP-FC27-PublicEvidence/1.0','Accept':'text/html'})
    print(json.dumps(collect(json.load(sys.stdin),get,lambda:datetime.now(timezone.utc).isoformat()),ensure_ascii=False))
