# -*- coding: utf-8 -*-
"""G2G 本店（Loot_Supply / seller_id=1003767531）货架读 + 改价写。

与 d4follow 的 core_g2g.py 的区别
--------------------------------
core_g2g.py 抓的是**竞品**（cheapold 等）的公开搜索接口，只读、无需登录；
本模块打的是**本店后台**接口，需要 accessToken：
  · 读货架  GET  /v3/offer/seller/{seller_id}/my_offers?page=N&page_size=100&status=live
  · 改价格  PUT  /offer/{offer_id}?v=v2      body {"seller_id":..., "unit_price":"1.99"}

## 接口事实（2026-10-10 实测，勿凭印象改）
  · ⚠️ 2026-10-12 重大修正：分页参数是 **`page_size`**，不是 `limit`！
    实测对比（同一时刻、同一 token）：
        page=1&limit=100                        → 返回 20 条（limit 被静默忽略）
        page=1&page_size=100&status=live        → 返回 74 条（全量）
    后果：旧代码只读到 20 条，本店 74 条在售里 **54 条从未被改价覆盖**，
    表现为「G2G 前台一直是旧价 9.99、后台 Manage offer 页 Live 显示 74 条」。
  · 认证头是 `authorization: <accessToken>`，**裸 token，没有 Bearer 前缀**。
  · unit_price 必须是**字符串**（"1.99"）；传数字或 "abc" 会 4002 unit_price not a valid number。
  · PUT /offer/{id} 是**部分更新**：只传 unit_price 时 qty / min_qty / status 分毫不动。
  · 批量上下架是 PUT /offer/seller/{id}/bulk_update?v=v2（status ∈ live/delisted/remove），
    **不是**改价端点；批量改价只能逐条调 PUT /offer/{id}。
  · 零净变化回写（写入与当前价相同的值）会刷新 updated_at ⇒ 说明真落库，可放心做 dry-run 校验。

## 标题解析
本店 Aion2 商品标题两种形态（75 条实测）：
  · "Siel - Elyos [NA West]"                  ← 74 条，标准形态
  · "白傑爾 - 天族 (Vaizel - Elyos)"           ← 1 条 TW 区，中文形态
解析结果统一成 (服务区, 阵营, 区服组)；配不上的一律返回 None，让上层跳过（绝不猜）。
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
API_BASE = "https://sls.g2g.com"
SELLER_ID = "1003767531"

MIL_KINAH = "Mil Kinah"          # Aion2 金币的 unit_name，用它筛掉其它游戏商品
AION_BRAND = "Aion 2"            # brand_name，双保险

# "Siel - Elyos [NA West]"
_RE_TITLE = re.compile(
    r"^(?P<srv>.+?)\s*-\s*(?P<side>Elyos|Asmodian)\s*\[(?P<grp>[^\]]+)\]\s*$")
# "白傑爾 - 天族 (Vaizel - Elyos)"
_RE_CN = re.compile(
    r"^.+?\s*-\s*(?:天族|魔族)\s*\(\s*(?P<srv>.+?)\s*-\s*(?P<side>Elyos|Asmodian)\s*\)\s*$")

# G2G 大区 UUID → 本项目「区服组」（与 config 的「大区」字段同口径）
REGION_BY_UUID = {
    "dfced32f-2f0a-4df5-a218-1e068cfadffa": "US",       # 含 NA West / NA East，按标题后缀细分
    "ac3f85c1-7562-437e-b125-e89576b9a38e": "EU",
    "7d971a93-e541-4055-8fcd-eb942b65701a": "Asia",
    "5b2d2761-128d-4185-9f42-6c502df03516": "SAM",
    "9820a142-1bc7-4ebe-9997-4e2dc7385879": "TW",       # 本项目不跟价
    "34571f6d-f812-45e1-b446-cf753e44f79b": "KR",
}


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_title(title, region_id=None):
    """标题 + region_id → dict(服务区, 阵营, 区服组)；解析不出返回 None。

    区服组优先取标题后缀 [NA West]/[NA East]/[EU]/[Asia]；
    中文形态没有后缀，回退到 region_id 映射（会得到 US，再靠上层按服务区名兜底）。
    """
    t = (title or "").strip()
    m = _RE_TITLE.match(t)
    if m:
        return {"服务区": m.group("srv").strip(),
                "阵营": m.group("side"),
                "区服组": m.group("grp").strip()}
    m = _RE_CN.match(t)
    if m:
        grp = REGION_BY_UUID.get(region_id or "", "")
        return {"服务区": m.group("srv").strip(),
                "阵营": m.group("side"),
                "区服组": grp}
    return None


def parse_offer(o):
    """把一条 my_offers 原始记录整成统一结构；非 Aion2 金币 → None。"""
    if (o.get("unit_name") or "") != MIL_KINAH:
        return None
    if (o.get("brand_name") or "") != AION_BRAND:
        return None
    k = parse_title(o.get("title"), o.get("region_id"))
    if not k:
        return None
    price = _f(o.get("converted_unit_price"))
    if price is None:
        price = _f(o.get("unit_price"))
    return {
        "offer_id": o.get("offer_id"),
        "title": o.get("title"),
        "服务区": k["服务区"],
        "阵营": k["阵营"],
        "区服组": k["区服组"],
        "现价": price,
        "币种": o.get("offer_currency") or o.get("display_currency") or "USD",
        "可售量": o.get("available_qty"),
        "起售": o.get("min_qty"),
        "状态": o.get("status"),
        "region_id": o.get("region_id"),
        "updated_at": o.get("updated_at"),
    }


# ─────────────────────────── HTTP 层 ───────────────────────────

class TokenError(RuntimeError):
    """token 缺失 / 已过期 / 被服务端拒绝。"""


def _headers(token):
    return {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "authorization": token or "",           # 裸 token，无 Bearer 前缀
        "Origin": "https://www.g2g.com",
        "Referer": "https://www.g2g.com/",
    }


def _request(method, path, token, body=None, timeout=30, retry=2, log=None):
    url = API_BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    last = None
    for i in range(max(1, retry)):
        try:
            req = urllib.request.Request(url, data=data, headers=_headers(token),
                                         method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            if e.code in (401, 403):
                raise TokenError("G2G 拒绝（%d）：%s" % (e.code, raw[:200]))
            last = RuntimeError("HTTP %d %s" % (e.code, raw[:200]))
        except TokenError:
            raise
        except Exception as e:                  # noqa: BLE001
            last = e
        if log:
            log("  [self] %s %s 第 %d 次失败：%r" % (method, path, i + 1, last))
        time.sleep(1.2 * (i + 1))
    raise last


def fetch_my_offers(token, seller_id=SELLER_ID, limit=100, max_pages=20, log=None):
    """拉全店货架（原样 results 列表）。分页到不足一页为止。"""
    out, page = [], 1
    while page <= max_pages:
        st, d = _request("GET",
                         "/v3/offer/seller/%s/my_offers?page=%d&page_size=%d"
                         "&status=live&include_sub_category=1&tree_version=v2"
                         % (seller_id, page, limit),
                         token, log=log)
        if st != 200 or not isinstance(d, dict):
            raise RuntimeError("my_offers 返回异常：%s" % str(d)[:200])
        res = ((d.get("payload") or {}).get("results")) or []
        out += res
        if len(res) < limit:
            break
        page += 1
        time.sleep(0.3)
    return out


def update_price(token, offer_id, price, seller_id=SELLER_ID, log=None):
    """把某个 offer 的单价改成 price（$/M）。返回 (ok, info)。

    ok=False 时 info 里带 detail，调用方据此记录失败原因。
    """
    body = {"seller_id": str(seller_id), "unit_price": "%.2f" % float(price)}
    try:
        st, d = _request("PUT", "/offer/%s?v=v2" % offer_id, token, body=body, log=log)
    except Exception as e:                      # noqa: BLE001
        return False, {"status": None, "detail": repr(e)[:300]}
    code = (d or {}).get("code")
    ok = st == 200 and code in (2000, 200, None)
    return ok, {"status": st, "code": code, "detail": str(d)[:300]}


def fetch_one_price(token, offer_id, seller_id=SELLER_ID, log=None):
    """写后读回：从货架里找该 offer 的当前价。找不到返回 None。"""
    for o in fetch_my_offers(token, seller_id=seller_id, log=log):
        if o.get("offer_id") == offer_id:
            return _f(o.get("converted_unit_price")) or _f(o.get("unit_price"))
    return None


def load_token(path):
    """读保活器推送的 token 文件；缺失/过期抛 TokenError。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:                      # noqa: BLE001
        raise TokenError("读不到 token 文件 %s：%r" % (path, e))
    tok = d.get("access_token")
    if not tok:
        raise TokenError("token 文件里没有 access_token")
    exp = (d.get("payload") or {}).get("exp")
    # 注意用 is not None 而不是真值判断：exp=0 是「已失效」，被 falsy 吃掉就会误判成「无过期时间」
    left = (float(exp) - time.time()) if exp is not None else None
    if left is not None and left <= 0:
        raise TokenError("token 已过期（%.0f 秒前）" % (-left))
    return {"token": tok, "remaining": int(left) if left is not None else None,
            "saved_at": d.get("saved_at"), "payload": d.get("payload")}


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else "var/token.json"
    info = load_token(p)
    print("token 剩余 %ss" % info["remaining"])
    offers = fetch_my_offers(info["token"], log=print)
    print("货架 %d 条" % len(offers))
    for o in offers:
        r = parse_offer(o)
        if r:
            print("  %-8s %-16s %-10s %8s  %s"
                  % (r["区服组"], r["服务区"], r["阵营"], r["现价"], r["offer_id"]))
