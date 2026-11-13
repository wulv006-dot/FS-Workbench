"""FC27 金币单价与售价计算。

售价口径（业务方给定）：

    单价 = (游戏内所需金币 × 每金币价格 + 0.24) × 加成

其中「每金币价格」取自 MMOEXP 的 FC27 Coins 页面（用户指定的参考站）：

    https://www.mmoexp.com/Fc-27/Coins.html

该页面切换区服时调用 ``POST /ajax/goods``，参数
``{Game_id, top_cid, aid, cid, site_id}``，返回里
``goods.index.list[0].more`` 中购买100K对应的售价是本次基准；旧顶层单价不再用于分档价表。历史单价示例：
（``unit`` 字段为 ``"K"``，例如 0.12949 表示 100K 卖 $12.95）。
因此 ``每金币价格 = unit_price / 1000``。

实测（2026-09-24，site_id=266 mmoexp.com，gid=1327）：

    PlayStation 5      aid=21587   0.12949 / 1K   → 100K $12.95
    Xbox Series X|S    aid=21585   0.12949 / 1K   → 100K $12.95
    PC Platform        aid=21589   0.12990 / 1K   → 100K $12.99
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

import sys
sys.path.insert(0, "/opt/fs-sports-outbound")
import sports_outbound
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

MMOEXP_AJAX = "https://www.mmoexp.com/ajax/goods"
MMOEXP_REFERER = "https://www.mmoexp.com/Fc-27/Coins.html"

GID_FC27 = 1327
CID_COINS = 9623            # 金币类目（MMOEXP 的 container data-cid）
SITE_ID_MMOEXP = 266        # mmoexp.com

# 游戏区服（与后台 all_aids 一致）
AREA_AIDS: dict[int, str] = {
    21587: "PlayStation 5",
    21585: "Xbox Series X|S",
    21589: "PC Platform",
}
DEFAULT_AREA_AID = 21587     # 页面默认展示 PlayStation 5

# 计价参数
BASE_FEE = Decimal("0.24")           # 固定手续费，业务口径
DEFAULT_MARKUP = Decimal("1.1")
PRICE_FLOOR = Decimal("0.50")

CACHE_TTL_SECONDS = 1800             # 单价缓存 30 分钟
RATE_BASIS = 'actual_100k_purchase_v1'
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class PricingError(RuntimeError):
    """金币单价获取失败。"""


@dataclass(frozen=True)
class CoinPrice:
    aid: int
    area: str
    unit_price_per_1k: Decimal      # 每 1K 金币价格，如 0.12949
    per_coin: Decimal               # 每金币价格，如 0.00012949

    @property
    def price_per_100k(self) -> Decimal:
        return (self.unit_price_per_1k * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _quantize(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_price(
    coins: Optional[int],
    per_coin: Decimal,
    *,
    markup: Decimal = DEFAULT_MARKUP,
    base_fee: Decimal = BASE_FEE,
    floor: Decimal = PRICE_FLOOR,
) -> Optional[Decimal]:
    """(金币 × 每金币价格 + 0.24) × 加成，四舍五入两位，不低于底价。"""

    if coins is None:
        return None
    value = (Decimal(str(coins)) * Decimal(str(per_coin)) + Decimal(str(base_fee))) * Decimal(str(markup))
    value = _quantize(value)
    if floor is not None and value < floor:
        return _quantize(Decimal(str(floor)))
    return value


def _request_area(aid: int) -> Mapping:
    body = urllib.parse.urlencode({
        "Game_id": GID_FC27,
        "top_cid": 1,
        "aid": int(aid),
        "cid": CID_COINS,
        "site_id": SITE_ID_MMOEXP,
    }).encode()
    request = urllib.request.Request(
        MMOEXP_AJAX,
        data=body,
        headers={
            "User-Agent": _USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": MMOEXP_REFERER,
        },
    )
    try:
        with sports_outbound.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PricingError(f"访问 MMOEXP 失败：{exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PricingError("MMOEXP 返回不是有效 JSON") from exc


def fetch_from_admin(client: Any, *, gid: int = GID_FC27, cid: int = CID_COINS,
                     site_id: int = SITE_ID_MMOEXP,
                     aids: Optional[Iterable[int]] = None,
                     log: Callable[[str], None] = print) -> dict[int, CoinPrice]:
    """Read actual main-site 100K tiers through the caller's existing Admin identity."""
    sys.path.insert(0, '/opt/fc27-cloud-browser')
    from fc_purchase_rate import PRODUCTS, purchase_rate
    if (int(gid), int(cid), int(site_id)) != (GID_FC27, CID_COINS, SITE_ID_MMOEXP):
        raise PricingError('金币商品范围不匹配')
    wanted = {int(a) for a in aids} if aids is not None else set(AREA_AIDS)
    if not wanted.issubset(AREA_AIDS):
        raise PricingError('金币平台不匹配')
    out: dict[int, CoinPrice] = {}
    for platform, (product_id, aid) in PRODUCTS.items():
        if aid not in wanted:
            continue
        try:
            value = client._json('GET', '/admin/goods.Goods/edit', params={'id': product_id})
            if not isinstance(value, dict) or value.get('code') not in (1, '1'):
                raise ValueError('admin_read_unconfirmed')
            unit = purchase_rate(value['data']['row'], platform)
        except (ValueError, KeyError, TypeError):
            log(f'Admin 100K 档位未确认：{platform}')
            continue
        out[aid] = CoinPrice(aid=aid, area=AREA_AIDS[aid], unit_price_per_1k=unit,
                             per_coin=unit / Decimal(1000))
    if not out:
        raise PricingError('Admin 100K 档位未返回')
    log(f'每金币价取自 Admin 主站实际100K档：{len(out)} 个区服')
    return out


def parse_price(payload: Mapping, aid: int) -> CoinPrice:
    items = (((payload or {}).get("goods") or {}).get("index") or {}).get("list") or []
    if not items:
        raise PricingError(f"aid={aid} 没有返回金币商品")
    sys.path.insert(0, '/opt/fc27-cloud-browser')
    from fc_purchase_rate import tier_purchase_rate
    if int(aid) not in AREA_AIDS:
        raise PricingError('金币平台不匹配')
    try:
        unit = tier_purchase_rate(items[0].get('more'), str(aid))
    except (ValueError, TypeError) as exc:
        raise PricingError(f'aid={aid} 的100K档位未确认') from exc
    return CoinPrice(
        aid=int(aid),
        area=AREA_AIDS.get(int(aid), str(aid)),
        unit_price_per_1k=unit,
        per_coin=unit / Decimal("1000"),
    )


def _read_cache(cache_path: Optional[Path]) -> tuple[float, dict]:
    """读缓存文件，返回 ``(fetched_at, prices)``。坏了/不存在就返回 ``(0, {})``。"""

    if not cache_path or not Path(cache_path).is_file():
        return 0.0, {}
    try:
        raw = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  缓存坏了就当没有
        return 0.0, {}
    if not isinstance(raw, Mapping) or raw.get('rate_basis') != RATE_BASIS:
        return 0.0, {}
    try:
        stamp = float(raw.get("fetched_at") or 0)
    except (TypeError, ValueError):
        stamp = 0.0
    prices = raw.get("prices")
    return stamp, dict(prices) if isinstance(prices, Mapping) else {}


def _price_from_stored(stored: Mapping, aid: int) -> Optional[CoinPrice]:
    """把缓存里的一个区服还原成 CoinPrice；缺字段/坏了返回 None。"""

    row = stored.get(str(aid))
    if not isinstance(row, Mapping) or "per_coin" not in row:
        return None
    try:
        return CoinPrice(
            aid=int(aid),
            area=str(row.get("area") or AREA_AIDS.get(int(aid), str(aid))),
            unit_price_per_1k=Decimal(str(row.get("unit_price_per_1k")
                                          or Decimal(str(row["per_coin"])) * 1000)),
            per_coin=Decimal(str(row["per_coin"])),
        )
    except Exception:  # noqa: BLE001
        return None


def load_cached_prices(
    cache_path: Optional[Path],
    aids: Iterable[int] = tuple(AREA_AIDS),
) -> dict[int, CoinPrice]:
    """只从缓存里读，联网一个字节都不发。

    给「强制刷新失败后退回缓存」「离线时也能看到上次取到的价」这类场景用。
    缓存不存在 / 坏了 / 缺某个区 → 能读出几个算几个（**不会抛**）。
    """

    wanted = [int(a) for a in aids]
    stored, out = _read_cache(cache_path)[1], {}
    for aid in wanted:
        price = _price_from_stored(stored, aid)
        if price is not None:
            out[aid] = price
    return out


def coin_cache_age(cache_path: Optional[Path]) -> Optional[float]:
    """缓存距今多少秒；没有缓存返回 None。界面上显示「X 分钟前取」用它。"""

    if not cache_path or not Path(cache_path).is_file():
        return None
    stamp = _read_cache(cache_path)[0]
    return None if not stamp else max(0.0, time.time() - stamp)


def fetch_coin_prices(
    aids: Iterable[int] = tuple(AREA_AIDS),
    *,
    cache_path: Optional[Path] = None,
    max_age: int = CACHE_TTL_SECONDS,
    use_cache: bool = True,
    meta: Optional[dict] = None,
) -> dict[int, CoinPrice]:
    """取各游戏区服的金币单价；带本地缓存，网络失败时回退到过期缓存。

    参数::

        max_age:     缓存新鲜有效期（默认 30 分钟）
        use_cache:   False = 强制重新联网取（界面上的「强制刷新」走这个）
        meta:        可选。传一个 dict 进来，函数会往里写
                     ``from_cache``（这次是不是用的缓存）、
                     ``fetched_at``（取价时刻的时间戳）、
                     ``areas``（实际取到的区服数）——
                     让调用方能**如实告诉用户价是哪来的**，别再把缓存值说成"最新"。

    ⚠️ **为什么要有缓存、又为什么必须能绕过它**（2026-09-28 用户报的 bug）：
    「点了『按 MMOEXP 带出』却没出最新价」—— 根因是缓存把请求挡住了，而界面
    完全没说这一层，30 分钟内点几次都返回同一个数，看起来就像"按钮没反应"。
    所以：**保留缓存**（省得每次都打人家站点），但把「来源」暴露出来，
    并给一条明确的强制刷新通道。

    ⚠️ 两个健壮性约定：
      · 全部取失败 → 退回**过期缓存**（有就用），都拿不到才抛；
      · 只取到一部分区 → 缓存**合并写入**（丢的那些区保留上次的值），
        并且只在**全部取到**时才推进 ``fetched_at`` —— 免得把某个区的旧价
        伪装成刚取的。
    """

    wanted = [int(a) for a in aids]
    stamp, stored = _read_cache(cache_path)
    fresh = bool(stamp) and (time.time() - stamp) <= max_age

    if use_cache and fresh:
        hit = {a: _price_from_stored(stored, a) for a in wanted}
        if all(v is not None for v in hit.values()):
            if meta is not None:
                meta.update({"from_cache": True, "fetched_at": stamp,
                             "areas": len(hit)})
            return {a: p for a, p in hit.items() if p is not None}

    result: dict[int, CoinPrice] = {}
    errors: list[str] = []
    for aid in wanted:
        try:
            result[aid] = parse_price(_request_area(aid), aid)
        except PricingError as exc:
            errors.append(str(exc))

    if not result:
        # 网络全挂 → 退回过期缓存（这就是 docstring 里那句话，之前**没实现**）
        fallback = load_cached_prices(cache_path, wanted)
        if fallback:
            if meta is not None:
                meta.update({"from_cache": True, "fetched_at": stamp,
                             "areas": len(fallback),
                             "warning": "；".join(errors) or "取价失败，已退回上次取到的价"})
            return fallback
        raise PricingError("；".join(errors) or "没有取到任何金币单价")

    now = time.time()
    if meta is not None:
        meta.update({"from_cache": False, "fetched_at": now,
                     "areas": len(result)})
        if errors:
            # 部分区服失败要如实上报 —— 别让用户以为三个区都刷新了
            meta["warning"] = "；".join(errors)

    if cache_path:
        merged: dict[str, dict] = {}
        for key, row in stored.items():
            if isinstance(row, Mapping):
                merged[str(key)] = dict(row)
        for p in result.values():
            merged[str(p.aid)] = {
                "area": p.area,
                "unit_price_per_1k": str(p.unit_price_per_1k),
                "per_coin": str(p.per_coin),
            }
        payload = {
            "rate_basis": RATE_BASIS,
            # 只有**全部**取到才推进时间戳；否则保留旧的时间戳，下次仍会重新取
            "fetched_at": now if len(result) == len(wanted) else (stamp or now),
            "source": MMOEXP_REFERER,
            "prices": merged,
        }
        try:
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            Path(cache_path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
    return result


def save_cached_prices(cache_path: Optional[Path], prices: Mapping[int, "CoinPrice"],
                       *, source: str = MMOEXP_REFERER) -> None:
    """把取到的价写进缓存（格式与 :func:`fetch_coin_prices` 一致）。

    为什么需要单独暴露：**后台取价那条路**（:func:`fetch_from_admin`）不走
    ``fetch_coin_prices``，但它同样得落到缓存 —— 否则界面上的"价是哪来的/多久前取的"
    和别的读缓存的代码会看到一份过期数据（2026-10-16）。
    """

    if not cache_path or not prices:
        return
    payload = {
        "rate_basis": RATE_BASIS,
        "fetched_at": time.time(),
        "source": source,
        "prices": {
            str(aid): {
                "area": p.area,
                "unit_price_per_1k": str(p.unit_price_per_1k),
                "per_coin": str(p.per_coin),
            }
            for aid, p in prices.items()
        },
    }
    try:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        Path(cache_path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def price_table(coins_list: Iterable[tuple[int, str]], per_coin: Decimal, *,
                markup: Decimal = DEFAULT_MARKUP) -> list[tuple[str, int, Decimal]]:
    """批量算价，便于在界面上预览。返回 [(名称, 金币, 单价)]。"""

    out: list[tuple[str, int, Decimal]] = []
    for coins, name in coins_list:
        price = compute_price(coins, per_coin, markup=markup)
        if price is not None:
            out.append((name, coins, price))
    return out


__all__ = [
    "AREA_AIDS",
    "BASE_FEE",
    "CID_COINS",
    "DEFAULT_AREA_AID",
    "DEFAULT_MARKUP",
    "MMOEXP_AJAX",
    "MMOEXP_REFERER",
    "PRICE_FLOOR",
    "CoinPrice",
    "PricingError",
    "compute_price",
    "fetch_coin_prices",
    "parse_price",
    "price_table",
]
