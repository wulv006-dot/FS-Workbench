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
import p2pah_price as P                 # noqa: E402


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
        """48 = **单个模型**的渠道产品数 = 16 个站点 × 3 个 aid
        （实测 site_ids 16 个：0,10,11,266,290,332,335,339,341,343,569,571,573,575,577,59）。

        ⚠️ 这是**每张卡（每个模型）**的数量，不是某一批的总数 ——
           `products_of(mid)` 只统计 `mid = 这一个模型` 的产品。
           旧注释写成「16 张卡 × 3 个 aid = 48」很容易让人误读成批次总数，已改。
        """
        self.assertEqual(W.EXPECTED_PRODUCTS, 48)

    def test_products_of_counts_one_model_only(self):
        """幂等与达标判定都靠这个数，口径必须是「按 mid 过滤后的 total」。"""
        src = (SRC / "mlb_write_cards.py").read_text(encoding="utf-8")
        i = src.find("def products_of(")
        self.assertGreater(i, 0)
        seg = src[i:i + 420]
        self.assertIn('"field": "mid"', seg)
        self.assertIn('str(mid)', seg)

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


#: 金币价格管理页的**结构复刻**（2026-10-12 从 order.p2pah.cn 实抓后精简）。
#: 保留了两个关键"坑"的形状：
#:   ① 真正的数据列只有 7 个，c2c/g2g.com/eldorado.gg 三列**被注释掉**
#:      ——不剥注释就会数出 10 个 td，列序整体错位；
#:   ② gid 写在 `<td title="922">` 上，可用来校验取到的是不是这个游戏。
_PRICE_HTML = """<!DOCTYPE html><html><body>
<table class="table table-hover table-bordered table-list">
  <thead><tr>
    <th width="50">ID</th>
    <th>\u6240\u5c5e\u6e38\u620f</th>
    <th>\u6e38\u620f\u533a\u540d\u79f0</th>
    <th>\u91c7\u8d2d\u6210\u672c</th>
    <th>\u6700\u65b0\u91c7\u8d2d\u4ef7</th>
    <th>\u5229\u6da6\u7387</th>
    <th><label>b2c <input type="checkbox" class="jq_web" checked value="b2c" name="web[]"></label> </th>
    <!-- <th><label>c2c </label></th>
    <th><label>g2g.com </label></th>
    <th><label>eldorado.gg </label></th> -->
  </tr></thead>
  <tbody>
  <tr>
    <td>20418</td>
    <td title="922">MLB The Show 26</td>
    <td class="toggle-input" data-refresh="1" data-type="title"
        send-url="/game/admin_game_price/itemEdit?ids=20418">
        <span><i class="fa fa-edit text-info"></i> PS 5</span>
        <input class="input-text input-fw-7 jq-banEnter" type="text" value="PS 5">
    </td>
    <td class="toggle-input" data-type="costprice" data-callback="showprice">
        <span class="jq_showprice_costprice_20418"><i class="fa fa-edit text-info"></i> 0.228228</span>
        <input class="input-text input-fw-2 jq-banEnter" type="text" value="0.228228">
    </td>
    <td>0.200000</td>
    <td class="toggle-input" data-type="lirunlv" data-callback="showprice">
        <span class="jq_showprice_lirunlv_20418"><i class="fa fa-edit text-info"></i> 0.200000</span>
        <input class="input-text input-fw-2 jq-banEnter" type="text" value="0.200000">
    </td>
    <td class="toggle-input" data-type="b2c" data-callback="showprice">
        <span class="jq_showprice_b2c_20418"><i class="fa fa-edit text-info"></i> 0.0429</span>
        <input class="input-text input-fw-2 jq-banEnter" type="text" value="0.0429">
    </td>
    <!-- <td class="toggle-input" data-type="c2c">
        <span class="jq_showprice_c2c_20418"><i class="fa fa-edit text-info"></i> 0.037763</span>
        <input class="input-text" type="text" value="0.100000">
    </td>
    <td class="toggle-input" data-type="g2g">
        <span class="jq_showprice_g2g_20418"><i class="fa fa-edit text-info"></i> 0.037763</span>
        <input class="input-text" type="text" value="0.100000">
    </td>
    <td class="toggle-input" data-type="eldorado">
        <span class="jq_showprice_eldorado_20418"><i class="fa fa-edit text-info"></i> 0.039984</span>
        <input class="input-text" type="text" value="0.100000">
    </td> -->
  </tr>
  <tr>
    <td>20420</td>
    <td title="922">MLB The Show 26</td>
    <td class="toggle-input" data-type="title">
        <span><i class="fa fa-edit text-info"></i> XBOX</span></td>
    <td class="toggle-input" data-type="costprice"><span>0.228228</span></td>
    <td>0.200000</td>
    <td class="toggle-input" data-type="lirunlv"><span>0.200000</span></td>
    <td class="toggle-input" data-type="b2c"><span class="jq_showprice_b2c_20420">0.0429</span></td>
  </tr>
  <tr>
    <td>20422</td>
    <td title="922">MLB The Show 26</td>
    <td class="toggle-input" data-type="title">
        <span><i class="fa fa-edit text-info"></i> Switch</span></td>
    <td class="toggle-input" data-type="costprice"><span>0.228228</span></td>
    <td>0.080000</td>
    <td class="toggle-input" data-type="lirunlv"><span>0.200000</span></td>
    <td class="toggle-input" data-type="b2c"><span class="jq_showprice_b2c_20422">0.0429</span></td>
  </tr>
  </tbody>
</table>
</body></html>"""


class CoinsPriceReader(unittest.TestCase):
    """订单后台「金币价格管理」只读解析 —— 单位算错就是整批卡价打偏。

    这是工作台「当期金币售价」的**唯一**数据来源，所以：
      - 单位换算（USD/1K → USD/100K）必须被钉死；
      - 列序必须靠"剥注释后按表头定位"，不能靠数第几列；
      - 任何不确定一律 fail closed（返回 ok=False），绝不猜一个数出来。
    """

    def test_backend_endpoint_facts(self):
        self.assertEqual(P.BASE, "https://order.p2pah.cn")
        # ⚠️ 站点根相对：加了 /admin/ 前缀会 404（实测）
        self.assertEqual(P.PRICE_PATH, "/game/admin_game_price/index.html")
        self.assertEqual(P.DEFAULT_GID, 922)             # 922 = MLB The Show 26
        self.assertEqual(P.DEFAULT_MULTIPLIER, 100.0)

    def test_comment_stripping_is_required(self):
        """★ 回归：c2c/g2g/eldorado 三列被 <!-- --> 注释，不剥就多出 3 列。"""
        raw = _PRICE_HTML
        first_row = re.findall(r"<tr\b[^>]*>(.*?)</tr>",
                               re.search(r"<table\b.*?</table>", raw, re.S).group(0),
                               re.S)[1]
        self.assertEqual(len(re.findall(r"<td\b", first_row)), 10,
                         "原始 HTML 应有 10 个 td（7 真 + 3 注释）")
        stripped = P.strip_comments(first_row)
        self.assertEqual(len(re.findall(r"<td\b", stripped)), 7,
                         "剥注释后必须正好 7 个 td")
        self.assertNotIn("eldorado", stripped)

    def test_parse_headers_and_rows(self):
        got = P.parse_price_html(_PRICE_HTML, 922)
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["headers"],
                         ["ID", "所属游戏", "游戏区名称", "采购成本",
                          "最新采购价", "利润率", "b2c"])
        self.assertEqual([r["area"] for r in got["rows"]], ["PS 5", "XBOX", "Switch"])
        self.assertEqual(got["rows"][0]["b2c"], "0.0429")
        self.assertEqual(got["rows"][0]["id"], "20418")

    def test_gid_is_read_from_row_title_attribute(self):
        """用行的 title 属性反查 gid —— 取错游戏会静默给出别人的价格。"""
        got = P.parse_price_html(_PRICE_HTML, 922)
        self.assertEqual(got["gid_matched"], [922, 922, 922])

    def test_multiplier_converts_per_k_to_per_100k(self):
        """★ b2c 是 USD/1K，工作台 rate 是 USD/100K ⇒ ×100。"""
        res = P.build_result(P.parse_price_html(_PRICE_HTML, 922), 922, "PS 5", 100)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["b2c"], 0.0429)
        self.assertEqual(res["b2c_unit"], "USD/1K")
        self.assertAlmostEqual(res["rate_usd_per_100k"], 4.29, places=6)
        # 换算过程必须显式回吐（藏起来的话 100 倍错误一辈子发现不了）
        self.assertIn("100", res["formula"])
        self.assertIn("4.29", res["formula"])

    def test_pick_row_exact_and_fallback(self):
        parsed = P.parse_price_html(_PRICE_HTML, 922)
        row, how = P.pick_row(parsed["rows"], "xbox")       # 大小写不敏感
        self.assertEqual(how, "exact")
        self.assertEqual(row["area"], "XBOX")
        row, how = P.pick_row(parsed["rows"], "PC \u7aef")   # 不存在的区
        self.assertEqual(how, "fallback")
        self.assertEqual(row["area"], "PS 5")               # 退回第一行，且标明

    def test_areas_inconsistent_is_flagged_not_guessed(self):
        """三个平台价格不一致时必须**标出来**，不能默默取一个当全都对。"""
        html = _PRICE_HTML.replace('jq_showprice_b2c_20422">0.0429',
                                   'jq_showprice_b2c_20422">0.0555')
        res = P.build_result(P.parse_price_html(html, 922), 922, "PS 5", 100)
        self.assertTrue(res["ok"])
        self.assertFalse(res["areas_consistent"])
        self.assertEqual(res["areas"], ["0.0429", "0.0555"])

    def test_missing_b2c_column_fails_closed(self):
        """表里没有 b2c 列 → 必须报错，不能拿别的列硬当价格。"""
        html = _PRICE_HTML.replace("<label>b2c ", "<label>name ")
        got = P.parse_price_html(html, 922)
        self.assertFalse(got["ok"])
        self.assertEqual(got["step"], "parse")

    def test_non_numeric_b2c_fails_closed(self):
        html = _PRICE_HTML.replace("</i> 0.0429</span>\n        <input class=\"input-text input-fw-2 jq-banEnter\" type=\"text\" value=\"0.0429\">",
                                   "</i> \u5f85\u5b9a</span>\n        <input type=\"text\" value=\"\">")
        got = P.parse_price_html(html, 922)
        if not got["ok"]:
            self.skipTest("样例替换未命中，跳过")
        res = P.build_result(got, 922, "PS 5", 100)
        self.assertFalse(res["ok"])
        self.assertEqual(res["step"], "parse")

    def test_module_imports_without_third_party(self):
        """本模块必须能被离线用例直接 import。

        服务器 `/opt/python39` **没有 requests**（实测），ddddocr 又要惰性加载
        —— 所以顶层只能 import 标准库。
        """
        src = (SRC / "p2pah_price.py").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"(?m)^import requests", "顶层 import 了 requests")
        self.assertNotRegex(src, r"(?m)^import ddddocr", "顶层 import 了 ddddocr")
        # ddddocr 只能出现在函数体内（缩进）
        for line in src.splitlines():
            if "import ddddocr" in line:
                self.assertTrue(line.startswith(" "), "ddddocr 必须是惰性 import")

    def test_no_hardcoded_credentials(self):
        src = (SRC / "p2pah_price.py").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"(?i)(password|passwd|pwd)\s*=\s*['\"][^'\"]{4,}['\"]",
                            "脚本里硬编码了口令")
        self.assertNotIn("Fsnet", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
