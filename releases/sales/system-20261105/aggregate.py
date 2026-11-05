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
import history_db as HDB
import sales_regions

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


# ---------------------------------------------------------------- 大区
# 订单 content 的区服有两种写法：
#   [Zikel - Asmodian [NA East]]   ← 带大区
#   [Nezekan - Elyos]              ← 不带大区（约占 29%）
# 不带大区的，用该单「发货记录」的 game 字段回填：
#   Aion 2 ▶美东-魔族-Zikel（魔2）
# 两者都有的 1334 单做过交叉校验，一致率 99.8%（仅 3 单 美东 与 EU 冲突）。
CN2REGION = {"美东": "NA East", "美西": "NA West", "欧服": "EU",
             "亚服": "Asia", "南美": "SA"}
REGION_RE = re.compile(r"\b(NA East|NA West|Asia|EU|SA)\b")


def region_of_area(area):
    m = REGION_RE.search(area or "")
    return m.group(1) if m else ""


def region_of_delivery(ds):
    """从发货记录的 game 字段里取大区，取不到返回空串。"""
    hit = {}
    for d in ds:
        g = d.get("game") or ""
        m = re.search(r"▶\s*([^-（(]+)", g)
        if not m:
            continue
        r = CN2REGION.get(m.group(1).strip())
        if r:
            hit[r] = hit.get(r, 0) + 1
    if not hit:
        return ""
    # 同一单多行发货时取出现次数最多的那个
    return next(iter(hit)) if len(hit) == 1 else ""


def norm_area(area, region):
    """把区服统一成「服务器 - 阵营 [大区]」，前端 regionOf() 直接就能解析。"""
    base = re.sub(r"\s*\[?(NA East|NA West|Asia|EU|SA)\s*\]?$", "", (area or "").strip()).strip()
    base = base.strip("[]").strip()
    if region:
        return "%s [%s]" % (base, region)
    return base



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

    # ---- 折扣码索引（同码多条时优先含 gid 891 的；**键统一大写**，见下方 attribute 说明） ----
    code2rec = {}
    for r in discounts:
        c = (r.get("code") or "").strip()
        if not c:
            continue
        k = c.upper()          # 后台配置存大写（FOCUS），订单里可能小写（focus）→ 必须不区分大小写
        gids = str(r.get("gid") or "")
        score = (1 if "891" in gids.split(",") else 0, int(r.get("id") or 0))
        if k not in code2rec or score > code2rec[k][0]:
            code2rec[k] = (score, r)
    code2rec = {k: v[1] for k, v in code2rec.items()}
    print("折扣码去重后 %d 个" % len(code2rec))

    # ---- 推广人目录（来源：Aion2团队分销信息.xlsx，由 import_promoter_dir.py 生成） ----
    # 一个推广人可以挂多个码（例：耿凯翔 = PRETTYANGEL + FOCUS），目录优先于后台配置：
    # FOCUS 在后台配置里 uid=0、归属账号是「刘晓辰」，只有目录才知道它属于耿凯翔。
    PROM_BY_CODE, PROM_BY_UID = {}, {}
    pd = DATA / "promoter_dir.json"
    if pd.exists():
        _pd = json.loads(pd.read_text(encoding="utf-8"))
        PROM_BY_CODE = {k.upper(): v for k, v in (_pd.get("by_code") or {}).items()}
        PROM_BY_UID = {str(k): v for k, v in (_pd.get("by_uid") or {}).items()}
        print("推广人目录 %d 人 / %d 个码（来自 %s）"
              % (len(_pd.get("people") or []), len(PROM_BY_CODE),
                 _pd.get("generated_at")))
    else:
        print("⚠ 没有 data/promoter_dir.json，推广人姓名只能靠后台折扣码配置")

    # ---- 折扣码 → 不从某个推广人身上归属（历史归属纠错，2026-10-29 新增） ----
    # 背景：peach / lpa / 6exp6 三个码在后台折扣码配置里「归属账号」写的是尹岚，
    # 实际与尹岚无关（历史录入错误）。要求：**只从尹岚名下摘掉，订单照常计入总量**。
    # 配置在 data/promoter_code_detach.json，改这个文件即生效，不用动代码：
    #   {"not_owner": "尹岚", "codes": ["6exp6", "lpa", "peach"]}
    # 只挡 not_owner 这一个人：以后若 xlsx 里把码正确挂到别人名下，仍然照常归属。
    DETACH_CODES, DETACH_NAME = set(), ""
    _dp = DATA / "promoter_code_detach.json"
    if _dp.exists():
        _dt = json.loads(_dp.read_text(encoding="utf-8"))
        DETACH_NAME = (_dt.get("not_owner") or "").strip()
        DETACH_CODES = {str(c).strip().upper() for c in (_dt.get("codes") or []) if str(c).strip()}
        if DETACH_CODES:
            print("折扣码摘除名单 %d 个（不从「%s」归属）：%s"
                  % (len(DETACH_CODES), DETACH_NAME, ",".join(sorted(DETACH_CODES))))

    def detached(code_up, name):
        """这个码是否要把这个人摘掉（只针对 not_owner，其他人不受影响）。"""
        return bool(DETACH_NAME) and code_up in DETACH_CODES \
            and (name or "").strip() == DETACH_NAME


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
        """订单 → 推广人归属。**先认「人」，折扣码只是这个人的属性。**

        身份键（同一个人的多个码必须合并成一行）：
          uid:<会员id>   目录/后台配置能定位到会员 uid
          name:<姓名>    没有 uid 但知道姓名（目录姓名 / 后台归属账号昵称）
          code:<CODE>    只认得出码，姓名未知 → 推广人字段直接用折扣码
          none           自然流量

        取值优先级：
          1) 分销目录（xlsx）里该码绑了 uid → 认这个人
             例：FOCUS 在后台配置里 uid=0、归属账号「刘晓辰」，但目录写明属于耿凯翔(751377)
          2) 后台折扣码配置绑了会员 uid
          3) 目录里有姓名但没 uid（YOLLY/尹岚）、或后台配了归属账号（PEACH、LPA → 尹岚）
          4) 有 recommend_uid → 认推荐人（目录能查到姓名就用姓名）
          5) 只剩折扣码 → 推广人字段用折扣码
          6) 都没有 → 自然流量
        说明：直到 2026-10-17 前，折扣码按**大小写敏感**匹配（配置 FOCUS / 订单 focus 对不上），
        且没匹配上时会把 code 清空，导致 FOCUS 29 单、YOLLY 48 单凭空消失，已修。

        0) 例外：`data/promoter_code_detach.json` 里的码（peach / lpa / 6exp6）一旦指向
           not_owner（尹岚）就跳过 → 落到 4)/5)，推广人显示折扣码本身。订单照样计入
           总单量/总销售额，只是不挂在尹岚名下（2026-10-29 需求：历史归属录入错误）。
        """
        raw = (o.get("discount_code") or "").strip()
        up = raw.upper()
        rec = code2rec.get(up)
        canon = ((rec or {}).get("code") or raw).strip()   # 用配置里的规范写法（FOCUS 而非 focus）
        admin_nick = ((rec or {}).get("admins") or {}).get("nickname") or ""
        cfg_uid = int(rec.get("uid") or 0) if rec else 0
        d = PROM_BY_CODE.get(up) or {}
        d_uid = int(d.get("uid") or 0)
        d_name = (d.get("name") or "").strip()
        r_uid = int(o.get("recommend_uid") or 0)
        r_name = (PROM_BY_UID.get(str(r_uid)) or {}).get("name") or ""

        # 摘除码（peach / lpa / 6exp6）：后台「归属账号」写的是尹岚，实际无关 → 不认这个人
        if detached(up, admin_nick):
            admin_nick = ""

        if d_uid and not detached(up, d_name):           # 1) 目录优先
            return ("uid:%d" % d_uid, d_name or str(d_uid), "折扣码", canon, d_uid, admin_nick)
        if cfg_uid:                                      # 2) 后台配置绑定会员
            nm = d_name or (PROM_BY_UID.get(str(cfg_uid)) or {}).get("name") or str(cfg_uid)
            if not detached(up, nm):
                return ("uid:%d" % cfg_uid, nm, "折扣码", canon, cfg_uid, admin_nick)
        who = d_name or admin_nick                       # 3) 知道姓名但没 uid
        if who and not detached(up, who):
            return ("name:%s" % who, who,
                    "折扣码" if d_name else "折扣码归属账号", canon, 0, admin_nick)
        if r_uid:                                        # 4) 推荐人
            if r_name:
                return ("uid:%d" % r_uid, r_name, "推荐人", canon, r_uid, "")
            # 摘除码：宁可显示折扣码本身，也别把裸 uid 当成人名（和前端 nameOfKey 同口径）
            if up not in DETACH_CODES:
                return ("uid:%d" % r_uid, str(r_uid), "推荐人", canon, r_uid, "")
        if raw:                                          # 5) 只有码
            return ("code:%s" % canon, canon, "折扣码(未配置归属)", canon, 0, "")
        return ("none", "自然流量/无归属", "无归属", "", 0, "")



    conn = HDB.open_db()
    regions = sales_regions.load_verified(conn)
    conn.close()
    out_orders = []
    prom_meta = {}
    owner_meta = {}
    code_meta = {}
    orphan_sn = set(deliv_by_sn.keys())
    backfilled = 0        # 大区由发货记录回填的单数
    unknown_region = 0    # 两边都没有大区的单数
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
        area0, prod = parse_content(o.get("content"))
        region = region_of_area(area0) or region_of_delivery(ds) or (regions.get(sn, {}).get('region') if regions.get(sn, {}).get('area_key') == area0 else '')
        if region and not region_of_area(area0):
            backfilled += 1
        elif not region:
            region = "未标注"
            unknown_region += 1
        area = norm_area(area0, "" if region == "未标注" else region)
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
            "area": area, "region": region, "product": prod,
            "region_source": (regions.get(sn) or {}).get("source", ""),
            "deliv_n": len(ds), "qty": qty,
            "cost_cny": round(cost, 2), "sale_cny": round(sale, 2),
            "profit_cny": round(sale - cost, 2),
            "margin": round((sale - cost) / sale, 4) if sale > 0 else None,
            "supplier": ", ".join(suppliers), "operator": ", ".join(operators),
        })

    print("订单 %d 单；无发货记录 %d 单；发货孤立单号 %d 个"
          % (len(out_orders),
             sum(1 for r in out_orders if r["deliv_n"] == 0), len(orphan_sn)))
    print("大区：发货记录回填 %d 单；仍无大区 %d 单（%.1f%%）"
          % (backfilled, unknown_region,
             unknown_region * 100.0 / max(len(out_orders), 1)))

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
                       "codes": len(code2rec), "members": len(members),
                       "region_backfill": backfilled, "region_unknown": unknown_region},
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
