"""Page-scoped aggregate reports through the existing FS Google read connection."""
import json
import math
import re
import sys
from datetime import date, datetime, timezone, timedelta
from urllib.parse import quote

PAGES = {
    'mmoexp-seasonal': ('/events/seasonal/', r'/events/seasonal/(index[.]html)?'),
    'mmoexp-carnival': ('/events/Carnival.html', r'/events/Carnival[.]html'),
}
GA = 'https://analyticsdata.googleapis.com/v1beta/properties/541418940:runReport'
GSC = 'https://www.googleapis.com/webmasters/v3/sites/' + quote('sc-domain:mmoexp.com', safe='') + '/searchAnalytics/query'
ADS = 'https://googleads.googleapis.com/v25/customers/1430398974/googleAds:search'


def validate(request):
    if (not isinstance(request, dict) or set(request) - {'activity'} != {'source', 'from', 'to'}
            or request['source'] not in ('ga4', 'gsc', 'ads')
            or request.get('activity', 'mmoexp-seasonal') not in PAGES):
        raise ValueError('INVALID_GOOGLE_FILTER')
    start, end = (date.fromisoformat(request[k]) for k in ('from', 'to'))
    if any(request[k] != d.isoformat() for k, d in [('from', start), ('to', end)]) or not 0 <= (end-start).days < 31 or start > datetime.now(timezone.utc).date():
        raise ValueError('INVALID_GOOGLE_FILTER')
    return request['source'], start.isoformat(), end.isoformat(), request.get('activity', 'mmoexp-seasonal')


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('INVALID_GOOGLE_RESPONSE')
    return result


def text(value):
    return re.sub(r'[\x00-\x1f\x7f]', '', str(value))[:200]


def ga(reader, start, end, pattern, dimensions, metrics, landing=False, organic=False):
    field = 'landingPage' if landing else 'pagePath'
    filters = [
        {'filter': {'fieldName': field, 'stringFilter': {'matchType': 'FULL_REGEXP', 'value': '^' + pattern + '$'}}},
        {'filter': {'fieldName': 'hostName', 'stringFilter': {'matchType': 'EXACT', 'value': 'www.mmoexp.com'}}},
    ]
    if organic:
        filters.append({'filter': {'fieldName': 'sessionDefaultChannelGroup',
                                   'stringFilter': {'matchType': 'EXACT', 'value': 'Organic Search'}}})
    body = {'dateRanges': [{'startDate': start, 'endDate': end}], 'dimensions': [{'name': d} for d in dimensions],
            'metrics': [{'name': m} for m in metrics], 'limit': 50,
            'dimensionFilter': {'andGroup': {'expressions': filters}}}
    result = reader.request('ga4', GA, body)
    empty = not result.get('rows') and not result.get('rowCount') and not result.get('metricHeaders')
    if not empty and ([x['name'] for x in result.get('metricHeaders', [])] != metrics or [x['name'] for x in result.get('dimensionHeaders', [])] != dimensions):
        raise ValueError('INVALID_GOOGLE_RESPONSE')
    rows = [{'dimensions': dict(zip(dimensions, [text(x['value']) for x in row.get('dimensionValues', [])])),
             'metrics': dict(zip(metrics, [number(x['value']) for x in row['metricValues']]))} for row in result.get('rows', [])]
    metadata = result.get('metadata', {})
    return {'status': 'available' if rows else 'no_rows', 'rows': rows, 'returnedRows': len(rows), 'totalRows': result.get('rowCount', 0),
            'truncated': result.get('rowCount', 0) > len(rows), 'timezone': metadata.get('timeZone'),
            'quality': {key: metadata.get(key) for key in ('subjectToThresholding', 'dataLossFromOtherRow', 'samplingMetadatas', 'schemaRestrictionResponse')}}


def gsc(reader, start, end, url_pattern, dimensions):
    body = {'startDate': start, 'endDate': end, 'dimensions': dimensions, 'type': 'web', 'dataState': 'final',
            'aggregationType': 'byPage', 'rowLimit': 50,
            'dimensionFilterGroups': [{'filters': [{'dimension': 'page', 'operator': 'includingRegex', 'expression': url_pattern + '$'}]}]}
    result = reader.request('gsc', GSC, body)
    rows = [{'dimensions': dict(zip(dimensions, map(text, row.get('keys', [])))),
             'metrics': {key: number(row[key]) for key in ('clicks', 'impressions', 'ctr', 'position')}} for row in result.get('rows', [])]
    return {'status': 'available' if rows else 'no_rows', 'rows': rows, 'topRowsOnly': bool(dimensions), 'limit': 50}


def collect(request, reader):
    source, start, end, activity = validate(request)
    page, pattern = PAGES[activity]
    url_pattern = r'^https://www[.]mmoexp[.]com' + pattern
    reports, failures, coverage = {}, {}, None
    if source == 'ga4':
        jobs = {'page_total': lambda: ga(reader, start, end, pattern, [], ['screenPageViews', 'activeUsers', 'userEngagementDuration']),
                'landing_total': lambda: ga(reader, start, end, pattern, [], ['sessions', 'engagedSessions', 'bounceRate'], True),
                'daily': lambda: ga(reader, start, end, pattern, ['date'], ['screenPageViews', 'activeUsers']),
                'country': lambda: ga(reader, start, end, pattern, ['country'], ['sessions'], True),
                'device': lambda: ga(reader, start, end, pattern, ['deviceCategory'], ['sessions'], True),
                'channel': lambda: ga(reader, start, end, pattern, ['sessionSourceMedium'], ['sessions'], True),
                'events': lambda: ga(reader, start, end, pattern, ['eventName'], ['eventCount'])}
        if activity == 'mmoexp-carnival':
            jobs['organic_landing_total'] = lambda: ga(reader, start, end, pattern, [], ['sessions'], landing=True, organic=True)
    elif source == 'gsc':
        jobs = {key: (lambda dims=dims: gsc(reader, start, end, url_pattern, dims)) for key, dims in
                [('total', []), ('daily', ['date']), ('query', ['query']), ('country', ['country']), ('device', ['device'])]}
    else:
        def ads():
            account = reader.request('ads', ADS, {'query': 'SELECT customer.id, customer.time_zone, customer.currency_code FROM customer LIMIT 1'}).get('results', [])
            if len(account) != 1 or account[0].get('customer', {}).get('id') != '1430398974':
                raise ValueError('INVALID_GOOGLE_RESPONSE')
            metadata = account[0]['customer']
            ads_pattern = url_pattern + r'([?].*)?$'
            query = "SELECT segments.date, campaign.name, segments.device, metrics.impressions, metrics.clicks, metrics.cost_micros FROM landing_page_view WHERE segments.date BETWEEN '"+start+"' AND '"+end+"' AND landing_page_view.unexpanded_final_url REGEXP_MATCH '"+ads_pattern+"' LIMIT 1001"
            result = reader.request('ads', ADS, {'query': query})
            rows = [{'dimensions': {'date': text(row['segments']['date']), 'campaign': text(row['campaign']['name']), 'device': text(row['segments']['device'])},
                     'metrics': {key: number(row['metrics'].get(key, 0)) for key in ('impressions', 'clicks', 'costMicros')}} for row in result.get('results', [])]
            return {'status': 'available' if rows else 'no_rows', 'rows': rows[:1000], 'truncated': len(rows)>1000 or bool(result.get('nextPageToken')), 'timezone': metadata.get('timeZone'), 'currency': metadata.get('currencyCode')}
        jobs = {'landing': ads}
    for key, job in jobs.items():
        try:
            reports[key] = job()
        except Exception as error:
            reason = str(error)
            failures[key] = reason if re.fullmatch(r'HTTP_\d{3}|INVALID_GOOGLE_RESPONSE', reason) else 'GOOGLE_SOURCE_UNAVAILABLE'
            if reason in ('HTTP_401', 'HTTP_403'):
                break
    if source == 'gsc' and not any(reason in ('HTTP_401', 'HTTP_403') for reason in failures.values()):
        try:
            available = reader.request('gsc', GSC, {'startDate': start, 'endDate': end, 'dimensions': ['date'], 'type': 'web', 'dataState': 'final', 'rowLimit': 31})
            days = sorted({row['keys'][0] for row in available.get('rows', []) if re.fullmatch(r'\d{4}-\d{2}-\d{2}', row['keys'][0])})
            expected = [(date.fromisoformat(start)+timedelta(days=i)).isoformat() for i in range((date.fromisoformat(end)-date.fromisoformat(start)).days+1)]
            coverage = {'availableFinalDates': days, 'missingDates': [day for day in expected if day not in days], 'watermarkBasis': 'property_final_daily_dates'}
        except Exception:
            failures['coverage'] = 'FINAL_DATE_COVERAGE_UNKNOWN'
    return {'source': source, 'status': 'partial' if failures and reports else 'unavailable' if failures else 'available' if any(r['rows'] for r in reports.values()) else 'no_rows',
            'from': start, 'to': end, 'timezone': reports.get('landing', {}).get('timezone') if source == 'ads' else 'Asia/Shanghai' if source == 'ga4' else 'America/Los_Angeles',
            'currency': reports.get('landing', {}).get('currency') if source == 'ads' else None,
            'page': 'https://www.mmoexp.com' + page, 'generatedAt': datetime.now(timezone.utc).isoformat(),
            'reports': reports, 'failures': failures, 'coverage': coverage, 'notAllVisitors': source == 'ga4', 'notOrderAttribution': True}


if __name__ == '__main__':
    reader = None
    try:
        request = json.loads(sys.stdin.read(4096))
        validate(request)
        sys.path.insert(0, '/opt/mmoexp-marketing/details')
        from collect_details import Reader
        reader = Reader()
        print(json.dumps(collect(request, reader), allow_nan=False))
    except Exception:
        print(json.dumps({'status': 'unavailable', 'reason': 'GOOGLE_READER_FAILED'}))
    finally:
        if reader:
            reader.close()
