"""Admin 侧价格读回：用于改价成功后核对 unit_price 是否等于目标价。

设计依据（docs/planning/fc-pricing-ops-20261028/DECOUPLE-DESIGN.md §6.3）：
    Order 修改明确返回成功 + Admin 读回 unit_price == 目标价 → 记录改价成功
    不再强制等待 PUBLIC_CONFIRMED

约束：
    - 只读，绝不写
    - 按 (gid, mid, aid) 精确读单个商品，不用 top_cid/site_id 组合筛选
      （那会混入地区覆盖记录，price=0 且 unit_price 为子站价格）
    - price 字段必须保持 0，读回只校验 unit_price
"""
from decimal import Decimal, InvalidOperation

# FC27 金币：平台 -> Admin 的 aid
PLATFORM_AID = {'PC': '21589', 'PS': '21587', 'XBOX': '21585'}
SITE_MAIN = '266'          # www.mmoexp.com
GID_FC27 = '1327'
MID_FC27_COINS = '41217957'  # 产品模型的 mid（金币）

READBACK_PATH = '/admin/goods.Goods/index'


def _money(value):
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def read_admin_unit_prices(session, *, gid=GID_FC27, mid=MID_FC27_COINS,
                           site_id=SITE_MAIN, platform_aid=None, pages=None):
    """读回当前各平台 unit_price。

    ``pages`` 传入时使用调用方已有的分页通道
    （``channel_source.pages(session, path, filters)``），与 v3 其他读取保持一致；
    不传则退回本模块的极简分页。

    返回 {'PC': Decimal, 'PS': Decimal, 'XBOX': Decimal}，读不到的键不出现。
    异常一律向上抛，由调用方决定是否视为"未知"。
    """
    platform_aid = platform_aid or PLATFORM_AID
    reader = pages or _pages
    result = {}
    for platform, aid in platform_aid.items():
        filters = (('gid', '=', gid), ('mid', '=', mid), ('site_id', '=', site_id), ('aid', '=', aid))
        rows = reader(session, READBACK_PATH, filters)
        if not rows:
            continue
        # 同 (site,gid,mid,aid) 可能有多行（不同 cid），取 unit_price 唯一值
        prices = {_money(r.get('unit_price')) for r in rows}
        prices.discard(None)
        if len(prices) == 1:
            result[platform] = prices.pop()
    return result


def _pages(session, path, filters, limit=200):
    """极简分页：读全量后返回（该查询结果集很小，通常 1~3 行）。"""
    page, rows = 1, []
    while page <= 20:
        params = {'page': page, 'limit': limit}
        for i, (field, operator, value) in enumerate(filters):
            params['search[%d][field]' % i] = field
            params['search[%d][operator]' % i] = operator
            params['search[%d][val]' % i] = value
        status, body = session.get_admin(path, **params)
        if status != 200 or not isinstance(body, dict) or body.get('code') != 1:
            raise ValueError('admin_readback_failed')
        data = body.get('data') or {}
        batch = data.get('list') or []
        rows.extend(batch)
        total = int(data.get('total') or 0)
        if not batch or len(rows) >= total:
            break
        page += 1
    return rows


def matches_targets(observed, targets, *, units_per_target=Decimal('100')):
    """observed: {'PC': Decimal}（Admin 的 unit_price，**每 K**）
    targets:  [{'platform': 'PC', 'quote': '7.46'}, ...]（Order 的 unit_price，**每 100K**）

    换算：Admin 每 K 价 × 100 == Order 每 100K 价。
    全部平台都读到且换算后相等才算匹配；任一读不到 → False（视为未知）。
    """
    targets = targets or []
    if not targets:
        return False
    for target in targets:
        platform = target.get('platform')
        expected = _money(target.get('quote'))
        per_k = observed.get(platform)
        if per_k is None or expected is None:
            return False
        if per_k * units_per_target != expected:
            return False
    return True
