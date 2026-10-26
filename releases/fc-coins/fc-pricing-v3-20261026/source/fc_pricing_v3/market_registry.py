"""Shared public observations, including the site's verified normal-delivery quote."""
from datetime import datetime,timezone
from decimal import Decimal
import http.cookiejar
import json
from urllib.request import build_opener,HTTPCookieProcessor,Request


def arab_normal():
    origin='https://www.arab-ut.com'
    opener=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    query='platform=playstation&delivery=normal&quantity=100000'
    warm=Request(origin+'/?'+query+'&currency=USD',headers={'User-Agent':'Mozilla/5.0','Accept':'text/html'})
    with opener.open(warm,timeout=18) as response:
        response.read(2*1024*1024+1)
    request=Request(origin+'/coins/quote?'+query,headers={'User-Agent':'Mozilla/5.0',
                    'Accept':'application/json','Referer':origin+'/?'+query+'&currency=USD'})
    with opener.open(request,timeout=18) as response:
        value=json.loads(response.read(1024*1024))
    value=value.get('data',value)
    if (value.get('platform')!='playstation' or value.get('delivery')!='normal' or
            value.get('quantity')!=100000 or value.get('market')!='console' or
            value.get('total',{}).get('currency')!='SAR' or value.get('displayTotal',{}).get('currency')!='USD'):
        raise ValueError('pricing_arab_quote_selection_invalid')
    total=value['displayTotal']['amountMinor']
    if type(total) is not int or total<=0:
        raise ValueError('pricing_arab_quote_amount_invalid')
    now=datetime.now(timezone.utc).isoformat()
    common=dict(source='ArabUT',region_id=21,delivery='normal',selection_verified=True,
                purchase_k='100',bonus_k='0',delivered_k='100',total_usd=str(Decimal(total)/100),
                currency='USD',comparison_currency='USD',settlement_currency='SAR',conversion_source='official_display_quote',
                original_currency='SAR',original_amount_minor=value['total']['amountHalalah'],
                price_version=value['priceVersion'],captured_at=now,priced_at=value['pricedAt'],
                url=origin+'/coins/quote?'+query,conditional=False,comparable=True,
                price_basis='public_merchandise',quantity_basis='official_quote_quantity_bonus_not_advertised',
                platform_mapping='official_playstation_market_console_shared_PS_Xbox',
                parser_version='arab-public-quote-v1')
    return dict(status='available',offers=[dict(common,platform=p) for p in ('PS','XBOX')],
                coverage=dict(PS='normal_verified',XBOX='official_shared_console',PC='normal_not_offered'))
