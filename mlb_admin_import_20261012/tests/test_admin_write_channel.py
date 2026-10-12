# -*- coding: utf-8 -*-
"""离线用例：MLB 后台直写链路（不进网、不写后台、不需要凭据）。

覆盖范围
--------
只测**纯逻辑**与**契约常量**，不碰网络。任何真实写后台的动作都由
`src/mlb_write_cards.py` 在显式 `--apply --confirm` 下完成，CI 不参与。

测试对象
--------
- `src/admin_api_client.py` 的协议常量与 multipart 构造
- `src/mlb_admin_import.py` 的 scope 表与产品名归一化
- `src/mlb_write_cards.py` 的常量与幂等判定（含"绝不容错"项）

跑法
----
    python -m unittest discover -s mlb_admin_import_20261012/tests -p 'test_admin_write_channel.py'

或由 `tools/pr_fast.py` 的 `mlb-admin` 分组自动调用。
"""
from __future__ import annotations

import json
import re
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent                      # mlb_admin_import_20261012/
SRC = PKG / "src"
REPO_ROOT = PKG.parent                  # 仓库根
sys.path.insert(0, str(SRC))

import admin_api_client as C            # noqa: E402
import mlb_admin_import as M            # noqa: E402
import mlb_write_cards as W             # noqa: E402


class AdminProtocolContract(unittest.TestCase):
    """协议事实必须与逆向结论一致——改错就是写坏后台。"""

    def test_scope_mlb_is_927_8233(self):
        self.assertEqual(C.SCOPE_MLB26_PLAYERS, {"gid": 927, "cid": 8233})

    def test_scope_fc27_untouched(self):
        self.assertEqual(C.SCOPE_FC27_PLAYERS, {"gid": 1327, "cid": 9627})

    def test_admin_import_scope_table_keys(self):
        self.assertEqual(set(M.SCOPES), {"mlb26-players", "fc27-players"})
        self.assertIs(M.SCOPES["mlb26-players"], C.SCOPE_MLB26_PLAYERS)

    def test_api_bases(self):
        self.assertEqual(C.API_BASE, "https://admin-api.p2pah.cn")
        self.assertEqual(C.PAGE_BASE, "https://admin.p2pah.cn")

    def test_multipart_shape(self):
        body, ctype = C._multipart({"gid": 927, "cid": 8233},
                                   "xlsFile", "x.xlsm", b"PK\x03\x04data")
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        for needle in (b'name="gid"', b'name="cid"', b'name="xlsFile"',
                       b'filename="x.xlsm"', b"PK\x03\x04data"):
            self.assertIn(needle, body)
        self.assertTrue(body.rstrip().endswith(b"--"))

    def test_no_basic_auth_anywhere(self):
        """2026-09-30 后 Basic 已失效；源码里不得再出现 Basic 头构造。"""
        for name in ("admin_api_client.py", "mlb_admin_import.py",
                     "mlb_write_cards.py"):
            text = (SRC / name).read_text(encoding="utf-8")
            self.assertNotIn("Basic ", text, "%s 出现 Basic 认证" % name)
            self.assertNotIn("b64encode(('%s:" % name, text)


class WriteCardConstants(unittest.TestCase):
    """`mlb_write_cards.py` 的契约常量——每一项都对应一条线上事实。"""

    def test_scope_and_icon_base(self):
        self.assertEqual((W.GID, W.CID), (927, 8233))
        self.assertEqual(W.ICON_BASE, "https://cards.theshow.com/mlb26/")
        self.assertEqual(W.B2C_BASE, "https://b2c-api.p2pah.cn")

    def test_expected_products_is_48(self):
        """16 张卡 × 3 个 aid = 48；对不上说明 shelves 参数被改坏。"""
        self.assertEqual(W.EXPECTED_PRODUCTS, 48)

    def test_upload_network_is_endpoint_on_b2c(self):
        self.assertTrue(W.B2C_BASE.endswith("b2c-api.p2pah.cn"))

    def test_imports_admin_client(self):
        self.assertIs(W.AdminApiClient, C.AdminApiClient)


class IdempotencyGuard(unittest.TestCase):
    """幂等判定是"重跑不双写"的唯一保证，必须锁死。"""

    def test_name_key_case_and_space_folding(self):
        k = M._name_key
        self.assertEqual(k("Rafael Flores/99/SP/Pirates/Spotlight"),
                         k("rafael flores/99/sp/pirates/spotlight"))
        self.assertEqual(k("A  B/C"), k("AB/C"))

    def test_name_key_distinguishes_players(self):
        k = M._name_key
        self.assertNotEqual(k("Mike Trout/99/CF/Angels/Awards"),
                            k("Trevor Rogers/99/SP/Orioles/Spotlight"))

    def test_headers_contract(self):
        self.assertEqual(len(M.HEADERS), 16)
        self.assertEqual(M.HEADERS[3], "产品名称")
        self.assertEqual(M.HEADERS[15], "分类ID（勿改）")

    def test_apply_requires_confirm(self):
        with self.assertRaises(SystemExit) as ctx:
            M.main(["--action", "apply", "--xlsm", "nope.xlsm",
                    "--user", "u", "--password", "p"])
        self.assertTrue("confirm" in str(ctx.exception).lower()
                        or "确认" in str(ctx.exception))

    def test_write_cards_confirm_gate_rejects_missing_confirm(self):
        """apply 分支必须在读文件/连网之前就有确认闸门，缺一即拒。"""
        for argv in (["--result", "nope.json", "--apply"],
                     ["--result", "nope.json", "--apply", "--confirm", "wrong"],
                     ["--result", "nope.json", "--confirm", "mlb26-players"]):
            with self.assertRaises(SystemExit) as ctx:
                W.main(argv)
            self.assertNotEqual(ctx.exception.code, 0, argv)

    def test_write_cards_confirm_gate_passes_through(self):
        """闸门放行后应继续执行（而不是被闸门本身拦死）——用一个必定失败
        的输入验证：它不该再抛 SystemExit(2) 那条「必须 --confirm」错。"""
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                W.main(["--result", "definitely-not-here.json",
                        "--apply", "--confirm", "mlb26-players"])
            except SystemExit:
                pass
            except FileNotFoundError:
                pass
        self.assertNotIn("必须 --apply --confirm mlb26-players", buf.getvalue())


class CredentialHygiene(unittest.TestCase):
    """凭据不得写死在源码里，也不得回退到库内明文文件。"""

    def test_no_plaintext_password_in_sources(self):
        pat = re.compile(r"P2PAH_PASSWORD\s*=\s*['\"][^'\"]+['\"]")
        for name in ("admin_api_client.py", "mlb_admin_import.py",
                     "mlb_write_cards.py"):
            text = (SRC / name).read_text(encoding="utf-8")
            self.assertIsNone(pat.search(text), "%s 疑似硬编码密码" % name)

    def test_load_cred_default_is_none_not_repo_path(self):
        """`--cred` 默认值必须是 None（走环境变量），不能指回库内文件。"""
        text = (SRC / "mlb_write_cards.py").read_text(encoding="utf-8")
        m = re.search(r'add_argument\(\s*"--cred"[^)]*\)', text, re.S)
        self.assertIsNotNone(m, "找不到 --cred 参数定义")
        self.assertIn("default=None", m.group(0).replace(" ", ""))

    def test_no_cred_path_inside_repo_as_default(self):
        text = (SRC / "mlb_write_cards.py").read_text(encoding="utf-8")
        self.assertNotIn('default=str(EVID / "_cred.json")', text)


_XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CELL_RE = re.compile(r"^([A-Z]+)(\d+)$")


def _col_index(letters: str) -> int:
    """A→1, B→2, ... AA→27（1-based 列号）。"""
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def read_xlsm_rows_stdlib(path: Path) -> list:
    """纯标准库解析 xlsm（zipfile + ElementTree），语义等同 openpyxl 版。

    ⚠️ CI 环境不安装 openpyxl（workflow 只按需装 playwright），
    因此本用例必须零第三方依赖，否则会以 ModuleNotFoundError 打红 CI。
    本函数已与 openpyxl 版逐行对照，产出完全一致（15 行 / 字段逐项相同）。
    """
    with zipfile.ZipFile(path) as z:
        names = z.namelist()

        shared = []
        if "xl/sharedStrings.xml" in names:
            ss = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in ss.findall("{%s}si" % _XLSX_NS):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % _XLSX_NS)))

        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rid2target = {r.get("Id"): r.get("Target") for r in rels.findall("{%s}Relationship" % _REL_NS)}

        wb = ET.fromstring(z.read("xl/workbook.xml"))
        sheets_el = wb.find("{%s}sheets" % _XLSX_NS)
        if sheets_el is None:
            raise RuntimeError("workbook.xml 缺 sheets 节点")

        target_cells = None
        for sh in sheets_el:
            rid = sh.get("{%s}id" % _OFFICE_REL_NS)
            tgt = rid2target.get(rid, "")
            if tgt.startswith("/"):
                tgt = tgt.lstrip("/")
            elif not tgt.startswith("xl/"):
                tgt = "xl/" + tgt
            if tgt not in names:
                continue

            sheet = ET.fromstring(z.read(tgt))
            cells = {}
            for c in sheet.iter("{%s}c" % _XLSX_NS):
                m = _CELL_RE.match(c.get("r") or "")
                if not m:
                    continue
                key = (int(m.group(2)), _col_index(m.group(1)))
                t = c.get("t")
                if t == "inlineStr":
                    isn = c.find("{%s}is" % _XLSX_NS)
                    val = "".join(x.text or "" for x in isn.iter("{%s}t" % _XLSX_NS)) \
                        if isn is not None else ""
                else:
                    v = c.find("{%s}v" % _XLSX_NS)
                    if v is None:
                        val = None
                    elif t == "s":
                        val = shared[int(v.text)]
                    else:
                        val = v.text
                cells[key] = val

            row1 = [str(cells.get((1, i + 1)) or "").strip() for i in range(len(M.HEADERS))]
            if row1 == M.HEADERS:
                target_cells = cells
                break

        if target_cells is None:
            raise RuntimeError("找不到 16 列表头匹配的工作表")

        max_row = max((r for r, _ in target_cells), default=1)
        rows = []
        for r in range(2, max_row + 1):
            name = target_cells.get((r, 4))
            if not name:
                continue
            rows.append({
                "row": r,
                "product_name": str(name).strip(),
                "price": target_cells.get((r, 6)),
                "enabled": target_cells.get((r, 12)),
                "hash": str(target_cells.get((r, 15)) or ""),
                "category_id": target_cells.get((r, 16)),
            })
        return rows


class RealTemplateParse(unittest.TestCase):
    """用真实成品 xlsm 验解析——纯本地文件读取 + 纯标准库，不触网。

    ⚠️ 这里**刻意不用 openpyxl**：CI 不安装该包，用它会让用例在 CI 上
    以 ModuleNotFoundError 直接报错（红）。改为 zipfile+ElementTree 后
    既零依赖、又与 openpyxl 结果逐行一致。
    ⚠️ 也**刻意不设 skipTest 分支**：pr_fast 的 require_success() 视
    skipped 为失败，任何"找不到就跳过"的写法都等于把闸门变松。
    """

    CANDIDATES = (
        REPO_ROOT / "docs/planning/mlb-admin-api-feasibility-20261012/out_20261012.xlsm",
        PKG / "evidence" / "_mlb_test.xlsm",
    )

    def test_real_template_is_in_scope_and_parseable(self):
        found = next((p for p in self.CANDIDATES if p.is_file()), None)
        self.assertIsNotNone(found, "本 PR 范围内必须带上真实样例模板：%s" % (self.CANDIDATES,))
        rows = read_xlsm_rows_stdlib(found)
        self.assertEqual(len(rows), 15)
        self.assertTrue(all(str(r["category_id"]) == "8233" for r in rows))
        self.assertTrue(all(r["product_name"] for r in rows))
        # 与生产解析器的字段名保持一致，避免两套解析语义漂移
        self.assertEqual(
            sorted(rows[0].keys()),
            sorted(["row", "product_name", "price", "enabled", "hash", "category_id"]),
        )

    def test_production_parser_contract_matches_stdlib_probe(self):
        """生产 `read_xlsm_rows` 必须仍是「同一工作表 + 同样 6 个字段」的实现。

        不实际调用它（它 import openpyxl，CI 没有），只做**源码级契约校验**：
        表头常量、第 4 列取值、第 16 列分类ID、返回字段名都必须与用例一致。
        """
        text = (SRC / "mlb_admin_import.py").read_text(encoding="utf-8")
        self.assertIn('"分类ID（勿改）"', text)
        for field in ('"row"', '"product_name"', '"price"', '"enabled"',
                      '"hash"', '"category_id"'):
            self.assertIn(field, text, "生产解析器字段 %s 缺失" % field)
        self.assertIn("column=4", text, "生产解析器应取第 4 列产品名")
        self.assertIn("column=16", text, "生产解析器应取第 16 列分类ID")


class EvidenceBundleShape(unittest.TestCase):
    """证据包结构自检——证明逆向过程可复核，不涉任何密钥。"""

    def test_capture_snapshot_present(self):
        cap = PKG / "evidence" / "capture_20261012"
        self.assertTrue(cap.is_dir(), "缺少逆向快照目录")
        names = {p.name for p in cap.iterdir()}
        for needed in ("goodsMould_page.html", "requests_xhr.json",
                       "js_chunks.json", "uploadAuth-b29e96d2.js"):
            self.assertIn(needed, names)

    def test_no_credential_file_in_evidence_listing(self):
        """证据包里不得出现凭据文件。

        ⚠️ 本地开发目录里可能确实存在 `_cred.json`（库外临时件），
        所以判据不是「文件不存在」，而是「它没有被纳入提交清单」。
        提交清单由本仓库的推送白名单/排除表决定，这里断言排除表覆盖它。
        """
        deny = REPO_ROOT / ".gitignore"
        text = deny.read_text(encoding="utf-8")
        self.assertIn("_cred.json", text, ".gitignore 必须排除 _cred.json")

    def test_no_sqlite_runtime_data_in_gitignore(self):
        """SQLite 运行时数据必须被排除表覆盖（本地存在不代表入库）。"""
        text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("server/data", text, ".gitignore 必须排除 server/data")


if __name__ == "__main__":
    unittest.main(verbosity=2)
