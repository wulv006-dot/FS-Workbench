"""P2PAH 后台的受控 HTTP 客户端。

客户端只实现静态证据中核实过的后台路径，并将 token/refresh token 只保存在
当前 Python 对象内存中。它不读取浏览器 Cookie、不写密码、不自动 OCR 验证码、
不自动 refresh 重试，也不把请求内容写日志。

写入方法本身只提供受控的 HTTP 原语；``AdminAdapter`` 默认关闭写入，GUI 必须
在用户明确操作后显式启用，并自行完成导入任务/回读验收。
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Callable, Mapping, Optional, Sequence


DEFAULT_ADMIN_BASE_URL = "https://admin-api.p2pah.cn"
DEFAULT_ADMIN_PAGE_URL = "https://admin.p2pah.cn"
SUPPORTED_GID = 1327
SUPPORTED_CID = 9627


class AdminClientError(RuntimeError):
    """后台客户端错误基类。"""


class AdminAuthError(AdminClientError):
    """登录、验证码或 token 错误。"""

    def __init__(self, message: str, *, diagnostic: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        # 仅允许调用方读取不含响应值的结构诊断；不会把原始响应放进异常。
        self.diagnostic = dict(diagnostic) if isinstance(diagnostic, Mapping) else None


class AdminAuthRefreshRequired(AdminAuthError):
    """服务端要求刷新 token；客户端不会自动刷新或重试。"""


class AdminContractError(AdminClientError):
    """响应结构未达到已核实契约，调用被 fail closed。"""

    def __init__(self, message: str, *, diagnostic: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        # 诊断只允许包含脱敏后的端点/响应摘要；绝不保存原始响应或请求认证信息。
        self.diagnostic = dict(diagnostic) if isinstance(diagnostic, Mapping) else None


class AdminHttpError(AdminClientError):
    """HTTP/网络错误。"""

    def __init__(self, message: str, *, status: Optional[int] = None, url: str = "", diagnostic: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.status = status
        self.url = url
        self.diagnostic = dict(diagnostic) if isinstance(diagnostic, Mapping) else None


@dataclass(frozen=True)
class AuthState:
    """登录结果；token 字段仅供当前进程内交给客户端，不写入持久化。"""

    token: str
    refresh_token: str
    user_info: Mapping[str, Any]


@dataclass(frozen=True)
class ModelPage:
    rows: tuple[Mapping[str, Any], ...]
    total: Optional[int]
    raw: Mapping[str, Any]


_MISSING = object()
_AUTH_ROOT_FIELDS = ("code", "data")
_AUTH_DATA_FIELDS = ("userInfo", "token", "refreshToken", "type", "routePath")
_AUTH_USER_INFO_FIELDS = ("token", "refreshToken")


def _safe_type_name(value: Any) -> str:
    if value is _MISSING:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return "other"


def _safe_shape_node(value: Any, known_fields: Sequence[str]) -> dict[str, Any]:
    node: dict[str, Any] = {
        "present": value is not _MISSING,
        "type": _safe_type_name(value),
    }
    if isinstance(value, Mapping):
        node["fields"] = {
            field: {
                "present": field in value,
                "type": _safe_type_name(value[field] if field in value else _MISSING),
            }
            for field in known_fields
        }
    return node


def safe_auth_response_structure(payload: Any) -> Mapping[str, Any]:
    """返回认证响应的安全结构摘要，绝不包含任意响应值。"""

    root = payload if isinstance(payload, Mapping) else _MISSING
    data = root.get("data", _MISSING) if isinstance(root, Mapping) else _MISSING
    user_info = data.get("userInfo", _MISSING) if isinstance(data, Mapping) else _MISSING
    return {
        "root": _safe_shape_node(root, _AUTH_ROOT_FIELDS),
        "data": _safe_shape_node(data, _AUTH_DATA_FIELDS),
        "data.userInfo": _safe_shape_node(user_info, _AUTH_USER_INFO_FIELDS),
    }


def _raise_auth_structure(message: str, payload: Any) -> None:
    raise AdminAuthError(message, diagnostic=safe_auth_response_structure(payload))


def _required_auth_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 必须是非空字符串")
    return value.strip()


def _optional_auth_string(value: Any, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label} 必须是字符串")
    return value.strip()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """后台 302 常表示登录失效，禁止 urllib 静默跟随到 HTML 登录页。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _normalise_base_url(value: str) -> str:
    base = str(value or DEFAULT_ADMIN_BASE_URL).strip().rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("后台 base_url 必须是 http/https URL")
    if parsed.query or parsed.fragment:
        raise ValueError("后台 base_url 不得包含 query/fragment")
    return base


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


def _request_diagnostic(method: str, path: str, status: Optional[int] = None) -> Mapping[str, Any]:
    """仅返回端点/方法/HTTP 状态；不携带 URL query、headers 或 token。"""

    endpoint = "/" + urllib.parse.urlsplit(path).path.lstrip("/")
    return {"method": method.upper(), "endpoint": endpoint, "http_status": status}


_SENSITIVE_RESPONSE_TEXT = re.compile(
    r"(?i)(password|passwd|token|secret|authorization|cookie|session|api[_-]?key|refresh[_-]?token)(\s*[=:]\s*)([^\s&,;]+)"
)
_URL_CREDENTIAL = re.compile(r"(?i)(https?://)([^/@\s]+):([^/@\s]+)@")


def _safe_response_code(value: Any) -> Any:
    """返回不会把异常对象/嵌套响应值带入诊断的 code 摘要。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return f"<{type(value).__name__}>"


def _safe_response_message(payload: Mapping[str, Any]) -> Optional[str]:
    """提取短的、脱敏的后台 msg；不把任意响应值写入异常或日志。"""

    value = payload.get("msg", payload.get("message"))
    if value is None:
        return None
    if not isinstance(value, (str, int, float, bool)):
        return f"<{type(value).__name__}>"
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    text = _URL_CREDENTIAL.sub(r"\1[REDACTED]@", text)
    text = _SENSITIVE_RESPONSE_TEXT.sub(r"\1\2[REDACTED]", text)
    return text[:240] or None


def _multipart_body(fields: Mapping[str, Any], file_field: str, filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = "----FC27ReadonlyAdapter" + secrets.token_hex(12)
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
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{file_field}"; filename="{safe_name}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        content,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class AdminClient:
    """只访问受控路径的标准库 HTTP 客户端。"""

    # 每个 method/path 都是静态证据中已核实的操作；未知路径在本地拒绝。
    _ALLOWED: Mapping[str, frozenset[str]] = {
        "GET": frozenset({
            "/admin/index/login",
            "/admin/index/index",
            "/api/common/captcha",
            "/admin/goods.GoodsMould/index",
            "/admin/goods.GoodsMould/add",
            "/admin/goods.GoodsMould/edit",
            "/admin/goods.GoodsMould/importPlayersProgress",
            "/admin/goods.GoodsTag/index",
            "/admin/goods.Goods/index",
            "/admin/goods.Goods/edit",
        }),
        "POST": frozenset({
            "/admin/index/login",
            "/api/common/refreshToken",
            "/admin/goods.GoodsMould/importPlayers",
            "/admin/goods.GoodsMould/add",
            "/admin/goods.GoodsMould/shelves",
            "/admin/goods.GoodsMould/singleEdit",
            "/admin/goods.GoodsMould/edit",
            "/admin/goods.Goods/edit",
            "/admin/goods.GoodsMould/recalcFc27Price",
        }),
    }

    def __init__(
        self,
        base_url: str = DEFAULT_ADMIN_BASE_URL,
        *,
        timeout: float = 30.0,
        opener: Optional[Callable[..., Any]] = None,
        get_retries: int = 2,
        retry_wait: float = 0.8,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        if get_retries < 0:
            raise ValueError("get_retries 不能为负数")
        if retry_wait < 0:
            raise ValueError("retry_wait 不能为负数")
        self.base_url = _normalise_base_url(base_url)
        self.timeout = float(timeout)
        self.get_retries = int(get_retries)
        self.retry_wait = float(retry_wait)
        self._opener = opener or urllib.request.build_opener(_NoRedirect()).open
        self._token = ""
        self._refresh_token = ""

    @property
    def authenticated(self) -> bool:
        return bool(self._token)

    def clear_auth(self) -> None:
        self._token = ""
        self._refresh_token = ""

    def verify_identity(self) -> None:
        """沿用 FC Coins 的只读身份端点，登录后立即验证 token 可用。"""
        self._request_json("GET", "/admin/index/index")

    def build_url(self, path: str, params: Optional[Mapping[str, Any]] = None) -> str:
        parsed = urllib.parse.urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            raise AdminContractError("后台路径必须是相对路径")
        normalized = "/" + parsed.path.lstrip("/")
        if normalized not in {item for values in self._ALLOWED.values() for item in values}:
            raise AdminContractError(f"后台路径未列入证据白名单: {normalized}")
        query_items: list[tuple[str, Any]] = []
        if parsed.query:
            query_items.extend(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        if params:
            for key, value in params.items():
                query_items.extend(_query_pairs(str(key), value))
        query = urllib.parse.urlencode(query_items)
        return f"{self.base_url}{normalized}" + (f"?{query}" if query else "")

    # ---- 独立认证接口 ----
    def get_login_config(self) -> Mapping[str, Any]:
        envelope = self._request_json("GET", "/admin/index/login", include_auth=False)
        data = envelope.get("data")
        if not isinstance(data, Mapping) or "captcha" not in data:
            raise AdminContractError("登录配置缺少 data.captcha")
        return data

    def fetch_captcha(self, captcha_id: str) -> bytes:
        value = str(captcha_id or "").strip()
        if not value:
            raise AdminAuthError("captcha_id 不能为空")
        body = self._request_bytes("GET", "/api/common/captcha", {"server": 1, "id": value}, include_auth=False)
        if not body:
            raise AdminAuthError("验证码响应为空")
        return body

    def fetch_captcha_response(self, captcha_id: str) -> tuple[bytes, str]:
        value = str(captcha_id or "").strip()
        if not value:
            raise AdminAuthError("captcha_id 不能为空")
        body, mime = self._request_bytes(
            "GET", "/api/common/captcha", {"server": 1, "id": value},
            include_auth=False, with_content_type=True,
        )
        if mime not in {"image/png", "image/jpeg", "image/gif", "image/webp"} or not body:
            raise AdminContractError("验证码格式不在安全图片白名单")
        signatures = {
            "image/png": body.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": body.startswith(b"\xff\xd8"),
            "image/gif": body.startswith((b"GIF87a", b"GIF89a")),
            "image/webp": body.startswith(b"RIFF") and body[8:12] == b"WEBP",
        }
        if not signatures[mime]:
            raise AdminContractError("验证码响应类型与图片内容不一致")
        return body, mime

    def login(
        self,
        username: str,
        password: str,
        captcha: str,
        captcha_id: str,
        *,
        keep: bool = False,
    ) -> AuthState:
        # 密码只作为该次调用的参数使用；不写日志、不写配置、不自动重试。
        self.clear_auth()
        if not str(username).strip() or not str(password) or not str(captcha).strip() or not str(captcha_id).strip():
            raise AdminAuthError("登录需要 username/password/captcha/captcha_id")
        envelope = self._request_json(
            "POST",
            "/admin/index/login",
            json_body={
                "username": str(username).strip(),
                "password": str(password),
                "captcha": str(captcha).strip(),
                "captcha_id": str(captcha_id).strip(),
                "keep": bool(keep),
            },
            include_auth=False,
        )
        data = envelope.get("data")
        if not isinstance(data, Mapping):
            _raise_auth_structure("登录成功响应缺少 data", envelope)
        user_info = data.get("userInfo")
        if not isinstance(user_info, Mapping):
            _raise_auth_structure("登录成功响应缺少 data.userInfo", envelope)
        try:
            token = _required_auth_string(user_info.get("token"), "登录响应 data.userInfo.token")
            refresh_value = user_info.get("refreshToken", data.get("refreshToken"))
            refresh = _optional_auth_string(refresh_value, "登录响应 refreshToken")
        except ValueError as exc:
            _raise_auth_structure(str(exc), envelope)
        self._token, self._refresh_token = token, refresh
        return AuthState(token=token, refresh_token=refresh, user_info=dict(user_info))

    def refresh(self, refresh_token: Optional[str] = None) -> AuthState:
        if refresh_token is None:
            value = self._refresh_token
        elif not isinstance(refresh_token, str):
            raise AdminAuthError("refresh_token 必须是字符串")
        else:
            value = refresh_token.strip()
        if not value:
            raise AdminAuthError("没有可用 refresh_token")
        envelope = self._request_json("POST", "/api/common/refreshToken", json_body={"refresh_token": value}, include_auth=False)
        data = envelope.get("data")
        if not isinstance(data, Mapping):
            raise AdminAuthError("刷新响应缺少 data")
        try:
            token = _required_auth_string(data.get("token"), "刷新响应 data.token")
            new_refresh = _optional_auth_string(data.get("refreshToken", value), "刷新响应 data.refreshToken") or value
        except ValueError as exc:
            _raise_auth_structure(str(exc), envelope)
        self._token, self._refresh_token = token, new_refresh
        return AuthState(token=token, refresh_token=new_refresh, user_info={})

    # ---- 已登录只读接口 ----
    def list_models(
        self,
        *,
        page: int = 1,
        limit: int = 200,
        order: str = "sort,desc",
        search: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> ModelPage:
        if page < 1 or limit < 1 or limit > 200:
            raise ValueError("模型列表 page/limit 必须在 1..200")
        params: dict[str, Any] = {"page": page, "limit": limit, "order": order}
        scope = {"gid": str(SUPPORTED_GID), "cid": str(SUPPORTED_CID)}
        filtered_search: list[Mapping[str, Any]] = []
        for item in search or ():
            if not isinstance(item, Mapping):
                raise ValueError("模型列表 search 条目必须是对象")
            field = str(item.get("field") or "")
            if field in scope:
                if item.get("operator") != "=" or str(item.get("val")) != scope[field]:
                    raise ValueError(f"模型列表仅允许 {field}={scope[field]}")
                continue
            filtered_search.append(item)
        params["search"] = [
            {"field": "gid", "operator": "=", "val": scope["gid"]},
            {"field": "cid", "operator": "=", "val": scope["cid"]},
            *filtered_search,
        ]
        envelope = self._request_json("GET", "/admin/goods.GoodsMould/index", params=params)
        data = envelope.get("data")
        if not isinstance(data, Mapping) or not isinstance(data.get("list"), list):
            raise AdminContractError("模型列表响应缺少 data.list")
        rows: list[Mapping[str, Any]] = []
        for row in data["list"]:
            if not isinstance(row, Mapping):
                raise AdminContractError("模型列表含非对象行")
            rows.append(row)
        if "total" not in data:
            raise AdminContractError("模型列表响应缺少 data.total，无法完成分页核验")
        total = data.get("total")
        try:
            total = int(total)
        except (TypeError, ValueError) as exc:
            raise AdminContractError("模型列表 data.total 不是整数") from exc
        if total < 0:
            raise AdminContractError("模型列表 data.total 不得为负数")
        return ModelPage(rows=tuple(rows), total=total, raw=dict(data))

    def get_model(self, model_id: int) -> Mapping[str, Any]:
        model_id = _positive_id(model_id, "模型 ID")
        envelope = self._request_json("GET", "/admin/goods.GoodsMould/edit", params={"id": model_id})
        data = envelope.get("data")
        if not isinstance(data, Mapping) or not isinstance(data.get("row"), Mapping):
            raise AdminContractError("模型详情响应缺少 data.row")
        return data["row"]

    def list_tags(self, *, gid: int = SUPPORTED_GID, cid: int = SUPPORTED_CID) -> tuple[Mapping[str, Any], ...]:
        _check_scope(gid, cid)
        # tagSelect has no usable permission node; index requires a nonempty search.
        rows = []
        seen = set()
        expected_total = None
        for page in range(1, 41):
            envelope = self._request_json("GET", "/admin/goods.GoodsTag/index",
                params={"page": page, "limit": 500, "quick_search": "%", "order": "sort,desc"})
            data = envelope.get("data")
            if not isinstance(data, Mapping) or not isinstance(data.get("list"), list):
                raise AdminContractError("Invalid tag list response")
            raw_total = data.get("total")
            if isinstance(raw_total, bool) or not str(raw_total).isascii() or not str(raw_total).isdecimal():
                raise AdminContractError("Invalid tag total")
            total = int(raw_total)
            if expected_total is None:
                expected_total = total
            if total != expected_total:
                raise AdminContractError("Tag catalog changed during pagination; retry")
            batch = data["list"]
            if len(batch) > 500:
                raise AdminContractError("Invalid tag page size")
            for item in batch:
                if not isinstance(item, Mapping):
                    raise AdminContractError("Invalid tag row")
                tag_id = item.get("id")
                if isinstance(tag_id, bool) or not str(tag_id).isascii() or not str(tag_id).isdecimal() or int(tag_id) <= 0:
                    raise AdminContractError("Invalid tag id")
                tag_id = int(tag_id)
                if tag_id in seen:
                    raise AdminContractError("Duplicate tag page; retry")
                seen.add(tag_id)
                rows.append(item)
            if len(rows) > total:
                raise AdminContractError("Tag rows exceed total")
            if len(rows) == total:
                break
            if not batch:
                raise AdminContractError("Incomplete tag catalog")
        else:
            raise AdminContractError("Tag catalog exceeds page limit")
        result = []
        for item in rows:
            categories = item.get("cate_id")
            if not isinstance(categories, (list, tuple)):
                categories = str(categories).split(",")
            if str(item.get("gid")) == str(gid) and str(cid) in [str(value).strip() for value in categories]:
                result.append(item)
        return tuple(result)

    def get_model_add_form(self, *, gid: int = SUPPORTED_GID, cid: int = SUPPORTED_CID) -> Mapping[str, Any]:
        _check_scope(gid, cid)
        envelope = self._request_json("GET", "/admin/goods.GoodsMould/add", params={"gid": gid, "cid": cid})
        data = envelope.get("data")
        if not isinstance(data, Mapping) or not isinstance(data.get("row"), Mapping):
            raise AdminContractError("新增模型表单缺少 data.row")
        return data

    def add_model(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(payload, Mapping) or payload.get("id") is not None:
            raise ValueError("新增模型不得携带已有模型 ID")
        _check_scope(payload.get("gid"), payload.get("cid"))
        return self._request_json("POST", "/admin/goods.GoodsMould/add", json_body=dict(payload))

    def shelves_models(self, model_ids: Sequence[int], *, gid: int = SUPPORTED_GID,
                       cid: int = SUPPORTED_CID, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        _check_scope(gid, cid)
        ids = _positive_ids(model_ids, "上架模型 ID")
        if len(ids) != 1:
            raise ValueError("逐人上架必须仅包含一个模型")
        if not isinstance(payload, Mapping) or set(payload) - {
            "num", "min_qty", "total", "discount", "price", "status", "is_rec",
            "duration", "open_watermark", "site_ids", "aids",
        }:
            raise ValueError("上架参数超出已核原生合同")
        if set(payload.get("site_ids") or []) != {266} or set(payload.get("aids") or []) != {21585, 21587, 21589}:
            raise ValueError("仅允许 MMOEXP FC27 三平台上架范围")
        body = {**dict(payload), "search": {"mids": ids[0]}}
        return self._request_json("POST", "/admin/goods.GoodsMould/shelves", json_body=body)

    def get_import_progress(self, job_id: str) -> Mapping[str, Any]:
        job_id = str(job_id or "").strip()
        if not job_id:
            raise ValueError("job_id 不能为空")
        envelope = self._request_json("GET", "/admin/goods.GoodsMould/importPlayersProgress", params={"job_id": job_id})
        data = envelope.get("data")
        if not isinstance(data, Mapping):
            raise AdminContractError("导入进度响应缺少 data")
        return data

    def get_products(self, model_id: int, *, limit: int = 200) -> tuple[Mapping[str, Any], ...]:
        """读取实际产品列表；价格验收由适配器检查字段，不读取模型默认 price。"""

        model_id = _positive_id(model_id, "模型 ID")
        if limit < 1 or limit > 200:
            raise ValueError("产品分页 limit 必须在 1..200")
        result: list[Mapping[str, Any]] = []
        page = 1
        expected_total: Optional[int] = None
        search = [
            {"field": "gid", "operator": "=", "val": str(SUPPORTED_GID)},
            {"field": "cid", "operator": "=", "val": str(SUPPORTED_CID)},
            {"field": "mid", "operator": "=", "val": str(model_id)},
        ]
        while True:
            envelope = self._request_json(
                "GET",
                "/admin/goods.Goods/index",
                params={"page": page, "limit": limit, "search": search},
            )
            data = envelope.get("data")
            if not isinstance(data, Mapping) or not isinstance(data.get("list"), list):
                raise AdminContractError("产品列表响应缺少 data.list，拒绝用模型 price 代替产品售价")
            raw_total = data.get("total")
            if raw_total is None:
                raise AdminContractError("产品列表响应缺少 data.total，无法完成分页核验")
            try:
                total = int(raw_total)
            except (TypeError, ValueError) as exc:
                raise AdminContractError("产品列表 data.total 不是整数") from exc
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise AdminContractError("产品列表分页 total 不一致")
            page_rows = data["list"]
            if len(page_rows) > limit:
                raise AdminContractError("产品列表单页行数超过 limit，无法核验分页范围")
            for row in page_rows:
                if not isinstance(row, Mapping):
                    raise AdminContractError("产品列表含非对象行")
                result.append(row)
            if len(result) > expected_total:
                raise AdminContractError("产品列表返回行数超过 data.total，无法安全写入")
            if len(result) >= expected_total:
                return tuple(result)
            if not page_rows:
                raise AdminContractError("产品列表提前结束，未完成 total 核验")
            page += 1
            if page > 10000:
                raise AdminContractError("产品列表分页超过安全上限")

    # ---- 写入原语；由 AdminAdapter 的 write_enabled 控制调用 ----
    def upload_players(self, path: str | Path, *, gid: int, cid: int) -> Mapping[str, Any]:
        _check_scope(gid, cid)
        source = Path(path).expanduser()
        if not source.is_file():
            raise FileNotFoundError(source)
        content = source.read_bytes()
        body, content_type = _multipart_body({"gid": gid, "cid": cid}, "xlsFile", source.name, content)
        return self._request_json(
            "POST",
            "/admin/goods.GoodsMould/importPlayers",
            body=body,
            content_type=content_type,
        )

    def single_edit(self, payload: Mapping[str, Any], *, params: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        if not isinstance(payload, Mapping) or not payload:
            raise ValueError("singleEdit payload 不能为空")
        return self._request_json("POST", "/admin/goods.GoodsMould/singleEdit", params=params, json_body=dict(payload))

    def edit_model(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """提交模型字段的最小编辑请求。

        只开放下架流程需要的 ``more``、``status``、``auto_off``，以及网页
        编辑表单的 ``tid``。网页清空标签已实测；最小 ``tid=[]`` 请求待脚本
        生产回读验收。标签清空使用最小编辑体，
        避免将模型详情中的展示/定价字段误作为写入内容。调用方必须先读回并
        构造完整的 ``more``，以保留其它扩展项。
        """

        return self._edit_fields(
            "/admin/goods.GoodsMould/edit",
            payload,
            allowed_fields={"more", "status", "auto_off", "tid"},
            label="模型",
        )

    def edit_product(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """只提交产品库存字段；产品级 auto_off 明确不在允许字段内。"""

        return self._edit_fields(
            "/admin/goods.Goods/edit",
            payload,
            allowed_fields={"total"},
            label="产品",
        )

    def recalc_fc27_price(self, *, model_ids: Sequence[int], gid: int = SUPPORTED_GID, cid: int = SUPPORTED_CID) -> Mapping[str, Any]:
        _check_scope(gid, cid)
        ids = _positive_ids(model_ids, "模型 ID")
        if not ids:
            raise ValueError("价格同步必须明确提供模型 ID，禁止无 ID 扩大到全类目")
        return self._request_json(
            "POST",
            "/admin/goods.GoodsMould/recalcFc27Price",
            json_body={"gid": gid, "cid": cid, "id": ids},
        )

    def set_product_status(self, model_id: int, product_id: int, status: int) -> Mapping[str, Any]:
        """Set only a product's sale status after binding it to the explicit FC model."""
        mid = _positive_id(model_id, "模型 ID")
        pid = _positive_id(product_id, "商品 ID")
        if type(status) is not int or status not in (0, 1):
            raise ValueError("商品状态必须为 0 或 1")
        rows = [row for row in self.get_products(mid) if str(row.get("id")) == str(pid)]
        if len(rows) != 1 or str(rows[0].get("mid")) != str(mid):
            raise AdminContractError("商品不属于本次明确模型范围")
        _check_scope(rows[0].get("gid"), rows[0].get("cid"))
        return self._request_json("POST", "/admin/goods.Goods/edit", json_body={"id": pid, "status": status})

    def set_product_fallback_price(self, model_id: int, product_id: int) -> Mapping[str, Any]:
        """Apply the user's 9999 sale-price fallback only to a missing-market-price platform."""
        mid = _positive_id(model_id, "模型 ID")
        pid = _positive_id(product_id, "商品 ID")
        rows = [row for row in self.get_products(mid) if str(row.get("id")) == str(pid)]
        if len(rows) != 1 or str(rows[0].get("mid")) != str(mid):
            raise AdminContractError("兜底商品不属于本次明确模型范围")
        _check_scope(rows[0].get("gid"), rows[0].get("cid"))
        field = {"21587": "ps_price", "21585": "ps_price", "21589": "pc_price"}.get(str(rows[0].get("aid")))
        model = self.get_model(mid)
        extend = {entry.get("key"): entry.get("value") for entry in (model.get("more") or {}).get("extend", [])}
        if field is None or field not in extend or extend[field] not in (None, ""):
            raise AdminContractError("有价或未知平台不得写入缺价兜底售价")
        return self._request_json("POST", "/admin/goods.Goods/edit", json_body={"id": pid, "unit_price": "9999"})

    def _edit_fields(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        allowed_fields: set[str],
        label: str,
    ) -> Mapping[str, Any]:
        if not isinstance(payload, Mapping) or not payload:
            raise ValueError(f"{label} edit payload 不能为空")
        if "id" not in payload:
            raise ValueError(f"{label} edit payload 缺少 id")
        normalized_id = _positive_id(payload["id"], f"{label} ID")
        fields = {str(key): value for key, value in payload.items() if key != "id"}
        unknown = set(fields) - allowed_fields
        if unknown:
            raise ValueError(f"{label} edit payload 含未授权字段: {sorted(unknown)!r}")
        if not fields:
            raise ValueError(f"{label} edit payload 没有可编辑字段")
        if "more" in fields and not isinstance(fields["more"], Mapping):
            raise ValueError("模型 more 必须是对象")
        if "tid" in fields:
            raw_tag_ids = fields["tid"]
            if not isinstance(raw_tag_ids, (list, tuple)):
                raise ValueError("模型 tid 必须是标签 ID 数组")
            fields["tid"] = _positive_ids(raw_tag_ids, "模型标签 ID")
        return self._request_json(
            "POST",
            path,
            json_body={"id": normalized_id, **fields},
        )

    # ---- 请求底层 ----
    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
        body: Optional[bytes] = None,
        content_type: Optional[str] = None,
        include_auth: bool = True,
    ) -> Mapping[str, Any]:
        raw = self._request_bytes(method, path, params=params, json_body=json_body, body=body, content_type=content_type, include_auth=include_auth)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdminContractError("后台响应不是有效 UTF-8 JSON") from exc
        if not isinstance(payload, Mapping):
            raise AdminContractError("后台 JSON 根节点不是对象")
        code = payload.get("code")
        if code in (302, "302"):
            raise AdminAuthError("后台返回 code=302，登录已失效", diagnostic=_request_diagnostic(method, path))
        if code in (409, "409"):
            raise AdminAuthRefreshRequired("后台返回 code=409，需要刷新 token；本客户端不会自动重试", diagnostic=_request_diagnostic(method, path))
        if code not in (1, "1"):
            safe_code = _safe_response_code(code)
            safe_msg = _safe_response_message(payload)
            diagnostic = dict(_request_diagnostic(method, path))
            diagnostic["response_code"] = safe_code
            if safe_msg is not None:
                diagnostic["response_msg"] = safe_msg
            detail = f"；msg={safe_msg}" if safe_msg is not None else ""
            endpoint = f"{method.upper()} {diagnostic['endpoint']}"
            raise AdminContractError(
                f"后台返回未核实业务 code: {safe_code!r}{detail}；endpoint={endpoint}",
                diagnostic=diagnostic,
            )
        return payload

    def _request_bytes(
        self,
        method: str,
        path: str,
        params: Optional[Mapping[str, Any]] = None,
        *,
        json_body: Optional[Mapping[str, Any]] = None,
        body: Optional[bytes] = None,
        content_type: Optional[str] = None,
        include_auth: bool = True,
        with_content_type: bool = False,
    ) -> bytes | tuple[bytes, str]:
        method = method.upper()
        parsed_path = "/" + urllib.parse.urlsplit(path).path.lstrip("/")
        if parsed_path not in self._ALLOWED.get(method, frozenset()):
            raise AdminContractError(f"未授权的后台方法/路径: {method} {parsed_path}")
        url = self.build_url(parsed_path, params)
        headers = {"Accept": "application/json, image/*, */*", "server": "true", "think-lang": "zh-cn"}
        if include_auth:
            if not self._token:
                raise AdminAuthError("尚未登录，拒绝调用后台业务接口")
            headers["batoken"] = self._token
        request_body = body
        if json_body is not None:
            if body is not None:
                raise ValueError("json_body 与 body 不能同时提供")
            request_body = json.dumps(dict(json_body), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(url, data=request_body, headers=headers, method=method)
        # GET 是幂等只读，可安全重试瞬时网络/5xx 故障；POST 可能触发后台写入，
        # 任何失败都必须保持"状态未知即禁止重传"的红线，绝不自动重试。
        attempts = 1 + (self.get_retries if method == "GET" else 0)
        last_error: AdminHttpError | None = None
        for attempt in range(attempts):
            if attempt:
                time.sleep(self.retry_wait * attempt)
            try:
                with self._opener(request, timeout=self.timeout) as response:
                    result = response.read()
                    if with_content_type:
                        raw_type = response.headers.get("Content-Type", "") if getattr(response, "headers", None) else ""
                        return result, raw_type.split(";", 1)[0].strip().lower()
                    return result
            except urllib.error.HTTPError as exc:
                diagnostic = _request_diagnostic(method, parsed_path, exc.code)
                if exc.code in (302, 401, 403):
                    raise AdminAuthError(f"后台认证失败: HTTP {exc.code}", diagnostic=diagnostic) from exc
                last_error = AdminHttpError(f"后台请求失败: HTTP {exc.code}", status=exc.code, url=url, diagnostic=diagnostic)
                if exc.code >= 500 and attempt + 1 < attempts:
                    continue
                raise last_error from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = AdminHttpError(f"后台网络请求失败: {exc}", url=url, diagnostic=_request_diagnostic(method, parsed_path))
                if attempt + 1 < attempts:
                    continue
                raise last_error from exc
        raise last_error or AdminHttpError("后台请求失败: 未知重试状态", url=url)


def _positive_id(value: Any, label: str) -> int:
    if isinstance(value, (bool, float)):
        raise ValueError(f"{label} 必须是整数")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是整数") from exc
    if result < 1:
        raise ValueError(f"{label} 必须大于 0")
    return result


def _positive_ids(values: Sequence[Any], label: str) -> list[int]:
    result = [_positive_id(value, label) for value in values]
    if len(result) != len(set(result)):
        raise ValueError(f"{label} 不得重复")
    return result


def _check_scope(gid: int, cid: int) -> None:
    if int(gid) != SUPPORTED_GID or int(cid) != SUPPORTED_CID:
        raise ValueError(f"仅允许 gid={SUPPORTED_GID}, cid={SUPPORTED_CID}")


__all__ = [
    "AdminAuthError",
    "AdminAuthRefreshRequired",
    "AdminClient",
    "AdminClientError",
    "AdminContractError",
    "AdminHttpError",
    "AuthState",
    "DEFAULT_ADMIN_BASE_URL",
    "DEFAULT_ADMIN_PAGE_URL",
    "ModelPage",
    "SUPPORTED_CID",
    "SUPPORTED_GID",
    "safe_auth_response_structure",
]
