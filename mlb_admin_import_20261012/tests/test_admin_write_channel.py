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
import tempfile
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


class LoginOcrRetryContract(unittest.TestCase):
    """2026-10-12 线上实证缺陷的回归闸。

    现象：`login_with_ocr` 的 tries 重试循环被 `_json()` 打死 —— 后台对
    **验证码判错**返回的是业务失败码（`code=0 msg='Please enter the correct
    verification code'`），而 `_json()` 对任何非 `code==1` 一律抛
    `AdminContractError`。结果第一次过码失手就直接退出，tries 形同虚设。

    这里用**假 transport** 离线复现两条路径，不需要网络、不需要 ddddocr：
      · 验证码被判定错误 → 必须换图重试，最终成功（consumed > 1）
      · 密码错误          → 必须立刻抛出，不消耗重试（consumed == 1）
    """

    class _FakeOcr:
        """按预设序列吐识别结果，模拟 OCR 连续命中/失手。"""

        def __init__(self, seq):
            self.seq = list(seq)
            self.calls = 0

        def classification(self, _png):
            self.calls += 1
            return self.seq.pop(0) if self.seq else ""

    _PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

    def _client(self, login_codes):
        """login_codes: 依次返回的 (code, msg) 序列。"""
        state = {"consumed": 0}

        def fake_request(_self, method, path, **kw):
            if path == "/api/common/captcha":
                return ({"code": 1}, self._PNG)[1]
            if path == "/admin/index/login":
                state["consumed"] += 1
                code, msg = login_codes[min(state["consumed"] - 1,
                                            len(login_codes) - 1)]
                if code == 1:
                    return json.dumps({"code": 1, "msg": "ok", "data": {
                        "userInfo": {"token": "tk", "refreshToken": "rt"}}})
                return json.dumps({"code": code, "msg": msg})
            raise AssertionError("意外请求 %s %s" % (method, path))

        c = C.AdminApiClient(log=lambda *_: None)
        c._request = fake_request.__get__(c, type(c))
        c._token = ""
        return c, state

    def test_captcha_rejection_retries_and_succeeds(self):
        codes = [(0, "Please enter the correct verification code"),
                 (0, "Please enter the correct verification code"),
                 (1, "ok")]
        c, st = self._client(codes)
        ocr = self._FakeOcr(["1234", "5678", "9012"])
        auth = c.login_with_ocr("u", "p", ocr=ocr, tries=3)
        self.assertEqual(st["consumed"], 3, "验证码判错必须重试，不能被第一次打死")
        self.assertEqual(auth.token, "tk")
        self.assertEqual(ocr.calls, 3)

    def test_wrong_password_fails_fast(self):
        """凭据错误不是验证码问题 —— 立刻抛出，绝不重试（防账号锁定）。"""
        c, st = self._client([(0, "用户名或密码错误")])
        ocr = self._FakeOcr(["1234", "5678", "9012"])
        with self.assertRaises(C.AdminContractError):
            c.login_with_ocr("u", "wrong", ocr=ocr, tries=3)
        self.assertEqual(st["consumed"], 1, "密码错只能试一次")

    def test_ocr_garbage_consumes_no_login_attempt(self):
        """识别结果连格式都不对时，连登录请求都不该发出去。"""
        c, st = self._client([(1, "ok")])
        ocr = self._FakeOcr(["ab", "###", "7788"])
        auth = c.login_with_ocr("u", "p", ocr=ocr, tries=3)
        self.assertEqual(st["consumed"], 1)
        self.assertEqual(auth.token, "tk")
        self.assertEqual(ocr.calls, 3)

    def test_all_captcha_failures_raise_auth_error(self):
        c, st = self._client([(0, "Please enter the correct verification code")])
        ocr = self._FakeOcr(["1111", "2222", "3333"])
        with self.assertRaises(C.AdminAuthError):
            c.login_with_ocr("u", "p", ocr=ocr, tries=3)
        self.assertEqual(st["consumed"], 3)



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


class _FakeAdmin:
    """假 transport：只实现 `Writer` 用到的三个方法，零网络。

    刻意**不**继承真实客户端 —— 一旦真实客户端改了协议签名，
    这里会立刻报 AttributeError，等于顺手钉住了契约。
    """

    def __init__(self, rows=None, products=48):
        self.rows = dict(rows or {})        # mid -> 写表单 row
        self.products = products
        self.posts = []                     # [(path, json_body)]
        self.gets = []                      # [(path, params)]

    def list_models(self, *, gid, cid, page=1, limit=200,
                    order="sort,desc", search=None):
        lst = [dict(v) for v in self.rows.values()]
        return {"list": lst, "total": len(lst)}

    def _json(self, method, path, **kw):
        if method == "GET":
            self.gets.append((path, dict(kw.get("params") or {})))
            if path == W.EDIT_PATH:
                mid = int(kw["params"]["id"])
                if mid not in self.rows:
                    raise RuntimeError("模型不存在 %s" % mid)
                return {"code": 1, "data": {"row": json.loads(
                    json.dumps(self.rows[mid]))}}
            if path == "/admin/goods.Goods/index":
                return {"code": 1, "data": {"total": self.products}}
            raise AssertionError("未预期的 GET %s" % path)
        self.posts.append((path, json.loads(json.dumps(kw.get("json_body")))))
        return {"code": 1, "msg": "保存成功", "data": {}}


def _row(mid, title="A B/99/SP/X/Awards", icon="101", zh="a" * 32):
    return {
        "id": mid, "title": title, "icon": icon, "price": "1.00",
        "more": {"extend": [{"key": "zh_title", "value": zh}]},
        "_format": {"icon_format": "https://x/%s.webp" % zh},
        "_extend": {"num": 1, "total": 0, "all_site_ids": [1, 2],
                    "all_aids": [3, 4, 5]},
    }


class ArchiveAndRestore(unittest.TestCase):
    """写前基线存档 + 还原 —— 这是「写错能回退」的唯一依据，必须锁死。"""

    def test_first_baseline_wins_never_overwritten(self):
        """第二次跑同一个 mid 时，绝不能把「已被改过」的状态当基线覆盖掉。"""
        with tempfile.TemporaryDirectory() as td:
            c = _FakeAdmin({111: _row(111, title="ORIGINAL")})
            p1 = W.Writer(c, False, log=lambda *a: None,
                          archive_dir=td).snapshot(111)
            self.assertTrue(p1.is_file())
            self.assertEqual(json.loads(p1.read_text("utf-8"))["title"], "ORIGINAL")

            c.rows[111]["title"] = "MUTATED"
            p2 = W.Writer(c, False, log=lambda *a: None,
                          archive_dir=td).snapshot(111)
            self.assertEqual(p1, p2)
            self.assertEqual(json.loads(p1.read_text("utf-8"))["title"], "ORIGINAL",
                             "基线被覆盖了 —— 还原会还原成坏值")

    def test_restore_replays_archived_row_with_mould_only(self):
        with tempfile.TemporaryDirectory() as td:
            row = _row(222, title="RESTORE ME", icon="7")
            Path(td, "222.before.json").write_text(
                json.dumps(row, ensure_ascii=False), encoding="utf-8")
            c = _FakeAdmin()
            out = W.Writer(c, False, log=lambda *a: None,
                           archive_dir=td).restore_all()
            self.assertEqual(out, [{"mid": 222, "ok": True, "msg": "保存成功"}])
            path, body = c.posts[-1]
            self.assertEqual(path, W.EDIT_PATH)
            self.assertEqual(body["icon"], "7")
            self.assertEqual(body["title"], "RESTORE ME")
            self.assertEqual(body["more"]["extend"][0]["value"], "a" * 32)
            # 必须是「只写模型、不动产品」的最小影响面形态
            self.assertEqual(body["_extend"]["gold_save_mode"], "mould_only")
            self.assertEqual(body["_extend"]["confirm_mould_trigger"], 1)

    def test_restore_without_archive_raises(self):
        with tempfile.TemporaryDirectory() as td:
            w = W.Writer(_FakeAdmin(), False, log=lambda *a: None, archive_dir=td)
            with self.assertRaises(RuntimeError):
                w.restore_all()

    def test_created_manifest_lists_new_mids(self):
        """新建模型没有 before 基线，必须被显式登记出来。"""
        with tempfile.TemporaryDirectory() as td:
            w = W.Writer(_FakeAdmin(), False, log=lambda *a: None, archive_dir=td)
            w.created.extend([555, 666, 555])
            p = w.write_manifest()
            self.assertTrue(p.is_file())
            self.assertEqual(json.loads(p.read_text("utf-8"))["created_mids"],
                             [555, 666])

    def test_dry_run_never_posts_and_never_archives(self):
        with tempfile.TemporaryDirectory() as td:
            # 已存在但字段不全 → 会走到「补全」分支
            c = _FakeAdmin({333: _row(333, icon="999", zh="b" * 32)},
                           products=0)
            rec = W.Writer(c, True, log=lambda *a: None,
                           archive_dir=td).write_one(
                {"product_name": "A B/99/SP/X/Awards", "hash": "a" * 32,
                 "sale_price": "1.00"})
            self.assertEqual(rec["verdict"], "dry-run")
            self.assertEqual(c.posts, [], "dry-run 不得发任何 POST")
            self.assertEqual(list(Path(td).glob("*.before.json")), [],
                             "dry-run 不该产生存档")

    def test_real_write_archives_before_posting(self):
        """非 dry-run 且模型已存在时，必须先落基线再写。"""
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            c = _FakeAdmin({444: _row(444, icon="999", zh="b" * 32)},
                           products=48)
            with mock.patch.object(W, "upload_network",
                                   return_value={"id": 101,
                                                 "full_url": "https://x/a.webp"}):
                rec = W.Writer(c, False, log=lambda *a: None,
                               archive_dir=td).write_one(
                    {"product_name": "A B/99/SP/X/Awards", "hash": "a" * 32,
                     "sale_price": "1.00"})
            self.assertEqual(rec.get("archive"), str(Path(td, "444.before.json")))
            self.assertTrue(Path(td, "444.before.json").is_file())
            self.assertTrue(c.posts, "应发出 /edit")
            self.assertEqual(c.posts[0][0], W.EDIT_PATH)


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
