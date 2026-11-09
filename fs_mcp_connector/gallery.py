"""Project audited fields from the existing FC gallery GET /api/state response."""
from .redaction import redact


class GalleryError(ValueError):
    code = 'unexpected_gallery_shape'


PLATFORMS = {platform: None for platform in ('PS', 'XBOX', 'PC')}
RATE_FIELDS = dict.fromkeys(('package_usd', 'base_k', 'bonus_k', 'usd_per_k', 'sku_id',
                            'checked_at', 'source', 'status'))
PLAN_FIELDS = dict.fromkeys(('package', 'platform', 'product_id', 'before', 'after', 'hours',
                            'protected_hash', 'keyword_before', 'changed'))
LATEST_FIELDS = {
    **dict.fromkeys(('checked_at', 'scope', 'revision', 'applied_at')),
    'rates': {platform: RATE_FIELDS for platform in PLATFORMS},
    'quote': {
        'prices': {kind: PLATFORMS for kind in ('your', 'provided')},
        'details': [{
            'label': None, 'service_usd': None,
            'platforms': {platform: dict.fromkeys(('your', 'provided', 'coins_usd')) for platform in PLATFORMS},
        }],
        'levels': None, 'business_hash': None,
    },
    'targets': [dict.fromkeys(('package', 'platform', 'product_id', 'model_id', 'site_id',
                              'title', 'levels', 'prices', 'hours'))],
    'plan': [PLAN_FIELDS],
}
STATE_FIELDS = {
    'config': {
        **dict.fromkeys(('revision', 'updated_at', 'actor', 'pause_reason')),
        'settings': {
            **dict.fromkeys(('enabled', 'interval_minutes', 'margin_percent', 'cny_per_usd')),
            'tiers': [dict.fromkeys(('label', 'cost_cny', 'coins_k', 'bonus_min_k', 'bonus_max_k'))],
        },
        'source': dict.fromkeys(('file_name', 'sheet', 'sha256', 'imported_date', 'scope')),
    },
    'latest': LATEST_FIELDS,
    'jobs': [{
        **dict.fromkeys(('id', 'kind', 'actor', 'revision', 'scope', 'created_at', 'status', 'finished_at')),
        'view': LATEST_FIELDS, 'steps': [{**PLAN_FIELDS, 'status': None}],
    }],
    'blocked': None, 'writer': None, 'server_time': None,
    'schedule': dict.fromkeys(('last_start_epoch', 'last_start_at')),
}


def _project(value, fields):
    if fields is None:
        if type(value) not in (str, int, float, bool, type(None)):
            raise GalleryError('unexpected_gallery_shape')
        return redact(value) if isinstance(value, str) else value
    if isinstance(fields, list):
        if not isinstance(value, list):
            raise GalleryError('unexpected_gallery_shape')
        return [_project(item, fields[0]) for item in value]
    if not isinstance(value, dict):
        raise GalleryError('unexpected_gallery_shape')
    return {key: _project(value[key], child) for key, child in fields.items() if key in value}


def project_gallery_state(value):
    """Keep original amounts, source metadata and states; do not calculate, collect or write."""
    return _project(value, STATE_FIELDS)
