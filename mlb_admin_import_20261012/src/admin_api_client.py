# -*- coding: utf-8 -*-
"""P2PAH 商品后台（admin-api.p2pah.cn）通用客户端 —— MLB / 多游戏复用版。

与 `fc27_players_cloud/球员维护工具/admin_client.py` 的关系
--------------------------------------------------------
那个客户端是 **FC27 Players 专用**（硬编码 gid=1327/cid=9627，且写入面很窄）。
本模块是**同一后台协议**的多游戏版本，只做两件事：
  1. 把 scope（gid/cid）参数化，支持 MLB；
  2. 专注「批量导入 xlsm → 产品模型生成」这条链路。

协议事实（全部照抄自已核实源码，不得凭猜改）
----------------------------------------
- 基址     https://admin-api.p2pah.cn
- 认证头   **batoken: <token>**（不是 Authorization / Bearer）
            另需 `server: 1`、`think-lang: zh-cn`、Referer / Origin = https://admin.p2pah.cn
- 验证码   GET  /api/common/captcha?server=1&id=<uuid>   → PNG
- 登录     POST /admin/index/login  JSON {username,password,captcha,captcha_id,keep}
            成功 → data.userInfo.token / data.userInfo.refreshToken
- 刷新     POST /api/common/refreshToken  JSON {refresh_token}
- 导入     POST /admin/goods.GoodsMould/importPlayers
            multipart：表单字段 gid / cid + 文件字段名 **xlsFile**
- 进度     GET  /admin/goods.GoodsMould/importPlayersProgress?job_id=<id>
- 模型列表 GET  /admin/goods.GoodsMould/index?page&limit&order&search[]
- 产品列表 GET  /admin/goods.Goods/index?page&limit&search[]

IP 白名单
--------
`/admin/*` 有后台侧 IP 白名单（历史记录：旧服务器 47.253.252.55 实测 403
"No permission request"）。**本机 IP 已在名单内**（2026-10-12 实测
`/admin/index/index` 返回 HTTP 200 + code:302，是正常"未登录"响应）。
⇒ 导入必须在本机跑，不要在服务器上跑。

安全边界（红线，不可协商）
-----------------------
- token / refreshToken **只在进程内存**，不落盘、不写日志
- 密码只作单次调用参数，不写日志、不写配置
- POST 写入**绝不自动重试**（网络失败 = 状态未知，重试可能双写）
- 幂等：导入前先查同 scope 下是否已存在同卡片，存在则跳过
"""
from __future__ import annotations

import base64
import http.cookiejar
import json
import mimetypes
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

API_BASE = "https://admin-api.p2pah.cn"
PAGE_BASE = "https://admin.p2pah.cn"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# ---- 已知 scope（gid = 游戏, cid = 类目）----
SCOPE_FC27_PLAYERS = {"gid": 1327, "cid": 9627}
# MLB 26：来自网页「产品模型管理」筛选区（游戏=927|MLB 26，类目=8233|Players）
# ⚠️ 待首次实跑核验；核验前脚本会要求 --confirm-scope
SCOPE_MLB26_PLAYERS = {"gid": 927, "cid": 8233}


class AdminError(RuntimeError):
    """后台客户端错误基类。"""


class AdminAuthError(AdminError):
    """登录 / 验证码 / token 错误。"""


class AdminAuthRequired(AdminError):
    """需要重新登录（code=302）。"""


class AdminContractError(AdminError):
    """响应结构不符合已核实契约，fail closed。"""


class AdminHttpError(AdminError):
    def __init__(self, message: str, *, status: Optional[int] = None, url: str = ""):
        super().__init__(message)
        self.status = status
        self.url = url


class AdminUnknownResult(AdminError):
    """写请求发出后结果未知。**调用方禁止自动重试。**"""


@dataclass
class AuthState:
    token: str
    refresh_token: str
    user_info: Mapping[str, Any] = field(default_factory=dict)


def _query_pairs(prefix: str, value: Any):
    """按后台前端 axios 的 bracket/index 规则展开嵌套 GET 参数。

    ⚠️ 后台筛选参数**必须是 axios 风格**（`search[0][field]=gid`），
    普通 `urlencode({"search": "[...]"})` 会被后端忽略 → 返回全表/空表。
    此函数逐字照抄自已验证过的 `fc27_players_cloud/球员维护工具/admin_client.py`。
    """
    if value is None:
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield from _query_pairs("%s[%s]" % (prefix, key), child)
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            yield from _query_pairs("%s[%d]" % (prefix, index), child)
        return
    yield prefix, value


def build_query(params: Optional[Mapping[str, Any]]) -> str:
    """把嵌套 dict 序列化成后台认的 axios bracket 查询串。"""
    if not params:
        return ""
    items: list[tuple[str, Any]] = []
    for key, value in params.items():
        items.extend(_query_pairs(str(key), value))
    return urllib.parse.urlencode(items)


def _multipart(fields: Mapping[str, Any], file_field: str,
               filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = "----wbmlb" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for k, v in fields.items():
        chunks += [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode(),
            str(v).encode("utf-8"), b"\r\n",
        ]
    ctype = mimetypes.guess_type(filename)[0] or "application/vnd.ms-excel.sheet.macroEnabled.12"
    chunks += [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {ctype}\r\n\r\n".encode(),
        content, b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class AdminApiClient:
    """admin-api.p2pah.cn 受控客户端（登录 / 只读 / 导入）。"""

    def __init__(self, *, base: str = API_BASE, timeout: int = 45,
                 log: Callable[..., None] = lambda *a, **k: None):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.log = log
        self._token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self.last_status: Optional[int] = None
        ctx = ssl.create_default_context()
        try:
            self._opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=ctx),
                urllib.request.ProxyHandler({}),   # 强制直连，绕开系统代理
            )
        except Exception:
            self._opener = urllib.request.build_opener()

    # ---------------------------------------------------------- 认证状态
    @property
    def authenticated(self) -> bool:
        return bool(self._token)

    def clear_auth(self) -> None:
        self._token = self._refresh_token = None

    # ---------------------------------------------------------- 底层请求
    def _headers(self, *, auth: bool, json_body: bool = False,
                 content_type: Optional[str] = None) -> dict:
        h = {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Referer": PAGE_BASE + "/",
            "Origin": PAGE_BASE,
            "server": "1",
            "think-lang": "zh-cn",
        }
        if json_body:
            h["Content-Type"] = "application/json"
        elif content_type:
            h["Content-Type"] = content_type
        if auth:
            if not self._token:
                raise AdminAuthError("尚未登录，拒绝调用后台业务接口")
            h["batoken"] = self._token
        return h

    def _request(self, method: str, path: str, *, params: Optional[Mapping] = None,
                 json_body: Optional[Mapping] = None, body: Optional[bytes] = None,
                 content_type: Optional[str] = None, auth: bool = True,
                 binary: bool = False, retry_get: bool = True):
        url = self.base + path
        if params:
            query = build_query(params)
            if query:
                url += ("&" if "?" in url else "?") + query
        data = body
        if json_body is not None:
            data = json.dumps(dict(json_body), ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8")
        headers = self._headers(auth=auth, json_body=json_body is not None,
                                content_type=content_type)
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        # ⚠️ 只有 GET 可安全重试；POST 失败一律保持"状态未知"，绝不重传
        attempts = 3 if (method == "GET" and retry_get) else 1
        last: Optional[Exception] = None
        for i in range(attempts):
            if i:
                time.sleep(1.2 * i)
            try:
                with self._opener.open(req, timeout=self.timeout) as r:
                    self.last_status = getattr(r, "status", None) or r.getcode()
                    raw = r.read()
                    return raw if binary else raw.decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                self.last_status = e.code
                raw = e.read()
                if e.code in (401, 403):
                    raise AdminAuthError("后台拒绝访问（HTTP %d）—— 检查 IP 白名单或凭据" % e.code)
                last = AdminHttpError("HTTP %d" % e.code, status=e.code, url=url)
                if e.code >= 500 and i + 1 < attempts:
                    continue
                raise last
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = AdminHttpError("网络错误: %r" % (e,), url=url)
                if i + 1 < attempts:
                    continue
                raise last
        raise last or AdminHttpError("未知请求失败", url=url)

    def _json(self, method: str, path: str, **kw) -> Mapping:
        raw = self._request(method, path, **kw)
        if not isinstance(raw, str):
            raise AdminContractError("期望 JSON 但收到二进制")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            raise AdminContractError("后台响应不是合法 JSON: %s" % raw[:160]) from e
        if not isinstance(payload, Mapping):
            raise AdminContractError("后台 JSON 根节点不是对象")
        code = payload.get("code")
        if code in (302, "302"):
            raise AdminAuthRequired("登录已失效（code=302）")
        if code not in (1, "1"):
            raise AdminContractError("后台业务码异常 code=%r msg=%r"
                                     % (payload.get("code"), payload.get("msg")))
        return payload

    # ---------------------------------------------------------- 登录
    def login_with_ocr(self, username: str, password: str,
                       ocr=None, *, keep: bool = True, tries: int = 3) -> AuthState:
        """ddddocr 自动过码登录。ocr 为 None 时按需 import。

        tries 次机会**只**用于验证码识别失败（识别异常 / 后台判定验证码错）——
        密码等凭据错误会立刻抛出，不消耗重试次数（避免把账号试到锁定）。
        """
        if ocr is None:
            import ddddocr  # 延迟导入，避免无 ddddocr 环境直接失败
            ocr = ddddocr.DdddOcr(show_ad=False)
        last_err = None
        for n in range(tries):
            captcha_id = str(uuid.uuid4())
            png = self._request("GET", "/api/common/captcha",
                                params={"server": "1", "id": captcha_id},
                                auth=False, binary=True)
            if not isinstance(png, bytes) or not png.startswith(b"\x89PNG\r\n\x1a\n"):
                last_err = "验证码不是 PNG"
                continue
            code = (ocr.classification(png) or "").strip()
            if not re.fullmatch(r"\d{4,6}", code):
                self.log("  [admin] 验证码识别结果异常 %r，重试" % code)
                last_err = "OCR 结果异常"
                continue
            self.log("  [admin] 第 %d 次过码识别为 %s" % (n + 1, code))
            # ⛔ 验证码被后台判错时，后台返回的是**业务失败码**（code=0
            #    msg='Please enter the correct verification code'），而 _json()
            #    对任何非 code==1 都会抛 AdminContractError。
            #    若不在这里兜住，tries 重试循环会被**第一次过码失手**直接打死
            #    （表现为「第 1 次过码识别为 5676」紧接着 AdminContractError 退出），
            #    与 docstring 承诺的语义（tries 只给验证码识别用）不符。
            #    ⇒ 只对「验证码」类失败 continue，其余（尤其密码错）原样抛出。
            try:
                payload = self._json("POST", "/admin/index/login", auth=False,
                                     json_body={"username": username,
                                                "password": password,
                                                "captcha": code,
                                                "captcha_id": captcha_id,
                                                "keep": bool(keep)})
            except AdminAuthRequired:
                raise
            except AdminContractError as e:
                msg = str(e)
                low = msg.lower()
                if "verification code" in low or "验证码" in msg:
                    self.log("  [admin] 验证码被判定错误，换一张重试（%d/%d）"
                             % (n + 1, tries))
                    last_err = "验证码错误"
                    continue
                raise
            data = payload.get("data")
            if not isinstance(data, Mapping):
                raise AdminContractError("登录响应缺少 data")
            user = data.get("userInfo")
            if not isinstance(user, Mapping) or not user.get("token"):
                raise AdminContractError("登录响应缺少 data.userInfo.token")
            self._token = str(user["token"])
            self._refresh_token = str(user.get("refreshToken") or "")
            self.log("  [admin] 登录成功")
            return AuthState(self._token, self._refresh_token, dict(user))
        raise AdminAuthError("验证码识别连续失败：%s" % last_err)

    def verify_identity(self) -> bool:
        try:
            self._json("GET", "/admin/index/index")
            return True
        except AdminAuthRequired:
            return False

    # ---------------------------------------------------------- 只读：模型
    def list_models(self, *, gid: int, cid: int, page: int = 1, limit: int = 200,
                    order: str = "sort,desc",
                    search: Optional[Sequence[Mapping]] = None) -> Mapping:
        params: dict[str, Any] = {"page": page, "limit": limit, "order": order}
        base_search = [
            {"field": "gid", "operator": "=", "val": str(gid)},
            {"field": "cid", "operator": "=", "val": str(cid)},
        ]
        params["search"] = base_search + list(search or [])
        payload = self._json("GET", "/admin/goods.GoodsMould/index", params=params)
        data = payload.get("data") or {}
        if not isinstance(data, Mapping) or not isinstance(data.get("list"), list):
            raise AdminContractError("模型列表缺少 data.list")
        return data

    # ---------------------------------------------------------- 导入
    def import_file(self, path: str | Path, *, gid: int, cid: int) -> Mapping:
        """上传 xlsm 触发批量导入。

        ⚠️ 这是**写操作**。返回后若网络异常，状态记为"未知"，调用方禁止重试。
        """
        src = Path(path).expanduser()
        if not src.is_file():
            raise FileNotFoundError(src)
        content = src.read_bytes()
        body, ctype = _multipart({"gid": gid, "cid": cid}, "xlsFile", src.name, content)
        try:
            payload = self._json("POST", "/admin/goods.GoodsMould/importPlayers",
                                 body=body, content_type=ctype)
        except AdminContractError as e:
            raise
        except AdminHttpError as e:
            raise AdminUnknownResult("导入请求结果未知（%s）—— 禁止自动重试，请人工核对后台" % e) from e
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise AdminContractError("导入响应缺少 data")
        return data

    def import_progress(self, job_id: str) -> Mapping:
        payload = self._json("GET", "/admin/goods.GoodsMould/importPlayersProgress",
                             params={"job_id": str(job_id or "").strip()})
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise AdminContractError("导入进度缺少 data")
        return data

    def wait_import(self, job_id: str, *, timeout: float = 180.0,
                    interval: float = 3.0) -> Mapping:
        t0 = time.monotonic()
        last: Mapping = {}
        while time.monotonic() - t0 < timeout:
            last = self.import_progress(job_id)
            status = str(last.get("status") or last.get("state") or "").lower()
            if status in {"done", "finished", "success", "complete", "completed", "2", "1"}:
                return last
            if status in {"fail", "failed", "error", "-1", "3"}:
                raise AdminContractError("后台导入失败: %s" % json.dumps(last, ensure_ascii=False)[:300])
            time.sleep(interval)
        raise AdminContractError("导入进度超时（%.0fs），最后状态: %s"
                                 % (timeout, json.dumps(last, ensure_ascii=False)[:300]))


__all__ = [
    "API_BASE", "PAGE_BASE", "SCOPE_FC27_PLAYERS", "SCOPE_MLB26_PLAYERS",
    "AdminApiClient", "AdminError", "AdminAuthError", "AdminAuthRequired",
    "AdminContractError", "AdminHttpError", "AdminUnknownResult", "AuthState",
    "build_query",
]
