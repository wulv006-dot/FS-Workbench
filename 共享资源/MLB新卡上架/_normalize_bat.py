# -*- coding: utf-8 -*-
"""把 Windows 批处理脚本规范化为 cmd.exe 能可靠解析的字节序列。

为什么需要这一步（两次踩坑，务必读注释再改）：
  坑 1 —— 换行符：.bat 里如果只有 LF（Unix 换行），cmd.exe 的解析器会出现
        标签跳转偏移、if/for 块提前闭合、甚至整段静默不执行，
        表现就是「双击没反应，也没弹窗」。

  坑 2 —— 编码与 BOM（本工具此前引入的回归，2026-10-05 修复）：
        cmd.exe 读取 .bat 时用的是**控制台代码页**（中文 Windows 是 936/GBK），
        不是 UTF-8。由此产生两个连锁故障：
          a) 写了 UTF-8 BOM → 首行变成 `锘絖echo off`，cmd 找不到这条命令，
             于是 `echo off` 从未生效，整个脚本的命令被逐行回显刷屏；
          b) 在 GBK 机器上执行 `chcp 65001` → cmd 的字节偏移与字符解码
             错位，多字节文本被拦腰截断，产出 `setpass`、`'etpass' is not
             recognized`、`◆◆` 这类完全不知所云的报错。
        根子在于：把中文写进 bat 本身就是雷区。

因此本工具现在的策略是**釜底抽薪**：
  1) 强制纯 7-bit ASCII —— bat 里一个非 ASCII 字符都没有；
  2) 强制 CRLF 换行；
  3) **绝不写 BOM**（BOM 是坑 2a 的直接元凶）；
  4) 禁止在 bat 里出现 chcp（中文输出交给 Python 处理，
     mlb_agent.py 内部已用 reconfigure + SetConsoleOutputCP 自行对齐 UTF-8）；
  5) 出现非 ASCII 内容直接报错退出，而不是"尽力转换"。

用法：
  python _normalize_bat.py <文件路径> [<文件路径> ...]
"""
import sys
import os

BAT_EXT = (".bat", ".cmd")
BOM = b"\xef\xbb\xbf"

# 这些指令在纯 ASCII bat 里也不该出现（chcp 会改变代码页，
# 即使文件是纯 ASCII 也不必要，只会引入不确定性）
FORBIDDEN = ("chcp ",)


def normalize(path):
    with open(path, "rb") as f:
        raw = f.read()

    before_crlf = raw.count(b"\r\n")
    before_lf = raw.count(b"\n") - before_crlf

    # 1) 去掉可能存在的 BOM，只为看清真实内容
    had_bom = raw.startswith(BOM)
    if had_bom:
        raw = raw[len(BOM):]

    # 2) 尝试解码出文本（用于校验 ASCII 纯净度）
    text = None
    for enc in ("utf-8", "gbk", "cp936", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise SystemExit("[X] 无法解码：%s" % path)

    # 3) 换行统一为 CRLF
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", "\r\n")

    # 4) 校验：必须是纯 ASCII
    non_ascii = []
    for i, line in enumerate(text.split("\r\n"), 1):
        try:
            line.encode("ascii")
        except UnicodeEncodeError:
            bad = [c for c in line if ord(c) > 127]
            non_ascii.append((i, "".join(bad[:12]), line.strip()[:60]))

    if non_ascii:
        print("[X] %s 含非 ASCII 字符，cmd.exe 会解析错乱" % os.path.basename(path))
        for i, chars, snippet in non_ascii[:10]:
            print("     第 %d 行: %r  |  %s" % (i, chars, snippet))
        if len(non_ascii) > 10:
            print("     ... 另有 %d 行" % (len(non_ascii) - 10))
        raise SystemExit(
            "[X] 规范化中止：请把中文提示移到 .py 里输出，bat 只留 ASCII。")

    # 5) 校验：不得出现 chcp
    low = text.lower()
    for bad_cmd in FORBIDDEN:
        if bad_cmd in low:
            raise SystemExit(
                "[X] bat 里不应出现 %r：它会改变代码页，"
                "中文输出请交给 Python。" % bad_cmd.strip())

    # 6) 输出：纯 ASCII，CRLF，无 BOM
    out = text.encode("ascii")

    with open(path, "wb") as f:
        f.write(out)

    after_crlf = out.count(b"\r\n")
    after_lf = out.count(b"\n") - after_crlf
    print("[OK] %s" % os.path.basename(path))
    print("     换行: CRLF %d / 裸LF %d  ->  CRLF %d / 裸LF %d"
          % (before_crlf, before_lf, after_crlf, after_lf))
    print("     BOM: %s  ->  False" % ("有(已移除)" if had_bom else "无"))
    print("     编码: 纯 ASCII (7-bit), %d bytes" % len(out))
    if after_lf != 0:
        raise SystemExit("[X] 仍存在裸 LF，规范化失败")
    if out.startswith(BOM):
        raise SystemExit("[X] 仍带 BOM，规范化失败")


def main():
    files = sys.argv[1:]
    if not files:
        raise SystemExit(__doc__)
    for p in files:
        if not os.path.isfile(p):
            print("[!] 跳过（不存在）：%s" % p)
            continue
        if not p.lower().endswith(BAT_EXT):
            print("[!] 跳过（非 bat/cmd）：%s" % p)
            continue
        normalize(p)


if __name__ == "__main__":
    main()
