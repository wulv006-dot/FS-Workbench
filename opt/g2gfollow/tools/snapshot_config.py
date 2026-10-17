# -*- coding: utf-8 -*-
"""从 d4follow 的 config.json 抽取本系统需要的部分，生成独立的 config.json。

为什么要「抽取」而不是直接读 d4follow 的 config
------------------------------------------------
本系统（G2G 金币改价）与 d4follow 要求**完全隔离**：
  · 独立目录 /opt/g2gfollow、独立进程、独立 SQLite、独立端口 8903；
  · 不读 d4follow 的任何运行时文件（只在本脚本里、一次性、只读地抽一份快照）。
抽出来的 config.json 只含 AION2 金币要用的东西（86 个服务区 + 汇率 + 定价参数），
体量从 1.3 MB 降到几十 KB，字段名与 d4follow 保持一致，便于日后人工比对。

用法：
    python tools/snapshot_config.py                 # 默认读 ../d4follow/config.json
    python tools/snapshot_config.py --src <path>    # 指定源
"""
import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # opt/g2gfollow
DEFAULT_SRC = os.path.join(os.path.dirname(ROOT), "d4follow", "config.json")
DST = os.path.join(ROOT, "config.json")

# 服务区只保留这几个字段（d4follow 里还有 后台行ID / 前端aid / iggm_sid 等，
# 那些是 d4follow 自己的链路标识，本系统用不到）
KEEP_SERVER_FIELDS = ["key", "中文名", "大区", "g2g_服务区", "eld_服务区", "g2g_dataset"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    a = ap.parse_args()
    if not os.path.isfile(a.src):
        print("× 源 config 不存在：%s" % a.src)
        return 1

    src = json.load(io.open(a.src, encoding="utf-8"))
    g = src.get("金币") or {}
    rate = float((src.get("汇率") or {}).get("USDCNY") or 6.65)

    servers = []
    for s in (g.get("服务区") or []):
        if s.get("游戏") != "AION2":
            continue
        if not s.get("g2g_服务区"):
            continue                                # 没挂 G2G 的区，本系统不管
        servers.append({k: s.get(k) for k in KEEP_SERVER_FIELDS})

    if not servers:
        print("× 源 config 里没有 AION2 + g2g_服务区 的条目")
        return 1

    out = {
        "_说明": ("G2G 金币改价系统（AION2 Kinah）独立配置。"
                  "由 tools/snapshot_config.py 从 d4follow/config.json 抽取，"
                  "运行时本系统不读 d4follow 任何文件。"),
        "版本": "2026-10-10",
        "source": os.path.relpath(a.src).replace("\\", "/"),
        "g2g": {
            "seller_id": "1003767531",
            "shop_name": "Loot_Supply",
            "api_base": "https://sls.g2g.com",
            "seo_term": "aion-2-kinah",
            "region_id_us": "dfced32f-2f0a-4df5-a218-1e068cfadffa",
            "my_offers_page_limit": 100,
            "token_file": "var/token.json",
            "token_max_age_sec": 900,               # accessToken 寿命 15 分钟
        },
        "定价": {
            "_口径": "目标挂牌价 $/M = DD373「买满 1 亿基纳的订单簿加权均价」÷ (1 − 利润率)",
            "利润率": 0.30,
            "闸门价_usd_per_m": 19.9,
            "目标采购量_万基纳": 10000,
            "小数位": 2,
            "_保护占位价说明": ("现价正好落在这些值时视为「标品占位价」不动它，"
                                "避免把不想卖的占位价误降到成本价。清空数组 = 关闭保护。"),
            "保护占位价": [],
        },
        "汇率": {"USDCNY": rate},
        "运行": {
            "端口": 8903,
            "采集超时秒": 30,
            "DD373请求间隔秒": 1.3,
            "写价间隔秒": 0.8,
        },
        "服务区": servers,
    }

    io.open(DST, "w", encoding="utf-8").write(
        json.dumps(out, ensure_ascii=False, indent=1))
    print(">>> 已生成 %s" % DST)
    print("    AION2 服务区 %d 个 | 汇率 %.4f | 利润率 %.0f%%（成本÷%.2f）| 闸门 $%.2f/M"
          % (len(servers), rate, out["定价"]["利润率"] * 100,
             1.0 - out["定价"]["利润率"], out["定价"]["闸门价_usd_per_m"]))
    from collections import Counter
    print("    大区分布：", dict(Counter(s["大区"] for s in servers)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
