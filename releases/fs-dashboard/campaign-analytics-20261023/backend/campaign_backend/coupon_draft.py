"""Verified native coupon create contract, restricted to disabled project validation drafts.

No grant, activation, shared coupon edits or automatic POST retry is implemented.
Routes/fields come from the actual 2026-10-24 Admin frontend and permission readback.
"""
import re
from .core import ContractError


def draft_payload(operation_id, goods_id='170014917'):
    if not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', operation_id):
        raise ContractError('INVALID_OPERATION_ID')
    if str(goods_id) not in ('170014917', '163329311'):
        raise ContractError('PROJECT_PRODUCT_SCOPE_REQUIRED')
    return dict(type=1, title='FS-V3 validation '+operation_id, fetch_scene=4, status=0,
                mode_type=2, attain='0', reduce='90', max_reduce='0', limit_qty=1,
                fetch_qty=0, used_qty=0, repeat_qty=1, time_effect=2, days=1,
                site_id=266, game_id=1327, product_type=2 if str(goods_id)=='170014917' else 1,
                goods_id=int(goods_id), is_open=0, jump_url='', param_code='',
                brief='FS-V3 integration validation only; disabled, no issuance.')


class DisabledCouponDraft:
    enabled = False
    route = '/admin/market.Coupon/add'

    def __init__(self, reader):
        self.reader = reader

    @staticmethod
    def validate(operation_id, payload):
        expected = draft_payload(operation_id, str(payload.get('goods_id', '')))
        if expected != payload:
            raise ContractError('DISABLED_DRAFT_ONLY')

    def _matches(self, payload):
        rows = self.reader.pages('coupons', [('title', '=', payload['title'])], limit=20,
                                 validate=lambda row: row.get('title') == payload['title'])
        if len(rows) != 1:
            return None
        row = rows[0]
        keys = ('title','type','status','fetch_scene','mode_type','site_id','game_id','goods_id','product_type',
                'time_effect','days','limit_qty','repeat_qty','is_open','fetch_qty','used_qty')
        if any(str(row.get(key)) != str(payload[key]) for key in keys):
            return None
        # Decimal formatting may differ on GET ("90.00" vs "90").
        from decimal import Decimal
        if any(Decimal(str(row.get(key))) != Decimal(payload[key]) for key in ('attain','reduce','max_reduce')):
            return None
        return str(row['id'])

    def readback(self, operation_id, payload):
        self.validate(operation_id,payload)
        found=self._matches(payload)
        if found:
            return dict(state='confirmed',upstream_ref=found)
        return dict(state='unknown',reason_code='DRAFT_NOT_UNIQUELY_CONFIRMED')

    def dispatch_once(self, operation_id, payload):
        raise ContractError('COUPON_CREATION_NOT_AUTHORIZED')
