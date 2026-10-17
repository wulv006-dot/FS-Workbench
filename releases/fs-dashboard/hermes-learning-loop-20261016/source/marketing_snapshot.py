"""Read the existing published marketing snapshot; never collect or export raw rows."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import re
from report_tracks import fc27_match_basis
from urllib.parse import urlsplit

PUBLISHED = Path('/var/www/mmoexp-marketing/current/data.json')
LIMIT = 8 * 1024 * 1024
SOURCE = {'ga4': ('541418940', 'Asia/Shanghai'), 'gsc': ('sc-domain:mmoexp.com', 'America/Los_Angeles')}
METRICS = {
    'ga4': ('sessions', 'activeUsers', 'newUsers', 'engagedSessions', 'engagementRate', 'screenPageViews', 'averageSessionDuration', 'bounceRate', 'ecommercePurchases', 'purchaseRevenue'),
    'gsc': ('clicks', 'impressions', 'ctr', 'position'),
    'ads': ('impressions', 'clicks', 'cost', 'conversions', 'conversionsValue', 'cpc', 'cpa', 'platformRoas'),
}


def checked_query(args):
    if not isinstance(args, dict) or set(args) != {'profile', 'start', 'end'} or args['profile'] != 'FC27':
        raise ValueError('marketing_fields')
    lo, hi = date.fromisoformat(args['start']), date.fromisoformat(args['end'])
    if lo.isoformat() != args['start'] or hi.isoformat() != args['end'] or hi < lo or (hi-lo).days > 365:
        raise ValueError('marketing_period')
    return args


def number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        result = Decimal(str(value))
        return format(result, 'f') if result.is_finite() and abs(result) <= Decimal('1e20') else None
    except InvalidOperation:
        return None


def metrics(value, source):
    return {key: number(value.get(key)) for key in METRICS[source]} if isinstance(value, dict) else None


def stamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.isoformat() if parsed.tzinfo else None
    except (ValueError, AttributeError, TypeError):
        return None


def coverage(value):
    value = value if isinstance(value, dict) else {}
    out = {}
    for key in ('complete_dates', 'query_range_complete', 'zero_rows_materialized', 'zero_metric_rows_omitted_by_api'):
        if type(value.get(key)) is bool:
            out[key] = value[key]
    for key in ('returned_days', 'requested_days'):
        if type(value.get(key)) is int and value[key] >= 0:
            out[key] = value[key]
    for key in ('requested_start', 'requested_end', 'latest_data_date'):
        if isinstance(value.get(key), str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value[key]):
            out[key] = value[key]
    for key in ('missing_dates', 'no_metric_row_dates'):
        if isinstance(value.get(key), list):
            out[key] = [v for v in value[key] if isinstance(v, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', v)]
    return out


def source_status(value):
    value = value if isinstance(value, dict) else {}
    quality = value.get('quality') or {}
    return {'status': value.get('status') if value.get('status') in ('success', 'failed', 'empty', 'not_collected') else 'unknown',
            'collected_at': stamp(value.get('collected_at')), 'last_attempt_at': stamp(value.get('last_attempt_at')),
            'retained_previous': value.get('retained_previous') is True,
            'quality': {**{key: quality[key] for key in ('pagination_complete', 'pagination_capped', 'subject_to_thresholding', 'sampling_present', 'data_loss_from_other_row') if type(quality.get(key)) is bool},
                        'active_metric_restrictions': bool(quality.get('active_metric_restrictions')),
                        'data_state': quality.get('data_state') if quality.get('data_state') in ('final', 'provisional', 'provisional_ads_attribution') else None}}


def country_table(table, source):
    table = table if isinstance(table, dict) else {}
    rows = []
    rejected = 0
    for row in table.get('rows', [])[:100]:
        country = row.get('dimensions', {}).get('country')
        if not isinstance(country, str) or not 1 <= len(country) <= 80 or not (country in ('(not set)', '(unknown)', 'unknown', 'xxx') or re.fullmatch(r"[^\W\d_]+(?:[ .()'-][^\W\d_]+)*", country)):
            rejected += 1
            continue
        rows.append({'country': country, 'metrics': metrics(row.get('metrics'), source)})
    return {'rows': rows, 'status': source_status(table.get('status')), 'row_coverage': number(table.get('row_coverage')),
            'returned_dimension_rows': table.get('returned_dimension_rows') if type(table.get('returned_dimension_rows')) is int else None,
            'displayed_rows': len(rows), 'rejected_rows': rejected, 'output_capped': len(table.get('rows', [])) > 100,
            'rule': 'Published top-country table only; omitted countries are not zero. GA4 country names and GSC country codes are not joined.'}


def public_label(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 160 or re.search(r'[@<>\r\n]|https?://|Bearer|Cookie|password|passwd|密码|密钥', value, re.I):
        return None
    return value


def source_medium_table(table):
    table = table if isinstance(table, dict) else {}
    rows, rejected = [], 0
    for row in table.get('rows', [])[:30]:
        label = public_label(row.get('dimensions', {}).get('sessionSourceMedium'))
        if label is None:
            rejected += 1
            continue
        rows.append({'source_medium': label, 'metrics': metrics(row.get('metrics'), 'ga4'), 'share': number((row.get('metrics') or {}).get('share'))})
    return {'rows': rows, 'status': source_status(table.get('status')), 'row_coverage': number(table.get('row_coverage')),
            'returned_dimension_rows': table.get('returned_dimension_rows') if type(table.get('returned_dimension_rows')) is int else None,
            'displayed_rows': len(rows), 'rejected_rows': rejected, 'output_capped': len(table.get('rows', [])) > 30,
            'rule': 'Whole-site GA4 session source/medium top rows, not paid-order attribution or a cause of FC sales changes.'}


def campaigns(value):
    rows, rejected = [], 0
    for row in (value.get('campaigns') or [])[:30]:
        ident = str(row.get('campaignId', ''))
        if row.get('customerId') != '1430398974' or not re.fullmatch(r'\d{1,20}', ident) or row.get('currency') != 'USD' or row.get('timezone') != 'Asia/Hong_Kong':
            rejected += 1
            continue
        rows.append({'campaign_id': ident, 'campaign_name': public_label(row.get('campaignName')),
                     'channel_type': row.get('channelType') if row.get('channelType') in ('SEARCH', 'DISPLAY', 'SHOPPING', 'VIDEO', 'MULTI_CHANNEL', 'LOCAL', 'SMART', 'PERFORMANCE_MAX', 'DISCOVERY', 'TRAVEL', 'DEMAND_GEN', 'UNKNOWN', 'UNSPECIFIED') else None,
                     'status': row.get('status') if row.get('status') in ('ENABLED', 'PAUSED', 'REMOVED', 'UNKNOWN', 'UNSPECIFIED') else None,
                     'metrics': metrics(row.get('metrics'), 'ads'),
                     'dates': [day for day in row.get('dates', []) if isinstance(day, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', day)]})
    return {'rows': rows, 'status': source_status(value.get('campaign_status')), 'rejected_rows': rejected,
            'source_campaign_count': value.get('campaign_count') if type(value.get('campaign_count')) is int else None,
            'row_cost_coverage': number(value.get('campaign_row_cost_coverage')), 'output_capped': len(value.get('campaigns') or []) > 30,
            'rule': 'Published MMOEXP campaign aggregates. User-confirmed FC27/Coins name rules classify FC-project spending; labels do not prove geographic targeting or order-level causality. Preserve missing campaign status and partial rows.'}


def projection(model, args, source_sha):
    checked_query(args)
    if model.get('schemaVersion') != 1 or model.get('isMock') is not False:
        raise ValueError('marketing_source_contract')
    details = model.get('details') or {}
    if details and (details.get('schemaVersion') != 1 or details.get('isMock') is not False):
        raise ValueError('marketing_detail_contract')
    base = {'contract': 'fc-marketing-read-v1', 'http_status': 200, 'status': 'partial', 'query': dict(args),
            'captured_at': stamp(model.get('data_generated_at')), 'read_at': datetime.now(timezone.utc).isoformat(),
            'source_snapshot_id': 'marketing_' + source_sha, 'source_sha256': source_sha,
            'scope': 'MMOEXP whole-site background with user-confirmed FC27/Coins name selection; no order/customer join',
            'sources': {}, 'ads_accounts': [], 'ads_geography': {'status': 'not_available', 'reason': 'existing_published_collector_has_no_geography_report'},
            'rule': 'Source timezones differ. Sessions/users/purchases are not paid orders, newUsers are not first buyers, purchaseRevenue and Ads conversion value are not financial revenue. Do not infer market acquisition or fulfillment causes from separate marginal tables.'}
    found = [p for p in details.get('periods', []) if p.get('start') == args['start'] and p.get('end') == args['end']]
    if not found:
        base.update(status='not_available', reason='exact_marketing_period_not_published',
                    available_periods=[{'start': p['start'], 'end': p['end']} for p in details.get('periods', []) if isinstance(p.get('start'), str) and isinstance(p.get('end'), str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', p['start']) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', p['end'])][:16])
        return base
    if len(found) != 1:
        raise ValueError('marketing_duplicate_period')
    current = found[0]
    for source, (resource, tz) in SOURCE.items():
        value = current.get('sources', {}).get(source)
        if not isinstance(value, dict):
            base['sources'][source] = {'status': 'not_available', 'reason': 'source_period_missing'}
            continue
        if value.get('resource') != resource or value.get('timezone') != tz:
            raise ValueError('marketing_resource_or_timezone')
        base['sources'][source] = {'resource': resource, 'timezone': tz, 'status': source_status(value.get('status')),
                                   'metrics': metrics(value.get('metrics'), source), 'coverage': coverage(value.get('coverage')),
                                   'country': country_table(value.get('breakdowns', {}).get('country'), source)}
        if source == 'ga4':
            base['sources'][source]['source_medium'] = source_medium_table(value.get('breakdowns', {}).get('source_medium'))
        if source == 'gsc':
            selected={}
            for dimension in ('query','page'):
                table=value.get('breakdowns',{}).get(dimension) or {};rows=[]
                for row in table.get('rows',[]):
                    label=(row.get('dimensions') or {}).get(dimension)
                    if not isinstance(label,str):continue
                    if dimension=='page':
                        try:parsed=urlsplit(label)
                        except ValueError:continue
                        label=parsed.path if parsed.scheme=='https' and parsed.hostname in ('mmoexp.com','www.mmoexp.com') else None
                    label=public_label(label)
                    basis=fc27_match_basis(label)
                    if label and basis:rows.append({'label':label,'match_basis':basis,'metrics':metrics(row.get('metrics'),'gsc')})
                selected[dimension]={'rows':rows,'status':source_status(table.get('status')),'returned_dimension_rows':table.get('returned_dimension_rows'),
                                     'published_rows':len(table.get('rows',[])),'scope':'已发布Top明细中的FC27/Coins名称匹配项；不是全量搜索词或全站FC流量，缺失不补零。'}
            base['sources'][source]['fc27_name_rows']=selected
    for value in current.get('adsAccounts', []):
        if value.get('customerId') != '1430398974':
            continue
        if base['ads_accounts'] or value.get('brand') != 'mmoexp' or value.get('currency') != 'USD' or value.get('timezone') != 'Asia/Hong_Kong':
            raise ValueError('marketing_ads_scope')
        base['ads_accounts'].append({'customer_id': '1430398974', 'brand': 'mmoexp', 'currency': 'USD', 'timezone': 'Asia/Hong_Kong',
                                     'status': source_status(value.get('status')), 'metrics': metrics(value.get('metrics'), 'ads'),
                                     'coverage': coverage(value.get('coverage')), 'campaigns': campaigns(value)})
    base['reason'] = 'source_coverage_and_country_top_rows_require_review; ads_geography_unavailable'
    return base


class MarketingReader:
    def __call__(self, args):
        checked_query(args)
        try:
            with PUBLISHED.open('rb') as stream:
                raw = stream.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError('marketing_size')
            return projection(json.loads(raw), args, sha256(raw).hexdigest())
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return {'http_status': 503, 'status': 'not_available', 'reason': 'published_marketing_unavailable'}
