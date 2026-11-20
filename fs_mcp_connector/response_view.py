"""Display already-authorized, credential-filtered data without truncating business values."""
import json
import re

from .backend import BackendError
from .catalog import ValidationError

MAX_BYTES = 15000
CONTEXT_FIELDS = ('normalisedScope', 'filters', 'system', 'currency', 'timezone',
                  'status', 'state', 'complete', 'partial', 'coverage', 'source', 'sources',
                  'query', 'archive', 'period',
                  'snapshot_id', 'snapshotId', 'generated_at', 'generatedAt', 'observed_at',
                  'as_of', 'cursor', 'next_cursor', 'retryAfter', 'retry_after', 'stale',
                  'live_non_snapshot', 'consistentPeriod', 'supplementStatus',
                  'scope', 'semantics', 'requested_scope', 'effective_scope', 'coverage_scope',
                  'source_timezone', 'time_basis', 'order_profit_source', 'revisions', 'captured_at',
                  'snapshot_sha256', 'next_offset', 'meta')


def _size(value):
    return len(json.dumps(value, ensure_ascii=False).encode('utf-8'))


def _path(parent, key):
    return parent + '/' + str(key).replace('~', '~0').replace('/', '~1')


def _field(path, value):
    kind = ('object' if isinstance(value, dict) else 'array' if isinstance(value, list)
            else 'null' if value is None else 'boolean' if isinstance(value, bool)
            else 'string' if isinstance(value, str) else 'number')
    return dict(data_path=path, type=kind, bytes=_size(value),
                **({'length': len(value)} if isinstance(value, (dict, list)) else {}))


def present(result, data_path='', offset=None, limit=None):
    if (not isinstance(data_path, str) or len(data_path) > 1024
            or data_path and not data_path.startswith('/') or re.search(r'~(?:[^01]|$)', data_path)):
        raise ValidationError('invalid_data_path')
    value = result['data']
    ancestors = [('', value)] if isinstance(value, dict) else []
    current_path = ''
    for token in data_path.split('/')[1:] if data_path else ():
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*', token) and len(token) <= 16 and int(token) < len(value):
            value = value[int(token)]
        else:
            raise ValidationError('unknown_data_path')
        current_path = _path(current_path, token)
        if isinstance(value, dict):
            ancestors.append((current_path, value))
    if offset is not None and (type(offset) is not int or offset < 0):
        raise ValidationError('invalid_display_offset')
    if limit is not None and (type(limit) is not int or not 1 <= limit <= 20):
        raise ValidationError('invalid_display_limit')
    if (offset is not None or limit is not None) and not isinstance(value, list):
        raise ValidationError('display_pagination_requires_array')
    if not data_path and offset is None and limit is None and _size(result) <= MAX_BYTES:
        return result

    context, context_index = {}, []
    for ancestor_path, ancestor in ancestors:
        fields = CONTEXT_FIELDS
        if (not ancestor_path and result.get('operation') == 'business.fc_project_review'
                and 'archivedAt' in ancestor and 'packets' in ancestor):
            fields = ('revision', 'archivedAt') + fields
        for key in fields:
            if key in ancestor:
                item = ancestor[key]
                metadata = {**context.get(ancestor_path, {}), key: item}
                if _size({**context, ancestor_path: metadata}) <= 3000:
                    context[ancestor_path] = metadata
                else:
                    context_index.append(_field(_path(ancestor_path, key), item))
    base = {**result, 'data_context': context}
    if context_index:
        base['data_context_index'] = context_index

    def response(data, kind, complete, **paging):
        return {**base, 'data': data, 'response_view': dict(
            kind=kind, data_path=data_path, value_complete=complete, **paging)}

    if isinstance(value, list):
        start, count = offset or 0, 20 if limit is None else limit
        if start >= len(value) and (start != 0 or value):
            raise ValidationError('invalid_display_offset')
        end = min(len(value), start + count)
        def page():
            return response(value[start:end], 'page', start == 0 and end == len(value),
                            offset=start, limit=count, total=len(value),
                            next_offset=end if end < len(value) else None)
        selected = page()
        while _size(selected) > MAX_BYTES and end - start > 1:
            end -= 1
            selected = page()
        if _size(selected) > MAX_BYTES:
            selected = response({'fields': [_field(_path(data_path, i), value[i]) for i in range(start, end)]},
                                'index', False, offset=start, total=len(value),
                                next_offset=end if end < len(value) else None)
    else:
        selected = response(value, 'selection', True)
        if _size(selected) > MAX_BYTES and isinstance(value, dict):
            selected = response({'fields': [_field(_path(data_path, key), child) for key, child in value.items()]},
                                'index', False)
    if _size(selected) > MAX_BYTES:
        error = BackendError('response_too_large', 502)
        error.display_result = {**response(None, 'error', False), 'error': 'response_too_large'}
        raise error
    return selected
