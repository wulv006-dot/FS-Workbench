"""Anonymous regional merchandise quotes via the existing site's verified goods request."""
from datetime import datetime,timezone
from decimal import Decimal,ROUND_HALF_UP
import hashlib
from html.parser import HTMLParser
import http.cookiejar
import json
import re
from urllib.parse import urlencode,urlsplit,parse_qs
from urllib.request import Request,build_opener,HTTPCookieProcessor


PLATFORMS={'PS':21587,'XBOX':21585,'PC':21589}
SKU_IDS={'PS':163329311,'XBOX':163329277,'PC':163329345}
SCOPE_FIELDS=('id','site_id','gid','top_cid','cid','sid','aid','unit')


def canonical_products():
    return {p:dict(id=SKU_IDS[p],site_id=266,gid=1327,top_cid=1,cid=9623,
                   sid=7645,aid=aid,unit='K') for p,aid in PLATFORMS.items()}


class _PageContext(HTMLParser):
    """Read the site's actual selected locale/currency, not navigation options."""
    def __init__(self):
        super().__init__()
        self.stack=[]
        self.headers=[]
        self.scripts=[]

    def handle_starttag(self,tag,attrs):
        if tag in ('area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'):
            return
        classes=dict(attrs).get('class','').split()
        self.stack.append((tag,[] if 'lang-currency' in classes or tag=='script' else None))

    def handle_endtag(self,tag):
        position=next((i for i in range(len(self.stack)-1,-1,-1) if self.stack[i][0]==tag),None)
        if position is None:return
        for name,parts in self.stack[position:]:
            if parts is not None:
                (self.scripts if name=='script' else self.headers).append(' '.join(''.join(parts).split()))
        del self.stack[position:]

    def handle_data(self,data):
        for _,parts in self.stack:
            if parts is not None:parts.append(data)


def selection_context(html,final_url,code,region_id):
    url=urlsplit(final_url)
    if (url.scheme!='https' or url.netloc!='www.mmoexp.com' or
            url.path!='/'+code+'/Fc-27/Coins.html' or parse_qs(url.query).get('cy')!=['USD']):
        raise ValueError('pricing_public_region_redirect_mismatch')
    page=_PageContext()
    page.feed(html)
    if not page.headers or any(header!=code.upper()+' | USD' for header in page.headers):
        raise ValueError('pricing_public_region_selected_context_mismatch')
    scripts='\n'.join(page.scripts)
    currencies=re.findall(r'\b(?:const|let|var)\s+currencyCode\s*=\s*[\"\x27]([^\"\x27]*)[\"\x27]',scripts)
    valuta=re.findall(r'\bvaluta\s*:\s*currencyCode\s*\?\s*(\{[^{}]*\})',scripts)
    if not currencies or set(currencies)!={'USD'} or not valuta:
        raise ValueError('pricing_public_region_currency_context_missing')
    for raw in valuta:
        currency=json.loads(raw)
        if currency.get('code')!='USD' or Decimal(str(currency.get('rate'))) != 1:
            raise ValueError('pricing_public_region_currency_context_mismatch')
    return dict(code=code,region_id=region_id,currency='USD',currency_rate='1',
                selected_header=page.headers[0],final_url=final_url,
                landing_sha256=hashlib.sha256(html.encode()).hexdigest())


def collect(code,region_id,expected_products=None):
    if (code,region_id) not in (('uk',39),('ar',21)):
        raise ValueError('pricing_public_region_scope_invalid')
    origin='https://www.mmoexp.com'
    url=origin+'/'+code+'/Fc-27/Coins.html?cy=USD'
    opener=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    headers={'User-Agent':'Mozilla/5.0','Referer':url,'Cache-Control':'no-cache'}
    with opener.open(Request(url,headers=headers),timeout=18) as response:
        html=response.read(2*1024*1024).decode('utf-8')
        final_url=response.geturl()
    context=selection_context(html,final_url,code,region_id)
    expected_products=expected_products if expected_products is not None else canonical_products()
    offers={}
    for platform,aid in PLATFORMS.items():
        form=urlencode(dict(Game_id=1327,top_cid=1,aid=aid,cid=9623,site_id=266)).encode()
        request=Request(origin+'/ajax/goods',data=form,headers=dict(headers,**{
            'Content-Type':'application/x-www-form-urlencoded','X-Requested-With':'XMLHttpRequest'}))
        with opener.open(request,timeout=18) as response:
            payload=json.loads(response.read(1024*1024))
        goods=payload['goods']['index']['list']
        if len(goods)!=1:
            raise ValueError('pricing_public_region_platform_mismatch')
        row=goods[0]
        expected=expected_products[platform]
        scope={field:row.get(field) for field in SCOPE_FIELDS}
        if any(str(scope[field])!=str(expected[field]) for field in SCOPE_FIELDS):
            raise ValueError('pricing_public_region_product_scope_mismatch:'+platform)
        if row.get('_region_factor') is None:
            raise ValueError('pricing_public_region_factor_missing')
        factor=Decimal(str(row['_region_factor']))
        if not factor.is_finite() or factor<=0:
            raise ValueError('pricing_public_region_factor_invalid')
        tiers=row['goods_list']
        tiers=list(tiers.values()) if isinstance(tiers,dict) else tiers
        anchors=[t for t in tiers if Decimal(str(t['num']))==100]
        if len(anchors)!=1:
            raise ValueError('pricing_public_region_anchor_ambiguous')
        tier=anchors[0]
        price=Decimal(str(tier['price_discount']))
        give=Decimal(str(tier['give']))
        if not price.is_finite() or price<=0 or not give.is_finite() or give<0:
            raise ValueError('pricing_public_region_price_invalid')
        display=price.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        offers[platform]=dict(platform=platform,region_id=region_id,sku_id=str(row['id']),aid=aid,
            coefficient=str(factor),regular_usd=str(display),exact_regular_usd=str(price),
            delivered_k=str(100+give),tiers=tiers,source_url=final_url,
            checked_at=datetime.now(timezone.utc).isoformat(),price_basis='public_merchandise',
            selection_verified=True,currency=context['currency'],selection_context=context,
            product_scope=scope,source='anonymous_regional_goods_request')
    return dict(region_id=region_id,code=code,offers=offers,status='verified',
                selection_context=context,request_contract='actual_selected_locale_USD_and_full_native_product_scope')
