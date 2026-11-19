"""Private, read-only email export. No files, mail delivery or PII logging.

Completeness means exhausted live pagination, not a point-in-time snapshot.
Unsupported filters fail closed rather than silently broadening an export.
"""
import datetime
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from contextlib import closing

from admin_live_page import valid_customer_email, validate_period, utc_now, LivePageError
from admin_email_export_source import validate_filters

MAX_PAGES = 1000
MAX_SECONDS = 45
MAX_EXPORT_BYTES = 1048576


BUYER_ARCHIVE = Path('/var/lib/fs-user-analytics/email-export-20261119/candidates.sqlite3')
BUYER_ID = re.compile(r'[0-9a-fA-F]{32}')


def lookup_buyer_emails(request, user, *, authorize=None):
    """Read the private all-site export index using the order-email ACL."""
    if not user:
        return 401, {'error': 'login_required'}
    if authorize is None:
        from user_runtime import authorize
    scope = {'scope': 'all'}
    if authorize(user, scope, True) is not True:
        return 403, {'error': 'scope_denied'}
    values = request.get('buyer_ids') if isinstance(request, dict) and set(request) == {'buyer_ids'} else None
    if not isinstance(values, list) or not 1 <= len(values) <= 50 or any(
            not isinstance(value, str) or not BUYER_ID.fullmatch(value) for value in values):
        return 422, {'error': 'invalid_buyer_ids'}
    ids = list(dict.fromkeys(value.lower() for value in values))
    try:
        info = BUYER_ARCHIVE.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (
                os.name == 'posix' and (info.st_uid != os.geteuid() or info.st_mode & 0o077)):
            raise ValueError('unsafe_buyer_archive')
        placeholders = ','.join('?' for _ in ids)
        with closing(sqlite3.connect(BUYER_ARCHIVE.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            rows = dict(db.execute('SELECT buyer,email FROM mapping WHERE buyer IN (' + placeholders + ')', ids))
        if any(not valid_customer_email(email) for email in rows.values()):
            raise ValueError('invalid_archived_email')
    except (OSError, sqlite3.Error, ValueError):
        return 503, {'error': 'buyer_email_archive_unavailable'}
    if authorize(user, scope, True) is not True:
        return 403, {'error': 'scope_denied'}
    items = []
    for buyer in ids:
        item = {'buyer_id': buyer, 'status': 'not_found_in_archive'}
        if buyer in rows:
            item.update(status='found', email=rows[buyer])
        items.append(item)
    return 200, {'items': items, 'matched': len(rows),
                 'period': {'start': '2026-01-01', 'end_exclusive': '2026-11-19', 'timezone': 'Asia/Shanghai'},
                 'scope': {'archive': 'order_email_export_20261119', 'progress': '10',
                           'excluded_games': ['RS', 'Diablo 4', 'Diablo II: Resurrected']}}


def parse_page_body(raw, *, observed_at=utc_now):
    """One source window; the source cursor is opaque and has no resume guarantee."""
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 4096:
        raise ValueError('invalid_export_request')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate_field')
            value[key] = item
        return value
    value = json.loads(raw.decode('utf8'), object_pairs_hook=unique)
    required = {'site_id', 'game_id', 'start', 'end_exclusive'}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {'filters', 'cursor'}:
        raise ValueError('invalid_export_request')
    if any(not isinstance(value[k], str) or not value[k].isascii() or not value[k].isdigit() or len(value[k]) > 20 for k in ('site_id', 'game_id')):
        raise ValueError('invalid_export_request')
    if not isinstance(value.get('filters', {}), dict):
        raise ValueError('invalid_export_request')
    validate_filters(value.get('filters', {}))
    if 'cursor' in value and (not isinstance(value['cursor'], str) or not 1 <= len(value['cursor']) <= 1024):
        raise ValueError('invalid_export_request')
    try:
        validate_period(value, observed_at)
    except LivePageError:
        raise ValueError('invalid_export_request') from None
    return value


def page_get(request, user, *, run_source=None):
    """Project exactly one authorized live page without storing PII or cursors."""
    import sys
    from admin_email_export_source import get as live_get
    if not user:
        return 401, {'error': 'login_required', 'complete': False}
    try:
        request = parse_page_body(json.dumps(request).encode('utf8'))
    except (ValueError, TypeError, UnicodeError):
        return 422, {'error': 'invalid_export_request', 'complete': False}
    try:
        sys.path.insert(0, '/opt/fs-access-policy')
        from user_runtime import authorize
        scope = {k: request[k] for k in ('site_id', 'game_id')}
        period = {k: request[k] for k in ('start', 'end_exclusive')}
        if authorize(user, {'scope': 'site', 'scope_id': request['site_id']}, True) is not True:
            return 403, {'error': 'scope_denied', 'complete': False}
        query = {k: [v] for k, v in request.items()}
        status, result = live_get(query, user, run_source=run_source)
        if type(status) is not int or not isinstance(result, dict):
            raise ValueError()
        if status != 206:
            failure = {'error': result.get('error', 'export_source_incomplete'), 'complete': False}
            if 'retryAfter' in result:
                failure['retryAfter'] = result['retryAfter']
            return status if status >= 400 else 503, failure
        if (result['complete'] is not False or result['status'] != 'partial'
                or result['semantics'] != 'live_non_snapshot'
                or result['limitation'] != 'live_pagination_not_snapshot'
                or result['scope'] != scope or result['period'] != period
                or result['timezone'] != 'Asia/Shanghai'):
            raise ValueError()
        at = result['observed_at']
        if not isinstance(at, str) or datetime.datetime.fromisoformat(at.replace('Z', '+00:00')).utcoffset() is None:
            raise ValueError()
        rows, total, count, cursor = (result[k] for k in ('data', 'source_reported_total', 'observed_page_rows', 'next_cursor'))
        if (not isinstance(rows, list) or type(total) is not int or total < 0
                or type(count) is not int or count != len(rows) or not 0 <= count <= min(20, total)
                or (not rows and total != 0)
                or (cursor is not None and (not isinstance(cursor, str) or not 1 <= len(cursor) <= 1024
                    or count != 20 or count >= total or cursor == request.get('cursor')))
                or ('cursor' not in request and cursor is None and count != total)):
            raise ValueError()
        data = []
        seen = set()
        for row in rows:
            ident, email = row['order_id'], row['customer_email']
            if not isinstance(ident, str) or not ident.isascii() or not ident.isdigit() or len(ident) > 20 or int(ident) <= 0 or ident in seen:
                raise ValueError()
            seen.add(ident)
            if email is not None:
                if not isinstance(email, str) or len(email) > 320:
                    raise ValueError()
                email = email.strip() or None
                if email is not None and not valid_customer_email(email):
                    raise ValueError()
            data.append(dict(order_id=ident, email=email, email_key=email.casefold() if email else None))
        return 206, dict(status='partial', complete=False, semantics='live_non_snapshot',
                         limitation='live_pagination_not_snapshot', scope=scope, period=period, filters=request.get('filters', {}),
                         date_field='paytime', timezone='Asia/Shanghai', email_field='user_email',
                         deduplication='trim_casefold', observed_at=at, source_reported_total=total,
                         observed_page_rows=count, data=data, next_cursor=cursor)
    except (KeyError, TypeError, ValueError, OverflowError):
        return 503, {'error': 'export_source_schema_changed', 'complete': False}
    except Exception:
        return 503, {'error': 'export_source_unavailable', 'complete': False}


def parse_body(raw):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 4096:
        raise ValueError('invalid_export_request')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate_field')
            value[key] = item
        return value
    value = json.loads(raw.decode('utf8'), object_pairs_hook=unique)
    required = {'site_id', 'game_ids', 'start', 'end_exclusive'}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {'filters'}:
        raise ValueError('invalid_export_request')
    if not isinstance(value['site_id'], str) or not value['site_id'].isascii() or not value['site_id'].isdigit() or len(value['site_id']) > 20:
        raise ValueError('invalid_export_request')
    games = value['game_ids']
    if not isinstance(games, list) or not 1 <= len(games) <= 100 or any(not isinstance(g, str) or not g.isascii() or not g.isdigit() or len(g) > 20 for g in games) or len(set(games)) != len(games):
        raise ValueError('invalid_export_request')
    if not isinstance(value.get('filters', {}), dict):
        raise ValueError('invalid_export_request')
    validate_filters(value.get('filters', {}))
    return value


def collect(request, user, *, page_get, observed_at=utc_now, clock=time.monotonic):
    if not user:
        return 401, {'error': 'login_required', 'complete': False}
    try:
        request = parse_body(json.dumps(request).encode('utf8'))
        start = datetime.date.fromisoformat(request['start'])
        end = datetime.date.fromisoformat(request['end_exclusive'])
        if start.isoformat() != request['start'] or end.isoformat() != request['end_exclusive'] or not 0 < (end - start).days <= 366:
            raise ValueError()
        windows = []
        while start < end:
            stop = min(end, start + datetime.timedelta(days=28))
            window = dict(start=start.isoformat(), end_exclusive=stop.isoformat())
            validate_period(window, observed_at)
            windows.append(window)
            start = stop
    except (ValueError, TypeError, KeyError, LivePageError):
        return 422, {'error': 'invalid_export_request', 'complete': False}
    started = clock()
    emails = {}
    seen_orders = set()
    pages = missing = email_bytes = 0
    for game in request['game_ids']:
        for window in windows:
            query = dict(site_id=[request['site_id']], game_id=[game], filters=[request.get('filters', {})], **{k: [v] for k, v in window.items()})
            total = None
            count = 0
            cursors = set()
            while True:
                if pages >= MAX_PAGES or clock() - started >= MAX_SECONDS:
                    return 503, {'error': 'export_budget_exceeded', 'complete': False}
                status, result = page_get(query, user)
                pages += 1
                if status != 206:
                    return status if status >= 400 else 503, {'error': result.get('error', 'export_source_incomplete'), 'complete': False}
                try:
                    if clock() - started >= MAX_SECONDS:
                        raise LivePageError('export_budget_exceeded')
                    if result['semantics'] != 'live_non_snapshot' or result['limitation'] != 'live_pagination_not_snapshot':
                        raise LivePageError('export_source_incomplete')
                    current_total = result['source_reported_total']
                    if type(current_total) is not int or current_total < 0 or total is not None and total != current_total:
                        raise LivePageError('source_changed_restart_required')
                    total = current_total
                    rows = result['data']
                    if not isinstance(rows, list) or len(rows) > 20:
                        raise ValueError()
                    for row in rows:
                        ident = row['order_id']
                        if not isinstance(ident, str) or ident in seen_orders:
                            raise LivePageError('source_changed_restart_required')
                        seen_orders.add(ident)
                        email = row['customer_email']
                        if email is None or email == '':
                            missing += 1
                        elif not valid_customer_email(email):
                            raise ValueError()
                        else:
                            normalized = email.strip().casefold()
                            if normalized not in emails:
                                emails[normalized] = email.strip()
                                email_bytes += len(emails[normalized].encode('utf8')) + 4
                            if email_bytes > MAX_EXPORT_BYTES - 4096:
                                raise LivePageError('export_response_too_large')
                    count += len(rows)
                    cursor = result['next_cursor']
                    if cursor is None:
                        if count != total:
                            raise LivePageError('export_source_incomplete')
                        break
                    if not isinstance(cursor, str) or cursor in cursors or not rows or count >= total:
                        raise LivePageError('source_changed_restart_required')
                    cursors.add(cursor)
                    query['cursor'] = [cursor]
                except LivePageError as error:
                    return 409 if 'changed' in error.code else 503, {'error': error.code, 'complete': False}
                except (KeyError, TypeError, ValueError):
                    return 503, {'error': 'export_source_schema_changed', 'complete': False}
    payload = dict(status='available', complete=True, filters=request.get('filters', {}), semantics='live_non_snapshot', emails=[emails[key] for key in sorted(emails)], unique_emails=len(emails), observed_orders=len(seen_orders), missing_email_orders=missing, observed_at=observed_at(), period={k: request[k] for k in ('start', 'end_exclusive')}, scope={k: request[k] for k in ('site_id', 'game_ids')}, email_field='user_email', deduplication='trim_casefold', limitation='live_pagination_not_snapshot')
    # Bound the complete JSON envelope, including escaping, not just raw addresses.
    # ASCII-escaped standard JSON is a conservative bound for the HTTP encoder.
    if len(json.dumps(payload, ensure_ascii=True).encode('utf8')) > MAX_EXPORT_BYTES:
        return 503, {'error': 'export_response_too_large', 'complete': False}
    return 200, payload


def get(request, user, *, run_source=None):
    import sys
    from admin_email_export_source import get as live_get
    if not user:
        return 401, {'error': 'login_required', 'complete': False}
    try:
        request = parse_body(json.dumps(request).encode('utf8'))
        sys.path.insert(0, '/opt/fs-access-policy')
        from user_runtime import authorize
        def page_get(params, actor):
            scope = {'scope': 'site', 'scope_id': request['site_id']}
            if authorize(actor, scope, True) is not True:
                return 403, {'error': 'scope_denied'}
            return live_get(params, actor, run_source=run_source)
        return collect(request, user, page_get=page_get)
    except (ValueError, TypeError, UnicodeError):
        return 422, {'error': 'invalid_export_request', 'complete': False}
    except Exception:
        return 503, {'error': 'export_source_unavailable', 'complete': False}
