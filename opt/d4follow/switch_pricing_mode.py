#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金币定价策略切换器（dd373_only ⇄ g2g_cheapold ⇄ dd373_markup ⇄ multisrc）—— 幂等、只改一个字段。

用法（服务器上）：
    # 切到「只跟 DD373 进货成本 +7%」（老板 2026-10-06 起的现行策略）
    python3 /opt/d4follow/switch_pricing_mode.py dd373_only

    # 切回「G2G cheapold 跟价」（2026-10-05 策略）
    python3 /opt/d4follow/switch_pricing_mode.py g2g_cheapold

    # 一键复活旧三源比价（基准=min(G2G,ELD)，让价 2%）
    python3 /opt/d4follow/switch_pricing_mode.py multisrc

    # 只看当前状态，不改
    python3 /opt/d4follow/switch_pricing_mode.py --show

⚠ 本脚本用 json.dumps 整份重写 config ⇒ **行尾会从 CRLF 全变 LF**（diff 出几万行）。
  只切换模式时用它没问题；**要在原文件上做定点改动，请用字节级补丁脚本**（读 rb / 写 wb）。

为什么单独一个脚本：
  patch_pricing_mode.py 是**首次上线时**用的补丁（硬编码写 dd373_markup，
  还会顺手整理多源采集开关），它**不接受 --mode 参数**，不能用来复活旧策略。
  切回旧策略只需改 定价策略.模式 一个字段，代码 core_gold.pricing_policy()
  两套口径都在，无需回滚文件、无需改代码。

安全：
  ① 先单独备份 config.json 到 _rollback_20261002_DD373定价/ 并打印 md5
  ② 只写 模式 这一个 key，其余字节原样保留（保留用户改过的开关）
  ③ 写回后重新读回断言，失败自动用备份还原
"""
import io
import json
import os
import shutil
import sys
import time

CFG = os.environ.get("D4_CFG", "/opt/d4follow/config.json")
BACKUP_DIR = "/opt/d4follow/_rollback_20261002_DD373定价"
VALID = ("dd373_only", "g2g_cheapold", "dd373_markup", "multisrc")


def show(c):
    g = c.get("金币") or {}
    p = g.get("定价策略") or {}
    print("=" * 72)
    print("config          : %s" % CFG)
    print("定价策略.模式    : %s" % p.get("模式"))
    print("适用游戏        : %s" % (p.get("适用游戏") or []))
    print("加价比例        : %s" % p.get("加价比例"))
    print("无货兜底售价    : %s USD/M（dd373_only：无报价或可买量 < 无货最小可买万基纳）"
          % (p.get("无货兜底售价_USD每M") if p.get("无货兜底售价_USD每M") is not None else 19.9))
    print("无货最小可买    : %s 万基纳（默认 20000 = 2 亿）"
          % (p.get("无货最小可买万基纳") if p.get("无货最小可买万基纳") is not None else 20000))
    print("下浮比例        : %s（g2g_cheapold 用）" % p.get("下浮比例"))
    print("利润率下限      : %s（g2g_cheapold 兜底；低于它就把目标抬到 成本÷(1+下限)）"
          % (p.get("利润率下限") if p.get("利润率下限") is not None else -0.1))
    print("成本兜底        : 基准价 < DD373 成本价（买满 2 亿订单簿加权）⇒ 按成本价定价（不下浮）")
    print("cheapold卖家    : %s" % p.get("cheapold卖家"))
    print("次源 / 次源加价  : %s / %s" % (p.get("次源"), p.get("次源加价")))
    print("默认售价_USD每M : %s" % p.get("默认售价_USD每M"))
    print("多源基准.启用    : %s（G2G/ELD/IGGM 是否照旧采集）" % (g.get("多源基准") or {}).get("启用"))
    for i, s in enumerate(p.get("顺延链") or [], 1):
        print("   顺延%d: %s" % (i, s))
    arc = p.get("已归档") or {}
    if arc.get("多源比价_20261001"):
        a = arc["多源比价_20261001"]
        print("已归档旧策略    : multisrc（让价 %s%%）" % a.get("让价百分比"))
    print("可切换模式      : %s" % list((p.get("可切换模式") or {}).keys()))
    print("=" * 72)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--show" in sys.argv or not args:
        show(json.load(open(CFG, encoding="utf-8")))
        return 0

    mode = args[0].strip()
    if mode not in VALID:
        print("模式只能是：%s（收到 %r）" % (" / ".join(VALID), mode))
        return 2

    c = json.load(open(CFG, encoding="utf-8"))
    pol = (c.get("金币") or {}).get("定价策略") or {}
    old = pol.get("模式")
    if old == mode:
        print("已经是 %s，无需改动。" % mode)
        show(c)
        return 0

    # ① 备份（单独一步，落地后由调用方核对 md5）
    # os.path.join 在 Windows 上会拼出混合分隔符，这里显式用 posix 风格，
    # 保证在 Linux 生产与 Windows 本地演练时路径都干净。
    bdir = BACKUP_DIR.rstrip("/\\").replace("\\", "/")
    os.makedirs(bdir, exist_ok=True)
    bak = "%s/config.before_switch_%s.json" % (
        bdir, time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(CFG, bak)
    print("已备份 -> %s" % bak)

    # ② 只改一个 key
    raw = io.open(CFG, encoding="utf-8", newline="").read()
    c["金币"]["定价策略"]["模式"] = mode
    out = json.dumps(c, ensure_ascii=False, indent=2)
    io.open(CFG, "w", encoding="utf-8", newline="").write(out)

    # ③ 读回断言，坏了就还原
    chk = json.load(open(CFG, encoding="utf-8"))
    got = (chk.get("金币") or {}).get("定价策略", {}).get("模式")
    if got != mode:
        shutil.copy2(bak, CFG)
        print("写入校验失败（%r != %r），已用备份还原。" % (got, mode))
        return 1

    print("定价策略.模式：%s -> %s" % (old, mode))
    if mode == "multisrc":
        print("提示：旧口径基准 = min(G2G,ELD)，目标价 = 基准 ×(1-让价%)；"
              "让价比例在 定价策略.已归档.多源比价_20261001.让价百分比（默认 2.0）。")
    if mode == "g2g_cheapold":
        print("提示：新口径 = 每个子服务器 G2G cheapold 价（无则推荐前二较低者）"
              "× (1−下浮比例，默认 3%%)；需 config.金币.服务区[].g2g_dataset 已填。")
    if mode == "dd373_only":
        print("提示：新口径 = DD373 该区进货成本（买满 2 亿订单簿加权）× (1+加价比例，默认 7%%)；"
              "DD373 无报价或可买量 < 2 亿的区统一挂 $19.9/M。"
              "需 app 每轮注入 DD373 成本（进货成本.启用=true），且"
              "config.金币.定价策略 里有 加价比例 / 无货兜底售价_USD每M / 无货最小可买万基纳。")
    if mode == "dd373_markup":
        print("提示：DD373 口径需 app 每轮注入 DD373 成本（进货成本.启用=true）。")
    print("提示：config 改动需重启 d4follow 才生效：systemctl restart d4follow")
    show(chk)
    return 0


if __name__ == "__main__":
    sys.exit(main())
