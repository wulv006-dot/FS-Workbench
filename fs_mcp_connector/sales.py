"""Page the existing sales snapshot without recomputing its business figures."""
import hashlib

from .backend import BackendError
from .redaction import redact


FIELDS = {
    'promoters': ('key', 'name', 'uid', 'source', 'sources', 'codes', 'admin'),
    'owners': ('key', 'name'),
    'codes': ('code', 'owner', 'admin', 'uid', 'discount'),
    'orders': ('order_no', 'order_id', 'email', 'customer_email', 'id', 'day', 'paytime', 'amount_usd', 'before_usd',
        'discount_usd', 'code', 'recommend_uid', 'promoter_key', 'promoter', 'source',
        'owner_key', 'owner', 'admin', 'uid', 'country', 'cc', 'paytype', 'status',
        'pay_status', 'refund', 'is_new', 'area', 'region', 'product', 'region_source',
        'deliv_n', 'qty', 'cost_cny', 'sale_cny', 'profit_cny', 'margin', 'supplier', 'operator'),
}
META = ('start', 'end', 'fetched_at', 'generated_at', 'game', 'admin_gid', 'order_gid',
        'counts', 'date_range', 'orphan_sn')


def _clean(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    return value


def project(value, raw, arguments):
    digest = hashlib.sha256(raw).hexdigest()
    offset, limit = arguments.get('offset', 0), arguments.get('limit', 100)
    expected = arguments.get('snapshot_sha256')
    if offset and not expected:
        raise BackendError('snapshot_required_for_continuation', 422)
    if expected and expected != digest:
        raise BackendError('snapshot_changed_restart_query', 409)
    dataset = arguments['dataset']
    if not isinstance(value, dict) or not isinstance(value.get('meta'), dict):
        raise BackendError('unexpected_sales_shape', 502)
    rows = value.get(dataset)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise BackendError('unexpected_sales_shape', 502)
    selected = [{key: row[key] for key in FIELDS[dataset] if key in row}
                for row in rows[offset:offset+limit]]
    next_offset = offset+len(selected) if offset+len(selected) < len(rows) else None
    return _clean(dict(meta={key: value['meta'][key] for key in META if key in value['meta']},
        dataset=dataset, rows=selected, total=len(rows), offset=offset, next_offset=next_offset,
        snapshot_sha256=digest, complete=next_offset is None, coverage='published_snapshot'))
