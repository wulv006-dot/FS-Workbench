"""Email channel configuration and explicitly requested single-recipient tests.

No customer export, campaign scheduler or automatic resend is enabled here.
Secrets never leave this server; provider responses are reduced to known fields.
"""
import hashlib
import hmac
from contextlib import contextmanager
import http.client
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

REGIONS = {"sg": "https://api.aurorasendcloud.com", "us": "https://api-us.aurorasendcloud.com", "hk": "https://api-hk.aurorasendcloud.com"}
PROVIDERS = ("aurora", "mamba")
LOCK = threading.RLock()

class Invalid(ValueError):
    pass

def mailbox(value):
    value = str(value or "").strip()
    if len(value) > 254 or not re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", value):
        raise Invalid("请填写单个有效邮箱")
    local, domain = value.rsplit("@", 1)
    return local + "@" + domain.lower()

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def transport(url, data, headers):
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=25) as response:
            return response.status, json.loads(response.read(1048576))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read(65536))
        except (ValueError, UnicodeError):
            return exc.code, {}

def authorize(headers, method, path):
    """Re-use the live portal role, never trust caller-supplied role headers."""
    conn = http.client.HTTPConnection("127.0.0.1", 8895, timeout=4)
    try:
        conn.request("GET", "/verify?group=dashboard", headers={
            "Cookie": headers.get("Cookie", ""), "X-Original-Method": method,
            "X-Original-URI": "/dashboard/modules/marketing" + path})
        response = conn.getresponse()
        role = response.getheader("X-Auth-Role")
        user = response.getheader("X-Auth-User")
        response.read()
        if response.status != 200 or role != "admin" or not user:
            return None
        if method == "POST":
            # A custom same-origin header is required. Email endpoints never allow CORS.
            if headers.get("X-FS-Email-Request") != "1":
                return None
            origin = headers.get("Origin")
            if origin and urllib.parse.urlparse(origin).netloc != headers.get("Host"):
                return None
            if headers.get("Sec-Fetch-Site") == "cross-site":
                return None
        return user
    except (OSError, http.client.HTTPException):
        return None
    finally:
        conn.close()

class Channels:
    def __init__(self, directory, sender=transport):
        self.directory = directory
        self.sender = sender
        os.makedirs(directory, mode=0o700, exist_ok=True)
        self.file = os.path.join(directory, "channels.json")
        self.db = os.path.join(directory, "tests.sqlite3")
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS sends (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, provider TEXT NOT NULL, recipient TEXT NOT NULL, state TEXT NOT NULL, provider_id TEXT, created REAL NOT NULL, actor TEXT NOT NULL, mode TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS diagnostics (id TEXT PRIMARY KEY, http_status INTEGER, message TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS events (event_key TEXT PRIMARY KEY, batch_id TEXT NOT NULL, recipient TEXT NOT NULL, status TEXT NOT NULL, occurred INTEGER NOT NULL)")
        os.chmod(self.db, 0o600)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def read(self):
        if not os.path.exists(self.file):
            return {}
        with open(self.file, encoding="utf-8") as stream:
            return json.load(stream)

    def public(self):
        data = self.read()
        result = {}
        for provider in PROVIDERS:
            config = data.get(provider, {})
            fields = ("region", "api_user", "from_email", "from_name", "reply_to", "test_email")
            safe = {key: config.get(key, "") for key in fields}
            safe["secret_configured"] = bool(config.get("secret"))
            safe["configured"] = bool(config.get("secret") and config.get("from_email") and config.get("reply_to") and (provider != "aurora" or config.get("api_user")))
            safe["status"] = "已保存，待平台联调" if safe["configured"] else "未配置完整"
            result[provider] = safe
        return {"ok": True, "channels": result, "version": "email-config-20261103-v3", "campaigns_enabled": False, "webhooks_enabled": os.path.isfile(os.path.join(self.directory, "mamba_callback_token"))}

    def save(self, body):
        provider = body.get("provider")
        if provider not in PROVIDERS:
            raise Invalid("未知邮件平台")
        with LOCK:
            data = self.read()
            current = dict(data.get(provider, {}))
            for key in ("api_user", "from_name"):
                value = body.get(key, "")
                if not isinstance(value, str) or len(value) > 100 or any(ord(c) < 32 for c in value):
                    raise Invalid("账户或名称格式不正确")
                current[key] = value.strip()
            for key in ("from_email", "reply_to", "test_email"):
                current[key] = mailbox(body[key]) if body.get(key) else ""
            region = body.get("region", "sg")
            if region not in REGIONS:
                raise Invalid("请选择有效账户地区")
            current["region"] = region
            secret = body.get("secret", "")
            if not isinstance(secret, str) or len(secret) > 4096 or any(ord(c) < 32 for c in secret):
                raise Invalid("密钥格式不正确")
            if secret:
                current["secret"] = secret.strip()
            if body.get("clear_secret") is True:
                current.pop("secret", None)
            data[provider] = current
            temp = self.file + "." + uuid.uuid4().hex
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.file)
        return self.public()

    def test(self, body, actor):
        provider = body.get("provider")
        mode = body.get("mode", "validate")
        if provider not in PROVIDERS or mode not in ("validate", "send"):
            raise Invalid("平台或测试方式不正确")
        if provider == "mamba" and mode == "validate":
            raise Invalid("Mamba 未核实免投递验证接口，请保存配置后使用指定邮箱测试")
        if mode == "send" and body.get("confirm") is not True:
            raise Invalid("需要明确确认发送一封测试邮件")
        request_id = body.get("request_id", "")
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{16,64}", request_id):
            raise Invalid("测试请求标识不正确")
        with LOCK:
            config = self.read().get(provider, {})
            if not self.public()["channels"][provider]["configured"]:
                raise Invalid("请先保存完整账户和发件人配置")
            recipient = mailbox(config.get("test_email"))
            digest = hashlib.sha256(json.dumps([provider, mode, config], sort_keys=True).encode()).hexdigest()
            with self.connect() as db:
                existing = db.execute("SELECT fingerprint,state,provider_id FROM sends WHERE id=?", (request_id,)).fetchone()
                if existing:
                    if existing[0] != digest:
                        raise Invalid("同一请求标识不能用于不同配置")
                    return {"ok": True, "request_id": request_id, "state": existing[1], "provider_id": existing[2], "replayed": True}
                unresolved = db.execute("SELECT 1 FROM sends WHERE provider=? AND recipient=? AND state IN ('sending','unknown') LIMIT 1", (provider, recipient)).fetchone()
                if unresolved:
                    raise Invalid("该邮箱存在结果待核实的测试，请先到平台核实，禁止盲目重发")
                db.execute("INSERT INTO sends VALUES (?,?,?,?,?,?,?,?,?)", (request_id,digest,provider,recipient,"sending",None,time.time(),actor,mode))
        subject = "FS 邮件通道连接测试"
        content = "<p>这是一封由 FS 营销系统管理员发起的邮件通道连接测试。</p>"
        if provider == "aurora":
            payload = {"apiUser":config["api_user"], "apiKey":config["secret"], "from":config["from_email"], "fromName":config["from_name"], "replyTo":config["reply_to"], "to":recipient, "subject":subject, "html":content, "sendRequestId":request_id, "respEmailId":"true"}
            if mode == "validate":
                payload["sandboxMode"] = "validate"
            url = REGIONS[config["region"]] + "/api/mail/send"
            encoded = urllib.parse.urlencode(payload).encode()
            headers = {"Content-Type":"application/x-www-form-urlencoded"}
        else:
            payload = {"request_id":request_id, "campaign_id":request_id, "from":config["from_email"], "from_name":config["from_name"], "reply_to":config["reply_to"], "emails":recipient, "total":1, "subject":subject, "content":content}
            url = "https://sending.mambasms.com/open/api/international/email/batch/send"
            encoded = json.dumps(payload).encode()
            headers = {"Content-Type":"application/json", "X-Mamba-Access-Token":config["secret"]}
        state, provider_id, diagnostic, status = "unknown", None, "", None
        try:
            status, result = self.sender(url, encoded, headers)
            # Keep only a bounded message; never persist an entire vendor response.
            if isinstance(result, dict):
                diagnostic = str(result.get("message") or "").replace(config["secret"], "[REDACTED]")
                diagnostic = re.sub(r"[\x00-\x1f\x7f]", " ", diagnostic)[:256]
            if isinstance(result, dict) and status == 200:
                if provider == "aurora":
                    ids = (result.get("info") or {}).get("emailIdList")
                    if result.get("result") is True and result.get("statusCode") == 200:
                        if mode == "validate":
                            state = "validated"
                        elif isinstance(ids, list) and len(ids) == 1:
                            state, provider_id = "accepted", str(ids[0])[:256]
                    elif result.get("result") is False and result.get("statusCode") not in (40000, None):
                        state = "rejected"
                else:
                    batch = result.get("batch_id") or result.get("batchId")
                    if batch:
                        provider_id = str(batch)[:256]
                    if result.get("status") == "all_success" and result.get("total_accepted_recipients") == 1 and batch:
                        state, provider_id = "accepted", str(batch)[:256]
                    elif result.get("status") == "fail" and result.get("total_accepted_recipients") == 0:
                        state = "rejected"
                    elif result.get("status") == "fail" and result.get("message") == "CallBackUrl is null, please concat system manager":
                        state = "rejected"
            elif status in (400, 401, 403, 422, 429):
                state = "rejected"
        except Exception:
            # No exception text or provider raw body: these can contain credentials.
            state = "unknown"
        with self.connect() as db:
            db.execute("UPDATE sends SET state=?, provider_id=? WHERE id=?", (state,provider_id,request_id))
            db.execute("INSERT OR REPLACE INTO diagnostics VALUES (?,?,?)", (request_id,status,diagnostic))
        return {"ok":True, "request_id":request_id, "state":state, "provider_id":provider_id}

    def records(self):
        with self.connect() as db:
            rows = db.execute("SELECT id,provider,recipient,state,provider_id,created,actor,mode FROM sends ORDER BY created DESC LIMIT 50").fetchall()
            result = []
            for row in rows:
                record = dict(zip(("id","provider","recipient","state","provider_id","created","actor","mode"),row))
                detail = db.execute("SELECT http_status,message FROM diagnostics WHERE id=?", (row[0],)).fetchone()
                event = db.execute("SELECT status FROM events WHERE batch_id=? AND recipient=? ORDER BY occurred DESC LIMIT 1", (row[4],row[2])).fetchone() if row[1] == 'mamba' else None
                record.update(http_status=detail[0] if detail else None, message=detail[1] if detail else '', delivery_event=event[0] if event else '')
                result.append(record)
        return {"ok":True,"records":result}

    def callback(self, token, body):
        token_file = os.path.join(self.directory, 'mamba_callback_token')
        if not os.path.isfile(token_file):
            raise PermissionError('callback disabled')
        with open(token_file, encoding='ascii') as stream:
            expected = stream.read().strip()
        if len(expected) != 64 or not hmac.compare_digest(expected, token):
            raise PermissionError('invalid callback token')
        results = body.get('results') if isinstance(body, dict) else None
        if not isinstance(results, list) or not 1 <= len(results) <= 100:
            raise Invalid('invalid callback results')
        allowed = {'delivery','open','click','delay','bounce','spam_complaint','list_unsubscribe','link_unsubscribe'}
        with self.connect() as db:
            for event in results:
                if not isinstance(event, dict):
                    raise Invalid('invalid callback event')
                batch, recipient, status = event.get('batch_id'), mailbox(event.get('email')), event.get('deliver_status')
                if not isinstance(batch, str) or not 1 <= len(batch) <= 256 or status not in allowed:
                    raise Invalid('invalid callback fields')
                stamp = str(event.get('timestamp', ''))
                if not stamp.isdigit() or not 1 <= len(stamp) <= 10:
                    raise Invalid('invalid callback timestamp')
                # Unknown batches are retried by Mamba; no unaffiliated customer data stored.
                if not db.execute("SELECT 1 FROM sends WHERE provider='mamba' AND provider_id=? AND recipient=?", (batch,recipient)).fetchone():
                    raise LookupError('batch not recorded yet')
                key = hashlib.sha256(json.dumps([batch,recipient,status,stamp]).encode()).hexdigest()
                db.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)', (key,batch,recipient,status,int(stamp)))
        return {'success': True}

def handle(handler):
    path = urllib.parse.urlparse(handler.path).path
    if not path.startswith("/api/email/"):
        return False
    def reply(value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode()
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.end_headers()
        handler.wfile.write(data)
    if path.startswith('/api/email/callback/mamba/'):
        try:
            if handler.command != 'POST':
                reply({'success':False},405)
                return True
            size = int(handler.headers.get('Content-Length','0'))
            if not 0 < size <= 65536 or not handler.headers.get('Content-Type','').startswith('application/json'):
                raise Invalid('invalid callback body')
            token = path.removeprefix('/api/email/callback/mamba/')
            if not re.fullmatch('[a-f0-9]{64}',token):
                raise PermissionError('invalid callback token')
            service = Channels(os.path.join(os.path.dirname(__file__), '_email_private'))
            reply(service.callback(token,json.loads(handler.rfile.read(size))))
        except PermissionError:
            reply({'success':False},403)
        except LookupError:
            reply({'success':False},503)
        except (ValueError,KeyError,TypeError):
            reply({'success':False},400)
        return True
    actor = authorize(handler.headers, handler.command, path)
    if not actor:
        reply({"ok":False,"error":"请使用具有配置权限的后台管理员账号登录"},403)
        return True
    try:
        service = Channels(os.path.join(os.path.dirname(__file__), "_email_private"))
        if handler.command == "GET" and path == "/api/email/config":
            reply(service.public())
        elif handler.command == "GET" and path == "/api/email/records":
            reply(service.records())
        elif handler.command == "POST" and path in ("/api/email/config", "/api/email/test"):
            size = int(handler.headers.get("Content-Length", "0"))
            if not 0 < size <= 16384 or not handler.headers.get("Content-Type", "").startswith("application/json"):
                raise Invalid("请求格式或大小不正确")
            body = json.loads(handler.rfile.read(size))
            if not isinstance(body, dict):
                raise Invalid("请求必须为对象")
            reply(service.save(body) if path.endswith("config") else service.test(body, actor))
        else:
            reply({"ok":False,"error":"接口不存在"},404)
    except (Invalid, ValueError):
        import sys
        exc = sys.exc_info()[1]
        reply({"ok":False,"error":str(exc) if isinstance(exc,Invalid) else "请求内容不正确"},400)
    except Exception:
        reply({"ok":False,"error":"邮件配置服务异常，请联系管理员核查"},500)
    return True
