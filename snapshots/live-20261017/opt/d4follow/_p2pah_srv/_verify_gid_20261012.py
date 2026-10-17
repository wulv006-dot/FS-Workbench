# -*- coding: utf-8 -*-
"""上线后验收（容器内只读，不写后台、不联网改价）。

证明三件事：
  ① 容器里 DEFAULT_CFG 指向的 /改造后v10/config.json **不存在** —— 这就是 2026-10-12
     07:44 那张 ARC 工单失败的直接原因（旧代码读不到 config 且静默吞异常）。
  ② 改后代码在「带 config」和「空 cfg」两种情况下都能解出 ARC Raiders = 864。
  ③ 老游戏（D4 / AION2 / MSCW）解析不回归；未登记游戏仍然抛错（不默认 456）。
"""
import json
import os
import sys

sys.path.insert(0, "/srv")
import p2pah_local as P  # noqa: E402

fails = []


def ck(name, cond, extra=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (("  " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


print("=== 0. 现场事实（烟雾弹的源头）===")
print("  p2pah_local       =", P.__file__)
print("  DEFAULT_CFG       =", P.DEFAULT_CFG)
ck("容器里 DEFAULT_CFG 指向的文件**不存在**（旧代码就是死在这）",
   not os.path.exists(P.DEFAULT_CFG))
print("  命令行 --config 实际值 =", "/srv/_cfg/config.json")
ck("/srv/_cfg/config.json 存在（服务器真正传给执行器的配置）",
   os.path.exists("/srv/_cfg/config.json"))

C = json.load(open("/srv/_cfg/config.json", encoding="utf-8"))

print("\n=== 1. ARC gid 解析 ===")
ck("gold_gid_of(真config, 'ARC Raiders') == 864",
   P.gold_gid_of(C, "ARC Raiders") == "864", P.gold_gid_of(C, "ARC Raiders"))
ck("gold_gid_of({}, 'ARC Raiders') == 864（内置表兜底）",
   P.gold_gid_of({}, "ARC Raiders") == "864", P.gold_gid_of({}, "ARC Raiders"))
ck("gold_gid_of({}, 'ARC') == 864",
   P.gold_gid_of({}, "ARC") == "864", P.gold_gid_of({}, "ARC"))
print("  gold_list_url(864) =", P.gold_list_url(P.gold_gid_of(C, "ARC Raiders")))
ck("列表页 URL 带上 gid=864", "gid=864" in P.gold_list_url("864"))

print("\n=== 2. 老游戏不回归 ===")
for g, want in (("D4", "456"), ("暗黑破坏神4", "456"), ("AION2", "826"),
                ("永恒之塔2", "826"), ("MSCW", "1300"),
                ("MapleStory Classic World", "1300"), ("冒险岛怀旧服", "1300")):
    try:
        got = P.gold_gid_of({}, g)
    except Exception as e:
        got = "EXC:%r" % e
    ck("%-28s → %s" % (g, want), got == want, "实得 %r" % got)

print("\n=== 3. 未登记游戏仍然抛错（绝不默认 456）===")
try:
    P.gold_gid_of({}, "XXX-NOT-EXIST")
    ck("未知游戏抛 KeyError", False, "竟然没抛错 —— 危险！")
except KeyError:
    ck("未知游戏抛 KeyError", True)

print("\n=== 4. 工单里的「游戏」字段与后台行ID 对得上 ===")
arc = ((C.get("p2pah") or {}).get("游戏") or {}).get("ARC") or {}
print("  config.p2pah.游戏.ARC =", json.dumps(arc, ensure_ascii=False))
ck("ARC.game_id == 864", str(arc.get("game_id")) == "864", arc.get("game_id"))
ck("行ID 含 19734/19736/19738",
   {s.get("id") for s in (arc.get("服务区") or [])} >= {"19734", "19736", "19738"},
   arc.get("服务区"))

print("\n=== 结果：FAIL %d %s ===" % (len(fails), fails))
sys.exit(1 if fails else 0)
