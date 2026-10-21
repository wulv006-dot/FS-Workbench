"""P2PAH 后台受控 HTTP 客户端（FC27 / SBC）。

本文件的每个方法都对应 2026-09-24 从线上前端生产包中直接提取并核对过的接口，
接口清单与证据见 evidence/接口证据.md。客户端遵守以下红线：

1. 仅从8767读取当前token，不接收账号密码或验证码；上传签名密钥读取服务器私有配置。
2. 只允许调用本文件 ``_ALLOWED`` 中列出的路径，未知路径在本地直接拒绝。
3. 写操作（新增模型 / 上架 / 上传图片）绝不自动重试：失败即"状态未知"，交给人处理。
4. GET 只读请求允许有限重试；POST / DELETE 一律不重试。
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

def _upload_secret():
    from pathlib import Path
    import os
    import stat
    path = Path('/etc/fc27-sbc-tool/upload-signing.key')
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (os.name == 'posix' and
            (info.st_uid not in {0, os.geteuid()} or info.st_mode & 0o077)):
        raise AdminAuthError('upload_signing_config_permissions')
    value = path.read_text(encoding='utf-8').strip()
    if not value or len(value) > 512:
        raise AdminAuthError('upload_signing_config_invalid')
    return value

def _fs_shared_admin_token():
    import importlib.util
    spec = importlib.util.spec_from_file_location('fs_shared_admin', '/opt/fs-shared-session/shared_admin.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    token, _ = module.admin_token_from_service()
    if not token:
        raise RuntimeError('FS_SHARED_SESSION_UNAVAILABLE')
    return token


# ---- 后台常量（来自线上前端 index.js / goodsMould 页面配置） ----
#: **必须带浏览器 UA**（2026-10-17 实测）：后台 API 在 Cloudflare 后面，
#: 匿名请求（比如取登录验证码）用 ``Python-urllib/…`` 会被拦成 **403 + Cloudflare 拦截页**，
#: 换成浏览器 UA 立刻 200。所以所有请求统一带上它。
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

DEFAULT_API_BASE = "https://admin-api.p2pah.cn"
DEFAULT_PAGE_BASE = "https://admin.p2pah.cn"
DEFAULT_UPLOAD_BASE = "https://b2c-api.p2pah.cn"

GID_FC27 = 1327              # 游戏：FC 27
CID_PLAYERS = 9627           # 类目：Players（叶子）
CID_SBC = 9625               # 类目树中的 SBC 节点（**父级**，仅可用于列表查询）
CID_SBC_ADD = 9971           # SBC 下的叶子「Upgrade」—— 新增模型必须用这个
CID_PACKS = 9629             # 类目：Packs（**父节点**）—— ⚠️ 2026-10-13 起它底下挂了叶子
                             # 10255 In-Game Packs，所以 **列表查询/改价收口不能只认 9629**；
                             # 「新增模型」这一侧暂时仍传 9629（见 README 类目收口一节）

# 实测结论（2026-09-24 用真实账号验证）：
#   1. GET goods.GoodsMould/add?cid=9625 -> code=0 "必须为最后一级类目！"
#      说明 9625(SBC) 是父级，新增会被拒绝；必须用叶子（2026-09-24 时只有 9971）。
#   2. 已有 4 条 SBC 产品的 cid 全部是 9971，与上述结论一致。
#
# ⚠️ 2026-10-06 更正上面第 2 条留下的印象：
#   「列表查询用 9625 或 9971 返回结果相同」**已经不再成立** ——
#   当天实测（site_id=0）：cid=9625 返 39 行、cid=9971 只返 21 行、cid=10203 返 18 行。
#   原因是后台在 SBC(9625) 底下又挂了一个新叶子 **10203 SBC Players**：
#       Items(2) ├ Players(9627)
#                ├ SBC(9625) ├ 10203 SBC Players  ← 新的
#                │           └ 9971  Upgrade       ← 老的
#                ├ Packs(9629) └ Coupons(9825)
#   9625 这行「返 39」证明**后端确实会带上子孙**；但**行里带的是叶子的 cid**，
#   所以工具侧按 cid 收口时必须知道「这个父类目底下现在有哪些叶子」——
#   写死单个叶子就会把新叶子整批静默丢掉。见 repricer.SBC_LEAF_CIDS 与
#   AdminClient.child_leaf_cids()。

MOULD = "/admin/goods.GoodsMould/"
TAG_CONTROLLER = "/admin/goods.GoodsTag/"
# 按区改价走的是 **Goods** 控制器（不是 GoodsMould）：
#   /admin/goods/goods（页面）= 已在售商品，每行一个 (模型, 站点, 区服) 组合
GOODS = "/admin/goods.Goods/"

# ⚠️⚠️ 2026-09-28 更正：**改价必须用 ``GOODS + "edit"``，不是 ``singleEdit``。**
#
# 这里原来是这么写的（错的）：
#   「goods.Goods/singleEdit = 按区分改价（前端产品页的改价按钮就是它）」
#   证据只引了 products-index 里的 ``function p(a,o)``。
#
# 错在哪：``p(a,o)`` 确实存在，但**它的调用点里没有一个带 price**。原文：
#     function p(a,o){ let s={[a]:o, id:t.getSelectionIds()}; ... POST W+"singleEdit" }
#     —— 而按钮是：p("is_rec",1) p("is_rec",0) p("status",1) p("status",0)
#                  p("auto_off",1) p("auto_off",0) p("sku_switch",1) p("attr_switch",0) …
#   也就是说 singleEdit 在产品管理页只用于「推荐 / 启用 / 禁用 / 自动下架 / SKU / 属性」，
#   **它根本不含 price**。当时只看了函数体、没看调用点，就把"批量按钮"当成了"改价按钮"。
#
# 三条硬证据（都可复现）：
#   1. 后台操作日志 ``GET /admin/auth.AdminLog/index``：
#        /admin/goods.GoodsMould/singleEdit -> 「产品模型管理-单值编辑」   ← 标题正常
#        /admin/goods.Goods/singleEdit      -> 「产品管理-**Unknown**(singleedit)」
#      后台是拿动作名去规则表查标题的 ⇒ 规则表里**没建**这个节点 ⇒
#      权限管理里勾不到 ⇒ 非 super 账号打它**恒 401**（不是登录失效）。
#   2. 产品管理页后台自己印的提示文字（products-index 的 el-alert）：
#        「按区改价、上架：去 产品模型 点『保存勾选区产品』」
#        「按收货价算每个价格：去 货币快捷修改（拉区服可选 0 ALL，改价要选真实站点）」
#      —— 连后台自己都不认为「在售商品列表」上有改价按钮。
#   3. 该页行内「编辑」弹窗的表单字段（products-index 的 ``form.defaultItems``）
#      **含 ``unit_price: 0, price: 0``** ⇒ ``goods.Goods/edit`` 才是写 price 的端点。
#
# 实测（2026-09-28，账号 zhangxingyu，super=False）：
#   POST /admin/goods.Goods/edit  body={"id":170163239,"price":2.49}
#   -> HTTP 200 {"code":1,"msg":"修改成功"}
#   写完回读整行逐字段 diff 为空 —— 只发 id+price，别的字段一个都没被动。
#   同一账号权限自检：``goods/goods/edit`` ✅ 有；``goods/goods/singleEdit`` ❌ 没有。
#
# 教训：**改价失败别急着下"权限不足"的结论 —— 先确认端点是前端真正在用的那个。**
#       （服务端不回 405 而是回 401，很容易把"路由猜错了"误诊成"权限不够"。）

# 后台首页接口：BuildAdmin 用它一次返回 adminInfo（账号 / super 标志）+ menus（规则树）。
# 这是**唯一**能安全回答"当前账号有没有某个权限"的只读接口 —— 见 AdminClient.whoami()。
ADMIN_INDEX = "/admin/index/index"


class AdminError(RuntimeError):
    """后台客户端错误基类。"""


class AdminAuthError(AdminError):
    """登录 / 验证码 / token 失效。"""


class AdminContractError(AdminError):
    """响应结构与已核实契约不一致，fail closed。"""


class AdminPermissionError(AdminContractError):
    """后台明确回 code=401 / ``You have no permission``。

    这**不是**登录态失效 —— token 是好的（读接口全都通），
    是当前账号的角色没勾「这个操作」对应的权限节点。

    实测（2026-09-28）：账号 ``zhangxingyu`` 打
    ``POST /admin/goods.Goods/singleEdit`` 恒回
    ``{"code":401,"msg":"You have no permission"}``，
    而它的权限树里**没有** ``goods/goods/singleEdit`` 这个按钮，
    只有 ``goods/goodsMould/singleEdit``（单值编辑）。

    ⚠️ 这种失败**重试和换参数都没有意义**（实测 4 种 params 组合结果完全一样）。
    调用方应立刻整体停下、只报一次，而不是逐行继续打后端。
    """


class AdminHttpError(AdminError):
    def __init__(self, message: str, *, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ModelPage:
    rows: tuple[Mapping[str, Any], ...]
    total: int
    all_site_ids: tuple[int, ...]
    all_aids: tuple[int, ...]
    site_config: tuple[Mapping[str, Any], ...]
    game_area_config: tuple[Mapping[str, Any], ...]
    top_cid: int = 0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """后台 302 常表示登录失效；禁止 urllib 静默跟随到 HTML 登录页。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _query_pairs(prefix: str, value: Any):
    """按后台前端 axios 的 bracket/index 规则展开嵌套 GET 参数。"""

    if value is None:
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield from _query_pairs(f"{prefix}[{key}]", child)
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            yield from _query_pairs(f"{prefix}[{index}]", child)
        return
    yield prefix, value


def _multipart(fields: Mapping[str, Any], file_field: str, filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = "----FC27Sbc" + secrets.token_hex(12)
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
            str(value).encode("utf-8"),
            b"\r\n",
        ])
    safe_name = Path(filename).name
    content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    if safe_name.lower().endswith(".webp"):
        content_type = "image/webp"
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{file_field}"; filename="{safe_name}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        content,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _collect_rule_names(node: Any, out: set[str]) -> None:
    """把权限树里所有节点的 ``name``（= 规则路径）递归收进 ``out``。

    BuildAdmin 的 ``/admin/index/index`` 返回 ``data.menus``（菜单树）和 ``data.rules``，
    leaf / 按钮节点都带 ``name``，形如 ``goods/goods/singleEdit``。结构可能是
    dict 套 list 套 dict，所以不假设层级，见 ``name`` 就收。
    """

    if isinstance(node, Mapping):
        name = node.get("name")
        if isinstance(name, str) and name:
            out.add(name)
        for value in node.values():
            _collect_rule_names(value, out)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _collect_rule_names(item, out)


def upload_auth_fields() -> dict[str, Any]:
    """复刻前端 uploadAuth：token = md5(毫秒时间戳 + 盐)，timestamp = 毫秒时间戳。"""

    timestamp = int(time.time() * 1000)
    token = hashlib.md5(f"{timestamp}{_upload_secret()}".encode("utf-8")).hexdigest()
    return {"token": token, "timestamp": timestamp}


class AdminClient:
    """只访问受控路径的标准库 HTTP 客户端。"""

    _ALLOWED: Mapping[str, frozenset[str]] = {
        "GET": frozenset({
            ADMIN_INDEX,
            MOULD + "index",
            MOULD + "edit",
            MOULD + "add",
            GOODS + "index",
            GOODS + "edit",
            GOODS + "add",
            TAG_CONTROLLER + "tagSelect",
            "/admin/goods.GoodsCategory/categorySelect",
        }),
        "POST": frozenset({
            # 两步验证第二步（2026-10-21 后台加了动态身份验证器）：{ticket, google_code}
            MOULD + "add",
            MOULD + "edit",
            MOULD + "shelves",
            MOULD + "singleEdit",
            MOULD + "recalcFc27Price",
            MOULD + "importPlayers",
            # 改价走 edit（逐行）。**故意不再放 singleEdit** —— 见 GOODS 常量上方的长注释：
            # 它不含 price，且规则表里没这个节点（非 super 恒 401），留着就是个坑。
            GOODS + "edit",
        }),
        "DELETE": frozenset({
            MOULD + "del",
        }),
    }

    def __init__(
        self,
        *,
        api_base: str = DEFAULT_API_BASE,
        upload_base: str = DEFAULT_UPLOAD_BASE,
        timeout: float = 30.0,
        get_retries: int = 2,
        retry_wait: float = 0.8,
        upload_field: str = "file",
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.upload_base = upload_base.rstrip("/")
        self.timeout = float(timeout)
        self.get_retries = int(get_retries)
        self.retry_wait = float(retry_wait)
        self.upload_field = upload_field
        self._opener = urllib.request.build_opener(_NoRedirect()).open
        self._token = ""
        self._refresh_token = ""

    # ---------------- 认证 ----------------
    @property
    def authenticated(self) -> bool:
        try:
            self._token = _fs_shared_admin_token()
        except RuntimeError:
            self._token = None
        return bool(self._token)

    def clear_auth(self) -> None:
        self._token = ""
        self._refresh_token = ""


    # ---------------- 模型读取 ----------------
    def list_models(
        self,
        *,
        gid: int = GID_FC27,
        cid: int = CID_SBC,
        page: int = 1,
        limit: int = 200,
        title_like: Optional[str] = None,
        extra_search: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> ModelPage:
        search: list[Mapping[str, Any]] = [
            {"field": "gid", "operator": "=", "val": str(gid)},
            {"field": "cid", "operator": "=", "val": str(cid)},
        ]
        if title_like:
            search.append({"field": "title", "operator": "LIKE", "val": str(title_like)})
        for item in extra_search or ():
            search.append(item)
        env = self._json(
            "GET", MOULD + "index",
            params={"page": page, "limit": limit, "order": "sort,desc", "search": search},
        )
        data = env.get("data")
        if not isinstance(data, Mapping) or not isinstance(data.get("list"), list):
            raise AdminContractError("模型列表响应缺少 data.list")
        try:
            total = int(data.get("total"))
        except (TypeError, ValueError) as exc:
            raise AdminContractError("模型列表 data.total 不是整数") from exc

        def _ids(key: str) -> tuple[int, ...]:
            raw = data.get(key) or []
            if isinstance(raw, Mapping):
                raw = list(raw.keys())
            if not isinstance(raw, (list, tuple)):
                return ()
            out: list[int] = []
            for item in raw:
                try:
                    out.append(int(item))
                except (TypeError, ValueError):
                    continue
            return tuple(out)

        site_config = data.get("siteConfig") or data.get("site_config") or []
        area_config = data.get("gameAreaConfig") or data.get("game_area_config") or []
        try:
            top_cid = int(data.get("topCid") or 0)
        except (TypeError, ValueError):
            top_cid = 0
        return ModelPage(
            rows=tuple(r for r in data["list"] if isinstance(r, Mapping)),
            total=total,
            all_site_ids=_ids("all_site_ids"),
            all_aids=_ids("all_aids"),
            site_config=tuple(x for x in site_config if isinstance(x, Mapping)) if isinstance(site_config, (list, tuple)) else (),
            game_area_config=tuple(x for x in area_config if isinstance(x, Mapping)) if isinstance(area_config, (list, tuple)) else (),
            top_cid=top_cid,
        )

    def get_model(self, model_id: int) -> Mapping[str, Any]:
        env = self._json("GET", MOULD + "edit", params={"id": int(model_id)})
        data = env.get("data")
        if not isinstance(data, Mapping) or not isinstance(data.get("row"), Mapping):
            raise AdminContractError("模型详情响应缺少 data.row")
        return data["row"]

    def list_tags(self, *, gid: int = GID_FC27, cid: int = CID_SBC) -> tuple[Mapping[str, Any], ...]:
        env = self._json("GET", TAG_CONTROLLER + "tagSelect", params={"gid": gid, "cid": cid})
        data = env.get("data")
        if not isinstance(data, Mapping) or not isinstance(data.get("list"), list):
            raise AdminContractError("标签响应缺少 data.list")
        return tuple(i for i in data["list"] if isinstance(i, Mapping))

    # ---------------- 类目树（只读） ----------------
    def category_tree(self, *, gid: int = GID_FC27) -> tuple[Mapping[str, Any], ...]:
        """拉类目树，返回顶层节点（子孙在各自的 children 里）。

        ⚠️ **别缓存长期用**：类目是后台随时能改的 —— 2026-10-06 就在 SBC(9625)
        底下加了个新叶子 10203 SBC Players。谁要"省一次请求"把它缓存起来，
        就会在下一次后台加类目时**静默漏掉一个新类目的全部产品**。
        """

        env = self._json("GET", "/admin/goods.GoodsCategory/categorySelect",
                         params={"gid": int(gid)})
        data = env.get("data")
        items = data.get("list") if isinstance(data, Mapping) else data
        if not isinstance(items, (list, tuple)):
            raise AdminContractError("类目树响应缺少 data.list")
        return tuple(x for x in items if isinstance(x, Mapping))

    def child_leaf_cids(self, parent_cid: int, *, gid: int = GID_FC27) -> tuple[int, ...]:
        """``parent_cid`` 底下**所有叶子**的 cid（递归；不含父自己，去重升序）。

        为什么工具需要这个：列表查询传父类目（如 SBC 9625）时后端会把子孙都带回来，
        但**返回的每一行带的是叶子的 cid**。工具侧要按 cid 收口，就必须知道
        "这个父类目底下**现在**有哪些叶子"，否则后台一加叶子，那批产品就被静默丢掉。

        若 ``parent_cid`` 本身就是叶子（底下没有任何子节点）返回空元组 ——
        调用方照旧直接用父级 cid。

        ⚠️ **别把"返回空元组"当成"这个类目永远是叶子"** —— 类目树是后台能改的。
        2026-09-24 实测 `child_leaf_cids(9629) == ()`，当时的结论写成"Packs 本身即叶子"，
        被抄到了好几个文件里；2026-10-13 后台在 9629 底下挂了 `10255 In-Game Packs`，
        于是那次调用变成 `(10255,)`，而写死"9629 即叶子"的收口把整批行丢掉了。
        结论：**每次拉取都现问一次**，不要缓存，也不要用"有没有叶子"当规则。
        """

        target = int(parent_cid)

        def children(node: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
            kids = node.get("children")
            if kids is None:
                kids = node.get("child")
            if not isinstance(kids, (list, tuple)):
                return ()
            return tuple(k for k in kids if isinstance(k, Mapping))

        def cid_of(node: Mapping[str, Any]) -> Optional[int]:
            try:
                return int(node.get("id"))
            except (TypeError, ValueError):
                return None

        found: list[int] = []

        def collect(node: Mapping[str, Any]) -> None:
            for kid in children(node):
                if children(kid):
                    collect(kid)          # 还是父级 -> 继续往下
                else:
                    cid = cid_of(kid)
                    if cid is not None:
                        found.append(cid)

        def find(nodes: Sequence[Mapping[str, Any]]) -> bool:
            for node in nodes:
                if cid_of(node) == target:
                    collect(node)
                    return True
                if find(children(node)):
                    return True
            return False

        find(self.category_tree(gid=gid))
        return tuple(sorted(set(found)))

    # ---------------- 写操作 ----------------
    def upload_image(self, path: str | Path) -> Mapping[str, Any]:
        """上传图标，返回 {id, url}。端点取自前端 uploadApiUrl = b2c-api/upload/file。"""

        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(source)
        body, ctype = _multipart(upload_auth_fields(), self.upload_field, source.name, source.read_bytes())
        url = f"{self.upload_base}/upload/file"
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": ctype, "Accept": "application/json, */*",
                     "User-Agent": USER_AGENT},   # 上传也在 Cloudflare 后面，UA 不能少
        )
        try:
            with self._opener(req, timeout=max(self.timeout, 120.0)) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise AdminHttpError(f"图片上传失败：HTTP {exc.code}", status=exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AdminHttpError(f"图片上传网络错误：{exc}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdminContractError("图片上传返回不是 JSON") from exc
        if not isinstance(payload, Mapping):
            raise AdminContractError("图片上传响应不是 JSON 对象")
        return self._extract_upload(payload)

    @staticmethod
    def _extract_upload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """从多种上传响应形状中取出 file 对象，并把嵌套错误码当作失败。

        2026-09-24 实测形状（b2c-api /upload/file，成功）::

            {"upload": {"picture": {"code": 200, "msg": "...", "file": {
                 "id": 16030599,
                 "full_url": "https://b2c-static.p2pah.cn/images/.../x.png", ...}}}}

        顶层**没有** code 字段；错误可能藏在任意一层（例如 admin-api 的
        ``{"code":1,"data":{"file":{"code":400,"msg":"INVALID TOKEN"}}}``），
        所以必须逐层扫描，不能只看顶层。
        """

        def looks_like_file(node: Mapping[str, Any]) -> bool:
            return node.get("id") is not None and any(
                node.get(key) for key in ("full_url", "url", "path", "sha1")
            )

        def walk(node: Any, path: str = ""):
            yield path, node
            if isinstance(node, Mapping):
                for key, child in node.items():
                    yield from walk(child, f"{path}.{key}" if path else str(key))
            elif isinstance(node, (list, tuple)):
                for index, child in enumerate(node):
                    yield from walk(child, f"{path}[{index}]")

        files: list[tuple[str, Mapping[str, Any]]] = []
        errors: list[tuple[str, Mapping[str, Any]]] = []
        for path, node in walk(payload):
            if not isinstance(node, Mapping):
                continue
            if looks_like_file(node):
                files.append((path, node))
                continue
            code = node.get("code")
            if code is not None and str(code) not in ("1", "200"):
                errors.append((path, node))

        if errors:
            path, node = errors[0]
            raise AdminContractError(
                f"图片上传被拒绝：{path or 'root'} code={node.get('code')!r} "
                f"msg={node.get('msg') or node.get('message')!r}"
            )
        if not files:
            raise AdminContractError("图片上传成功但响应中没有可识别的 file 对象")
        return files[0][1]

    def edit_model(self, model_id: int, *, icon: int) -> Mapping[str, Any]:
        """改**已有模型**的图标。``POST /admin/goods.GoodsMould/edit``，body ``{"id", "icon"}``。

        入口就是用户在后台点的那条路：产品管理 → 产品模型管理 → 游戏 1327 FC27 →
        类目 9625(SBC) / 9629(Packs) → 搜索 → 编辑 → 替换「图标」。

        ## 为什么只发 ``id`` + ``icon`` 两个键（2026-10-10 实测坐实）

        ``goods.Goods/edit`` 的规矩是「除 id 外只带**一个**业务字段才走快路径，
        带两个以上会滑进完整编辑分支并逐级报『请选定游戏！』…」（见 edit_goods_price）。
        ``GoodsMould/edit`` 是同一套 BuildAdmin 表单，所以这里也一律只发一个字段。

        实测（``联调/probe_model_icon.py --write-probe --mid 44093731``，
        一个 status=0 的已下架模型，发的是**原值**所以前台零变化）::

            POST /admin/goods.GoodsMould/edit  {"id": 44093731, "icon": 16220321}
            -> {"code":1,"msg":"成功修改 1 条数据"}

        写后整行 42 个键逐字段 diff，只有两处动：

        * ``icon``   —— **没变**（发的是原值）
        * ``shelf_time`` 1791494900 -> 1791626746（2026-10-09 05:28 -> 2026-10-10 18:05）
          以及它的回显 ``_format.shelf_time``

        ``title`` / ``cid`` / ``price`` / ``discount`` / ``status`` / ``_extend`` /
        ``_format.icon_format`` 等**逐字未动**。

        ⇒ 结论：单字段 body 走的是快路径，**这条端点只写 icon**。

        ## ⚠️ 已知副作用：上架时间会被刷成"现在"

        后台自己就是这么实现的 —— 在 UI 里改一次图，``shelf_time`` 一样会跳到当前时刻
        （不是本模块造成的）。这两个字段都是**只读**的：试着写回会得到
        ``code=0「抱歉，该字段值不允许编辑！」``，所以想"绕开"也绕不开，别徒劳回滚它们。

        ## 其它

        * ``icon`` 必须是**图片附件的数字 id**（``upload_image()`` 返回的 ``file.id``），
          **不是** URL。``_format.icon_format`` 只是回显用的地址。
        * 同一个模型的图是**全站点共用**的：改一次，这个模型在所有站点/区服的在售行
          一起换图（实测 goods 行的 icon 与模型的 icon 恒等，见联调探针 A 段）。
        * 写操作，不重试。失败即"状态未知"，交给人处理。
        """

        try:
            mid = int(model_id)
        except (TypeError, ValueError):
            raise ValueError(f"改模型图标需要明确的模型 ID，收到 {model_id!r}") from None
        if mid <= 0:
            raise ValueError(f"改模型图标需要正整数 ID，收到 {mid}")
        if icon in (None, "", 0, "0"):
            raise ValueError(f"不允许把图标写空（收到 icon={icon!r}）")

        body: dict[str, Any] = {"id": mid, "icon": icon}
        return self._json("POST", MOULD + "edit", json_body=body)

    def edit_model_status(self, model_id: int, status: int) -> Mapping[str, Any]:
        """改**产品模型**的状态开关（1 = 亮 / 0 = 灭，即 goodsMould 页面那一格）。

        用户 2026-10-15 定的「自动下架」口径：后台 ``admin.p2pah.cn/#/admin/goods/goodsMould``
        → 产品模型管理 → 游戏 1327 FC27 → 类目 9625 SBC / 9629 packs → 搜索 →
        点「状态」开关，**不亮就是关闭**。程序化等价物就是 ``POST goods.GoodsMould/edit``
        body 只带 ``{"id", "status"}`` 两个字段。

        ⚠️ 和 :meth:`edit_model` 同一条「单字段快路径」铁律：除 id 外**只带一个业务字段**，
        带两个以上会滑进完整编辑分支逐字段报错。写完后调用方应回读核对（``get_model``）。
        写操作，不重试；失败即"状态未知"，交给人处理。

        ⚠️ 对**已下架（status=0）**的模型再发一次 0 是无害的（2026-10-15 探针实测
        code=1、整行无变化）；但把 status 从 0 写成 1 属于「重新上架」语义，
        本方法不拦，调用方自律 —— 自动下架链路永远只发 0。
        """

        try:
            mid = int(model_id)
        except (TypeError, ValueError):
            raise ValueError(f"改模型状态需要明确的模型 ID，收到 {model_id!r}") from None
        if mid <= 0:
            raise ValueError(f"改模型状态需要正整数 ID，收到 {mid}")
        if int(status) not in (0, 1):
            raise ValueError(f"status 只能是 0 或 1，收到 {status!r}")
        body: dict[str, Any] = {"id": mid, "status": int(status)}
        return self._json("POST", MOULD + "edit", json_body=body)

    def get_model(self, model_id: int) -> Mapping[str, Any]:
        """读单个产品模型（GET goods.GoodsMould/edit?id=，后台编辑页的数据源）。

        ⚠️ 真实结构是 ``data.row``（2026-10-15 实测：顶层也有个空的 ``more``，
        那是表单默认值，不是模型数据 —— 读错了会以为"没有扩展属性"）。
        """
        return self._json("GET", MOULD + "edit", params={"id": int(model_id)})

    @staticmethod
    def model_row(payload: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        """从 get_model 的响应里取 ``data.row``（模型真实数据）。"""
        data = payload.get("data") if isinstance(payload, Mapping) else None
        row = data.get("row") if isinstance(data, Mapping) else None
        return row if isinstance(row, Mapping) else None

    # 整表单编辑时要剔掉的字段（2026-10-15 实测：带上它们会被拒或引发无谓变化）
    _EDIT_SKIP_FIELDS = ("id", "shelf_time", "_format", "_extend",
                         "stat_buy", "stat_cart", "stat_view", "time")

    def edit_model_more(self, model_id: int, more: Mapping[str, Any]) -> Mapping[str, Any]:
        """改模型的「更多扩展属性」（``more.extend`` 等）。

        ## 为什么不是 ``{"id", "more"}``（2026-10-15 实测踩到）

        单字段快路径对 ``more`` **不适用**：发 ``{"id", "more"}`` 得到
        ``code=0 抱歉，该字段值不允许编辑！``（跟 icon / status 不一样）。
        后台 UI 的「更多扩展属性」走的是**完整表单分支**，所以这里也照做：
        先读 ``data.row``，把整行字段原样回传、只改 ``more``。

        实测（play187，模型 44803519 一次性测试模型）::

            POST /admin/goods.GoodsMould/edit  {整行 + more.extend:[{"key":"set_id","value":"888888"}]}
            -> {"code":1,"msg":"保存成功"}
            回读整行 diff：**只有 more 变了**（_format 里两个回显字段本就不一致，与我们无关）

        ⚠️ 拿不到 ``data.row`` 时**拒绝写**（绝不猜结构盲写）。
        """

        try:
            mid = int(model_id)
        except (TypeError, ValueError):
            raise ValueError(f"改模型 more 需要明确的模型 ID，收到 {model_id!r}") from None
        if mid <= 0:
            raise ValueError(f"改模型 more 需要正整数 ID，收到 {mid}")
        if not isinstance(more, Mapping) or "extend" not in more:
            raise ValueError("more 必须是含 extend 列表的映射（照后台编辑页的形状原样传）")

        row = self.model_row(self.get_model(mid))
        if row is None:
            raise AdminContractError(
                f"模型 {mid} 的详情里没有 data.row，拿不到完整表单，拒绝盲写扩展属性")
        body = {k: v for k, v in row.items() if k not in self._EDIT_SKIP_FIELDS}
        body["id"] = mid
        body["more"] = dict(more)
        return self._json("POST", MOULD + "edit", json_body=body)

    def add_model(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """新增产品模型。POST /admin/goods.GoodsMould/add（前端 onSubmit -> postData('add')）。"""

        if not payload:
            raise ValueError("add_model payload 不能为空")
        return self._json("POST", MOULD + "add", json_body=dict(payload))

    def shelves(
        self,
        *,
        model_ids: Sequence[int],
        site_ids: Sequence[int],
        aids: Sequence[int],
        num: int = 1,
        stock: int = 0,
        duration: int = 0,
        open_watermark: int = 0,
        cid: Optional[int] = None,
    ) -> Mapping[str, Any]:
        """批量上架。POST /admin/goods.GoodsMould/shelves（popupShelves 组件）。"""

        mids = [int(i) for i in model_ids]
        if not mids:
            raise ValueError("上架必须明确提供模型 ID，禁止无 ID 扩大到全类目")
        if not site_ids or not aids:
            raise ValueError("上架必须同时选择站点与游戏服务区")
        body: dict[str, Any] = {
            "site_ids": [int(i) for i in site_ids],
            "aids": [int(i) for i in aids],
            "num": str(int(num)),
            "total": str(int(stock)),
            "duration": str(int(duration)),
            "open_watermark": int(open_watermark),
            "search": {"mids": mids},
        }
        if cid is not None:
            body["cid"] = int(cid)
        return self._json("POST", MOULD + "shelves", json_body=body)

    def recalc_price(self, model_ids: Sequence[int], *, gid: int = GID_FC27, cid: int = CID_SBC) -> Mapping[str, Any]:
        ids = [int(i) for i in model_ids]
        if not ids:
            raise ValueError("价格同步必须提供模型 ID")
        return self._json("POST", MOULD + "recalcFc27Price", json_body={"gid": gid, "cid": cid, "id": ids})

    # ---------------- 按区改价（goods 控制器） ----------------
    def list_goods(
        self,
        *,
        gid: int = GID_FC27,
        mid: Optional[int] = None,
        cid: Optional[int] = None,
        site_id: Optional[int] = None,
        page: int = 1,
        limit: int = 200,
        extra_search: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> ModelPage:
        """列在售商品（每行 = 一个 模型 × 站点 × 区服 组合）。

        ⚠️ 这张表是**按站点铺开**的：一个模型 × 18 个站点 × 3 个区服 = 54 行。
        所以不传 ``site_id`` 会看到大量"重复"（同价同名的行只差站点）。
        界面上改价时实际看的是 ``site_id=0``（"0 ALL" 模板）那 3 行 —— 每区一行。
        """

        search: list[Mapping[str, Any]] = [
            {"field": "gid", "operator": "=", "val": str(gid)},
        ]
        if mid is not None:
            search.append({"field": "mid", "operator": "=", "val": str(int(mid))})
        if cid is not None:
            search.append({"field": "cid", "operator": "=", "val": str(int(cid))})
        if site_id is not None:
            search.append({"field": "site_id", "operator": "=", "val": str(int(site_id))})
        for item in extra_search or ():
            search.append(item)
        env = self._json(
            "GET", GOODS + "index",
            params={"page": page, "limit": limit, "order": "sort,desc", "search": search},
        )
        data = env.get("data")
        if not isinstance(data, Mapping) or not isinstance(data.get("list"), list):
            raise AdminContractError("商品列表响应缺少 data.list")
        try:
            total = int(data.get("total"))
        except (TypeError, ValueError) as exc:
            raise AdminContractError("商品列表 data.total 不是整数") from exc

        def _ids(key: str) -> tuple[int, ...]:
            raw = data.get(key) or []
            if isinstance(raw, Mapping):
                raw = list(raw.keys())
            if not isinstance(raw, (list, tuple)):
                return ()
            out: list[int] = []
            for item in raw:
                try:
                    out.append(int(item))
                except (TypeError, ValueError):
                    continue
            return tuple(out)

        site_config = data.get("siteConfig") or data.get("site_config") or []
        area_config = data.get("gameAreaConfig") or data.get("game_area_config") or []
        return ModelPage(
            rows=tuple(r for r in data["list"] if isinstance(r, Mapping)),
            total=total,
            all_site_ids=_ids("all_site_ids"),
            all_aids=_ids("all_aids"),
            site_config=tuple(x for x in site_config if isinstance(x, Mapping)) if isinstance(site_config, (list, tuple)) else (),
            game_area_config=tuple(x for x in area_config if isinstance(x, Mapping)) if isinstance(area_config, (list, tuple)) else (),
            top_cid=0,
        )

    def get_goods(self, goods_id: int) -> Mapping[str, Any]:
        """读取单条在售商品的详情（含 price / num / discount 等）。"""

        env = self._json("GET", GOODS + "edit", params={"id": int(goods_id)})
        data = env.get("data")
        if not isinstance(data, Mapping) or not isinstance(data.get("row"), Mapping):
            raise AdminContractError("商品详情响应缺少 data.row")
        return data["row"]

    def whoami(self) -> Mapping[str, Any]:
        """读当前登录账号 + 这个角色**实际被授予**的权限节点集合。

        BuildAdmin 加载后台首页用的 ``GET /admin/index/index`` 会一次性返回
        ``data.adminInfo``（账号 / ``super`` 标志）+ ``data.menus``（规则树），
        所以它是**唯一**安全的"查我有没有某个权限"的手段。

        ⚠️ **千万不要拿写端点当权限探针**。实测 ``POST .../recalcFc27Price`` 的
        ``id: []`` 会被真实前端解释成「未勾选 = 重算当前类目下全部模型」——
        那不是空操作，真会动数据。

        返回::

            {"username": ..., "nickname": ..., "id": ..., "super": bool,
             "rules": frozenset[str]}
        """

        env = self._json("GET", ADMIN_INDEX)
        data = env.get("data")
        if not isinstance(data, Mapping):
            raise AdminContractError("后台首页响应缺少 data")
        info = data.get("adminInfo") or data.get("admin_info") or {}
        if not isinstance(info, Mapping):
            info = {}
        rules: set[str] = set()
        _collect_rule_names(data.get("menus"), rules)
        _collect_rule_names(data.get("rules"), rules)
        return {
            "username": info.get("username"),
            "nickname": info.get("nickname"),
            "id": info.get("id"),
            "super": bool(info.get("super")),
            "rules": frozenset(rules),
        }

    def edit_goods_price(
        self,
        goods_id: int,
        *,
        unit_price: float | str,
        discount: float | str | None = None,
    ) -> Mapping[str, Any]:
        """按区改价：``POST /admin/goods.Goods/edit``，一次一行。

        **端点是逐行的，所以签名也是单个 id** —— 这不是保守，是因为
        ``edit`` 天然要求 ``id``，结构上就不可能"漏传 id 变成改全表"
        （老实现用的 ``singleEdit`` 有那个隐患）。

        ## 写哪个字段（2026-09-28 第二次更正，实测三组实验坐实）

        产品管理页语言包（``refs/live/chunks/goods-0a1ec705.js``）::

            num:"每份数量", discount:"折扣", unit_price:"每个价格", price:"单价"

        后台口径（products-index 的 el-alert）：**前台售价 = 每个价格 × 每份数量 × 折扣 ÷ 100**。
        所以：

        ============  ============  =========================================
        页面标签       API 字段       角色
        ============  ============  =========================================
        **每个价格**   ``unit_price``  **输入**（基准价）—— 工具要写的就是它
        每份数量       ``num``        输入
        折扣          ``discount``    输入（百分比，干净状态 = 100）
        **单价**      ``price``       **结果** = 前台售价，**不要直接写**
        ============  ============  =========================================

        ⚠️ 上一版把目标价写进 ``price`` —— 那是写「单价」（结果列）。后端随即
           **反算 ``discount = price ÷ unit_price × 100``**，店里 27 行折扣被顶成
           87.05 / 124.9 / 147.74（>100 即加价），而「每个价格」原地不动 ——
           界面上看起来就像"没改价"。（⚠️ 产品**模型**页语言包把 ``price`` 叫
           "每个价格"，两个页面同名键含义相反，别拿模型页的字段名往产品页套。）

        ## 为什么是两次写入、且先写折扣

        实测 ``edit`` 的规矩：body 除 ``id`` 外**只带一个业务字段**才走快路径；
        带两个以上就走"完整编辑"分支，依次要 gid → aid → mid，凑齐后又当
        "新增"报「该产品已存在」—— **一次写 ``unit_price``+``discount`` 是死路**。

        所以拆两发，且**顺序必须是先折扣后价格**：写 ``unit_price`` 时后端会按
        「单价 = 每个价格 × 数量 × 折扣 ÷ 100」重算 ``price``，折扣还没归位时
        写价格会闪一下 ``目标价 × 畸形折扣`` 的错价（前台可见）。先归折扣，
        中间态只是回到基准价，无害。实测（已下架行）::

            造歪：{id, price:3.79}           -> 2.57 / 147.47 / 3.79
            ① {id, discount:"100"}           -> 2.57 / 100 / 2.57   ← 中间态干净
            ② {id, unit_price:"3.59"}        -> 3.59 / 100 / 3.59   ← 三件套干净

        参数::

            unit_price: 新的「每个价格」（工具算出的目标价）
            discount:   传入（如 "100"）则先发一发把折扣归位；None 则只写价格
                        （调用方在行折扣已是 100 时传 None，省一次请求）

        ⚠️ 老实现走的是 ``GOODS + "singleEdit"``，那是错的门（不含 price，
           且规则表里没建该节点 ⇒ 非 super 恒 401）。详见 ``GOODS`` 常量上方的注释。
        """

        try:
            gid = int(goods_id)
        except (TypeError, ValueError):
            raise ValueError(f"按区改价需要明确的商品行 ID，收到 {goods_id!r}") from None
        if gid <= 0:
            raise ValueError(f"按区改价需要正整数 ID，收到 {gid}")

        if discount is not None:
            self._json("POST", GOODS + "edit",
                       json_body={"id": gid, "discount": str(discount)})
        return self._json("POST", GOODS + "edit",
                          json_body={"id": gid, "unit_price": str(unit_price)})

    # ---------------- 底层 ----------------
    def _json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
        auth: bool = True,
    ) -> Mapping[str, Any]:
        raw = self._bytes(method, path, params=params, json_body=json_body, auth=auth)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdminContractError("后台响应不是有效 UTF-8 JSON") from exc
        if not isinstance(payload, Mapping):
            raise AdminContractError("后台 JSON 根节点不是对象")
        code = payload.get("code")
        if code in (302, "302"):
            raise AdminAuthError("后台返回 code=302，登录已失效")
        if code in (401, "401"):
            # 权限节点没勾，不是登录失效 —— 报文照抄给用户看，别吞掉
            raise AdminPermissionError(
                f"后台拒绝了 {method} {path}：当前账号的角色没有这个操作的权限"
                f"（后台原话：code=401；msg={str(payload.get('msg'))[:120]}）"
            )
        if code not in (1, "1"):
            msg = payload.get("msg")
            msg = str(msg)[:200] if isinstance(msg, (str, int, float)) else ""
            raise AdminContractError(f"后台返回业务 code={code!r}；msg={msg}")
        return payload

    def _bytes(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
        auth: bool = True,
    ) -> bytes:
        if auth:
            try:
                self._token = _fs_shared_admin_token()
            except RuntimeError:
                self._token = None
                raise AdminAuthError('FS_SHARED_SESSION_UNAVAILABLE') from None
        if urllib.parse.urlsplit(path).path in ('/admin/index/login', '/admin/index/loginGoogle', '/api/common/refreshToken'):
            raise AdminAuthError('FS_SHARED_AUTH_ONLY')
        method = method.upper()
        normalized = "/" + urllib.parse.urlsplit(path).path.lstrip("/")
        if normalized not in self._ALLOWED.get(method, frozenset()):
            raise AdminContractError(f"未授权的后台方法/路径：{method} {normalized}")

        query_items: list[tuple[str, Any]] = []
        if params:
            for key, value in params.items():
                query_items.extend(_query_pairs(str(key), value))
        url = f"{self.api_base}{normalized}"
        if query_items:
            url += "?" + urllib.parse.urlencode(query_items)

        headers = {"Accept": "application/json, image/*, */*", "server": "true",
                   "think-lang": "zh-cn", "User-Agent": USER_AGENT}
        if auth:
            if not self._token:
                raise AdminAuthError("尚未登录，拒绝调用后台业务接口")
            headers["batoken"] = self._token

        body: Optional[bytes] = None
        if json_body is not None:
            body = json.dumps(dict(json_body), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        attempts = 1 + (self.get_retries if method == "GET" else 0)
        last: Optional[Exception] = None
        for attempt in range(attempts):
            if attempt:
                time.sleep(self.retry_wait * attempt)
            try:
                with self._opener(request, timeout=self.timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code in (302, 401, 403):
                    raise AdminAuthError(f"后台认证失败：HTTP {exc.code}") from exc
                last = AdminHttpError(f"后台请求失败：HTTP {exc.code}", status=exc.code)
                if exc.code >= 500 and attempt + 1 < attempts:
                    continue
                raise last from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = AdminHttpError(f"后台网络请求失败：{exc}")
                if attempt + 1 < attempts:
                    continue
                raise last from exc
        raise last or AdminHttpError("后台请求失败：未知状态")


__all__ = [
    "AdminAuthError",
    "AdminClient",
    "AdminContractError",
    "AdminError",
    "AdminHttpError",
    "AdminPermissionError",
    "AuthState",
    "ModelPage",
    "ADMIN_INDEX",
    "CID_PACKS",
    "CID_PLAYERS",
    "CID_SBC",
    "CID_SBC_ADD",
    "GID_FC27",
    "MOULD",
    "new_captcha_id",
    "upload_auth_fields",
]
