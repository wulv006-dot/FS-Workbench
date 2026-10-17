#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AION2 金币改价：DD373 进货成本加价比例 20% -> 25%（只动这一个值 + 两处"当前值"文案）。

背景：dd373_only 模式口径 = 目标售价 $/M = DD373 该区进货成本 $/M × (1 + 加价比例)。
      老板 2026-10-07 二次定案：加价比例 0.2 -> 0.25（比进货价高 25% 出售），其余全部不变。

用法：
    python3 patch_aion2_markup25.py --dry           # 只演练，不写
    python3 patch_aion2_markup25.py                 # 写 /opt/d4follow/config.json
    python3 patch_aion2_markup25.py --file=<路径>   # 换文件（本地演练用）

安全：
  * 字节级定点替换（读文本无损），**不整份 json.dumps 重写** -> 行尾/缩进/其它字段一字节不动；
  * 替换前断言目标串**恰好出现 1 次**；
  * 写回后重新 json 解析 + 逐项断言（生效值变了、其余关键字段一个没变），失败自动还原。
"""
import io
import json
import shutil
import sys
import time

DEFAULT_CFG = "/opt/d4follow/config.json"

OLD = '"加价比例": 0.2'
NEW = '"加价比例": 0.25'
OLD_NOTE = "当前加价比例 = 0.2（+20%）"
NEW_NOTE = "当前加价比例 = 0.25（+25%）"
OLD_NOTE2 = "×(1+加价 20%)"
NEW_NOTE2 = "×(1+加价 25%)"


def load(path):
    return io.open(path, encoding="utf-8", newline="").read()


def changed_spans(a, b):
    """返回 [(旧起点, 旧终点, 新终点)] —— 前后缀扫描，避免 difflib 在百万字符文本上 O(n^2)。"""
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    j = 0
    while j < n - i and a[len(a) - 1 - j] == b[len(b) - 1 - j]:
        j += 1
    return [(i, len(a) - j, len(b) - j)]


def deep_diff(x, y, path=()):
    """递归找出两个已解析 JSON 的所有差异路径（用于证明"其余一字未动"）。"""
    out = []
    if isinstance(x, dict) and isinstance(y, dict):
        for k in sorted(set(x) | set(y), key=str):
            if k not in x or k not in y:
                out.append(path + (k,))
            else:
                out += deep_diff(x[k], y[k], path + (k,))
    elif isinstance(x, list) and isinstance(y, list):
        if len(x) != len(y):
            out.append(path)
        else:
            for i, (u, v) in enumerate(zip(x, y)):
                out += deep_diff(u, v, path + (i,))
    elif x != y:
        out.append(path)
    return out


def main():
    dry = "--dry" in sys.argv
    cfg = DEFAULT_CFG
    for a in sys.argv[1:]:
        if a.startswith("--file="):
            cfg = a.split("=", 1)[1]

    raw = load(cfg)
    n = raw.count(OLD)
    print("目标文件 : %s" % cfg)
    print("文件大小 : %d 字符" % len(raw))
    print("目标串 %r 出现 %d 次" % (OLD, n))
    if n != 1:
        print("!! 要求恰好 1 次，中止，未做任何改动。")
        return 2

    out = raw.replace(OLD, NEW, 1)
    note_hit = OLD_NOTE in out
    if note_hit:
        out = out.replace(OLD_NOTE, NEW_NOTE, 1)
    n2 = out.count(OLD_NOTE2)
    note2_hit = (n2 == 1)
    if note2_hit:
        out = out.replace(OLD_NOTE2, NEW_NOTE2, 1)
    print("说明文案1 : %s（'当前加价比例 = ...' 描述）" % ("已同步" if note_hit else "未找到"))
    print("说明文案2 : %s（'×(1+加价 ...)' 出现 %d 次）"
          % ("已同步" if note2_hit else "跳过", n2))

    spans = changed_spans(raw, out)
    print("改动段数 : %d" % len(spans))
    for i1, i2, j2 in spans:
        print("   旧 : ...%r..." % raw[max(0, i1 - 50):i2 + 50])
        print("   新 : ...%r..." % out[max(0, i1 - 50):j2 + 50])

    # ---- 断言：新内容必须合法且只有期望的变化 ----
    b = json.loads(raw)
    a = json.loads(out)
    pa = a["金币"]["定价策略"]

    ok = True
    _paths = set(deep_diff(b, a))
    print("深层差异路径 : %s" % sorted(_paths, key=str))
    checks = [
        ("生效值 加价比例 0.2 -> 0.25", pa.get("加价比例") == 0.25),
        ("模式仍为 dd373_only", pa.get("模式") == "dd373_only"),
        ("适用游戏仍为 ['AION2']", pa.get("适用游戏") == ["AION2"]),
        ("次源仍为 G2G", pa.get("次源") == "G2G"),
        ("次源加价仍为 0.02", pa.get("次源加价") == 0.02),
        ("默认售价仍为 9.9", pa.get("默认售价_USD每M") == 9.9),
        ("无货兜底仍为 19.9", pa.get("无货兜底售价_USD每M") == 19.9),
        ("无货最小可买仍为 10000", pa.get("无货最小可买万基纳") == 10000),
        ("下浮比例仍为 0.03", pa.get("下浮比例") == 0.03),
        ("成本源/换算/顺延链 未动",
         pa.get("成本源") == b["金币"]["定价策略"].get("成本源")
         and pa.get("换算") == b["金币"]["定价策略"].get("换算")
         and pa.get("顺延链") == b["金币"]["定价策略"].get("顺延链")),
        ("归档旧值 0.05 未被误改",
         pa["已归档"]["DD373加价_20261002"]["加价比例"] == 0.05),
        ("整体 JSON 仅 加价比例(及两处说明文案) 不同",
         _paths <= {("金币", "定价策略", "加价比例"),
                    ("金币", "定价策略", "_dd373_only说明"),
                    ("金币", "定价策略", "可切换模式", "dd373_only")}
         and ("金币", "定价策略", "加价比例") in _paths),
    ]
    for name, res in checks:
        print("   [%s] %s" % ("OK" if res else "FAIL", name))
        ok = ok and res
    if not ok:
        print("!! 断言失败，未写入。")
        return 1

    if dry:
        print("\n--dry：演练通过，未写文件。")
        return 0

    bak = "%s.bak_%s" % (cfg, time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(cfg, bak)
    print("\n已备份 -> %s" % bak)

    io.open(cfg, "w", encoding="utf-8", newline="").write(out)

    chk = json.load(open(cfg, encoding="utf-8"))
    got = chk["金币"]["定价策略"]["加价比例"]
    note_now = "当前加价比例 = 0.25（+25%）" in load(cfg)
    if got != 0.25:
        shutil.copy2(bak, cfg)
        print("!! 读回失败（加价比例 = %r），已用备份还原。" % got)
        return 1
    print("读回校验 : 加价比例 = %s，说明文案已同步 = %s" % (got, note_now))
    print("完成。需重启服务生效：systemctl restart d4follow")
    return 0


if __name__ == "__main__":
    sys.exit(main())
