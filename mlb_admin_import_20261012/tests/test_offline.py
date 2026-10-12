# -*- coding: utf-8 -*-
"""离线自检：不连网络、不需要凭据，验证纯逻辑正确性。

跑法：
  python tests/test_offline.py
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
sys.path.insert(0, str(SRC))

from admin_api_client import _multipart, SCOPE_MLB26_PLAYERS, SCOPE_FC27_PLAYERS  # noqa: E402
import mlb_admin_import as M  # noqa: E402

FAIL = []


def check(name, cond, extra=""):
    print(("  [OK] " if cond else "  [FAIL] ") + name + (" — " + str(extra) if extra else ""))
    if not cond:
        FAIL.append(name)


print("=== 1. multipart 构造 ===")
body, ctype = _multipart({"gid": 927, "cid": 8233}, "xlsFile", "x.xlsm", b"PK\x03\x04data")
check("content-type 是 multipart", ctype.startswith("multipart/form-data; boundary="), ctype)
check("含 gid 字段", b'name="gid"' in body and b"927" in body)
check("含 cid 字段", b'name="cid"' in body and b"8233" in body)
check("文件字段名 = xlsFile", b'name="xlsFile"' in body, )
check("含文件名", b'filename="x.xlsm"' in body)
check("含文件内容", b"PK\x03\x04data" in body)
check("以结束边界收尾", body.rstrip().endswith(b"--"))

print("=== 2. scope 常量 ===")
check("MLB scope gid=927", SCOPE_MLB26_PLAYERS["gid"] == 927, SCOPE_MLB26_PLAYERS)
check("MLB scope cid=8233", SCOPE_MLB26_PLAYERS["cid"] == 8233)
check("FC27 scope 未被改动", SCOPE_FC27_PLAYERS == {"gid": 1327, "cid": 9627})

print("=== 3. 产品名归一化（幂等比对用）===")
check("大小写归一", M._name_key("Rafael Flores/99/SP/Pirates/Spotlight")
      == M._name_key("rafael flores/99/sp/pirates/spotlight"))
check("空格归一", M._name_key("A  B/C") == M._name_key("AB/C"), M._name_key("A  B/C"))
check("不同球员不误判", M._name_key("Mike Trout/99/CF/Angels/Awards")
      != M._name_key("Trevor Rogers/99/SP/Orioles/Spotlight"))

print("=== 4. 表头常量 ===")
check("16 列表头", len(M.HEADERS) == 16, len(M.HEADERS))
check("第4列=产品名称", M.HEADERS[3] == "产品名称")
check("第16列=分类ID", M.HEADERS[15] == "分类ID（勿改）")

print("=== 5. apply 保护闸 ===")
try:
    rc = M.main(["--action", "apply", "--xlsm", "nope.xlsm", "--user", "u", "--password", "p"])
    check("apply 无 --confirm 被拦", False, "竟然返回 %r" % rc)
except SystemExit as e:
    check("apply 无 --confirm 被拦", "confirm" in str(e).lower() or "确认" in str(e), str(e))
except Exception as e:
    check("apply 无 --confirm 被拦", False, repr(e))

print("=== 6. xlsm 解析（用真实成品文件）===")
cand = [
    HERE.parent.parent / "docs/planning/mlb-admin-api-feasibility-20261012/out_20261012.xlsm",
    Path(os.path.expanduser("~/MLB新卡上架/mould-create_gid927_20261005102322.xlsx")),
]
found = next((p for p in cand if p.is_file()), None)
if found:
    rows = M.read_xlsm_rows(found)
    check("解析出 15 行", len(rows) == 15, "%d 行 @ %s" % (len(rows), found.name))
    names = [r["product_name"] for r in rows]
    check("含 Pettitte（今早新卡）", any("Pettitte" in n for n in names))
    check("含 Eckersley（今早新卡）", any("Eckersley" in n for n in names))
    check("分类ID=8233", all(str(r["category_id"]) == "8233" for r in rows))
    print("    样例：", names[0] if names else "(空)")
else:
    print("  [SKIP] 找不到样例 xlsm，跳过")

print()
if FAIL:
    print("结果：%d 项失败 -> %s" % (len(FAIL), FAIL))
    sys.exit(1)
print("结果：全部通过 ✅")
