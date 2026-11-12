"""Export-only supervised child. No arbitrary paths or credential handling."""
import base64
import datetime
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from admin_live_worker import load_shared, shanghai_today
from admin_email_export_source import FILTERS, METADATA, validate_filters, validate_metadata_args


def handle(value, loader=load_shared, *, today=shanghai_today):
    if not isinstance(value, dict) or set(value) != {'path', 'params', 'max_bytes'} or value['path'] != '/admin/order.Order/index' or type(value['max_bytes']) is not int or not 1 <= value['max_bytes'] <= 1048576:
        raise ValueError('worker_input')
    params, path = value['params'], value['path']
    if not isinstance(params, dict):
        raise ValueError('worker_scope')
    if set(params) == {'metadata', 'arguments', 'page'}:
        name, args = params['metadata'], params['arguments']
        if not validate_metadata_args(name, args) or type(params['page']) is not int or not 1 <= params['page'] <= 100:
            raise ValueError('worker_scope')
        path = METADATA[name][0]
        params = dict(args, page=params['page'], select='true', quick_search='', initKey={'status': 'status', 'countries': 'country'}.get(name, 'id'), initValue='')
    else:
        if type(params.get('page')) is not int or not 1 <= params['page'] <= 100000 or params.get('limit') != 20 or type(params['limit']) is not int or params.get('order') != 'id,desc':
            raise ValueError('worker_scope')
        terms, expected = [], {'page', 'limit', 'order'}
        operators = dict(FILTERS, site_id='=', gid='=', paytime='RANGE')
        for i in range(14):
            prefix = 'search[%d]' % i
            if prefix + '[field]' not in params:
                break
            field, operator, val = [params[prefix + '[' + k + ']'] for k in ('field', 'operator', 'val')]
            if field in dict(terms) or field not in operators or operator != operators[field]:
                raise ValueError('worker_scope')
            terms.append((field, val))
            expected.update(prefix + '[' + k + ']' for k in ('field', 'operator', 'val'))
            if field == 'paytime':
                expected.add(prefix + '[render]')
                if params.get(prefix + '[render]') != 'datetime':
                    raise ValueError('worker_scope')
        fields = dict(terms)
        if set(params) != expected or not {'site_id', 'gid', 'paytime'} <= fields.keys():
            raise ValueError('worker_scope')
        for key in ('site_id', 'gid'):
            v = fields[key]
            if not isinstance(v, str) or not v.isascii() or not v.isdigit() or not 1 <= len(v) <= 20:
                raise ValueError('worker_scope')
        validate_filters({k: v for k, v in terms if k in FILTERS})
        period = fields['paytime']
        if not isinstance(period, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2} 00:00:00,[0-9]{4}-[0-9]{2}-[0-9]{2} 23:59:59', period):
            raise ValueError('worker_dates')
        start, end = datetime.date.fromisoformat(period[:10]), datetime.date.fromisoformat(period[20:30])
        def check_dates():
            current = today()
            if not 0 <= (end - start).days < 28 or start < current - datetime.timedelta(days=365) or end > current:
                raise ValueError('worker_dates')
        check_dates()
    shared = loader()
    session = shared.SessionManager({})
    base = shared.api_base(session.config)
    if base != 'http://127.0.0.1:8912' or base not in shared.API_BASES:
        raise ValueError('worker_proxy')
    query = urlencode(params)
    if len(query) > 8192:
        raise ValueError('worker_query')
    if path == '/admin/order.Order/index':
        check_dates()
    request = Request(base + path + '?' + query, headers=dict(shared.HEADERS), method='GET')
    try:
        with session.opener.open(request, timeout=10) as response:
            status, body = response.status, response.read(value['max_bytes'] + 1)
    except HTTPError as error:
        try:
            status, body = error.code, b''
        finally:
            error.close()
    if type(status) is not int or not 100 <= status <= 599 or not isinstance(body, bytes):
        raise ValueError('worker_response')
    if len(body) > value['max_bytes']:
        return {'error': 'source_response_too_large'}
    return {'status': status, 'body': base64.b64encode(body).decode('ascii')}


def main():
    if os.name != 'posix' or os.geteuid() != 0:
        raise SystemExit(1)
    try:
        raw = sys.stdin.buffer.read(8193)
        if len(raw) > 8192:
            raise ValueError('input_too_large')
        sys.stdout.write(json.dumps(handle(json.loads(raw)), separators=(',', ':')))
        sys.stdout.flush()
    except Exception:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
