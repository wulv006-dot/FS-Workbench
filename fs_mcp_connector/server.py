"""Standard MCP transport and OAuth browser flow; no model calls or business writes."""
from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import jsonschema
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from .auth import AuthError, PortalError
from .consent import render_browser_error, render_consent
from .response_view import present

LOG = logging.getLogger(__name__)
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
TOOLS = [
    Tool(name="fs_list_data_sources", description="无参数返回本人可见的简短导航，包含全部操作名、module、方法索引和覆盖状态；须再传module取得该模块完整参数schema、来源、覆盖缺项和data_methods口径后查询。由当前AI自主分析，不调用Hermes会话或报告生成。", inputSchema={"type": "object", "properties": {"module": {"type": "string", "minLength": 1, "maxLength": 80}}, "additionalProperties": False}, annotations=READ_ONLY),
    Tool(name="fs_query_data", description="按目录operation和arguments读取原权限业务数据。小结果原形返回；大结果给response_view字段索引，按data_path(JSON Pointer，如/profile/primary)继续展开；数组用offset/limit展示分页，每页最多20，沿next_offset取全。data_context按祖先路径保留原范围/口径/覆盖/上游游标，data_context_index中的元数据须继续读取；不同来源范围可能不同。value_complete仅指展示节点，不能当业务全覆盖，实时多次读取仍非快照。超长字符串明确报response_too_large，不截断。", inputSchema={"type": "object", "properties": {"operation": {"type": "string", "minLength": 1}, "arguments": {"type": "object"}, "data_path": {"type": "string", "maxLength": 1024}, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "required": ["operation", "arguments"], "additionalProperties": False}, annotations=READ_ONLY),
]


def _result(data: dict, *, error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False))], structuredContent=data, isError=error)


def _oauth_values(parsed: dict) -> dict:
    # Native clients can repeat RFC 8707 resource; its single audience must remain identical.
    for key, values in parsed.items():
        if len(values) != 1 and not (key == "resource" and values and all(value == values[0] for value in values)):
            raise ValueError("invalid_request")
    return {key: values[0] for key, values in parsed.items()}


async def _params(request: Request) -> dict:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise ValueError("request_too_large")
    if request.headers.get("content-type", "").split(";")[0] == "application/json":
        def unique_fields(pairs):
            result = dict(pairs)
            if len(result) != len(pairs):
                raise ValueError("duplicate_parameter")
            return result
        result = json.loads(body, object_pairs_hook=unique_fields)
        if not isinstance(result, dict):
            raise ValueError("invalid_request")
        return result
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True, strict_parsing=True)
    return _oauth_values(parsed)


def create_app(*, store, portal, catalog, backend, issuer: str, resource_url: str,
               cookie_names: tuple[str, ...] = ("MMOEXP_AUTH", "FS_ACCESS_CANDIDATE"),
               login_path: str = "/__auth/login") -> Starlette:
    """Dependencies use the same portal/IAM and query services as FS; never caller identities."""
    issuer = issuer.rstrip("/")
    origin = urlsplit(issuer)
    resource = urlsplit(resource_url)
    if (origin.scheme != "https" and not (origin.scheme == "http" and origin.hostname in {"127.0.0.1", "localhost", "::1"})) or origin.query or origin.fragment or origin.username:
        raise ValueError("issuer requires HTTPS (HTTP is restricted to loopback tests)")
    if (resource.scheme, resource.netloc) != (origin.scheme, origin.netloc) or resource.query or resource.fragment or not resource.path or not login_path.startswith("/") or login_path.startswith("//"):
        raise ValueError("resource and login must be on the configured FS origin")
    if store.resource != resource_url:
        raise ValueError('OAuth store resource must match the MCP endpoint')
    prefix = origin.path.rstrip("/")
    oauth_base = prefix + "/oauth"
    asset_base = prefix + "/assets"
    resource_metadata = "/.well-known/oauth-protected-resource" + resource.path
    secure_headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
    # Preserve the consent POST Origin without sending referrers to external callbacks.
    browser_headers = {**secure_headers, "Content-Security-Policy": "default-src 'none'; style-src 'self'; script-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'", "Referrer-Policy": "same-origin", "X-Content-Type-Options": "nosniff"}
    root = Path(__file__).resolve().parents[1]
    assets = {
        asset_base + '/fs-tokens.css': (root/'ui-system/tokens/fs-tokens.css', 'text/css'),
        asset_base + '/fs-ui.css': (root/'ui-system/components/fs-ui.css', 'text/css'),
        asset_base + '/fs-theme.js': (root/'ui-system/adapters/fs-theme.js', 'text/javascript'),
        asset_base + '/consent.css': (Path(__file__).with_name('consent.css'), 'text/css'),
    }

    async def static_asset(request):
        path, media_type = assets[request.url.path]
        try:
            body = await run_in_threadpool(path.read_bytes)
        except OSError:
            return JSONResponse({'error': 'asset_unavailable'}, status_code=503, headers=secure_headers)
        return Response(body, media_type=media_type, headers={**secure_headers, 'X-Content-Type-Options': 'nosniff'})

    def browser_error(reason, status):
        return HTMLResponse(render_browser_error(reason=reason, asset_base=asset_base),
                            status_code=status, headers=browser_headers)
    mcp = Server("FS data", version="1.0.0", instructions="FS 提供只读业务数据和 data_methods 取数口径，由当前 AI 按问题自主分析。先查看数据目录，只调用获准操作，保留来源、口径、期间、完整性和续页信息。方法导航不是强制报告模板；不接入 Hermes 会话、代理或报告生成。")

    @mcp.list_tools()
    async def list_tools():
        return TOOLS

    @mcp.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        definition = next((tool for tool in TOOLS if tool.name == name), None)
        if definition is None:
            return _result({"error": "unknown_tool"}, error=True)
        try:
            jsonschema.validate(arguments, definition.inputSchema)
        except jsonschema.ValidationError:
            return _result({"error": "invalid_arguments"}, error=True)
        principal = mcp.request_context.request.state.principal
        try:
            if name == "fs_list_data_sources":
                return _result(await run_in_threadpool(catalog.list, principal, **arguments))
            queried = await run_in_threadpool(backend.query, principal, arguments["operation"], arguments["arguments"])
            return _result(present(queried, **{key: arguments[key] for key in ('data_path', 'offset', 'limit') if key in arguments}))
        except (ValueError, PermissionError, RuntimeError) as exc:
            if getattr(exc, 'display_result', None) is not None:
                return _result(exc.display_result, error=True)
            code = getattr(exc, "code", None) or ("permission_denied" if isinstance(exc, PermissionError) else "query_failed")
            detail = {"error": code, "status_code": getattr(exc, "status_code", 400 if isinstance(exc, ValueError) else 503)}
            if getattr(exc, 'retry_after', None) is not None:
                detail['retryAfter'] = exc.retry_after
            return _result(detail, error=True)

    manager = StreamableHTTPSessionManager(mcp, stateless=True, json_response=True,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=[resource.netloc], allowed_origins=[f"{origin.scheme}://{origin.netloc}"]))

    async def mcp_endpoint(scope, receive, send):
        request = Request(scope, receive)
        auth = request.headers.get("authorization", "").split(" ", 1)
        try:
            if len(auth) != 2 or auth[0].lower() != "bearer" or not auth[1] or len(auth[1]) > 4096:
                raise ValueError("invalid_token")
            principal = await run_in_threadpool(store.authenticate, auth[1], resource_url)
        except (AuthError, PortalError, ValueError) as exc:
            unavailable = (isinstance(exc, PortalError) and exc.status not in {401, 403}
                           or isinstance(exc, AuthError) and exc.error == 'temporarily_unavailable')
            status = 503 if unavailable else 401
            response = JSONResponse({"error": "temporarily_unavailable" if status == 503 else "invalid_token"}, status_code=status,
                headers={**secure_headers, "WWW-Authenticate": f'Bearer resource_metadata="{origin.scheme}://{origin.netloc}{resource_metadata}", scope="fs.read"'})
            await response(scope, receive, send)
            return
        scope.setdefault("state", {})["principal"] = principal
        if request.method == 'POST':
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 65536:
                    await JSONResponse({'error': 'request_too_large'}, status_code=413)(scope, receive, send)
                    return
            original_receive = receive
            delivered = False
            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                return await original_receive()
            receive = bounded_receive
        await manager.handle_request(scope, receive, send)

    async def metadata(request):
        if request.url.path.startswith("/.well-known/oauth-protected-resource"):
            return JSONResponse({"resource": resource_url, "authorization_servers": [issuer], "scopes_supported": ["fs.read"], "bearer_methods_supported": ["header"]})
        return JSONResponse({"issuer": issuer, "authorization_endpoint": issuer + "/oauth/authorize", "token_endpoint": issuer + "/oauth/token", "registration_endpoint": issuer + "/oauth/register", "revocation_endpoint": issuer + "/oauth/revoke", "response_types_supported": ["code"], "grant_types_supported": ["authorization_code", "refresh_token"], "code_challenge_methods_supported": ["S256"], "token_endpoint_auth_methods_supported": ["none"], "scopes_supported": ["fs.read"]})

    async def browser_principal(request):
        selected = SimpleCookie()
        for cookie_name in cookie_names:
            value = request.cookies.get(cookie_name, "")
            if value:
                selected[cookie_name] = value
        if not selected:
            return None
        try:
            cookie = '; '.join(part.OutputString() for part in selected.values())
            return await run_in_threadpool(portal.verify, cookie, "/dashboard/", "GET")
        except PortalError as exc:
            if exc.status == 401:
                return None
            raise

    async def authorize(request):
        try:
            if len(request.scope.get("query_string", b"")) > 8192:
                raise ValueError("invalid_request")
            if request.method == "GET":
                items = parse_qs(request.url.query, keep_blank_values=True)
                params = _oauth_values(items)
                # The current consent UI is fixed-language; this standard hint never changes authorization.
                locales = params.pop('ui_locales', None)
                if locales is not None and (len(locales) > 128 or not re.fullmatch(
                        r'[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*(?: [A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*)*', locales)):
                    raise ValueError('invalid_request')
                if set(params) == {"request_id"}:
                    params = await run_in_threadpool(store.consume_login_request, params["request_id"])
                if set(params) - {"client_id", "redirect_uri", "resource", "code_challenge", "code_challenge_method", "response_type", "scope", "state"} or params.get("response_type") != "code" or params.get("code_challenge_method") != "S256":
                    raise ValueError("invalid_request")
                await run_in_threadpool(store.validate_authorization, params.get("client_id", ""), params.get("redirect_uri", ""), params.get("resource", ""), params.get("code_challenge", ""), params.get("scope", "fs.read"))
                principal = await browser_principal(request)
                if principal is None:
                    request_id = await run_in_threadpool(store.create_login_request, params)
                    return RedirectResponse(login_path + "?" + urlencode({"next": oauth_base + "/authorize?" + urlencode({"request_id": request_id})}), status_code=302, headers=secure_headers)
                pending, csrf = await run_in_threadpool(store.create_pending, params, principal)
                client = await run_in_threadpool(store.get_client, params["client_id"])
                page = render_consent(principal=principal, client_name=client.get('client_name') or client['client_id'],
                    redirect_uri=params['redirect_uri'], pending_id=pending, csrf_token=csrf,
                    oauth_base=oauth_base, asset_base=asset_base)
                # Chrome also checks the form's redirect against form-action.
                callback = urlsplit(params['redirect_uri'])
                callback_source = quote(f'{callback.scheme}://{callback.netloc}', safe=':/[]')
                consent_headers = {**browser_headers, 'Content-Security-Policy': browser_headers['Content-Security-Policy'].replace(
                    "form-action 'self';", f"form-action 'self' {callback_source};")}
                return HTMLResponse(page, headers=consent_headers)
            if request.headers.get("origin") != f"{origin.scheme}://{origin.netloc}":
                return browser_error('invalid_request', 403)
            form = await _params(request)
            if (set(form) != {"pending_id", "csrf_token", "decision"}
                    or not all(isinstance(value, str) for value in form.values())
                    or form["decision"] not in {"approve", "deny"}):
                raise ValueError("invalid_request")
            principal = await browser_principal(request)
            if principal is None:
                return browser_error('login_required', 401)
            params = await run_in_threadpool(store.consume_pending, form["pending_id"], form["csrf_token"], principal)
            result = {"state": params["state"]} if "state" in params else {}
            if form["decision"] == "approve":
                result["code"] = await run_in_threadpool(store.issue_code, params["client_id"], params["redirect_uri"], params["resource"], params["code_challenge"], principal, params.get("scope", "fs.read"))
            else:
                result["error"] = "access_denied"
            separator = "&" if "?" in params["redirect_uri"] else "?"
            return RedirectResponse(params["redirect_uri"] + separator + urlencode(result), status_code=302, headers=secure_headers)
        except (AuthError, PortalError, ValueError, KeyError) as exc:
            return oauth_error(exc, browser=True)

    def oauth_error(exc, *, browser=False):
        if isinstance(exc, PortalError):
            error = 'login_required' if browser and exc.status == 401 else 'access_denied' if exc.status in {401, 403} else 'temporarily_unavailable'
            status = exc.status if exc.status in {401, 403} else 503
        else:
            error = exc.error if isinstance(exc, AuthError) else "invalid_request"
            status = 503 if error == "temporarily_unavailable" else 401 if error == "invalid_client" else 400
        if browser:
            return browser_error(error, status)
        return JSONResponse({"error": error}, status_code=status, headers=secure_headers)

    async def oauth_post(request):
        try:
            params = await _params(request)
            if request.url.path.endswith("/register"):
                grants = params.get("grant_types", ["authorization_code"])
                if set(params) - {"redirect_uris", "client_name", "token_endpoint_auth_method", "grant_types", "response_types", "scope", "application_type"} or params.get("application_type", "web") not in ("native", "web") or params.get("token_endpoint_auth_method", "none") != "none" or params.get("response_types", ["code"]) != ["code"] or params.get("scope", "fs.read") != "fs.read":
                    raise ValueError("invalid_request")
                return JSONResponse(await run_in_threadpool(store.register_client, params["redirect_uris"], params.get("client_name", ""), grants), status_code=201, headers=secure_headers)
            if request.url.path.endswith("/revoke"):
                if set(params) - {"token", "client_id", "token_type_hint"}:
                    raise ValueError("invalid_request")
                await run_in_threadpool(store.revoke, params["token"], params["client_id"])
                return JSONResponse({}, headers=secure_headers)
            if params.get("grant_type") == "authorization_code":
                if set(params) - {"grant_type", "code", "client_id", "redirect_uri", "resource", "code_verifier"}:
                    raise ValueError("invalid_request")
                result = await run_in_threadpool(store.exchange_code, params["code"], params["client_id"], params["redirect_uri"], params["resource"], params["code_verifier"])
            elif params.get("grant_type") == "refresh_token":
                if set(params) - {"grant_type", "refresh_token", "client_id", "resource", "scope"} or params.get("scope", "fs.read") != "fs.read":
                    raise ValueError("invalid_request")
                result = await run_in_threadpool(store.refresh, params["refresh_token"], params["client_id"], params["resource"])
            else:
                return JSONResponse({"error": "unsupported_grant_type"}, status_code=400, headers=secure_headers)
            return JSONResponse(result, headers=secure_headers)
        except (AuthError, PortalError, ValueError, KeyError, TypeError) as exc:
            return oauth_error(exc)

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    class MCPRoute:
        async def __call__(self, scope, receive, send):
            await mcp_endpoint(scope, receive, send)

    routes = [Route("/.well-known/oauth-authorization-server" + prefix, metadata),
              Route(resource_metadata, metadata),
              *[Route(path, static_asset, methods=['GET']) for path in assets],
              Route(oauth_base + "/authorize", authorize, methods=["GET", "POST"]),
              *[Route(oauth_base + "/" + name, oauth_post, methods=["POST"]) for name in ("register", "token", "revoke")],
              Route(resource.path, MCPRoute(), methods=["GET", "POST", "DELETE"])]
    if resource.path != "/":
        routes.insert(2, Route("/.well-known/oauth-protected-resource", metadata))
    return Starlette(routes=routes, lifespan=lifespan)
