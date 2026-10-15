# -*- coding: utf-8 -*-
"""聚合：把 orders / discounts / members / deliveries 合成看板数据集 dashboard.json

推广人归属（三级）
  1) 订单带 discount_code 且该码在折扣码配置里 → 归属到「码所属会员 uid」（配置里 uid 字段）；
     同时保留「码归属后台账号」昵称备用。
  2) 无码 或 码未配置 → 用订单 recommend_uid 反查会员。
  3) 都没有 → 「自然流量 / 无归属」。

利润率口径（按用户要求）
  推广人利润率 = (Σ销售价 − Σ采购总价) / Σ销售价   ← 先各自求和再相除，不是逐单利润率求平均。
  数额取发货记录「订单发货」行的 ￥采购总价 / ￥销售价（人民币，分子分母同币种）。
"""
from __future__ import annotations

import html as H
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def load(name):
    p = DATA / name
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def num(x, default=0.0):
    if x is None:
        return default
    s = str(x).replace(",", "").replace("￥", "").replace("$", "").strip()
    try:
        return float(s)
    except Exception:
        return default


def parse_content(raw):
    """从订单 content 里抽 区服 与 商品明细文本。"""
    if not raw:
        return "", ""
    t = H.unescape(raw)
    area = ""
    m = re.search(r'class="area"[^>]*>\s*\[?([^\]<]*)', t)
    if m:
        area = m.group(1).strip().strip("[").strip()
    items = re.findall(r'class="item"[^>]*>(.*?)</span>', t)
    prod = " | ".join(re.sub(r"[☑&#12288;\s]+", " ", H.unescape(x)).strip()
                      for x in items)[:200]
    if not prod:
        prod = re.sub(r"<[^>]+>", " ", t)
        prod = re.sub(r"\s+", " ", prod).strip()[:200]
    return area, prod


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    orders = load("orders.json")
    discounts = load("discounts.json")
    members = {str(k): v for k, v in (load("members.json") or {}).items()}
    deliveries = load("deliveries.json")
    meta_in = {}
    mp = DATA / "_meta.json"
    if mp.exists():
        meta_in = json.loads(mp.read_text(encoding="utf-8"))
    print("载入：订单 %d / 折扣码 %d / 会员 %d / 发货 %d"
          % (len(orders), len(discounts), len(members), len(deliveries)))

    # ---- 折扣码索引（同码多条时优先含 gid 891 的） ----
    code2rec = {}
    for r in discounts:
        c = (r.get("code") or "").strip()
        if not c:
            continue
        gids = str(r.get("gid") or "")
        score = (1 if "891" in gids.split(",") else 0, int(r.get("id") or 0))
        if c not in code2rec or score > code2rec[c][0]:
            code2rec[c] = (score, r)
    code2rec = {c: v[1] for c, v in code2rec.items()}
    print("折扣码去重后 %d 个" % len(code2rec))

    # ---- 发货记录按商户订单号归并 ----
    deliv_by_sn = defaultdict(list)
    for d in deliveries:
        sn = (d.get("sn") or "").strip()
        if sn:
            deliv_by_sn[sn].append(d)
    print("发货记录覆盖 %d 个订单号" % len(deliv_by_sn))

    def member_name(uid):
        m = members.get(str(uid))
        if not m:
            return None
        nm = ((m.get("first_name") or "") + " " + (m.get("last_name") or "")).strip()
        return nm or (m.get("usname") or None)

    def attribute(o):
        code = (o.get("discount_code") or "").strip()
        rec = code2rec.get(code)
        admin_nick = ((rec or {}).get("admins") or {}).get("nickname") or ""
        uid = int(rec.get("uid") or 0) if rec else 0
        if code and rec:
            if uid:
                # 身份键统一用会员 uid：同一个人既可能靠「折扣码」也可能靠「推荐人」带单，
                # 之前拆成 promo:码 与 uid:号 两条，导致同一个人重复出现 → 现合并为一行。
                # 展示名直接用会员数字 UID（后台「推广人」列就是数字 ID），不要邮箱/姓名等杂字段。
                return ("uid:%d" % uid, str(uid), "折扣码", code, uid, admin_nick)
            # 码没绑会员 → 退到码归属后台账号
            if admin_nick:
                return ("admp:%s" % admin_nick, admin_nick, "折扣码归属账号", code, 0, admin_nick)
            return ("code:%s" % code, "折扣码 " + code, "折扣码(未配置归属)", code, 0, "")
        r_uid = int(o.get("recommend_uid") or 0)
        if r_uid:
            return ("uid:%d" % r_uid, str(r_uid), "推荐人", "", r_uid, "")
        return ("none", "自然流量/无归属", "无归属", "", 0, "")

    out_orders = []
    prom_meta = {}
    owner_meta = {}
    code_meta = {}
    orphan_sn = set(deliv_by_sn.keys())
    for o in orders:
        sn = (o.get("order_no") or "").strip()
        orphan_sn.discard(sn)
        ds = deliv_by_sn.get(sn, [])
        cost = sum(num(d.get("cost_total")) for d in ds)
        sale = sum(num(d.get("sale_total")) for d in ds)
        qty = sum(num(d.get("qty")) for d in ds)
        key, nm, src, code, uid, admin_nick = attribute(o)
        pm = prom_meta.get(key)
        if pm is None:
            pm = prom_meta[key] = {"key": key, "name": nm, "uid": uid, "source": src,
                                   "sources": [], "codes": [], "admin": admin_nick}
        if src not in pm["sources"]:
            pm["sources"].append(src)
        if code and code not in pm["codes"]:
            pm["codes"].append(code)
        if admin_nick and not pm["admin"]:
            pm["admin"] = admin_nick
        if code:
            code_meta.setdefault(code, {"code": code, "owner": nm, "admin": admin_nick,
                                        "uid": uid,
                                        "discount": num((code2rec.get(code) or {}).get("discount"))})
        area, prod = parse_content(o.get("content"))
        status_fmt = o.get("status_format") or ""
        pay_status = int(o.get("pay_status") or 0)
        refund = (pay_status == 2) or ("退款" in status_fmt)
        try:
            paytime = o.get("paytime") or ""
            day = paytime[:10]
        except Exception:
            day, paytime = "", ""
        amt = num(o.get("amount"))
        before = num(o.get("before_discount"))
        operators = sorted({(d.get("operator") or "").split("/")[-1].strip()
                            for d in ds if d.get("operator")})
        suppliers = sorted({(d.get("supplier") or "").split(" (")[0].strip()
                            for d in ds if d.get("supplier")})
        # 第二口径：折扣码归属的后台账号（没有码/没配归属就退回推广人）
        if admin_nick:
            okey, oname = "adm:%s" % admin_nick, admin_nick
        else:
            okey, oname = key, nm
        owner_meta.setdefault(okey, {"key": okey, "name": oname})
        out_orders.append({
            "order_no": sn, "id": o.get("id"), "day": day, "paytime": paytime,
            "amount_usd": round(amt, 2), "before_usd": round(before, 2),
            "discount_usd": round(max(before - amt, 0), 2),
            "code": code, "recommend_uid": int(o.get("recommend_uid") or 0),
            "promoter_key": key, "promoter": nm, "source": src,
            "owner_key": okey, "owner": oname,
            "admin": admin_nick, "uid": uid,
            "country": o.get("country") or "", "cc": o.get("country_code") or "",
            "paytype": o.get("paytype") or "", "status": status_fmt,
            "pay_status": pay_status, "refund": refund,
            "is_new": bool(int(o.get("isNew") or 0)),
            "area": area, "product": prod,
            "deliv_n": len(ds), "qty": qty,
            "cost_cny": round(cost, 2), "sale_cny": round(sale, 2),
            "profit_cny": round(sale - cost, 2),
            "margin": round((sale - cost) / sale, 4) if sale > 0 else None,
            "supplier": ", ".join(suppliers), "operator": ", ".join(operators),
        })

    print("订单 %d 单；无发货记录 %d 单；发货孤立单号 %d 个"
          % (len(out_orders),
             sum(1 for r in out_orders if r["deliv_n"] == 0), len(orphan_sn)))

    days = sorted({r["day"] for r in out_orders if r["day"]})
    # 归属方式标签统一排序，避免同一个人在不同位置显示成「折扣码+推荐人 / 推荐人+折扣码」
    SRC_ORDER = ["折扣码", "推荐人", "折扣码归属账号", "折扣码(未配置归属)", "无归属"]
    for pm in prom_meta.values():
        pm["sources"].sort(key=lambda s: SRC_ORDER.index(s) if s in SRC_ORDER else 99)
    payload = {
        "meta": {
            "start": meta_in.get("start"), "end": meta_in.get("end"),
            "fetched_at": meta_in.get("fetched_at"),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "game": "Aion 2", "admin_gid": 891, "order_gid": 826,
            "counts": {"orders": len(out_orders), "deliveries": len(deliveries),
                       "codes": len(code2rec), "members": len(members)},
            "date_range": [days[0] if days else "", days[-1] if days else ""],
            "orphan_sn": len(orphan_sn),
        },
        "promoters": sorted(prom_meta.values(), key=lambda x: x["name"]),
        "owners": sorted(owner_meta.values(), key=lambda x: x["name"]),
        "codes": sorted(code_meta.values(), key=lambda x: x["code"]),
        "orders": out_orders,
    }
    (DATA / "dashboard.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("→ data/dashboard.json  %.0f KB"
          % (len(json.dumps(payload, ensure_ascii=False)) / 1024))

    # 控制台预览：推广人排行
    agg = defaultdict(lambda: {"nm": "", "n": 0, "sale": 0.0, "cost": 0.0, "usd": 0.0})
    for r in out_orders:
        if r["refund"]:
            continue
        a = agg[r["promoter_key"]]
        a["nm"] = r["promoter"]
        a["n"] += 1
        a["sale"] += r["sale_cny"]
        a["cost"] += r["cost_cny"]
        a["usd"] += r["amount_usd"]
    print("\n推广人排行（不含退款单 · 按会员 uid 合并后）")
    print("%-22s %5s %12s %12s %10s %8s" % ("推广人", "单量", "销售额￥", "采购￥", "利润￥", "利润率"))
    for _, a in sorted(agg.items(), key=lambda x: -x[1]["sale"]):
        mg = (a["sale"] - a["cost"]) / a["sale"] if a["sale"] > 0 else 0
        print("%-22s %5d %12.2f %12.2f %10.2f %7.2f%%"
              % (a["nm"][:22], a["n"], a["sale"], a["cost"], a["sale"] - a["cost"], mg * 100))


if __name__ == "__main__":
    main()
