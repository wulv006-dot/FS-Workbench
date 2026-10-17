#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G2G accessToken 服务器侧续签器（纯 HTTP，无浏览器、无本机依赖）。

背景
----
原先 accessToken（900s 寿命）靠本机一台 Windows 上的专用 Chrome：开页面 → 前端
用 refresh cookie 续签 → CDP 读 localStorage → ssh 推到服务器。**电脑一关就断供。**

2026-10-12 实测确认 G2G 前端续签就是一个普通接口调用（反编译 app.cd14ab6a.js）：

    POST https://sls.g2g.com/user/refresh_access
    body = {"user_id", "refresh_token", "active_device_token", "long_lived_token"}

  · 不需要 Cookie 头（实测带/不带均 200）
  · 不需要 accessToken（这是续签接口，本身就是用来换 accessToken 的）
  · 返回值 payload = {access_token, refresh_token, long_lived_token,
                      active_device_token, *_exp}
  · 三个长期令牌 **不轮换**（2026-10-12 实测：返回值与传入值逐字节相同）

因此整个链条可以 100% 放在服务器上：本脚本每 3 分钟跑一次，token 快到期才真调接口。

凭据
----
VAR/g2g_session.json（chmod 600）保存三个长期令牌：
  refresh_token        寿命约 25 天（本机迁移时剩余 13 天）
  long_lived_token     寿命约半年（2027-04-10）← 长跑主力
  active_device_token  寿命约 60 天
三者任一为空都能续（前端只在 refresh_token 与 long_lived_token **同时**为空时才报
err_missing_tokens）。全部失效时只能人工重新登录（邮箱验证码，无法无人值守）。

输出
----
VAR/token.json —— 与旧保活器推送的**完全同 schema**，app/core_self.load_token 直接读：
  {"access_token", "payload":{...JWT 载荷...}, "saved_at", "seller_id", "remaining"}
"""
import base64
import hashlib
import hmac
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://sls.g2g.com"
ROOT = "/opt/g2gfollow"
VAR = os.path.join(ROOT, "var")
LOGS = os.path.join(ROOT, "logs")
SESSION = os.path.join(VAR, "g2g_session.json")
TOKEN = os.path.join(VAR, "token.json")
LOGF = os.path.join(LOGS, "token_refresh.log")
ALERT_MARK = os.path.join(VAR, ".token_refresh_alert")
DINGTALK_ENV = "/opt/d4follow/dingtalk.env"      # 复用 d4follow 已有的告警通道

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 现有 token 剩余超过该秒数就不打扰 G2G（900s 寿命，留足冗余）
MIN_KEEP = int(os.environ.get("G2G_MIN_KEEP_SEC", "480"))
# 同一类失败多久内不重复告警（秒）
ALERT_GAP = int(os.environ.get("G2G_ALERT_GAP_SEC", "1800"))
LOG_MAX = 1024 * 1024


def log(*a):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), " ".join(str(x) for x in a))
    print(line, flush=True)
    try:
        os.makedirs(LOGS, exist_ok=True)
        if os.path.isfile(LOGF) and os.path.getsize(LOGF) > LOG_MAX:
            os.replace(LOGF, LOGF + ".1")
        with io.open(LOGF, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:                       # noqa: BLE001
        print("  (写日志失败 %r)" % e, flush=True)


def jload(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def jwrite_600(path, obj):
    """原子写 + 0600（token 是敏感数据，必须不落半截文件）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with io.open(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=1))
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def jwt_payload(tok):
    try:
        p = tok.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p.encode()).decode("utf-8", "replace"))
    except Exception:                            # noqa: BLE001
        return None


# ---------------------------------------------------------------- 告警
def dingtalk(msg):
    """带加签发钉钉；通道不可用就静默降级（绝不因为告警失败影响主流程）。"""
    try:
        if not os.path.isfile(DINGTALK_ENV):
            return False
        env = {}
        for ln in io.open(DINGTALK_ENV, encoding="utf-8", errors="ignore"):
            ln = ln.strip()
            if "=" in ln and not ln.startswith("#"):
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip()
        hook = env.get("DINGTALK_WEBHOOK")
        secret = env.get("DINGTALK_SECRET")
        if not hook:
            return False
        url = hook
        if secret:
            ts = str(round(time.time() * 1000))
            s = "%s\n%s" % (ts, secret)
            sign = urllib.parse.quote_plus(base64.b64encode(
                hmac.new(secret.encode(), s.encode(), hashlib.sha256).digest()))
            url = "%s&timestamp=%s&sign=%s" % (hook, ts, sign)
        body = json.dumps({"msgtype": "text",
                           "text": {"content": msg}}).encode("utf-8")
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception as e:                       # noqa: BLE001
        log("  (钉钉告警发送失败 %r)" % e)
        return False


def alert_once(kind, msg):
    """同一类告警在 ALERT_GAP 内只发一次。"""
    try:
        last = jload(ALERT_MARK) if os.path.isfile(ALERT_MARK) else {}
    except Exception:                            # noqa: BLE001
        last = {}
    now = time.time()
    if now - float(last.get(kind, 0)) < ALERT_GAP:
        log("  (同类告警 %s 刚发过，跳过)" % kind)
        return
    if dingtalk(msg):
        last[kind] = now
        try:
            jwrite_600(ALERT_MARK, last)
        except Exception:                        # noqa: BLE001
            pass
        log("  已发钉钉告警 [%s]" % kind)


# ---------------------------------------------------------------- 主流程
def current_remaining():
    """现有 token.json 还剩多少秒；不可用返回 None。"""
    try:
        d = jload(TOKEN)
        exp = (d.get("payload") or {}).get("exp")
        if not d.get("access_token") or exp is None:
            return None
        return float(exp) - time.time()
    except Exception:                            # noqa: BLE001
        return None


def do_refresh(sess):
    body = json.dumps({
        "user_id": str(sess.get("user_id") or "1003767531"),
        "refresh_token": sess.get("refresh_token") or "",
        "active_device_token": sess.get("active_device_token") or "",
        "long_lived_token": sess.get("long_lived_token") or "",
    }).encode("utf-8")
    req = urllib.request.Request(BASE + "/user/refresh_access", data=body, headers={
        "content-type": "application/json",
        "accept": "application/json, text/plain, */*",
        "origin": "https://www.g2g.com",
        "referer": "https://www.g2g.com/",
        "user-agent": UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:                        # noqa: BLE001
            return e.code, {"raw": raw[:300]}


def main():
    if not os.path.isfile(SESSION):
        log("× 缺少长期凭据 %s —— 需从本机 Chrome 重新迁移一次" % SESSION)
        alert_once("no_session",
                   "【G2G】服务器续签器找不到长期凭据 var/g2g_session.json，改价将不可用。\n"
                   "需在本机（已登录的专用 Chrome）跑一次 脚本/g2g_export_session_to_server.py 回迁凭据。")
        return 2

    sess = jload(SESSION)

    left = current_remaining()
    if left is not None and left > MIN_KEEP:
        log("跳过：现有 token 还剩 %.0fs（阈值 %ds）" % (left, MIN_KEEP))
        return 0

    tag = "无 token" if left is None else "剩余 %.0fs" % left
    log("续签中（%s）..." % tag)
    t0 = time.time()
    status, j = do_refresh(sess)
    dt = time.time() - t0
    code = (j or {}).get("code")

    if status != 200 or code not in (2000, 200):
        msgs = (j or {}).get("messages")
        detail = json.dumps(msgs, ensure_ascii=False)[:200] if msgs else str(j)[:200]
        log("× 续签失败 HTTP %s code=%s 耗时 %.2fs  %s" % (status, code, dt, detail))
        # 4401 / 401 = 会话真的失效了（要重新登录）；其他多为网络抖动
        dead = status in (401, 403) or code in (4401, 4400, 41001)
        alert_once("refresh_dead" if dead else "refresh_err",
                   ("【G2G】服务器续签失败：长期会话已失效（HTTP %s code=%s）。\n"
                    "改价系统将不可用，需人工重新登录一次 G2G 并回迁凭据。" % (status, code))
                   if dead else
                   ("【G2G】服务器续签失败（HTTP %s code=%s），可能是网络抖动，会自动重试。\n%s"
                    % (status, code, str(j)[:160])))
        return 3

    pl = (j.get("payload") or {})
    tok = pl.get("access_token")
    if not tok:
        log("× 返回里没有 access_token：%s" % str(j)[:200])
        alert_once("refresh_err", "【G2G】续签返回异常：没有 access_token。%s" % str(j)[:160])
        return 3

    payload = jwt_payload(tok) or {}

    # 长期令牌若被服务端轮换，就地落盘（实测未轮换，但留好处理）
    rotated = []
    for k in ("refresh_token", "long_lived_token", "active_device_token"):
        nv = pl.get(k)
        if isinstance(nv, str) and nv and nv != sess.get(k):
            sess[k] = nv
            rotated.append(k)
    for k in ("refresh_token_exp", "long_lived_token_exp", "active_device_token_exp"):
        if pl.get(k) is not None:
            sess[k] = pl[k]
    sess["last_refresh_at"] = int(time.time())
    if rotated:
        jwrite_600(SESSION, sess)

    left_new = int(payload.get("exp", 0) - time.time())
    jwrite_600(TOKEN, {
        "access_token": tok,
        "payload": payload,
        "saved_at": time.time(),
        "seller_id": str(sess.get("user_id") or "1003767531"),
        "remaining": left_new,
        "source": "server-side refresh_access",
    })
    log("OK 新 token 剩余 %ds（exp %s）耗时 %.2fs%s"
        % (left_new, time.strftime("%H:%M:%S", time.localtime(payload.get("exp", 0))), dt,
           "；长期令牌已轮换 %s" % ",".join(rotated) if rotated else ""))

    # 顺手报一次长期令牌的寿命，方便提前安排重新登录
    for k, name in (("long_lived_token_exp", "long_lived_token"),
                    ("refresh_token_exp", "refresh_token"),
                    ("active_device_token_exp", "active_device_token")):
        v = sess.get(k)
        if v:
            d = int(v / 1000.0 - time.time()) // 86400 if v > 1e11 else int(v - time.time()) // 86400
            if 0 < d <= 7:
                alert_once("expiring_" + name,
                           "【G2G】%s 将在 %d 天后到期，届时需人工重新登录一次 G2G 并回迁凭据。"
                           % (name, d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
