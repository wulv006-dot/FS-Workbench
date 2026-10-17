#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地冒烟测试：用临时目录伪造两个机器人的配置，验证 HTTP 层行为。
   不联网、不碰 /opt、不碰 systemd。"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server as S  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="botconsole-smoke-"))
FAIL = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  | " + str(extra)) if extra else ""))
    if not cond:
        FAIL.append(name)


# ---- 伪造：把两个机器人的目录指到临时目录 ----
def mkdir_bot(key, cfg, wl=None, token=None):
    d = TMP / key
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    if wl is not None:
        (d / "whitelist.json").write_text(json.dumps(wl, ensure_ascii=False, indent=2), encoding="utf-8")
    if token is not None:
        (d / "token.txt").write_text(token + "\n", encoding="utf-8")
    S.BOTS[key]["dir"] = str(d)
    return d


guard_dir = mkdir_bot("guard", {
    "token": "FAKE.GUARD.TOKEN",
    "guildId": "",
    "action": "kick",
    "dryRun": True,
    "matchMode": "strict",
    "brandPattern": "^(?:the)?(?:mm[o0]+)exp([a-z0-9]*)$",
    "extraStartsWith": [],
    "whitelistRoleIds": [],
    "whitelistUserIds": [],
    "logChannelId": "",
    "_说明": "不要丢我",
}, wl={"note": "白名单", "roleIds": [], "userIds": []})

shugo_dir = mkdir_bot("shugo", {
    "guild_id": "1555436884593741916",
    "menu_channel_id": "1557641711067467816",
    "news_boards": ["notice_en"],
    "news_poll_minutes": 30,
    "layout": {"class_per_row": 4, "row_px": 480},
    "faction_roles": [], "class_roles": [],
    "texts": {"card_title": "Hi"},
    "_news_说明": "不要丢我",
}, token="FAKE.SHUGO.TOKEN")

# 白名单与 token 文件路径需要在 BOTS 生效后重新解析
S.BOTS["guard"]["config_file"] = "config.json"
S.BOTS["guard"]["whitelist_file"] = "whitelist.json"
S.BOTS["shugo"]["config_file"] = "config.json"

S.CFG["data_dir"] = TMP / "data"
S.CFG["data_dir"].mkdir(parents=True, exist_ok=True)
(S.CFG["data_dir"] / "backups").mkdir(parents=True, exist_ok=True)
S.AUDIT_LOG = S.CFG["data_dir"] / "audit.log"
S.CFG["static_dir"] = Path(__file__).resolve().parent / "static"

PORT = 18936
srv = S.ThreadingHTTPServer(("127.0.0.1", PORT), S.Handler)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.4)
BASE = "http://127.0.0.1:%d" % PORT


def call(path, method="GET", body=None, user=None, role=None, xrw=None, origin=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if user:
        req.add_header("X-Auth-User", user)
    if role:
        req.add_header("X-Auth-Role", role)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        if xrw != "__NONE__":
            req.add_header("X-Requested-With", xrw or "XMLHttpRequest")
    if origin:
        req.add_header("Origin", origin)
    req.add_header("Host", "127.0.0.1:%d" % PORT)

    def _decode(text):
        if raw:
            return text
        return json.loads(text)

    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            body_txt = r.read().decode()
            return r.status, _decode(body_txt)
    except urllib.error.HTTPError as e:
        raw_txt = e.read().decode()
        try:
            return e.code, _decode(raw_txt)
        except Exception:  # noqa: BLE001
            return e.code, {"raw": raw_txt[:200]}


print("=== 1. 公开端点 ===")
st, d = call("/healthz")
check("healthz 200", st == 200 and d.get("ok"), d)
st, html = call("/", raw=True)
check("GET / 返回控制台 HTML", st == 200 and "<title>Discord 机器人控制台</title>" in html, st)

print("\n=== 2. 鉴权 ===")
st, d = call("/api/overview")
check("未登录 overview -> 401", st == 401, st)
st, d = call("/api/overview", user="chenchao", role="readonly")
check("只读用户 overview -> 200", st == 200, st)
check("overview 标记只读", d.get("actions_allowed") is False, d.get("actions_allowed"))
check("overview 不回传 token 明文", "FAKE" not in json.dumps(d), "泄露!")
check("overview 含两个机器人", set(d.get("bots", {}).keys()) == {"guard", "shugo"}, list(d.get("bots", {})))

print("\n=== 3. 配置读取 ===")
st, d = call("/api/guard/config", user="chenchao", role="readonly")
check("guard config 200", st == 200, st)
check("guard token 被隐藏", d["config"]["token"] == "__UNCHANGED__", d["config"].get("token"))
check("guard 注释键保留", d["config"].get("_说明") == "不要丢我", d["config"].get("_说明"))
check("guard 白名单已读", isinstance(d.get("whitelist"), dict), d.get("whitelist"))
st, d = call("/api/shugo/config", user="chenchao", role="admin")
check("shugo config 200", st == 200, st)
check("shugo 无 token 字段", "token" not in d["config"], list(d["config"]))

print("\n=== 4. 写权限闸门 ===")
st, d = call("/api/guard/config", "POST", {"config": {"action": "ban"}}, user="chenchao", role="readonly")
check("只读用户写配置 -> 403", st == 403, st)
st, d = call("/api/guard/config", "POST", {"config": {"action": "ban"}}, user="chenchao", role="admin", xrw="__NONE__")
check("缺 X-Requested-With -> 403", st == 403, st)
st, d = call("/api/guard/config", "POST", {"config": {"action": "ban"}}, user="chenchao", role="admin",
             origin="https://evil.example.com")
check("跨站 Origin -> 403", st == 403, st)
st, d = call("/api/guard/config", "POST", {"config": {"action": "badvalue"}}, user="chenchao", role="admin")
check("非法 action -> 400", st == 400, st)
st, d = call("/api/guard/config", "POST", {"config": {"brandPattern": "^(unclosed"}}, user="chenchao", role="admin")
check("非法正则 -> 400", st == 400, st)

print("\n=== 5. 配置写入 + 备份 ===")
st, d = call("/api/guard/config", "POST",
             {"config": {"action": "ban", "guildId": "1041923524601851914", "matchMode": "strict"},
              "whitelist": {"roleIds": ["123456789"], "userIds": ["999"]}},
             user="chenchao", role="admin")
check("保存成功", st == 200 and d.get("ok"), d)
check("报告变更字段", "action" in (d.get("changed_fields") or []), d.get("changed_fields"))
check("产生备份文件", (S.CFG["data_dir"] / "backups" / (d.get("backup") or "x")).exists(), d.get("backup"))
check("白名单已写入", d.get("whitelist") == {"roleIds": 1, "userIds": 1}, d.get("whitelist"))

saved = json.loads((guard_dir / "config.json").read_text(encoding="utf-8"))
check("action 已落盘", saved["action"] == "ban", saved.get("action"))
check("token 未被清空", saved["token"] == "FAKE.GUARD.TOKEN", saved.get("token"))
check("注释键未被冲掉", saved.get("_说明") == "不要丢我", saved.get("_说明"))
check("未提交字段保持原值", saved.get("dryRun") is True, saved.get("dryRun"))
wl_saved = json.loads((guard_dir / "whitelist.json").read_text(encoding="utf-8"))
check("白名单落盘正确", wl_saved["roleIds"] == ["123456789"], wl_saved)
check("白名单注释保留", wl_saved.get("note") == "白名单", wl_saved.get("note"))

print("\n=== 6. Token 更新路径 ===")
st, d = call("/api/shugo/config", "POST", {"config": {"news_poll_minutes": 45}, "token": "NEW.SHUGO.TOKEN"},
             user="chenchao", role="admin")
check("shugo token 更新成功", st == 200 and d.get("token_updated") is True, d.get("token_updated"))
tok = (shugo_dir / "token.txt").read_text(encoding="utf-8").strip()
check("token.txt 已更新", tok == "NEW.SHUGO.TOKEN", tok)
mode = oct(os.stat(shugo_dir / "token.txt").st_mode & 0o777)
if os.name == "nt":
    print("SKIP  token.txt 权限 600（Windows 不体现 POSIX 权限位，Linux 上生效）")
else:
    check("token.txt 权限 600", mode == "0o600", mode)
st, d = call("/api/shugo/config", "POST", {"config": {"news_poll_minutes": 60}, "token": ""},
             user="chenchao", role="admin")
tok2 = (shugo_dir / "token.txt").read_text(encoding="utf-8").strip()
check("空 token 不覆盖", tok2 == "NEW.SHUGO.TOKEN", tok2)
st, d = call("/api/shugo/config", "POST", {"config": {"news_poll_minutes": 3}}, user="chenchao", role="admin")
check("轮询间隔 <5 -> 400", st == 400, st)

st, d = call("/api/guard/config", "POST", {"config": {"action": "kick"}, "token": "NEW.GUARD.TOKEN"},
             user="chenchao", role="admin")
g2 = json.loads((guard_dir / "config.json").read_text(encoding="utf-8"))
check("guard token 写入 config.json", g2["token"] == "NEW.GUARD.TOKEN", g2.get("token"))

print("\n=== 7. 名称测试器 ===")
st, d = call("/api/guard/test", "POST",
             {"names": ["MMOEXP Support", "mmoexpert", "MM0EXP", "John"],
              "overrides": {"matchMode": "strict"}},
             user="readonly", role="readonly")
check("测试器 200", st == 200 and d.get("ok"), st)
hits = {r["name"]: r["hit"] for r in d.get("results", [])}
check("MMOEXP Support 命中", hits.get("MMOEXP Support") is True, hits)
check("mmoexpert 放行", hits.get("mmoexpert") is False, hits)
check("MM0EXP 命中", hits.get("MM0EXP") is True, hits)
check("John 放行", hits.get("John") is False, hits)

print("\n=== 8. 日志与状态（无 systemd 环境下应优雅失败）===")
st, d = call("/api/guard/status", user="chenchao", role="readonly")
check("status 接口可用", st == 200 and "status" in d, st)
st, d = call("/api/guard/logs?lines=10", user="chenchao", role="readonly")
check("logs 接口有结构", st == 200 and ("ok" in d), st)
st, d = call("/api/guard/service", "POST", {"action": "nonsense"}, user="chenchao", role="admin")
check("非法服务动作 -> 400/500", st in (400, 500), st)

print("\n=== 9. 审计日志 ===")
audit_lines = [json.loads(l) for l in (S.CFG["data_dir"] / "audit.log").read_text(encoding="utf-8").splitlines() if l.strip()]
check("有审计记录", len(audit_lines) >= 3, len(audit_lines))
check("审计含操作人", all(a.get("actor") == "chenchao" for a in audit_lines), audit_lines[:1])
check("审计不含 token 明文", "FAKE" not in json.dumps(audit_lines) and "NEW." not in json.dumps(audit_lines))

print("\n=== 10. 目录穿越防护 ===")
st, d = call("/assets/../server.py", user="chenchao", role="admin")
check("穿越被拒", st in (400, 404), st)

print("\n=== 11. curl 回退路径（模拟解释器缺 _ssl）===")
if os.environ.get("SKIP_NET"):
    print("SKIP  网络测试（SKIP_NET=1）")
else:
    S._HTTPS_OK = False          # 强制走 curl 分支
    ok, res = S.discord_api("MTU1OTgxOTA3MjE2ODc5NjI0MA.G7OjRj.iuQHnmnUG0lBD9DisNP-nRN5BGP2uq1e3muWwo",
                            "/users/@me")
    check("curl 回退能拿到身份", ok is True and isinstance(res, dict) and res.get("id"),
          (res if ok else res))
    if ok and isinstance(res, dict):
        check("curl 回退返回正确机器人",
              str(res.get("username", "")).lower() == "mmoexp_bot", res.get("username"))
    ok2, res2 = S.discord_api("bogus.token.here", "/users/@me")
    check("curl 回退正确处理 401", ok2 is False and "401" in str(res2), res2)
    S._HTTPS_OK = None

srv.shutdown()
shutil.rmtree(TMP, ignore_errors=True)

print("\n===== 汇总：失败 %d 项 =====" % len(FAIL))
if FAIL:
    for f in FAIL:
        print("  ✗", f)
sys.exit(1 if FAIL else 0)
