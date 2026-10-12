# -*- coding: utf-8 -*-
"""打包执行器为 agent.zip（供网页「下载执行器压缩包」链接使用）。

产物：web/files/agent.zip
结构：
  mlb_agent/
    mlb_agent.py
    requirements.txt
    README.md
    启动执行器.bat

入包前的强制自检（2026-10-05 起因「用户双击后满屏乱码」事故）：
  cmd.exe 读取 .bat 用的是**控制台代码页**（中文 Windows 为 936/GBK），
  不是 UTF-8。因此包里的 bat 必须满足三条硬约束，否则用户那边必炸：
    1. 纯 7-bit ASCII —— bat 里一个非 ASCII 字符都没有
    2. CRLF 换行，且裸 LF 为 0
    3. **不带 BOM** —— BOM 会让首行 `@echo off` 变成 `锘絖echo off`，
       cmd 找不到该命令 ⇒ echo 永远没关 ⇒ 全屏命令回显
  这三条任何一条不满足，本脚本直接 SystemExit，拒绝出包。
"""
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT = os.path.join(HERE, "client")
OUT_DIR = os.path.join(HERE, "web", "files")
OUT = os.path.join(OUT_DIR, "agent.zip")

FILES = ["mlb_agent.py", "requirements.txt", "README.md", "启动执行器.bat"]

BOM = b"\xef\xbb\xbf"

sys.path.insert(0, HERE)

os.makedirs(OUT_DIR, exist_ok=True)
if os.path.exists(OUT):
    os.remove(OUT)

# 入包前先把 bat 规范化（纯 ASCII + CRLF + 去 BOM）。
# 注意：这里**不允许** try/except 吞掉异常 —— 规范化失败必须中止出包，
# 否则等于把已知有问题的字节流到用户手上（这正是 2026-10-05 那次事故的成因）。
from _normalize_bat import normalize

for fn in FILES:
    if fn.lower().endswith((".bat", ".cmd")):
        p = os.path.join(CLIENT, fn)
        if not os.path.exists(p):
            raise SystemExit("[X] 缺少 %s，无法出包" % fn)
        normalize(p)

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for fn in FILES:
        p = os.path.join(CLIENT, fn)
        if not os.path.exists(p):
            print("[!] 缺失，跳过：%s" % fn)
            continue
        z.write(p, "mlb_agent/%s" % fn)
        print("[OK] 加入 %-24s (%d bytes)" % (fn, os.path.getsize(p)))

# ---- 出包后硬自检：三条硬约束逐条验 ----
print("-" * 56)
with zipfile.ZipFile(OUT) as z:
    for fn in FILES:
        if not fn.lower().endswith((".bat", ".cmd")):
            continue
        raw = z.read("mlb_agent/%s" % fn)

        crlf = raw.count(b"\r\n")
        lf = raw.count(b"\n") - crlf
        has_bom = raw.startswith(BOM)
        non_ascii = [b for b in raw if b > 127]

        print("包内 %s 自检：" % fn)
        print("   纯 ASCII   : %s  (非 ASCII 字节 %d 个)"
              % ("OK" if not non_ascii else "FAIL", len(non_ascii)))
        print("   CRLF 换行  : %s  (CRLF=%d 裸LF=%d)"
              % ("OK" if lf == 0 and crlf > 0 else "FAIL", crlf, lf))
        print("   无 BOM     : %s" % ("OK" if not has_bom else "FAIL"))

        if lf != 0 or crlf == 0:
            raise SystemExit("[X] 包内 bat 换行不合格，拒绝出包")
        if has_bom:
            raise SystemExit(
                "[X] 包内 bat 带 BOM，cmd 会把首行读成乱码导致 echo off 失效，拒绝出包")
        if non_ascii:
            raise SystemExit(
                "[X] 包内 bat 含非 ASCII 字节（%d 个），"
                "cmd 按 GBK 解析会错乱，拒绝出包" % len(non_ascii))

size = os.path.getsize(OUT)
print("-" * 56)
print("[+] 打包完成：%s" % OUT)
print("    大小：%d bytes (%.1f KB)" % (size, size / 1024.0))
