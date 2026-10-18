"""单进程 WSGI 工作台。仅从本机反代进入，门禁身份由可信 Nginx 覆写。"""
from __future__ import annotations

import json
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server
from socketserver import ThreadingMixIn

from 球员维护工具.admin_adapter import AdminAdapter, build_existing_model_map
from 球员维护工具.admin_client import AdminAuthError
from 球员维护工具.existing_model_domain import normalize_model_rows

from .client_factory import admin_client
from .collection import collect_only, collection_lock
from .existing_action_service import execute_existing_action, prepare_existing_action, prepare_unlist_preview
from .model_service import export_selected_futbin_ids, intersect_database_properties, query_models, refresh_models
from .new_card_service import (execute_confirmed_plan, prepare_plan,
                               verify_manual_new_card_scope, verify_source_policy)
from .repository import Repository, StateError
from .settings import Settings
from .shared_session import shared_client
from .model_image_service import (create_batch, stage_png, prepare_image_plan,
                                  verify_image_plan, execute_image_plan, MAX_PNG_BYTES)


class ThreadingServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args: Any) -> None:
        # 不记录 URL、Cookie、认证字段或请求体。
        return


class App:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.repository = Repository(settings.data_root / "db" / "control.sqlite3")
        # 缺库即拒绝启动，避免丢失未决账本后自动形成空状态。
        with self.repository.connection() as db:
            if db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] != "1":
                raise StateError("状态库 schema 不兼容")
            feature = db.execute("SELECT value FROM meta WHERE key='feature_parity_schema'").fetchone()
            if not feature or feature[0] != "2":
                raise StateError("功能对齐状态库未迁移；拒绝启动")
        self.repository.interrupted_jobs()
        self._csrf: dict[str, str] = {}
        self._preauth: dict[str, tuple[str, Any, bytes, str, float]] = {}
        self._sessions: dict[str, tuple[Any, float, float]] = {}
        self._last_challenge: dict[str, float] = {}
        self._state_lock = threading.RLock()
        self._writer_lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fc27-players-writer")
        self._stops: dict[str, threading.Event] = {}

    @staticmethod
    def _json(start: Callable[..., Any], status: str, payload: Any,
              extra_headers: list[tuple[str, str]] | None = None) -> list[bytes]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        start(status, [("Content-Type", "application/json; charset=utf-8"),
                       ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
                       ("X-Content-Type-Options", "nosniff")] + (extra_headers or []))
        return [body]

    @staticmethod
    def _browser_sid(env: dict[str, Any]) -> str:
        match = re.search(r"(?:^|;\s*)FC27PLAYER_SID=([A-Za-z0-9_-]{32,64})(?:;|$)",
                          str(env.get("HTTP_COOKIE") or ""))
        return match.group(1) if match else ""

    @staticmethod
    def _bytes(start: Callable[..., Any], status: str, body: bytes, mime: str,
               extra_headers: list[tuple[str, str]] | None = None) -> list[bytes]:
        start(status, [("Content-Type", mime), ("Content-Length", str(len(body))),
                       ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")]
              + (extra_headers or []))
        return [body]

    def _session(self, owner: str) -> Any | None:
        with self._state_lock:
            entry = self._sessions.get(owner)
            if not entry:
                return None
            client, created, last = entry
            if time.time() - created > 28800 or time.time() - last > 1800:
                client.clear_auth()
                self._sessions.pop(owner, None)
                return None
            return client

    def _post_guard(self, env: dict[str, Any], session_key: str, role: str) -> None:
        if role != "admin":
            raise PermissionError("ROLE_REQUIRED")
        if not self.settings.public_origin:
            raise PermissionError("PUBLIC_ORIGIN_REQUIRED")
        origin = env.get("HTTP_ORIGIN") or ""
        if origin != self.settings.public_origin:
            raise PermissionError("ORIGIN_MISMATCH")
        with self._state_lock:
            if not secrets.compare_digest(env.get("HTTP_X_CSRF_TOKEN") or "", self._csrf.get(session_key) or "\x00"):
                raise PermissionError("CSRF_INVALID")
            if session_key in self._sessions:
                client, created, _ = self._sessions[session_key]
                self._sessions[session_key] = (client, created, time.time())

    @staticmethod
    def _body(env: dict[str, Any]) -> dict[str, Any]:
        length = int(env.get("CONTENT_LENGTH") or 0)
        if length < 0 or length > 524288:
            raise StateError("REQUEST_TOO_LARGE")
        raw = env["wsgi.input"].read(length)
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise StateError("INVALID_BODY")
        return value

    @staticmethod
    def _plan_preview(plan: dict[str, Any]) -> dict[str, Any]:
        result = {key: value for key, value in plan.items() if key not in {"artifact_path"}}
        if plan.get("kind") == "model_images":
            result["items"] = [{key: value for key, value in item.items() if key != "artifact_path"}
                               for item in plan.get("items") or []]
        return result

    def __call__(self, env: dict[str, Any], start: Callable[..., Any]) -> list[bytes]:
        path = env.get("PATH_INFO") or "/"
        method = env.get("REQUEST_METHOD") or "GET"
        if path == "/healthz":
            return self._json(start, "200 OK", {"status": "ok"})
        if env.get("REMOTE_ADDR") not in {"127.0.0.1", "::1"}:
            return self._json(start, "403 Forbidden", {"error": "TRUSTED_PROXY_REQUIRED"})
        owner = str(env.get("HTTP_X_FC27_USER") or "").strip()
        role = str(env.get("HTTP_X_FC27_ROLE") or "").strip()
        if not owner or role not in {"admin", "readonly"}:
            return self._json(start, "403 Forbidden", {"error": "GATE_REQUIRED"})
        sid = self._browser_sid(env)
        session_key = owner + ":" + sid if sid else ""
        if path != "/api/bootstrap" and path not in {"/", "/index.html", "/models.html", "/app.css", "/app.js", "/images.js"}:
            with self._state_lock:
                known_session = bool(session_key and session_key in self._csrf)
            if not known_session:
                return self._json(start, "403 Forbidden", {"error": "BROWSER_SESSION_REQUIRED"})
        try:
            if method == "GET" and path in {"/", "/index.html", "/models.html", "/app.css", "/app.js", "/images.js"}:
                filename = "index.html" if path == "/" else path.lstrip("/")
                mime = ("text/html; charset=utf-8" if filename.endswith(".html") else
                        "text/css; charset=utf-8" if filename.endswith(".css") else
                        "application/javascript; charset=utf-8")
                body = (Path(__file__).parent / "static" / filename).read_bytes()
                return self._bytes(start, "200 OK", body, mime)
            if method == "GET" and path == "/api/bootstrap":
                with self._state_lock:
                    cookie_headers: list[tuple[str, str]] = []
                    if not session_key or session_key not in self._csrf:
                        sid = secrets.token_urlsafe(32)
                        session_key = owner + ":" + sid
                        cookie_headers = [("Set-Cookie", "FC27PLAYER_SID=" + sid + "; Path=" +
                                           self.settings.root_path + "/; Secure; HttpOnly; SameSite=Strict")]
                    csrf = self._csrf.setdefault(session_key, secrets.token_urlsafe(32))
                return self._json(start, "200 OK", {
                    "owner": owner, "role": role, "csrf": csrf, "root_path": self.settings.root_path,
                    "shared_backend_session": self.settings.shared_backend_session,
                    "backend_authenticated": self._session(session_key) is not None,
                    "write_enabled": self.settings.write_enabled,
                    "new_card_write_enabled": self.settings.new_card_write_enabled,
                    "model_image_write_enabled": self.settings.model_image_write_enabled,
                    "existing_recommend_write_enabled": self.settings.existing_action_write_enabled("recommend_enable"),
                }, cookie_headers)
            if method == "GET" and path == "/api/status":
                return self._json(start, "200 OK", {
                    "latest_collection": self.repository.latest_collection(),
                    "last_successful_collection": self.repository.last_successful_collection(),
                    "latest_model_snapshot": self.repository.latest_model_snapshot(owner),
                    "jobs": self.repository.status_counts(),
                    "collector_enabled": self.settings.collector_enabled,
                    "write_enabled": self.settings.write_enabled,
                    "new_card_write_enabled": self.settings.new_card_write_enabled,
                    "model_image_write_enabled": self.settings.model_image_write_enabled,
                    "existing_recommend_write_enabled": self.settings.existing_action_write_enabled("recommend_enable"),
                    "source_transport": self.settings.source_transport,
                    "source_freshness": "unknown",
                    "backend_authenticated": self._session(session_key) is not None,
                })
            if method == "GET" and path == "/api/candidates":
                query = parse_qs(env.get("QUERY_STRING") or "")
                collection_id = (query.get("collection_id") or [None])[0]
                if not collection_id:
                    latest = self.repository.last_successful_collection()
                    collection_id = latest["id"] if latest else None
                rows = self.repository.candidates(collection_id)
                collection = self.repository.get_collection(collection_id) if collection_id else None
                model_map: dict[str, int] | None = None
                client = self._session(session_key)
                if client is not None:
                    adapter = AdminAdapter(client, state_root=self.settings.data_root / "admin_state" / "shared")
                    try:
                        model_map = build_existing_model_map(adapter.list_all_models())
                    except Exception:
                        model_map = None
                safe_rows = []
                for row in rows:
                    item = dict(row)
                    key = str(item["futbin_id"])
                    item["backend_status"] = ("backend_unchecked" if model_map is None
                                              else "existing" if key in model_map else "new")
                    if model_map is not None and key in model_map:
                        item["model_id"] = model_map[key]
                    safe_rows.append(item)
                return self._json(start, "200 OK", {"items": safe_rows, "total": len(safe_rows),
                                                     "collection": collection})
            if method == "GET" and path == "/api/models":
                client = self._session(session_key)
                if client is None:
                    raise StateError("AUTH_REQUIRED")
                query = parse_qs(env.get("QUERY_STRING") or "")
                snapshot_id = (query.get("snapshot_id") or [""])[0]
                if not snapshot_id:
                    latest = self.repository.latest_model_snapshot(owner)
                    snapshot_id = latest["snapshot_id"] if latest else ""
                if not snapshot_id:
                    raise StateError("MODEL_SNAPSHOT_REQUIRED")
                criteria = {key: query[key][0] for key in ("is_rec", "tag_id", "tag_name", "keyword", "status")
                            if key in query and query[key][0] != ""}
                return self._json(start, "200 OK", query_models(
                    self.repository, owner, snapshot_id, criteria,
                    page=int((query.get("page") or ["1"])[0]),
                    per_page=int((query.get("per_page") or ["20"])[0]),
                ))
            if method == "GET" and path == "/api/tags":
                client = self._session(session_key)
                if client is None:
                    raise StateError("AUTH_REQUIRED")
                rows = client.list_tags(gid=1327, cid=9627)
                return self._json(start, "200 OK", {"items": [
                    {"id": row.get("id"), "name": row.get("name")} for row in rows
                ]})
            if method == "GET" and path.startswith("/api/auth/challenge/") and path.endswith("/image"):
                challenge_id = path.split("/")[4]
                with self._state_lock:
                    entry = self._preauth.get(session_key)
                if not entry or entry[0] != challenge_id or time.time() > entry[4]:
                    raise StateError("CHALLENGE_EXPIRED")
                return self._bytes(start, "200 OK", entry[2], entry[3])
            if method == "GET" and path.startswith("/api/plans/"):
                return self._json(start, "200 OK", self._plan_preview(
                    self.repository.get_plan(path.rsplit("/", 1)[-1], owner)
                ))
            if method == "GET" and path.startswith("/api/jobs/"):
                return self._json(start, "200 OK",
                                  self.repository.get_execution(path.rsplit("/", 1)[-1], owner))
            if method == "GET" and path == "/api/jobs":
                return self._json(start, "200 OK", {"items": self.repository.list_executions(owner)})
            if method != "POST":
                return self._json(start, "404 Not Found", {"error": "NOT_FOUND"})
            self._post_guard(env, session_key, role)
            if path == "/api/collections":
                body = self._body(env)
                if set(body) - {"days_new"}:
                    raise StateError("查询参数不在白名单")
                days = body.get("days_new", self.settings.lookback_days)
                return self._json(start, "200 OK", collect_only(self.settings, self.repository,
                                                                  days_new=days))
            if path == "/api/models/refresh":
                client = self._session(session_key)
                if client is None:
                    raise StateError("AUTH_REQUIRED")
                return self._json(start, "200 OK", refresh_models(
                    self.settings, self.repository, client, owner))
            if path == "/api/models/intersect":
                if self._session(session_key) is None:
                    raise StateError("AUTH_REQUIRED")
                body = self._body(env)
                return self._json(start, "200 OK", intersect_database_properties(
                    self.settings, self.repository, owner, str(body.get("snapshot_id") or ""),
                    body.get("criteria") or {},
                ))
            if path == "/api/models/export":
                if self._session(session_key) is None:
                    raise StateError("AUTH_REQUIRED")
                body = self._body(env)
                content = export_selected_futbin_ids(
                    self.repository, owner, str(body.get("snapshot_id") or ""),
                    body.get("selected_model_ids") or [],
                )
                self.repository.audit(owner, "futbin_txt_export", str(body.get("snapshot_id") or ""),
                                      {"count": len(content.splitlines())})
                return self._bytes(start, "200 OK", content, "text/plain; charset=utf-8",
                                   [("Content-Disposition", 'attachment; filename="fc27_selected_futbin_ids.txt"')])
            if path == "/api/auth/shared":
                if not self.settings.shared_backend_session:
                    raise StateError("FS_SHARED_SESSION_DISABLED")
                client = shared_client(self.settings)
                with self._state_lock:
                    old = self._sessions.pop(session_key, None)
                    if old:
                        old[0].clear_auth()
                    self._sessions[session_key] = (client, time.time(), time.time())
                    self._csrf[session_key] = secrets.token_urlsafe(32)
                self.repository.audit(owner, "backend_login", "", {"status": "success", "method": "fs_shared"})
                return self._json(start, "200 OK", {"authenticated": True, "csrf": self._csrf[session_key]})
            if path in {"/api/auth/challenge", "/api/auth/login"} and self.settings.shared_backend_session:
                raise StateError("USE_FS_SHARED_SESSION")
            if path == "/api/auth/challenge":
                with self._state_lock:
                    if time.time() - self._last_challenge.get(session_key, 0) < 15:
                        raise StateError("CHALLENGE_RATE_LIMITED")
                    self._last_challenge[session_key] = time.time()
                client = admin_client(self.settings)
                client.get_login_config()
                challenge_id = secrets.token_urlsafe(16)
                image, mime = client.fetch_captcha_response(challenge_id)
                with self._state_lock:
                    self._preauth[session_key] = (challenge_id, client, image, mime, time.time() + 300)
                return self._json(start, "200 OK", {"challenge_id": challenge_id,
                                                     "image_url": "/api/auth/challenge/" + challenge_id + "/image"})
            if path == "/api/auth/login":
                body = self._body(env)
                with self._state_lock:
                    entry = self._preauth.pop(session_key, None)
                if not entry or time.time() > entry[4] or body.get("challenge_id") != entry[0]:
                    raise StateError("CHALLENGE_EXPIRED")
                client = entry[1]
                client.login(str(body.get("username") or ""), str(body.get("password") or ""),
                             str(body.get("captcha") or ""), entry[0], keep=False)
                try:
                    client.verify_identity()
                except Exception:
                    client.clear_auth()
                    raise
                with self._state_lock:
                    old = self._sessions.pop(session_key, None)
                    if old:
                        old[0].clear_auth()
                    self._sessions[session_key] = (client, time.time(), time.time())
                    self._csrf[session_key] = secrets.token_urlsafe(32)
                self.repository.audit(owner, "backend_login", "", {"status": "success"})
                return self._json(start, "200 OK", {"authenticated": True, "csrf": self._csrf[session_key]})
            if path == "/api/auth/logout":
                with self._state_lock:
                    old = self._sessions.pop(session_key, None)
                    if old:
                        old[0].clear_auth()
                self.repository.audit(owner, "backend_logout", "", {})
                return self._json(start, "200 OK", {"authenticated": False})
            if path == "/api/image-batches" or path.startswith("/api/image-batches/"):
                client = self._session(session_key)
                if client is None:
                    raise StateError("AUTH_REQUIRED")
                if path == "/api/image-batches":
                    body = self._body(env)
                    return self._json(start, "200 OK", create_batch(
                        self.settings, self.repository, client, owner,
                        str(body.get("snapshot_id") or ""), body.get("files"), body.get("overwrite", False)))
                match = re.fullmatch(r"/api/image-batches/([0-9a-f]{32})/files/([1-9][0-9]*\.[pP][nN][gG])", path)
                if not match:
                    raise StateError("IMAGE_BATCH_INVALID")
                length = int(env.get("CONTENT_LENGTH") or 0)
                if not 1 <= length <= MAX_PNG_BYTES or env.get("CONTENT_TYPE", "").split(";", 1)[0] != "image/png":
                    raise StateError("INVALID_PNG")
                content = env["wsgi.input"].read(length)
                with self._state_lock:
                    staged = stage_png(self.settings, owner, match[1], match[2], content)
                return self._json(start, "200 OK", staged)
            if path == "/api/plans/model-images":
                client = self._session(session_key)
                if client is None:
                    raise StateError("AUTH_REQUIRED")
                body = self._body(env)
                return self._json(start, "200 OK", self._plan_preview(prepare_image_plan(
                    self.settings, self.repository, client, owner, str(body.get("batch_id") or ""))))
            if path == "/api/plans/new-cards":
                client = self._session(session_key)
                if client is None:
                    raise StateError("AUTH_REQUIRED")
                body = self._body(env)
                plan = prepare_plan(
                    self.settings, self.repository, client, owner,
                    str(body.get("collection_id") or ""),
                    body.get("upload_futbin_ids") or [], body.get("tag_futbin_ids") or [],
                    body.get("recommend_futbin_ids") or [], body.get("selected_tag_ids") or [],
                    rating_threshold=body.get("rating_threshold", 85),
                )
                return self._json(start, "200 OK", self._plan_preview(plan))
            if path == "/api/plans/existing-actions":
                client = self._session(session_key)
                if client is None:
                    raise StateError("AUTH_REQUIRED")
                body = self._body(env)
                plan = prepare_existing_action(
                    self.settings, self.repository, client, owner,
                    str(body.get("snapshot_id") or ""), body.get("selected_model_ids") or [],
                    str(body.get("action") or ""), body.get("tag_ids") or [],
                )
                return self._json(start, "200 OK", self._plan_preview(plan))
            if path == "/api/plans/unlist-preview":
                client = self._session(session_key)
                if client is None:
                    raise StateError("AUTH_REQUIRED")
                body = self._body(env)
                plan = prepare_unlist_preview(
                    self.settings, self.repository, client, owner,
                    str(body.get("snapshot_id") or ""), body.get("selected_model_ids") or [],
                )
                return self._json(start, "200 OK", self._plan_preview(plan))
            if path.startswith("/api/plans/") and path.endswith("/confirm"):
                if (self.settings.data_root / "STOP_WRITES").exists():
                    raise StateError("WRITE_DISABLED")
                client = self._session(session_key)
                if client is None:
                    raise StateError("AUTH_REQUIRED")
                body = self._body(env)
                if body.get("confirmed") is not True:
                    raise StateError("EXPLICIT_CONFIRMATION_REQUIRED")
                plan_id = path.split("/")[3]
                plan = self.repository.get_plan(plan_id, owner)
                can_write = self.settings.write_enabled
                if plan.get("kind") == "existing_action":
                    can_write = self.settings.existing_action_write_enabled(plan.get("action"))
                elif plan.get("kind") == "new_cards":
                    can_write = self.settings.new_card_write_enabled
                    if can_write:
                        verify_source_policy(self.settings, plan)
                        verify_manual_new_card_scope(self.settings, plan)
                elif plan.get("kind") == "model_images":
                    can_write = self.settings.model_image_write_enabled
                    if can_write and not plan.get("execution_id"):
                        verify_image_plan(self.settings, client, plan)
                execution_id, created = self.repository.confirm(
                    plan_id, owner, str(body.get("plan_digest") or ""),
                    write_enabled=can_write,
                )
                if created:
                    plan = self.repository.get_plan(plan_id, owner)
                    stop = threading.Event()
                    with self._state_lock:
                        self._stops[execution_id] = stop
                    self._pool.submit(self._run_job, client, execution_id, plan, stop)
                return self._json(start, "202 Accepted", {"execution_id": execution_id,
                                                           "status": "queued" if created else "existing"})
            if path.startswith("/api/jobs/") and path.endswith("/stop"):
                execution_id = path.split("/")[3]
                self.repository.get_execution(execution_id, owner)
                with self._state_lock:
                    stop = self._stops.get(execution_id)
                    if stop:
                        stop.set()
                self.repository.audit(owner, "stop_requested", execution_id, {})
                return self._json(start, "200 OK", {"stop_requested": True})
            return self._json(start, "404 Not Found", {"error": "NOT_FOUND"})
        except PermissionError as exc:
            return self._json(start, "403 Forbidden", {"error": str(exc)})
        except AdminAuthError:
            return self._json(start, "409 Conflict", {"error": "BACKEND_AUTH_UNAVAILABLE"})
        except (StateError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            code = str(exc)
            # 不把任意异常文本、上游响应或用户输入返回给浏览器。
            known = {"WRITE_DISABLED", "PLAN_BLOCKED", "PLAN_STALE", "AUTH_REQUIRED",
                     "FS_SHARED_SESSION_DISABLED", "USE_FS_SHARED_SESSION",
                     "CHALLENGE_EXPIRED", "CHALLENGE_RATE_LIMITED", "COLLECTOR_DISABLED",
                     "UNRESOLVED_IMPORT", "LEGACY_UNRESOLVED", "EXPLICIT_CONFIRMATION_REQUIRED",
                     "MODEL_SNAPSHOT_REQUIRED", "INVALID_DAYS_NEW", "SOURCE_PAGE_INCOMPLETE",
                     "SOURCE_PAGE_DRIFT", "EMPTY_TAG_SET", "SOURCE_TRANSPORT_UNVERIFIED",
                     "SOURCE_CONFIG_CHANGED", "NEW_CARD_SCOPE_REQUIRED"}
            known |= {"IMAGE_BATCH_INVALID", "IMAGE_BATCH_EXPIRED", "IMAGE_BATCH_TOO_LARGE",
                      "IMAGE_DUPLICATE_FILENAME", "IMAGE_FILE_CHANGED", "IMAGE_MODEL_CHANGED",
                      "IMAGE_MODEL_IDENTITY_CHANGED", "IMAGE_FIELD_UNKNOWN", "IMAGE_NO_MATCHES", "INVALID_PNG"}
            return self._json(start, "409 Conflict", {"error": code if code in known else type(exc).__name__})
        except Exception as exc:
            return self._json(start, "502 Bad Gateway", {"error": "OPERATION_FAILED",
                                                          "error_type": type(exc).__name__})

    def _run_job(self, client: Any, execution_id: str, plan: dict[str, Any], stop: threading.Event) -> None:
        with self._writer_lock:
            try:
                if stop.is_set():
                    self.repository.set_execution(execution_id, "stopped", "not_started", release_scope=True)
                    return
                lease_deadline = time.time() + 1800
                should_stop = lambda: stop.is_set() or time.time() > lease_deadline or (
                    self.settings.data_root / "STOP_WRITES").exists()
                if plan.get("kind") == "existing_action":
                    execute_existing_action(self.settings, self.repository, client,
                                            execution_id, plan, should_stop)
                elif plan.get("kind") == "new_cards":
                    execute_confirmed_plan(self.settings, self.repository, client,
                                           execution_id, plan, should_stop)
                elif plan.get("kind") == "model_images":
                    execute_image_plan(self.settings, self.repository, client,
                                       execution_id, plan, should_stop)
                else:
                    raise StateError("PLAN_BLOCKED")
            except Exception:
                # 写前核验也可能失败；所有未知结果保留范围锁且不自动重试。
                try:
                    current = self.repository.get_execution(execution_id, str(plan["owner"]))
                    if current["status"] in {"queued", "running"}:
                        self.repository.set_execution(execution_id, "needs_reconcile", "unknown",
                                                      {"error_type": "execution_failed"})
                except Exception:
                    pass
            finally:
                with self._state_lock:
                    self._stops.pop(execution_id, None)


def serve() -> None:
    import os
    settings = Settings.from_env()
    host = os.environ.get("LISTEN_HOST", "127.0.0.1")
    port = int(os.environ.get("LISTEN_PORT", "8901"))
    with collection_lock(settings.data_root / "locks" / "api-instance.lock") as acquired:
        if not acquired:
            raise StateError("第二个 Players API 实例被拒绝")
        app = App(settings)
        with make_server(host, port, app, server_class=ThreadingServer, handler_class=QuietHandler) as server:
            server.serve_forever()


if __name__ == "__main__":
    serve()
