"""Read the known Evolutions business state, excluding backend payload/error bodies."""
from copy import deepcopy

from .redaction import redact

from .backend import BackendError


MODEL_FIELDS = ('id', 'gid', 'cid', 'title', 'unit', 'status', 'sku_switch', 'attr_switch')
PRODUCT_FIELDS = ('id', 'gid', 'cid', 'mid', 'aid', 'site_id', 'sid', 'top_cid', 'title',
                  'price', 'unit_price', 'discount', 'status', 'unit', 'num', 'sku_switch', 'attr_switch')
ROW_FIELDS = ('model_id', 'product_id', 'cid', 'title', 'platform', 'coins', 'model_coins',
              'premium', 'rate', 'current', 'enabled', 'fixed', 'target')
BUSINESS_ERRORS = {'ALL三平台产品缺失或重复', '模型或产品已禁用', '数值不能是开关',
                   '数值无效', '数值超出范围', '目标售价不足一美分'}


def _pick(value, fields):
    if not isinstance(value, dict):
        raise BackendError('unexpected_evolutions_shape', 502)
    return {key: deepcopy(value[key]) for key in fields if key in value}


def _rows(value, fields):
    if not isinstance(value, list):
        raise BackendError('unexpected_evolutions_shape', 502)
    return [_pick(row, fields) for row in value]


def _error(result, source, *, business=False):
    if 'error' not in source:
        return
    error = source['error']
    if error is None or isinstance(error, str) and (not error or business and error in BUSINESS_ERRORS):
        result['error'] = error
    else:
        result.update(error_present=True, error_detail_withheld=True)


def _job(value):
    if value is None:
        return None
    result = _pick(value, ('id', 'action', 'actor', 'at', 'finished_at', 'status', 'cache'))
    if 'results' in value:
        result['results'] = _rows(value['results'], ('product_id', 'action', 'operation_id', 'target'))
        for row, original in zip(result['results'], value['results']):
            _error(row, original, business=True)
    _error(result, value)
    return result


def _redact(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: _redact(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_redact(child) for child in value]
    return value


def project(value):
    result = _pick(value, ('version', 'stale', 'writable', 'blocked', 'cache_pending', 'next_auto_at'))
    result['config'] = _pick(value.get('config'), ('revision', 'automatic', 'premium', 'interval_minutes'))
    config = value['config']
    if 'overrides' in config:
        if not isinstance(config['overrides'], dict):
            raise BackendError('unexpected_evolutions_shape', 502)
        overrides = {}
        for model_id, entry in config['overrides'].items():
            if not isinstance(model_id, str) or not model_id.isascii() or not model_id.isdecimal():
                raise BackendError('unexpected_evolutions_shape', 502)
            overrides[model_id] = _pick(entry, ('enabled', 'coins', 'premium'))
            if 'prices' in entry:
                overrides[model_id]['prices'] = _pick(entry['prices'], ('PS', 'XBOX', 'PC'))
        result['config']['overrides'] = overrides
    snapshot = value.get('snapshot')
    result['snapshot'] = None
    if snapshot is not None:
        result['snapshot'] = _pick(snapshot, ('at',))
        result['snapshot'].update(models=_rows(snapshot.get('models'), MODEL_FIELDS),
            products=_rows(snapshot.get('products'), PRODUCT_FIELDS),
            rates=_pick(snapshot.get('rates'), ('PS', 'XBOX', 'PC')))
    result['rows'] = _rows(value.get('rows'), ROW_FIELDS)
    for row, original in zip(result['rows'], value['rows']):
        _error(row, original, business=True)
    result['job'] = _job(value.get('job'))
    if not isinstance(value.get('history'), list):
        raise BackendError('unexpected_evolutions_shape', 502)
    result['history'] = [_job(job) for job in value['history']]
    result['projection'] = dict(snapshot_fields='known_business_fields', raw_backend_payload=False, raw_error_details=False)
    return _redact(result)
