"""Server-resident P2PAH authentication health service.

Secrets are read from a private bind mount. Tokens stay in process memory and
neither credentials nor response bodies are written to logs.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import ddddocr


CONFIG_PATH = Path(os.environ.get("FC27_PRIVATE_CONFIG", "/run/secrets/fc27.env"))
DEFAULT_API = "https://admin-api.p2pah.cn"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://admin.p2pah.cn/",
    "Origin": "https://admin.p2pah.cn",
    "Accept": "application/json, text/plain, */*",
    "think-lang": "zh-cn",
    "server": "1",
}


def read_private_config(path: Path = CONFIG_PATH) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or key not in {"P2PAH_USERNAME", "P2PAH_PASSWORD", "P2PAH_API_BASE"}:
            raise ValueError("invalid_private_config")
        result[key] = json.loads(value)
    if not result.get("P2PAH_USERNAME") or not result.get("P2PAH_PASSWORD"):
        raise ValueError("missing_credentials")
    api = result.get("P2PAH_API_BASE", DEFAULT_API).rstrip("/")
    if api != DEFAULT_API:
        raise ValueError("unexpected_api_base")
    result["P2PAH_API_BASE"] = api
    return result


class SessionManager:
    def __init__(self, config: dict[str, str]):
        self.config = config
        self.ocr = ddddocr.DdddOcr(show_ad=False)
        self.lock = threading.RLock()
        self.token = None
        self.refresh_token = None
        self.last_ok = None
        self.last_refresh = 0.0
        self.status = "starting"

    def request(self, path: str, *, data: dict | None = None, token: str | None = None, timeout: float = 15):
        headers = dict(HEADERS)
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode("utf-8")
        if token:
            headers["batoken"] = token
        req = urllib.request.Request(self.config["P2PAH_API_BASE"] + path,
                                     data=body, headers=headers,
                                     method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def identity_ok(self, token: str | None) -> bool:
        if not token:
            return False
        status, raw = self.request("/admin/index/index", token=token)
        try:
            return status == 200 and json.loads(raw).get("code") == 1
        except (ValueError, UnicodeDecodeError):
            return False

    def login(self) -> bool:
        self.status = "logging_in"
        for _ in range(3):
            captcha_id = str(uuid.uuid4())
            status, png = self.request("/api/common/captcha?" + urllib.parse.urlencode(
                {"server": "1", "id": captcha_id}))
            if status != 200 or not png.startswith(b"\x89PNG\r\n\x1a\n"):
                self.status = "captcha_unavailable"
                return False
            code = (self.ocr.classification(png) or "").strip()
            if not re.fullmatch(r"\d{4,6}", code):
                continue
            status, raw = self.request("/admin/index/login", data={
                "username": self.config["P2PAH_USERNAME"],
                "password": self.config["P2PAH_PASSWORD"],
                "captcha": code, "keep": True, "captcha_id": captcha_id,
            })
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                self.status = "invalid_login_response"
                return False
            if status != 200 or payload.get("code") != 1:
                msg = str(payload.get("msg") or "").lower()
                if "password" in msg or "密码" in msg:
                    self.status = "credentials_rejected"
                    return False
                continue
            user = (payload.get("data") or {}).get("userInfo") or {}
            token, refresh = user.get("token"), user.get("refreshToken")
            if not token or not refresh or not self.identity_ok(token):
                self.status = "identity_unverified"
                return False
            self.token, self.refresh_token = token, refresh
            self.last_ok = datetime.now(timezone.utc).isoformat()
            self.last_refresh = time.monotonic()
            self.status = "ready"
            return True
        self.status = "captcha_or_policy_rejected"
        return False

    def refresh(self) -> bool:
        if not self.token or not self.refresh_token:
            return False
        status, raw = self.request("/api/common/refreshToken",
                                   data={"refresh_token": self.refresh_token}, token=self.token)
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return False
        user = payload.get("data") or {}
        renewed = user.get("token")
        if status != 200 or payload.get("code") != 1 or not renewed:
            return False
        if not self.identity_ok(renewed):
            return False
        self.token = renewed
        self.refresh_token = user.get("refreshToken") or self.refresh_token
        self.last_ok = datetime.now(timezone.utc).isoformat()
        self.last_refresh = time.monotonic()
        self.status = "ready"
        return True

    def ensure(self) -> bool:
        with self.lock:
            try:
                if self.token and time.monotonic() - self.last_refresh >= 1200:
                    if self.refresh():
                        return True
                    self.token = self.refresh_token = None
                    return self.login()
                if self.token and self.identity_ok(self.token):
                    self.last_ok = datetime.now(timezone.utc).isoformat()
                    self.status = "ready"
                    return True
                if self.refresh():
                    return True
                self.token = self.refresh_token = None
                return self.login()
            except (OSError, ValueError, TypeError):
                self.token = self.refresh_token = None
                self.status = "auth_unavailable"
                return False

    def health(self) -> dict:
        with self.lock:
            return {"status": self.status, "ready": self.status == "ready",
                    "last_ok": self.last_ok}

    def new_customers(self, target: str) -> dict:
        """Return only the verified FC27 OrderEs new_people aggregate."""
        parsed = date.fromisoformat(target)
        if parsed.isoformat() != target:
            raise ValueError("invalid_date")
        payload = {
            "order_status": "", "pay_status": 1, "game": 1327, "site": 266,
            "country_code": "", "client": "",
            "date": [target + " 00:00:00", target + " 23:59:59"],
            "pay_type": "", "time_unit": 3, "cid": "", "discount_code": "",
        }
        with self.lock:
            if not self.ensure():
                raise RuntimeError("admin_es_auth_unavailable")
            status, raw = self.request(
                "/admin/order.Order/orderStaticsDetailByEs",
                data=payload, token=self.token,
            )
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("admin_es_invalid_json") from exc
        if status != 200 or result.get("code") != 1:
            raise RuntimeError("admin_es_query_failed")
        data = result.get("data")
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data["data"]
        value = data.get("new_people") if isinstance(data, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise RuntimeError("admin_es_new_people_missing")
        if isinstance(value, str):
            if not value.isdecimal():
                raise RuntimeError("admin_es_new_people_invalid")
            value = int(value)
        if value < 0:
            raise RuntimeError("admin_es_new_people_invalid")
        return {"date": target, "new_customers": value,
                "source": {"system": "admin_order_es", "game_id": 1327,
                           "game_name": "FC 27", "site": 266,
                           "metric": "new_people", "captured_at": datetime.now(timezone.utc).isoformat(),
                           "status": "valid"}}

    def fc_capability(self, query):
        if isinstance(query,dict) and query.get('kind')=='es_structure':
            from es_order_structure import checked_query,session_bundle
            if set(query)-{'kind','profile','start','end','poll_only'} or not isinstance(query.get('poll_only',False),bool):raise ValueError('es_query_fields')
            args={k:v for k,v in query.items() if k not in ('kind','poll_only')}
            checked_query(args)
            return session_bundle(self,args,HEADERS,poll_only=query.get('poll_only',False))
        from admin_order_capabilities_20261014.admin_session_entry import collect_with_manager
        # Use this already-running manager; this route never login/ensure/imports auth.
        return collect_with_manager(self, query, {'enabled':True,'game_id':1327,'main_site_id':266})

    def business_summary(self, game, start, end):
        from admin_summary import collect
        def existing_read(path, **kwargs):
            with self.lock:
                if self.status != "ready" or not self.token:
                    raise OSError("existing_session_unavailable")
                return self.request(path, token=self.token, **kwargs)
        return collect(existing_read, game, start, end)

    def marketing_summary(self, start: str, end: str) -> dict:
        from admin_links import collect
        def existing_read(path, **kwargs):
            with self.lock:
                if self.status != "ready" or not self.token:
                    raise OSError("existing_session_unavailable")
                return self.request(path, token=self.token, **kwargs)
        return collect(existing_read, start, end)

    def daily_summary(self, target: str, game_id: int, product_type: str) -> dict:
        """Return only aggregate Es metrics for a fixed game/site/category contract."""
        parsed = date.fromisoformat(target)
        if parsed.isoformat() != target or game_id not in (1327, 833) or product_type not in ("", "1", "0"):
            raise ValueError("invalid_es_filter")
        payload = {
            "order_status": "", "pay_status": 1, "game": game_id, "site": 266,
            "country_code": "", "client": "", "pay_type": "",
            "date": [target + " 00:00:00", target + " 23:59:59"],
            "time_unit": 3, "cid": "" if product_type == "" else int(product_type),
            "discount_code": "", "isNew": "",
        }
        with self.lock:
            if not self.ensure():
                raise RuntimeError("admin_es_auth_unavailable")
            status, raw = self.request(
                "/admin/order.Order/orderStaticsDetailByEs",
                data=payload, token=self.token,
            )
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("admin_es_invalid_json") from exc
        if status != 200 or result.get("code") != 1:
            raise RuntimeError("admin_es_query_failed")
        data = result.get("data")
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data["data"]
        if not isinstance(data, dict):
            raise RuntimeError("admin_es_data_missing")
        orders_raw = data.get("total")
        amount_raw = data.get("amount")
        new_raw = data.get("new_people")
        if isinstance(orders_raw, bool) or not str(orders_raw).replace(",", "").isdecimal():
            raise RuntimeError("admin_es_orders_invalid")
        orders = int(str(orders_raw).replace(",", ""))
        from decimal import Decimal, InvalidOperation
        try:
            amount = Decimal(str(amount_raw).replace(",", ""))
        except (InvalidOperation, TypeError) as exc:
            raise RuntimeError("admin_es_amount_invalid") from exc
        if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
            raise RuntimeError("admin_es_amount_invalid")
        if isinstance(new_raw, bool) or not str(new_raw).isdecimal():
            raise RuntimeError("admin_es_new_people_invalid")
        new_people = int(new_raw)
        if new_people > orders:
            raise RuntimeError("admin_es_new_people_exceeds_orders")
        return {
            "status": "valid", "date": target, "game_id": game_id,
            "product_type": product_type, "site": 266, "pay_status": 1,
            "orders": orders, "amount_usd": str(amount),
            "new_people": new_people,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }


def serve(manager: SessionManager):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != '/business/fc-capability':self.send_error(404);return
            try:
                if self.headers.get('Transfer-Encoding'):raise ValueError('unsupported_encoding')
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=4096:raise ValueError('body_size')
                value=json.loads(self.rfile.read(length))
                result=manager.fc_capability(value)
                code=403 if result.get('status')=='denied' else 503 if result.get('status')=='not_available' else 200
            except (ValueError,TypeError):result,code={'status':'invalid'},400
            except PermissionError:result,code={'status':'denied'},403
            except (OSError,RuntimeError):result,code={'status':'not_available'},503
            body=json.dumps(result,ensure_ascii=False,allow_nan=False).encode('utf-8')
            self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/business/summary":
                params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
                try:
                    if set(params) != {"game", "start", "end"} or any(len(v) != 1 for v in params.values()):
                        raise ValueError("invalid_parameters")
                    result = manager.business_summary(params["game"][0], params["start"][0], params["end"][0])
                    code = 200
                except PermissionError:
                    result, code = {"status": "denied"}, 403
                except (ValueError, TypeError):
                    result, code = {"status": "invalid"}, 400
                except (OSError, RuntimeError):
                    result, code = {"status": "unavailable"}, 503
                body = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/marketing/summary":
                params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
                try:
                    if set(params) != {"start", "end"} or any(len(v) != 1 for v in params.values()):
                        raise ValueError("invalid_parameters")
                    from datetime import date
                    start, end = params["start"][0], params["end"][0]
                    if date.fromisoformat(start).isoformat() != start or date.fromisoformat(end).isoformat() != end or start > end or (date.fromisoformat(end) - date.fromisoformat(start)).days > 365:
                        raise ValueError("invalid_date_range")
                    result = manager.marketing_summary(start, end)
                    code = 200
                except (ValueError, TypeError):
                    result, code = {"status": "invalid"}, 400
                body = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/es/daily-summary":
                params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
                try:
                    result = manager.daily_summary(
                        params.get("date", [""])[0],
                        int(params.get("game", [""])[0]),
                        params.get("product_type", [""])[0],
                    )
                    code = 200
                except (ValueError, IndexError):
                    result, code = {"error": "invalid_filter"}, 400
                except (OSError, RuntimeError, TypeError):
                    result, code = {"error": "admin_es_unavailable"}, 503
                body = json.dumps(result).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/es/new-customers":
                params = urllib.parse.parse_qs(parsed.query)
                target = params.get("date", [""])[0]
                try:
                    result = manager.new_customers(target)
                    code = 200
                except ValueError:
                    result, code = {"error": "invalid_date"}, 400
                except (OSError, RuntimeError, TypeError):
                    result, code = {"error": "admin_es_unavailable"}, 503
                body = json.dumps(result).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path != "/health":
                self.send_error(404)
                return
            result = manager.health()
            body = json.dumps(result).encode("utf-8")
            self.send_response(200 if result["ready"] else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", 8767), Handler)
    server.serve_forever()


def main():
    manager = SessionManager(read_private_config())
    def upkeep():
        while True:
            ok = manager.ensure()
            print(json.dumps({"event": "auth_check", "ready": ok,
                              "status": manager.status}), flush=True)
            time.sleep(300 if ok else 60)
    threading.Thread(target=upkeep, daemon=True).start()
    serve(manager)


if __name__ == "__main__":
    main()
