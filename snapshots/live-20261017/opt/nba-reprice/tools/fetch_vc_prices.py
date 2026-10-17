#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NBA 2K27 VC 竞品价格抓取（u7buy / iggm / u4gm）
=================================================
三家均为纯 HTTP/接口抓取，无需登录、无需浏览器。
用法:  python fetch_vc_prices.py            # 打印表格 + 写 vc_prices.json

关键点（2026-09-30 逆向后确认）:
  u7buy  getFaceValueList 必须带 areaId，areaId 来自 getFilterConditions -> deliveryInfoVoList[].regionInfoList[]
         areaId 即平台开关: PS5 / PC / XBOX
  iggm   /goods/goods_ajax?template_type=golds&server_id=X&cate_id=0
         server_id: PS=27443  Xbox=27441  PC=27439
  u4gm   产品页 ?server_code=ps|xbox|pc，单价在 data-unit-price
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

U7_SPU = "2095709820309200897"          # NBA 2K27 VC
U7_CLIENTID = "94f670c954182e9c30535fa9cad35983"
U7_BASE = "https://www.u7buy.com/prod-api"

IGGM_SERVERS = {"PS": "27443", "Xbox": "27441", "PC": "27439"}
U4GM_CODES = {"PS": "ps", "Xbox": "xbox", "PC": "pc"}


def curl(url, headers=None, timeout=30):
    """用系统 curl 抓取（能过 Cloudflare，urllib 会被 403）。"""
    cmd = ["curl", "-s", "--max-time", str(timeout), "-H", f"User-Agent: {UA}"]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    cmd.append(url)
    out = subprocess.run(cmd, capture_output=True)
    return out.stdout.decode("utf-8", "ignore")


def to_vc(face):
    """'100K' -> 100000"""
    s = str(face).strip().upper().replace(",", "")
    m = re.match(r"^([\d.]+)\s*([KMB]?)$", s)
    if not m:
        return None
    return float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)]


# ---------------------------------------------------------------- u7buy
def fetch_u7buy():
    hdr = {"clientid": U7_CLIENTID, "Content-Language": "en",
           "content-currency": "USD", "Accept": "application/json",
           "Referer": f"https://www.u7buy.com/nba-2k27/vc"}

    fc = json.loads(curl(f"{U7_BASE}/product/urlMapping/topUpProductInfo/getFilterConditions?spuId={U7_SPU}", hdr))
    cats = fc.get("data") or []
    if not cats:
        raise RuntimeError("getFilterConditions 返回空")
    cat = cats[0]
    category_id = cat["categoryId"]
    dv = (cat.get("deliveryInfoVoList") or [{}])[0]
    delivery_id = dv.get("deliveryId")
    areas = {r["areaName"]: r["areaId"] for r in (dv.get("regionInfoList") or [])}

    result = {}
    for plat, area_id in areas.items():
        url = (f"{U7_BASE}/product/urlMapping/topUpProductInfo/getFaceValueList"
               f"?spuId={U7_SPU}&categoryId={category_id}"
               f"&deliveryId={delivery_id}&areaId={area_id}")
        js = json.loads(curl(url, hdr))
        tiers = []
        for it in js.get("data") or []:
            amt = to_vc(it.get("faceValue"))
            price = float(it.get("price") or 0)
            tiers.append({
                "face": it.get("faceValue"),
                "vc": amt,
                "price": price,
                "per_1k": round(price / (amt / 1000), 4) if amt else None,
                "sold_out": it.get("soldOutFlag"),
            })
        tiers.sort(key=lambda t: t["vc"] or 0)
        alive = [t for t in tiers if not t["sold_out"] and t["per_1k"]]
        result[plat] = {
            "tiers": tiers,
            "entry_per_1k": alive[0]["per_1k"] if alive else None,      # 最小档
            "best_per_1k": min((t["per_1k"] for t in alive), default=None),  # 大额最优
        }
    return result


# ---------------------------------------------------------------- iggm
def fetch_iggm():
    result = {}
    for plat, sid in IGGM_SERVERS.items():
        url = (f"https://www.iggm.com/goods/goods_ajax?template_type=golds"
               f"&server_id={sid}&cate_id=0")
        html = curl(url, {"X-Requested-With": "XMLHttpRequest",
                          "Referer": "https://www.iggm.com/nba-2k/2k27-vc"})
        prices = [float(x) for x in re.findall(r'data-unit-price="([\d.]+)"', html)]
        if not prices:
            prices = [float(x) for x in re.findall(r'"price"\s*:\s*"?([\d.]+)', html)]
        result[plat] = {"per_1k": min(prices) if prices else None}
    return result


# ---------------------------------------------------------------- u4gm
def fetch_u4gm():
    result = {}
    for plat, code in U4GM_CODES.items():
        html = curl(f"https://www.u4gm.com/nba-2k27/vc?server_code={code}",
                    {"X-Requested-With": "XMLHttpRequest",
                     "Referer": "https://www.u4gm.com/nba-2k27/vc"})
        m = re.search(r'data-unit-price="([\d.]+)"', html)
        result[plat] = {"per_1k": float(m.group(1)) if m else None}
    return result


def main():
    out = {"fetched_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
           "source": {}}
    for name, fn in (("u7buy", fetch_u7buy), ("iggm", fetch_iggm), ("u4gm", fetch_u4gm)):
        try:
            out["source"][name] = fn()
            print(f"[OK]   {name}")
        except Exception as e:
            out["source"][name] = {"error": str(e)}
            print(f"[FAIL] {name}: {e}", file=sys.stderr)

    json.dump(out, open("vc_prices.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(f"\n抓取时间: {out['fetched_at']}")
    print(f"{'平台':<6}{'U7BUY入门':>12}{'U7BUY大额':>12}{'IGGM':>10}{'U4GM':>10}")

    # 平台名归一: u7buy 用 PS5/XBOX，iggm/u4gm 用 PS/Xbox
    CANON = {"PS": "PS", "PS5": "PS", "Xbox": "Xbox", "XBOX": "Xbox", "PC": "PC"}

    def norm(src_data):
        d = {}
        for k, v in (src_data or {}).items():
            c = CANON.get(k)
            if c and c not in d:
                d[c] = v
        return d

    u7, ig, u4 = (norm(out["source"][s]) for s in ("u7buy", "iggm", "u4gm"))

    for plat in ("PS", "Xbox", "PC"):
        cell = []
        v = u7.get(plat)
        cell.append(f"${v['entry_per_1k']:.4f}" if isinstance(v, dict) and v.get("entry_per_1k") else "-")
        cell.append(f"${v['best_per_1k']:.4f}" if isinstance(v, dict) and v.get("best_per_1k") else "-")
        for src in (ig, u4):
            v = src.get(plat)
            cell.append(f"${v['per_1k']:.4f}" if isinstance(v, dict) and v.get("per_1k") else "-")
        print(f"{plat:<6}{cell[0]:>12}{cell[1]:>12}{cell[2]:>10}{cell[3]:>10}")
        best = min(x for x in cell if x != "-")
        print(f"       └ 本平台最低 {best}")

    print("\n已写出 vc_prices.json")


if __name__ == "__main__":
    main()
