"""Classify coupon use without exposing codes or changing order/site attribution."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def mapping():
    raw = Path(__file__).with_name('coupon_channels.json').read_bytes()
    value = json.loads(raw)
    if value.get('contract') != 'coupon-channel-map-v1' or len(value.get('codes', {})) != 373:
        raise ValueError('coupon_mapping_contract')
    if any(not k or not isinstance(v, str) or not v for k, v in value['codes'].items()):
        raise ValueError('coupon_mapping_values')
    return value['codes'], hashlib.sha256(raw).hexdigest()


def classify(row):
    codes, version = mapping()
    if row.get('_coupon_mapping_version') == version:
        channel, match = row.get('_coupon_channel'), row.get('_coupon_match')
        if match in ('matched','unmatched','no_code','not_retained','invalid') and channel in {*codes.values(),'有码未映射','无码','码字段未保留','码字段无效'}:
            return channel, match, version
        raise ValueError('retained_coupon_contract')
    if '折扣码' not in row:
        return '码字段未保留', 'not_retained', version
    raw = row['折扣码']
    if not isinstance(raw, str):
        return '码字段无效', 'invalid', version
    code = raw.strip()
    return (codes[code], 'matched', version) if code in codes else (
        ('有码未映射', 'unmatched', version) if code else ('无码', 'no_code', version))


def retained(row):
    channel, match, version = classify(row)
    return {'_coupon_channel': channel, '_coupon_match': match, '_coupon_mapping_version': version}
