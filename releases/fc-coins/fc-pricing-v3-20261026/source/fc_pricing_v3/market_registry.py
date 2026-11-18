"""Shared public observations using the same official platform parser as 183."""
from datetime import datetime, timezone
import http.cookiejar
from types import SimpleNamespace
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPCookieProcessor, Request

def arab_normal():
    sys.path.insert(0, '/opt/fs-fc-control/code')
    from fc_collection.adapters import (ARAB_DELIVERY_ERROR_MAX_BYTES, ArabNormalDeliveryUnavailable,
                                        SourceUnavailable, arab_normal_delivery_unavailable)
    from fc_collection.contracts import arab_quote_details, arab_status
    from fc_collection.public_sources import REGISTRY, arab_adapter
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def get(template):
        item = REGISTRY['ArabUT'][template]
        url = 'https://' + item['host'] + item['path'] + '?' + urlencode(item['query'])
        request = Request(url, headers={'User-Agent':'Mozilla/5.0',
            'Accept':'application/json' if template.startswith('quote') else 'text/html',
            'Referer':'https://www.arab-ut.com/en'})
        try:
            with opener.open(request, timeout=18) as response:
                payload = response.read(item['max_bytes'] + 1)
        except HTTPError as exc:
            retry = exc.headers.get('Retry-After', '')
            code = exc.code
            retry_after = int(retry) if retry.isdigit() else 0
            try:
                if code == 422 and template == 'quote' and arab_normal_delivery_unavailable(
                        exc.read(ARAB_DELIVERY_ERROR_MAX_BYTES + 1)):
                    raise ArabNormalDeliveryUnavailable(retry_after) from None
            finally:
                exc.close()
            raise SourceUnavailable('http_' + str(code), retry_after) from None
        if len(payload) > item['max_bytes']:
            raise ValueError('arab_quote_response_too_large')
        return payload
    requested = ['PS', 'XBOX', 'PC']
    result = arab_adapter(dict(requested_platforms=requested, region_scope=[21]),
        SimpleNamespace(get=get, clock=lambda:datetime.now(timezone.utc)))
    rows = []
    for offer in result['offers']:
        row = dict(source='ArabUT', status='valid', platform=offer['platform'], region_id=offer['region_id'],
            purchase_k='100', bonus_k='0', currency=offer['currency'],
            settlement_currency=offer['settlement_currency'], conversion_source=offer['conversion_source'],
            captured_at=offer['observed_at'], selection_verified=offer['selection_verified'],
            conditional=offer['conditional'], comparable=offer['comparable'],
            price_basis=offer['price_basis'], auth_state=offer['auth_state'], discount_source=offer['discount_source'],
            delivery_method=offer['delivery_method'], coupon_excluded=offer['coupon_excluded'])
        row.update(arab_quote_details(offer))
        rows.append(row)
    return arab_status(rows, requested, result.get('platform_errors'))
