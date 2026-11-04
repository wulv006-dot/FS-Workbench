"""Direct Google reads reuse the existing controlled identity, without weekly limits."""
import datetime as dt
import json
import re
import time
from decimal import InvalidOperation
from urllib.parse import quote

from mmoexp_google_data.details.game_dimensions import PATHS
from .contracts import game, make_daily_context
from .metrics import number


def path_expression(scope, url=True):
    game(scope)
    paths = sorted(re.escape(p) for p, value in PATHS.items() if value == scope)
    prefix = r'https://www\.mmoexp\.com' if url else ''
    return '(?i)^' + prefix + r'/(?:[a-z]{2}/)?(?:' + '|'.join(paths) + r')(?:/|$)'


class SourceError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class GoogleTransport:
    def __init__(self, *, response_emergency_bytes, connect_seconds, idle_seconds, attempts=3,
                 clock=lambda: dt.datetime.now(dt.timezone.utc)):
        if response_emergency_bytes <= 0 or not 0 < attempts <= 10 or min(connect_seconds, idle_seconds) <= 0:
            raise ValueError('INVALID_SOURCE_RUNTIME_CONFIG')
        self.ceiling = response_emergency_bytes
        self.connect, self.idle, self.attempts = connect_seconds, idle_seconds, attempts
        self.clock, self.sessions, self.calls = clock, {}, 0

    def close(self):
        for session in self.sessions.values():
            session.close()

    def __call__(self, kind, url, body=None):
        if kind not in ('gsc', 'ga4'):
            raise ValueError('INVALID_GOOGLE_SOURCE')
        if kind not in self.sessions:
            from mmoexp_google_data.details.collect_details import credential
            self.sessions[kind] = credential(kind)
        for attempt in range(self.attempts):
            context = make_daily_context(self.clock())
            if not context.publication_allowed:
                raise SourceError('NIGHT_DEADLINE')
            remaining = (self.clock().astimezone(dt.timezone(dt.timedelta(hours=8))).replace(hour=6, minute=30, second=0, microsecond=0)
                         - self.clock()).total_seconds()
            self.calls += 1
            response = self.sessions[kind].request('GET' if body is None else 'POST', url, json=body,
                stream=True, allow_redirects=False, timeout=(min(self.connect, remaining), min(self.idle, remaining)))
            try:
                if response.status_code in (401, 403):
                    error = PermissionError('GOOGLE_PERMISSION_DENIED')
                    error.code = 'HTTP_' + str(response.status_code)
                    raise error
                if response.status_code in (429, 500, 502, 503, 504) and attempt + 1 < self.attempts:
                    time.sleep(min(2 ** attempt, max(0, remaining)))
                    continue
                if response.status_code != 200:
                    raise SourceError('HTTP_' + str(response.status_code))
                content = bytearray()
                for chunk in response.iter_content(65536):
                    if len(content) + len(chunk) > self.ceiling:
                        raise SourceError('RESPONSE_EMERGENCY_SIZE')
                    if not make_daily_context(self.clock()).publication_allowed:
                        raise SourceError('NIGHT_DEADLINE')
                    content.extend(chunk)
                result = json.loads(content)
                if not isinstance(result, dict):
                    raise SourceError('INVALID_GOOGLE_RESPONSE')
                return result
            finally:
                response.close()


class GoogleSource:
    def __init__(self, name, request, *, resource, timezone, page_size=1000):
        if name not in ('gsc', 'ga4') or not resource or not 1 <= page_size <= 25000:
            raise ValueError('INVALID_GOOGLE_CONFIG')
        self.name, self.request, self.resource, self.timezone = name, request, resource, timezone
        self.page_size, self.checked = page_size, False
        self.ga_metrics = ('sessions', 'engagedSessions')

    def check_ga(self):
        base = 'https://analyticsdata.googleapis.com/v1beta/properties/' + self.resource
        metadata = self.request('ga4', base + '/metadata')
        dimensions = {d['apiName'] for d in metadata.get('dimensions', [])}
        metrics = {m['apiName'] for m in metadata.get('metrics', [])}
        if not {'date', 'hostName', 'landingPage', 'sessionDefaultChannelGroup'} <= dimensions or not {'sessions', 'engagedSessions'} <= metrics:
            raise SourceError('GA4_REQUIRED_FIELDS_UNAVAILABLE')
        requested = self.ga_metrics + (('ecommercePurchases',) if 'ecommercePurchases' in metrics else ())
        body = dict(dimensions=[dict(name='date')], metrics=[dict(name=x) for x in requested])
        check = self.request('ga4', base + ':checkCompatibility', body)
        dims = {v['dimensionMetadata']['apiName'] for v in check.get('dimensionCompatibilities', []) if v['compatibility'] == 'COMPATIBLE'}
        values = {v['metricMetadata']['apiName'] for v in check.get('metricCompatibilities', []) if v['compatibility'] == 'COMPATIBLE'}
        if 'date' not in dims or not {'sessions', 'engagedSessions'} <= values:
            raise SourceError('GA4_FIELDS_INCOMPATIBLE')
        self.ga_metrics = tuple(x for x in requested if x in values)
        self.checked = True

    def pages(self, scope, day, cursor=0):
        try:
            yield from self._pages(scope, day, cursor)
        except (KeyError, TypeError, InvalidOperation):
            raise SourceError('INVALID_GOOGLE_SCHEMA') from None

    def _pages(self, scope, day, cursor=0):
        game(scope)
        dt.date.fromisoformat(day)
        if self.name == 'ga4' and not self.checked:
            self.check_ga()
        while True:
            if self.name == 'gsc':
                body = dict(startDate=day, endDate=day, dimensions=['date'], type='web', dataState='final',
                            aggregationType='byPage', rowLimit=self.page_size, startRow=cursor,
                            dimensionFilterGroups=[dict(groupType='and', filters=[dict(dimension='page', operator='includingRegex', expression=path_expression(scope))])])
                url = 'https://www.googleapis.com/webmasters/v3/sites/' + quote(self.resource, safe='') + '/searchAnalytics/query'
            else:
                filters = [dict(filter=dict(fieldName='hostName', stringFilter=dict(matchType='EXACT', value='www.mmoexp.com'))),
                           dict(filter=dict(fieldName='sessionDefaultChannelGroup', stringFilter=dict(matchType='EXACT', value='Organic Search'))),
                           dict(filter=dict(fieldName='landingPage', stringFilter=dict(matchType='FULL_REGEXP', value=path_expression(scope, False) + '.*', caseSensitive=False)))]
                body = dict(dateRanges=[dict(startDate=day, endDate=day)], dimensions=[dict(name='date')],
                            metrics=[dict(name=x) for x in self.ga_metrics],
                            dimensionFilter=dict(andGroup=dict(expressions=filters)), returnPropertyQuota=True,
                            offset=cursor, limit=self.page_size)
                url = 'https://analyticsdata.googleapis.com/v1beta/properties/' + self.resource + ':runReport'
            result = self.request(self.name, url, body)
            raw = result.get('rows', [])
            quality = dict(pagination_complete=len(raw) < self.page_size)
            rows = []
            if self.name == 'gsc':
                quality.update(data_state='final', aggregation=result.get('responseAggregationType'))
                for row in raw:
                    if row.get('keys') != [day]:
                        raise SourceError('GOOGLE_SOURCE_DATE_MISMATCH')
                    rows.append(dict(key=day, metrics={n: str(number(row[n])) for n in ('clicks', 'impressions', 'position')}))
                status = 'available' if rows else 'no_rows'
                next_cursor = cursor + len(raw) if len(raw) == self.page_size else None
            else:
                metadata = result.get('metadata', {})
                if metadata.get('timeZone') != self.timezone:
                    raise SourceError('GA4_TIMEZONE_REQUIRES_REBINDING')
                if [d['name'] for d in result.get('dimensionHeaders', [])] != ['date'] or [m['name'] for m in result.get('metricHeaders', [])] != list(self.ga_metrics):
                    raise SourceError('GA4_RESPONSE_HEADERS_MISMATCH')
                quality.update(data_state='provisional', subject_to_thresholding=bool(metadata.get('subjectToThresholding')),
                               sampling_present=bool(metadata.get('samplingMetadatas')), data_loss_from_other_row=bool(metadata.get('dataLossFromOtherRow')),
                               property_quota=result.get('propertyQuota'),
                               purchase_events_status='available' if 'ecommercePurchases' in self.ga_metrics else 'unavailable')
                for row in raw:
                    if [v['value'] for v in row['dimensionValues']] != [day.replace('-', '')]:
                        raise SourceError('GOOGLE_SOURCE_DATE_MISMATCH')
                    if len(row['metricValues']) != len(self.ga_metrics):
                        raise SourceError('GA4_RESPONSE_METRIC_COUNT_MISMATCH')
                    rows.append(dict(key=day, metrics={n: str(number(v['value'])) for n, v in zip(self.ga_metrics, row['metricValues'])}))
                status = 'provisional' if rows else 'no_rows'
                next_cursor = cursor + len(raw) if cursor + len(raw) < result.get('rowCount', 0) else None
                if next_cursor is not None and not raw:
                    raise SourceError('GA4_PAGINATION_NO_PROGRESS')
            yield dict(rows=rows, next_cursor=next_cursor, source_timezone=self.timezone, status=status, quality=quality)
            if next_cursor is None:
                return
            cursor = next_cursor
