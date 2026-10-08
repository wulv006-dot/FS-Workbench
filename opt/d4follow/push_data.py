# -*- coding: utf-8 -*-
"""本机推送数据到服务器在线看板（千岛进货成本 + 我方前端价）

本机推送 = 兜底通道（2026-09-24 起服务器已能自抓，正常情况下不必跑本脚本）
--------------------------------------------------------------------
* 我方价：服务器已可直连 www.mmoexp.com（实测 HTTP 200 / 抓 10 条匹配 9 条），
  由「前端.服务器直连」开关控制，默认开。
* 千岛：服务器已装 Playwright+Chromium，实测直连成功
  （3 区服 552 条 / 1m22s / 内存无压力），由「千岛.服务器抓取」开关控制，默认开。
  旧注释「接口带 HMAC 签名、服务器没装 Chromium」不准确 —— 千岛的拦路虎是
  「反爬 + CORS 预检」，与签名无关，装好真实浏览器内核即可。

本脚本保留的用途：服务器两个开关被关掉、或服务器抓取持续失败时，
在本机手动补一份数据（POST /api/cost 与 /api/our）。

用法
----
  python push_data.py                # 千岛（3h 内命中缓存则复用）+ 我方价，一起推
  python push_data.py --force-qd     # 强制重抓千岛（忽略缓存）
  python push_data.py --only our     # 只推我方前端价
  python push_data.py --only cost    # 只推千岛成本
  python push_data.py --server http://47.85.224.112/d4
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import core_front
import core_qd
import store

DEFAULT_SERVER = "http://47.85.224.112/d4"
UA = "d4follow-pusher/1.0"


def _mny(v):
    """价格显示：正数 $0.5600 / 负数 -$0.5600 / 空 --"""
    if v is None:
        return "--"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return ("-$%.4f" % abs(f)) if f < 0 else ("$%.4f" % f)


def load_cfg():
    return json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))


def post(server, path, payload):
    url = server.rstrip("/") + path
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# ------------------------------------------------------------------ 千岛成本

def push_costs(a, cfg, con):
    rows = []
    ts = dt.datetime.now().isoformat(timespec="seconds")
    if a.from_db:
        prev = store.prev_ts(con, "qd_cost", "9999")
        if not prev:
            print("本地库里没有千岛成本，去掉 --from-db 重新抓")
            return False
        rows = [dict(r) for r in con.execute("SELECT * FROM qd_cost WHERE ts=?", (prev,))]
        ts = prev
        print("从本地库取 %s 的 %d 条" % (ts, len(rows)))
    else:
        print("[千岛] 正在抓…（本机 Playwright，一轮约 1~2 分钟）")
        got, qd_ts, cached = core_qd.fetch(cfg, log=print, force=a.force_qd)
        if not got:
            print("[千岛] ⚠ 没抓到数据，跳过")
            return False
        rows = [dict(r) for r in got]
        ts = qd_ts if cached else ts
        if not cached:
            store.save_qd(con, ts, rows)
        print("[千岛] 共 %d 条，快照 ts=%s（%s）"
              % (len(rows), ts, "命中缓存" if cached else "新抓"))

    # 服务器端 store.save_qd 认这套原始字段名
    payload = []
    for r in rows:
        spuid = r.get("spuId") or r.get("spu_id")
        price = r.get("rmbPrice") if r.get("rmbPrice") is not None else r.get("price_cny")
        if not spuid or price in (None, "", 0):
            continue
        payload.append({
            "spuId": str(spuid),
            "_spec_label": r.get("_spec_label") or r.get("spec") or "",
            "spuName": r.get("spuName") or r.get("name"),
            "typeName": r.get("typeName") or r.get("category") or "",
            "rmbPriceUnit": r.get("rmbPriceUnit") or r.get("unit") or "个",
            "rmbPrice": price,
        })
    if not payload:
        print("[千岛] ⚠ 没有可推送的有效行")
        return False
    res = post(a.server, "/api/cost", {"ts": ts, "rows": payload,
                                       "spec": cfg["千岛"]["对标区服"]})
    print("[千岛] ✔ 推送成功：入库 %s 条，快照 %s" % (res.get("saved"), res.get("ts")))
    print("       区服：%s" % "、".join(res.get("specs") or []))
    return True


# ------------------------------------------------------------------ 我方前端价

def push_our(a, cfg, con):
    print("[我方价] 正在抓 MMOEXP 公开页…")
    items = core_front.fetch_all(cfg, log=print)
    if not items:
        print("[我方价] ⚠ 没抓到商品")
        return False
    rows, unmatched = core_front.to_our_rows(cfg, items)
    for r in rows:
        if not r.get("_装量匹配"):
            print("[我方价] ⚠ %s 装量降级匹配到 %s（config 里可能缺该规格）"
                  % (r["title"], r["key"]))
    if unmatched:
        print("[我方价] 未匹配的页面商品：%s" % "、".join(unmatched[:10]))
    if not rows:
        print("[我方价] ⚠ 一条都没匹配上对照项，检查 config 的商品映射")
        return False

    ts = dt.datetime.now().isoformat(timespec="seconds")
    payload = [{"key": r["key"], "title": r.get("title"),
                "price_usd": r.get("price_usd"), "cost_cny": r.get("cost_cny"),
                "game": "D4", "server_zone": "", "cate": "",
                "source": "mmoexp-front-push",
                "unit_price_usd": r.get("unit_price_usd"),
                "_pack_size": r.get("_pack_size")} for r in rows]
    res = post(a.server, "/api/our", {"ts": ts, "rows": payload})
    print("[我方价] ✔ 推送成功：入库 %s 条，快照 %s" % (res.get("saved"), res.get("ts")))
    for r in rows:
        print("        %-26s 整包 $%-9s 单价 $%-9s 装量 %s"
              % (r.get("title"), _mny(r.get("price_usd")), _mny(r.get("unit_price_usd")),
                 r.get("_pack_size")))
    # 本地也留一份，便于离线比对
    store.save_our(con, ts, rows)
    return True


def main():
    ap = argparse.ArgumentParser(description="推送千岛成本 + 我方前端价到在线看板")
    ap.add_argument("--server", default=DEFAULT_SERVER)
    ap.add_argument("--force-qd", action="store_true", help="强制重抓千岛（忽略缓存）")
    ap.add_argument("--from-db", action="store_true", help="千岛不抓网，用本地库里最近一份")
    ap.add_argument("--only", choices=["our", "cost"], help="只推其中一项")
    a = ap.parse_args()

    cfg = load_cfg()
    data_dir = os.path.join(ROOT, cfg["运行"]["数据目录"])
    con = store.connect(data_dir)

    print("目标服务器：%s" % a.server)
    print("=" * 62)
    ok = []
    if a.only != "our":
        try:
            ok.append(("千岛成本", push_costs(a, cfg, con)))
        except Exception as e:
            print("[千岛] ✘ 失败：%r" % e)
            ok.append(("千岛成本", False))
        print("-" * 62)
    if a.only != "cost":
        try:
            ok.append(("我方前端价", push_our(a, cfg, con)))
        except Exception as e:
            print("[我方价] ✘ 失败：%r" % e)
            ok.append(("我方前端价", False))

    print("=" * 62)
    for n, v in ok:
        print("  %-10s %s" % (n, "✔ 成功" if v else "✘ 失败"))
    if not all(v for _, v in ok):
        print("\n检查：网络是否能访问 %s，服务是否在跑（systemctl status d4follow）" % a.server)
        sys.exit(1)


if __name__ == "__main__":
    main()
