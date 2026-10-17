# -*- coding: utf-8 -*-
"""MSCW（冒险岛怀旧服）DD373 专区结构探针 —— 只读。

目的：定下
  ① 北美NA / 欧洲EU 两个子区的**可用 URL 形态**（短页 / 长页 / 综合排序链接）
  ② 分页能不能用（?PageIndex=N vs 长 URL 的页位）
  ③ 单价口径（元/万金？单位串是什么）+ 订单簿字段是否与 AION2 一致
  ④ 目标量换算（我方要 100 万金）

服务器上跑：
  /opt/d4follow/venv/bin/python /opt/d4follow/_p2pah_srv/_mscw_dd373_probe.py
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, "/opt/d4follow")
import core_dd373_cost as D  # noqa: E402

OUTDIR = "/opt/d4follow/_p2pah_srv/_mscw_dd373"
SID = "063g3j"
SEG_NA = "k5faqj"
SEG_EU = "sphpwv"
_VARIANTS = {
    "long_p1": "https://www.dd373.com/s-%s-46qwx3-%s-0-0-0-et9e1b-0-0-0-0-0-1-0-0-0.html",
    "short":   "https://www.dd373.com/s-%s-46qwx3-%s.html",
    "short2":  "https://www.dd373.com/s-%s-46qwx3-%s-0-0-0-et9e1b.html",
    "long_p2": "https://www.dd373.com/s-%s-46qwx3-%s-0-0-0-et9e1b-0-0-0-0-0-2-0-0-0.html",
    "pix2":    "https://www.dd373.com/s-%s-46qwx3-%s-0-0-0-et9e1b-0-0-0-0-0-1-0-0-0.html?PageIndex=2",
}


def probe(name, url, dump=True):
    print("\n" + "=" * 100)
    print("### %s\n%s" % (name, url))
    try:
        h = D._get(url, referer="https://www.dd373.com/", tries=2)
    except Exception as e:
        print("  ✗ 抓取失败：%r" % (e,))
        return None
    print("  字节 %d ｜ blocked=%s ｜ goods-list-item ×%d ｜ sell-btn-box=%s"
          % (len(h), D._blocked(h), h.count("goods-list-item"), "sell-btn-box" in h))
    if dump:
        try:
            if not os.path.isdir(OUTDIR):
                os.makedirs(OUTDIR)
            with io.open(os.path.join(OUTDIR, "%s.html" % name), "w",
                         encoding="utf-8", errors="ignore") as f:
                f.write(h)
        except Exception as e:
            print("  (dump 失败 %r)" % (e,))
    print("  站点统计:", D._site_stat(h))
    pf = D.parse_first(h)
    print("  parse_first:", json.dumps(pf, ensure_ascii=False) if pf else None)
    q = D._parse_quotes(h)
    print("  报价条数 %d；前 6 条:" % len(q))
    for t in q[:6]:
        print("     可供 %.0f 万 @ %.6f 元/%s" % (t[0], t[1], t[2]))
    ob = D.orderbook_avg(q, 100.0)
    if ob:
        print("  吃满 100 万金 → 均价 %.6f 元/万金（吃 %d/%d 条，可供 %.0f 万，够量 %s）"
              % (ob["均价"], ob["参与条数"], ob["报价条数"], ob["可供量"], ob["够量"]))
        print("     明细:", ob["明细"])
    else:
        print("  orderbook_avg(100) = None")
    ob2 = D.orderbook_avg(q, D.TARGET_WAN)
    if ob2:
        print("  吃满 10000 万金 → 均价 %.6f（可供 %.0f 万，够量 %s）"
              % (ob2["均价"], ob2["可供量"], ob2["够量"]))
    # 单位串 & 1元=？ 采样
    for _u in set(re.findall(r"<span>([^<]{1,12})</span>", h)) if False else []:
        pass
    un = set(re.findall(r'goods-icon-clear dn"></i>\s*<span>([^<]+)</span>', h))
    print("  单价单位串采样:", sorted(un)[:5])
    rt = re.findall(r'1</span>元=<span class="colorFF5">([\d.]+)</span>([^<]*)', h)
    print("  1元=X 采样:", rt[:3])
    return h


for _nm, _seg in (("NA", SEG_NA), ("EU", SEG_EU)):
    for _v in ("long_p1", "short", "short2"):
        probe("mscw_%s_%s" % (_nm, _v), _VARIANTS[_v] % (SID, _seg))

print("\n" + "=" * 100)
print("### 分页测试（NA）")
probe("mscw_NA_long_p2", _VARIANTS["long_p2"] % (SID, SEG_NA))
probe("mscw_NA_short2_pix2", _VARIANTS["pix2"] % (SID, SEG_NA))
print("\nDONE")
