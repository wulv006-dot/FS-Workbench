#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discord 机器人控制台 · 后端服务
================================

零第三方依赖（只用 Python 3 标准库），与 /opt/mmoexp-taskboard、/opt/auth-portal 同款做法。

架构位置
--------
    nginx(443)
      |-- auth_request /__auth_verify  --> auth-portal 127.0.0.1:8895/verify
      |-- location /bots/              --> proxy_pass http://127.0.0.1:8936/   (本服务)

本服务只监听 127.0.0.1，公网不可达。身份唯一来源是 nginx 注入的 X-Auth-User / X-Auth-Role
—— 这两个头由 nginx 用 auth_request_set 覆盖写入，客户端自带同名字头会被覆盖，无法伪造。

管两个机器人
------------
    guard  MMOEXP-GuardBot   服务 mmoexp-guardbot   目录 /opt/mmoexp-guardbot   Node.js
    shugo  Shugo-bot (AION2) 服务 shugo-bot          目录 /opt/shugo-bot         Python

能力
----
    * 状态查询 / 启动 / 停止 / 重启
    * 配置读写（写前自动备份，原子落盘）
    * 日志读取（journalctl）
    * Discord 角色 / 频道代理查询（token 只在服务端使用，永不出网到浏览器）
    * 名称冒充判定测试器（忠实复刻 Node 端 canon/squash/classify）

安全
----
    * 读操作：任意已登录用户（dashboard 组）
    * 写操作（改配置 / 启停服务）：要求 X-Auth-Role == admin
    * Token 永不回传前端；只回 hasToken 布尔
    * 写操作全量审计到 data/audit.log
    * POST 校验 Origin 与 Host 同源 + 必需 X-Requested-With 头（防 CSRF）
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.0.0"
HERE = Path(__file__).resolve().parent


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, "").strip() or default


CFG = {
    "bind": _env("BOTCONSOLE_BIND", "127.0.0.1"),
    "port": int(_env("BOTCONSOLE_PORT", "8936")),
    "data_dir": Path(_env("BOTCONSOLE_DATA", str(HERE / "data"))),
    "static_dir": Path(_env("BOTCONSOLE_STATIC", str(HERE / "static"))),
    "max_body": 1 << 20,          # 请求体上限 1 MiB
    "max_lines": 2000,            # 日志单次最多行数
}
CFG["data_dir"].mkdir(parents=True, exist_ok=True)
(CFG["data_dir"] / "backups").mkdir(parents=True, exist_ok=True)

AUDIT_LOG = CFG["data_dir"] / "audit.log"

# ---------------------------------------------------------------- 机器人注册表

BOTS = {
    "guard": {
        "key": "guard",
        "label": "MMOEXP GuardBot",
        "subtitle": "防冒充守卫 · 前缀命中即处置",
        "service": "mmoexp-guardbot",
        "dir": "/opt/mmoexp-guardbot",
        "runtime": "node",
        "config_file": "config.json",
        "whitelist_file": "whitelist.json",
        "token_from": "config.token",
        "guild_from": "config.guildId",
        "accent": "#f38ba8",
    },
    "shugo": {
        "key": "shugo",
        "label": "Shugo-bot",
        "subtitle": "AION2 迎新面板 · 官方资讯推送",
        "service": "shugo-bot",
        "dir": "/opt/shugo-bot",
        "runtime": "python",
        "config_file": "config.json",
        "whitelist_file": None,
        "token_from": "file.token.txt",
        "guild_from": "config.guild_id",
        "accent": "#89b4fa",
    },
}

# ------------------------------------------------------- 与 Node 端逐字对齐的判定

ZERO_WIDTH = re.compile(r"[\u200B-\u200D\u2060\uFEFF\u00AD\u180E\u034F]")

HOMOGLYPH = {
    "\u041C": "m", "\u043C": "m", "\u217F": "m", "\uFF4D": "m", "\uFF2D": "m",
    "\u039C": "m", "\u03BC": "m", "\u041E": "o", "\u043E": "o", "\u039F": "o",
    "\u03BF": "o", "\u0585": "o", "\u0586": "o", "\uFF4F": "o", "\uFF2F": "o",
    "\u0415": "e", "\u0435": "e", "\u0395": "e", "\u03B5": "e", "\uFF45": "e",
    "\uFF25": "e", "\u212E": "e", "\u0425": "x", "\u0445": "x", "\u03A7": "x",
    "\u03C7": "x", "\u00D7": "x", "\u2573": "x", "\uFF58": "x", "\uFF38": "x",
    "\u0420": "p", "\u0440": "p", "\u03A1": "p", "\u03C1": "p", "\uFF50": "p",
    "\uFF30": "p",
}

HOMO_RE = re.compile("[" + "".join(re.escape(k) for k in HOMOGLYPH) + "]")

SUFFIX_OK = [
    "support", "official", "admin", "team", "service", "help", "cs", "staff",
    "store", "sale", "sales", "gift", "giveaway", "airdrop", "claim", "reward",
    "promo", "bot", "mod", "manager", "agent", "online", "shop", "market",
    "trade", "vip", "global", "hq", "inc", "llc", "top", "buy", "sell",
]

DEFAULT_BRAND_PATTERN = r"^(?:the)?(?:mm[o0]+)exp([a-z0-9]*)$"


def canon(raw) -> str:
    """全角→半角、去零宽、异体字归一、小写。"""
    s = "" if raw is None else str(raw)
    s = unicodedata.normalize("NFKC", s)
    s = ZERO_WIDTH.sub("", s)
    s = HOMO_RE.sub(lambda m: HOMOGLYPH.get(m.group(0), m.group(0)), s)
    return s.lower()


def squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s)


def drop_one_char(a: str, b: str) -> bool:
    """a 删掉恰好 1 个字符后是否等于 b。"""
    if len(a) - len(b) != 1:
        return False
    return any(a[:i] + a[i + 1:] == b for i in range(len(a)))


def one_char_diff(a: str, b: str) -> bool:
    """等长且恰好 1 个位置不同。"""
    if len(a) != len(b):
        return False
    return sum(1 for i in range(len(a)) if a[i] != b[i]) == 1


def token_match(raw_name, cfg: dict):
    """片段式匹配：品牌词作为「独立片段」出现在名字任意位置即命中。

    背景：旧的前缀正则只认「开头」，抓不到 nick.mmoexp（品牌词在中间/结尾）
    和 service_mmoex（品牌词拼错少个字母）这两类。这里按非字母数字切分后的
    独立片段比对品牌词核心，并允许 1 个字符的拼写容错。
    只匹配独立片段，所以 mmoexpert / mmoexpfan 这类粘连名字不会被误伤。
    """
    if not cfg.get("brandTokenMatch", True):
        return None
    core = squash(canon(cfg.get("brandCore") or "mmoexp"))
    if len(core) < 4:
        return None
    try:
        fuzzy = int(cfg.get("brandTokenFuzzy") or 0)
    except (TypeError, ValueError):
        fuzzy = 0
    for p in re.split(r"[^a-z0-9]+", canon(raw_name)):
        if len(p) < 4:
            continue
        if p == core:
            return {"tail": "", "via": "token", "token": p}
        if fuzzy >= 1 and (drop_one_char(core, p) or one_char_diff(core, p)):
            return {"tail": "", "via": "token-approx", "token": p}
    return None


def classify(raw_name, cfg: dict):
    """冒充判定。命中返回 dict，否则 None。与 index.js 的 classify 行为一致。"""
    sq = squash(canon(raw_name))
    if len(sq) < 6:
        return None

    for token in cfg.get("extraStartsWith") or []:
        t = squash(canon(token))
        if t and sq.startswith(t):
            return {"tail": sq[len(t):], "via": "extraStartsWith"}

    # 片段式匹配（品牌词在任意位置的独立片段）——先于前缀正则，命中信息更准确
    tk = token_match(raw_name, cfg)
    if tk:
        return tk

    pattern = cfg.get("brandPattern") or DEFAULT_BRAND_PATTERN
    try:
        m = re.match(pattern, sq, re.I)
    except re.error as e:
        return {"error": "正则无效：%s" % e}
    if not m:
        return None
    tail = (m.group(1) if m.groups() else "") or ""

    if cfg.get("matchMode") == "loose":
        return {"tail": tail, "via": "loose"}
    if tail == "":
        return {"tail": tail, "via": "exact"}
    if re.fullmatch(r"[0-9]+", tail):
        return {"tail": tail, "via": "digits"}
    for s in SUFFIX_OK:
        if tail.startswith(s):
            return {"tail": tail, "via": "suffix"}
    return None


# ------------------------------------------------------------------ 小工具


def _run(cmd, timeout=30, stdin_text=None):
    """执行命令，返回 (rc, stdout, stderr)。"""
    try:
        p = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            input=(stdin_text.encode("utf-8") if stdin_text is not None else None),
            timeout=timeout, shell=False,
        )
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return 124, "", "命令超时（%ss）" % timeout
    except Exception as e:  # noqa: BLE001
        return 1, "", "%s: %s" % (type(e).__name__, e)


def _dig(d, path, default=None):
    cur = d
    for part in str(path).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _set_path(d: dict, path: str, value):
    parts = str(path).split(".")
    cur = d
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def deep_merge(base: dict, patch: dict) -> dict:
    """把 patch 合并进 base（保留 base 里 patch 没提到的键，含 _说明 之类注释键）。"""
    out = dict(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def atomic_write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def audit(actor: str, action: str, target: str, detail: str = "") -> None:
    line = json.dumps({
        "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "actor": actor,
        "action": action,
        "target": target,
        "detail": detail,
    }, ensure_ascii=False)
    try:
        with open(AUDIT_LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# ------------------------------------------------------------- 机器人状态/配置


def bot_paths(key: str) -> dict:
    b = BOTS[key]
    root = Path(b["dir"])
    return {
        "root": root,
        "config": root / b["config_file"],
        "whitelist": (root / b["whitelist_file"]) if b["whitelist_file"] else None,
        "token_file": root / "token.txt" if b["token_from"] == "file.token.txt" else None,
    }


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def bot_token(key: str) -> str:
    """只在服务端读取 token，绝不回传前端。"""
    b = BOTS[key]
    token_from = b["token_from"]
    if token_from.startswith("config."):
        cfg = read_json(bot_paths(key)["config"], {}) or {}
        return (_dig(cfg, token_from[len("config."):], "") or "").strip()
    if token_from.startswith("file."):
        f = bot_paths(key)["token_file"]
        if f and f.exists():
            return f.read_text(encoding="utf-8").strip()
    return ""


def service_status(key: str) -> dict:
    svc = BOTS[key]["service"]
    out = {
        "service": svc, "active": False, "sub": "unknown", "enabled": False,
        "pid": 0, "uptime_sec": 0, "mem_kb": 0, "since": "",
    }
    rc, so, _ = _run([
        "systemctl", "show", svc,
        "-p", "ActiveState,SubState,UnitFileState,MainPID,ActiveEnterTimestamp",
    ], timeout=10)
    if rc == 0:
        kv = {}
        for line in so.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                kv[k.strip()] = v.strip()
        out["active"] = kv.get("ActiveState") == "active"
        out["sub"] = kv.get("SubState", "unknown")
        out["enabled"] = kv.get("UnitFileState", "") in ("enabled", "enabled-runtime")
        out["since"] = kv.get("ActiveEnterTimestamp", "")
        try:
            out["pid"] = int(kv.get("MainPID", "0") or 0)
        except ValueError:
            out["pid"] = 0
    if out["pid"] > 0:
        rc, so, _ = _run(["ps", "-o", "etimes=", "-p", str(out["pid"])], timeout=5)
        if rc == 0 and so.strip().isdigit():
            out["uptime_sec"] = int(so.strip())
        rc, so, _ = _run(["ps", "-o", "rss=", "-p", str(out["pid"])], timeout=5)
        if rc == 0 and so.strip().isdigit():
            out["mem_kb"] = int(so.strip())
    return out


def service_action(key: str, action: str) -> dict:
    svc = BOTS[key]["service"]
    if action not in ("start", "stop", "restart"):
        return {"ok": False, "error": "不支持的动作：%s" % action}
    rc, so, se = _run(["systemctl", action, svc], timeout=60)
    time.sleep(0.6)
    st = service_status(key)
    return {
        "ok": rc == 0,
        "rc": rc,
        "stdout": so.strip()[:2000],
        "stderr": se.strip()[:2000],
        "status": st,
    }


def read_logs(key: str, lines: int = 200) -> dict:
    svc = BOTS[key]["service"]
    lines = max(1, min(int(lines), CFG["max_lines"]))
    rc, so, se = _run(
        ["journalctl", "-u", svc, "--no-pager", "-n", str(lines), "-o", "short-iso"],
        timeout=20,
    )
    if rc != 0:
        # 退化：直接读日志文件
        logf = bot_paths(key)["root"] / ("shugo-bot.log" if key == "shugo" else "guardbot.log")
        if logf.exists():
            try:
                data = logf.read_text(encoding="utf-8", errors="replace").splitlines()
                return {"ok": True, "source": str(logf), "text": "\n".join(data[-lines:])}
            except OSError as e:
                return {"ok": False, "error": str(e)}
        return {"ok": False, "error": se.strip() or "journalctl 读取失败"}
    return {"ok": True, "source": "journalctl -u %s" % svc, "text": so.rstrip("\n")}


def _https_available() -> bool:
    """本机 /usr/bin/python3 的构建漏了 _ssl，urllib 发不出 https。
       这里探测一次并记住，供 discord_api 决定是否走 curl 回退。"""
    global _HTTPS_OK
    if _HTTPS_OK is None:
        try:
            import ssl  # noqa: F401
            _HTTPS_OK = True
        except Exception:  # noqa: BLE001
            _HTTPS_OK = False
            sys.stderr.write("[WARN] 当前解释器缺少 _ssl，Discord API 调用将回退到 curl。\n")
    return _HTTPS_OK


_HTTPS_OK = None


def discord_api(token: str, path: str, timeout=15):
    """调用 Discord API。返回 (ok, data_or_error)。

    token 只在服务端使用，绝不回传浏览器。curl 回退路径用 `--config -` 从 stdin 读选项，
    因此 token 不会出现在进程命令行（/proc/<pid>/cmdline）里。
    """
    if not token:
        return False, "未配置 Token"
    url = "https://discord.com/api/v10" + path
    headers = {
        "Authorization": "Bot " + token,
        "User-Agent": "MMOEXP-BotConsole/1.0",
    }

    if _https_available():
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return True, json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:400]
            return False, "HTTP %s %s" % (e.code, body)
        except Exception as e:  # noqa: BLE001
            return False, "%s: %s" % (type(e).__name__, e)

    # ---- curl 回退 ----
    cfg_lines = [
        'url = "%s"' % url,
        "silent",
        "show-error",
        "max-time = %d" % timeout,
        'write-out = "\\nBOTCONSOLE_HTTP_CODE=%{http_code}"',
    ]
    for k, v in headers.items():
        cfg_lines.append('header = "%s: %s"' % (k, v.replace('"', '\\"')))
    rc, out, err = _run(["curl", "--config", "-"], timeout=timeout + 8,
                        stdin_text="\n".join(cfg_lines) + "\n")
    if rc != 0 and not out.strip():
        return False, "curl 失败（rc=%s）：%s" % (rc, (err or "").strip()[:300])
    marker = "\nBOTCONSOLE_HTTP_CODE="
    code = 0
    if marker in out:
        out, _, tail = out.rpartition(marker)
        try:
            code = int(tail.strip() or 0)
        except ValueError:
            code = 0
    if code and not (200 <= code < 300):
        return False, "HTTP %s %s" % (code, out.strip()[:400])
    try:
        return True, json.loads(out)
    except ValueError as e:
        return False, "返回不是合法 JSON（%s）：%s" % (e, out.strip()[:300])


# --------------------------------------------------------------- 应用信息缓存

_CACHE = {}
_CACHE_LOCK = threading.Lock()


def cached(key: str, ttl: int, fn):
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _CACHE_LOCK:
        _CACHE[key] = (now, val)
    return val


def service_runtime(key: str, lines: int = 400) -> dict:
    """从服务日志里读「本次运行」的运行证据。

    为什么读日志、而不是看应用的 flags 位：
      flags 的 LIMITED / 非 LIMITED 语义极易搞反（本项目就据此误报过
      「SERVER MEMBERS INTENT 未开启」，而实际早已开启）。下面的判据全部
      来自机器人自身打印的行为，不存在歧义。

    为什么必须切「本次运行」窗口：
      journal 是累积的。上一轮会话失败留下的 [FATAL] 会一直躺在日志里，
      只要还在 -n 的范围内就会被算进来，把「现在运行良好」的服务误报成故障
      （本项目 15:14 的报错 vs 15:51 起的正常登录，就是这么被混淆的）。
      因此先以最后一条 systemd 的 "Started <svc>" 为界，只分析其后的日志。

    返回字段：
      * disallowed_intents —— 本次运行出现过 "Used disallowed intents"
      * connected          —— 本次运行出现过成功登录标记
      * mode_line          —— 守卫的「模式：DRY-RUN…」那行，直接反映是否真在处置
      * last_error         —— 本次运行最后一条错误（无则空串）
      * run_started_at     —— 本次运行起点时间戳（取不到则为空）
    """
    svc = BOTS[key]["service"]
    rc, out, _ = _run(
        ["journalctl", "-u", svc, "--no-pager", "-n", str(lines), "-o", "short-iso"],
        timeout=20,
    )
    raw = (out if rc == 0 else "").splitlines()

    # ---- 切成「本次运行」窗口 ----
    cut = -1
    for i, line in enumerate(raw):
        if " Started " in line and svc.lower() in line.lower():
            cut = i
    if cut >= 0:
        window = raw[cut + 1:]
    else:
        # 日志被轮转 / 非 systemd 环境：退化为「最后一次成功登录之后」
        last_ok = -1
        for i, line in enumerate(raw):
            if "已登录" in line or "successfully logged in" in line.lower():
                last_ok = i
        window = raw[last_ok:] if last_ok >= 0 else raw[-40:]

    run_started_at = ""
    if cut >= 0:
        run_started_at = raw[cut].split()[0] if raw[cut].split() else ""

    text = "\n".join(window)
    low = text.lower()

    connected = (
        "已登录" in text
        or "has successfully" in low
        or "successfully logged in" in low
    )

    mode_line = ""
    for line in window:
        s = line.strip()
        # 注意：用 in 而不是 startswith —— journalctl 带时间戳输出时，
        # 行首是 "2026-10-14T15:52:10+0800 play187 node[11059]: " 而不是「模式：」。
        if "模式：" in s or "模式:" in s:
            # 只保留冒号后的内容，避免把时间戳/进程号一起显示给用户
            idx = s.find("模式")
            mode_line = s[idx:idx + 160]

    last_error = ""
    for line in reversed(window):
        if "[FATAL]" in line or "Traceback" in line or "Error:" in line:
            last_error = line.strip()[:240]
            break

    return {
        "disallowed_intents": "disallowed intents" in low,
        "connected": connected,
        "mode_line": mode_line,
        "last_error": last_error,
        "run_started_at": run_started_at,
    }


def app_info(key: str) -> dict:
    """应用自身信息。flags 只作参考展示 —— 不要把 LIMITED/非 LIMITED 位当成开关真相。"""
    def _fetch():
        token = bot_token(key)
        ok, data = discord_api(token, "/applications/@me")
        if not ok:
            return {"ok": False, "error": data, "hasToken": bool(token)}
        return {
            "ok": True,
            "hasToken": bool(token),
            "id": data.get("id"),
            "name": data.get("name"),
            "bot_require_code_grant": bool(data.get("bot_require_code_grant")),
            "flags": int(data.get("flags") or 0),
        }
    return cached("app:%s" % key, 120, _fetch)


def bot_identity(key: str) -> dict:
    def _fetch():
        ok, data = discord_api(bot_token(key), "/users/@me")
        if not ok:
            return {"ok": False, "error": data}
        return {
            "ok": True,
            "id": data.get("id"),
            "username": data.get("username"),
            "global_name": data.get("global_name"),
            "bot": data.get("bot", True),
        }
    return cached("me:%s" % key, 120, _fetch)


def bot_guilds(key: str):
    def _fetch():
        ok, data = discord_api(bot_token(key), "/users/@me/guilds")
        if not ok or not isinstance(data, list):
            return {"ok": False, "error": data if not ok else "返回不是列表", "guilds": []}
        return {"ok": True, "guilds": data}
    return cached("guilds:%s" % key, 120, _fetch)


def guild_meta(key: str, guild_id: str) -> dict:
    """角色 + 频道 + 概览 + 机器人自身角色层级。供前端下拉/多选与风险提示使用。"""
    def _fetch():
        out = {"ok": True, "guild": None, "roles": [], "channels": [],
               "bot_member": None, "errors": []}

        ok, g = discord_api(bot_token(key), "/guilds/%s?with_counts=true" % guild_id)
        if ok and isinstance(g, dict):
            out["guild"] = {
                "id": g.get("id"),
                "name": g.get("name"),
                "member_count": g.get("approximate_member_count"),
                "presence_count": g.get("approximate_presence_count"),
                "verification_level": g.get("verification_level"),
                "mfa_level": g.get("mfa_level"),
            }
        else:
            out["ok"] = False
            out["errors"].append("guild: %s" % g)

        ok, roles = discord_api(bot_token(key), "/guilds/%s/roles" % guild_id)
        if ok and isinstance(roles, list):
            out["roles"] = sorted(
                [{
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "position": r.get("position", 0),
                    "managed": bool(r.get("managed")),
                    "color": r.get("color", 0),
                } for r in roles],
                key=lambda r: -r["position"],
            )
        else:
            out["errors"].append("roles: %s" % roles)

        ok, chans = discord_api(bot_token(key), "/guilds/%s/channels" % guild_id)
        if ok and isinstance(chans, list):
            out["channels"] = sorted(
                [{
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "type": c.get("type"),
                    "parent_id": c.get("parent_id"),
                    "position": c.get("position", 0),
                } for c in chans],
                key=lambda c: (c["parent_id"] or "", c["position"]),
            )
        else:
            out["errors"].append("channels: %s" % chans)

        # 机器人自身在该服务器的最高角色位置 —— 决定它「能处置谁」
        ident = bot_identity(key)
        bot_id = ident.get("id") if ident.get("ok") else None
        if bot_id:
            ok, mem = discord_api(bot_token(key), "/guilds/%s/members/%s" % (guild_id, bot_id))
            if ok and isinstance(mem, dict):
                role_ids = set(mem.get("roles") or [])
                pos_by_id = {r["id"]: r for r in out["roles"]}
                mine = [pos_by_id[rid] for rid in role_ids if rid in pos_by_id]
                mine.sort(key=lambda r: -r["position"])
                top = mine[0] if mine else None
                players = [r for r in out["roles"] if not r["managed"] and r["position"] > 0]
                top_pos = (top or {}).get("position", 0)
                above = [r["name"] for r in out["roles"]
                         if not r["managed"] and r["position"] > top_pos]
                out["bot_member"] = {
                    "top_role": (top or {}).get("name"),
                    "top_position": top_pos,
                    "role_count": len(role_ids),
                    "role_names": [pos_by_id[rid]["name"] for rid in role_ids if rid in pos_by_id],
                    "max_role_position": max([r["position"] for r in out["roles"]] or [0]),
                    "highest_player_position": (players[0]["position"] if players else 0),
                    "roles_above": above,
                }
            else:
                out["errors"].append("bot_member: %s" % mem)

        return out
    return cached("meta:%s:%s" % (key, guild_id), 90, _fetch)


# ------------------------------------------------- 处置历史（封禁 / 踢出 / 解封）

DISCORD_EPOCH_MS = 1420070400000

# 只关心这三类「处置」动作
AUDIT_KINDS = {
    20: ("kick", "踢出"),
    22: ("ban", "封禁"),
    23: ("unban", "解封"),
}

# 只在封禁列表、审计日志已查不到的老记录：逐条列出太多（2773 条 ≈ 850KB），
# 只带最近的一批，其余用 summary 里的计数交代。
OUTSIDE_LIMIT = 400


def _snowflake_iso(sid):
    """审计日志条目没有 created_at 字段，时间只能自己从雪花 ID 里还原。"""
    try:
        ms = (int(sid) >> 22) + DISCORD_EPOCH_MS
        return datetime.fromtimestamp(ms / 1000).astimezone().isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001
        return None


def _audit_fetch(key: str, action_type: int, pages: int = 2):
    """拉某一类审计日志。返回 (entries, users_map, error)。"""
    gid = bot_guild_id(key)
    token = bot_token(key)
    entries, users, before = [], {}, None
    for _ in range(max(1, pages)):
        p = "/guilds/%s/audit-logs?limit=100&action_type=%d" % (gid, action_type)
        if before:
            p += "&before=%s" % before
        ok, data = discord_api(token, p, timeout=20)
        if not ok:
            return entries, users, str(data)
        if not isinstance(data, dict):
            return entries, users, "返回格式异常"
        for u in (data.get("users") or []):
            if isinstance(u, dict) and u.get("id"):
                users[u["id"]] = u
        ents = data.get("audit_log_entries") or []
        entries.extend(ents)
        if len(ents) < 100:
            break
        before = ents[-1].get("id")
    return entries, users, None


def _guild_bans(key: str, pages: int = 5):
    """拉当前封禁列表（全量分页）。返回 (by_id, total, error)。"""
    gid = bot_guild_id(key)
    token = bot_token(key)
    by_id, total, after = {}, 0, None
    for _ in range(max(1, pages)):
        p = "/guilds/%s/bans?limit=1000" % gid
        if after:
            p += "&after=%s" % after
        ok, data = discord_api(token, p, timeout=25)
        if not ok:
            return by_id, total, str(data)
        if not isinstance(data, list):
            return by_id, total, "返回格式异常"
        for b in data:
            u = b.get("user") or {}
            uid = str(u.get("id") or "")
            if uid:
                by_id[uid] = {
                    "username": u.get("username") or "",
                    "global_name": u.get("global_name") or "",
                    "reason": b.get("reason") or "",
                }
        total += len(data)
        if len(data) < 1000:
            break
        after = (data[-1].get("user") or {}).get("id")
    return by_id, total, None


def bans_history(key: str, audit_pages: int = 2) -> dict:
    """合并「审计日志（谁在什么时候处置了谁）」+「当前封禁列表（还在不在黑名单里）」。

    为什么两边都要：
      * 审计日志有确切时间和操作者，但 Discord 只保留 45 天；
      * 封禁列表没有时间字段，却回答了「现在是否仍在封禁中」。
    """
    def _fetch():
        gid = bot_guild_id(key)
        if not gid:
            return {"ok": False, "error": "该机器人还没填 guildId"}

        errors = []
        events, users = [], {}
        for at in (22, 23, 20):
            ents, us, err = _audit_fetch(key, at, audit_pages)
            if err:
                errors.append("审计日志 action_type=%d：%s" % (at, err))
            users.update(us)
            events.extend(ents)

        by_id, ban_total, err = _guild_bans(key)
        if err:
            errors.append("封禁列表：%s" % err)

        ident = bot_identity(key)
        bot_id = str(ident.get("id") or "") if ident.get("ok") else ""

        items = []
        for e in events:
            kind, kind_cn = AUDIT_KINDS.get(e.get("action_type"), ("?", "?"))
            tid = str(e.get("target_id") or "")
            mid = str(e.get("user_id") or "")
            tu = users.get(tid) or {}
            bu = by_id.get(tid) or {}
            mu = users.get(mid) or {}
            items.append({
                "entry_id": str(e.get("id") or ""),
                "at": _snowflake_iso(e.get("id")),
                "kind": kind,
                "kind_cn": kind_cn,
                "target_id": tid,
                "target_name": bu.get("username") or tu.get("username") or "",
                "target_global": bu.get("global_name") or tu.get("global_name") or "",
                "reason": (e.get("reason") or "") or bu.get("reason") or "",
                "mod_id": mid,
                "mod_name": mu.get("username") or "",
                "mod_is_bot": bool(mu.get("bot")),
                "by_guard": bool(bot_id and mid == bot_id),
                "still_banned": tid in by_id,
            })
        items.sort(key=lambda x: -int(x["entry_id"] or 0))

        # 只在封禁列表里、审计日志没覆盖到的（45 天以前或审计日志查不到）
        covered = {i["target_id"] for i in items}
        listed = [{
            "entry_id": "0",
            "at": None,
            "kind": "ban",
            "kind_cn": "封禁",
            "target_id": uid,
            "target_name": v.get("username") or "",
            "target_global": v.get("global_name") or "",
            "reason": v.get("reason") or "",
            "mod_id": "",
            "mod_name": "",
            "mod_is_bot": False,
            "by_guard": False,
            "still_banned": True,
            "outside_audit": True,
        } for uid, v in by_id.items() if uid not in covered]

        shown = listed[:OUTSIDE_LIMIT]
        return {
            "ok": True,
            "guild_id": gid,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "summary": {
                "still_banned": ban_total,
                "events": len(items),
                "by_guard": sum(1 for i in items if i["by_guard"]),
                "by_human": sum(1 for i in items if not i["by_guard"]),
                "outside_audit": len(listed),
                "outside_shown": len(shown),
                "audit_window": "最近 %d 页 × 100 条" % audit_pages,
            },
            "items": items + shown,
            "errors": errors,
        }
    return cached("bans:%s" % key, 90, _fetch)


def bot_guild_id(key: str) -> str:
    cfg = read_json(bot_paths(key)["config"], {}) or {}
    return str(_dig(cfg, BOTS[key]["guild_from"].split(".", 1)[1], "") or "").strip()


# ---------------------------------------------------------------- HTTP 处理


class Handler(BaseHTTPRequestHandler):
    server_version = "BotConsole/" + VERSION
    protocol_version = "HTTP/1.1"

    # ---------------- 基础输出 ----------------

    def _send(self, code: int, body: bytes, ctype: str, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        for k, v in (extra or []):
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj, extra=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8",
                   [("Cache-Control", "no-store, no-cache, must-revalidate")] + list(extra or []))

    def _text(self, code: int, text: str, ctype="text/plain; charset=utf-8"):
        self._send(code, text.encode("utf-8"), ctype,
                   [("Cache-Control", "no-store, no-cache, must-revalidate")])

    # ---------------- 身份 ----------------

    @property
    def user(self) -> str:
        return (self.headers.get("X-Auth-User") or "").strip()

    @property
    def role(self) -> str:
        return (self.headers.get("X-Auth-Role") or "").strip()

    def _require_login(self) -> bool:
        if not self.user:
            self._json(401, {"ok": False, "error": "未登录"})
            return False
        return True

    def _require_admin(self) -> bool:
        if not self._require_login():
            return False
        if self.role != "admin":
            self._json(403, {"ok": False, "error": "需要管理员权限"})
            return False
        return True

    @staticmethod
    def _bot_of(path: str):
        """从 /api/<name>/<bot>/... 里取 bot key。"""
        parts = [p for p in path.split("/") if p]
        for p in parts:
            if p in BOTS:
                return p
        return None

    # ---------------- 路由 ----------------

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            self._route("GET")
        except Exception:  # noqa: BLE001
            sys.stderr.write(traceback.format_exc())
            try:
                self._json(500, {"ok": False, "error": "服务端异常"})
            except Exception:  # noqa: BLE001
                pass

    def do_POST(self):
        try:
            self._route("POST")
        except Exception:  # noqa: BLE001
            sys.stderr.write(traceback.format_exc())
            try:
                self._json(500, {"ok": False, "error": "服务端异常"})
            except Exception:  # noqa: BLE001
                pass

    def _route(self, method: str):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)

        # --- 静态资源与健康检查（不需要登录，nginx 已挡） ---
        if path in ("/", "/index.html"):
            return self._serve_static("index.html")
        if path == "/healthz":
            return self._json(200, {
                "ok": True,
                "version": VERSION,
                "bots": list(BOTS),
                "python": sys.version.split()[0],
                "https": "urllib" if _https_available() else "curl",
            })
        if path.startswith("/assets/"):
            return self._serve_static(path[len("/assets/"):])

        # --- 其余全部需要登录 ---
        if not path.startswith("/api/"):
            return self._json(404, {"ok": False, "error": "not found"})

        bot = self._bot_of(path)
        action = "/".join([p for p in path.split("/") if p and p != "api" and p not in BOTS]) or "overview"
        seg = [p for p in path.split("/") if p]

        if method == "GET":
            if path == "/api/overview":
                return self._api_overview()
            if bot and action == "config":
                return self._api_get_config(bot)
            if bot and action == "status":
                if not self._require_login():
                    return
                return self._json(200, {"ok": True, "status": service_status(bot)})
            if bot and action == "logs":
                if not self._require_login():
                    return
                n = int((query.get("lines") or ["200"])[0] or 200)
                return self._json(200, read_logs(bot, n))
            if bot and action == "meta":
                if not self._require_login():
                    return
                gid = (query.get("guild") or [bot_guild_id(bot)])[0]
                if not gid:
                    return self._json(400, {"ok": False, "error": "该机器人还没填 guildId"})
                return self._json(200, guild_meta(bot, gid))
            if bot and action == "guilds":
                if not self._require_login():
                    return
                return self._json(200, bot_guilds(bot))
            if bot and action == "bans":
                return self._api_bans(bot)
            return self._json(404, {"ok": False, "error": "未知接口 %s" % path})

        if method == "POST":
            if not self._check_csrf():
                return
            if seg[:1] != ["api"]:
                return self._json(404, {"ok": False, "error": "not found"})
            if not bot:
                return self._json(400, {"ok": False, "error": "缺少机器人标识"})
            if action == "config":
                return self._api_save_config(bot)
            if action == "service":
                return self._api_service(bot)
            if action == "test":
                return self._api_test()
            return self._json(404, {"ok": False, "error": "未知接口 %s" % path})

        return self._json(405, {"ok": False, "error": "method not allowed"})

    def _check_csrf(self) -> bool:
        """Origin 必须与 Host 同源；必须有 X-Requested-With（跨站表单发不出自定义头）。"""
        origin = (self.headers.get("Origin") or "").strip()
        host = (self.headers.get("Host") or "").strip()
        if origin:
            try:
                o = urllib.parse.urlparse(origin)
                if o.netloc and o.netloc != host:
                    self._json(403, {"ok": False, "error": "跨站请求被拒绝"})
                    return False
            except Exception:  # noqa: BLE001
                self._json(403, {"ok": False, "error": "Origin 非法"})
                return False
        if (self.headers.get("X-Requested-With") or "") != "XMLHttpRequest":
            self._json(403, {"ok": False, "error": "缺少 X-Requested-With"})
            return False
        return True

    def _read_body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return {}
        if n > CFG["max_body"]:
            raise ValueError("请求体过大")
        raw = self.rfile.read(n)
        return json.loads(raw.decode("utf-8"))

    # ---------------- 静态 ----------------

    def _serve_static(self, rel: str):
        rel = rel.lstrip("/")
        if ".." in rel.split("/"):
            return self._json(400, {"ok": False, "error": "bad path"})
        f = CFG["static_dir"] / rel
        if not f.is_file():
            return self._json(404, {"ok": False, "error": "not found"})
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".json": "application/json; charset=utf-8",
        }.get(f.suffix.lower(), "application/octet-stream")
        extra = [("Cache-Control", "no-store, no-cache, must-revalidate")]
        if f.suffix.lower() == ".html":
            extra.append(("Content-Security-Policy",
                          "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                          "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                          "connect-src 'self'; object-src 'none'; frame-src 'none'; "
                          "base-uri 'self'; form-action 'none'"))
        return self._send(200, f.read_bytes(), ctype, extra)

    # ---------------- 业务接口 ----------------

    def _api_overview(self):
        if not self._require_login():
            return
        bots = {}
        for key in BOTS:
            b = BOTS[key]
            st = service_status(key)
            cfg = read_json(bot_paths(key)["config"], {}) or {}
            info = app_info(key)
            ident = bot_identity(key)
            runtime = service_runtime(key)
            wl = read_json(bot_paths(key)["whitelist"], {}) if bot_paths(key)["whitelist"] else {}
            bots[key] = {
                "key": key,
                "label": b["label"],
                "subtitle": b["subtitle"],
                "service": b["service"],
                "dir": b["dir"],
                "runtime": b["runtime"],
                "accent": b["accent"],
                "status": st,
                "runtime_state": runtime,
                "hasToken": bool(bot_token(key)),
                "guildId": bot_guild_id(key),
                "app": info,
                "identity": ident,
                "configReadable": bool(cfg),
                "whitelistCount": (
                    len((wl or {}).get("roleIds") or []) + len((wl or {}).get("userIds") or [])
                ) if wl else None,
                "guard": {
                    "dryRun": cfg.get("dryRun"),
                    "action": cfg.get("action"),
                    "matchMode": cfg.get("matchMode"),
                } if key == "guard" else None,
            }
        return self._json(200, {
            "ok": True,
            "user": self.user,
            "role": self.role,
            "now": datetime.now().astimezone().isoformat(timespec="seconds"),
            "bots": bots,
            "actions_allowed": self.role == "admin",
        })

    def _api_bans(self, bot: str):
        """处置历史：审计日志（时间/操作者/理由）+ 当前封禁列表（是否仍在封禁中）。"""
        if not self._require_login():
            return
        try:
            data = bans_history(bot)
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"ok": False, "error": "读取处置历史失败：%s" % e})
        status = 200 if data.get("ok") else 400
        return self._json(status, data)

    def _api_get_config(self, bot: str):
        if not self._require_login():
            return
        paths = bot_paths(bot)
        cfg = read_json(paths["config"], None)
        if cfg is None:
            return self._json(500, {"ok": False, "error": "读不到配置文件 %s" % paths["config"]})
        safe = json.loads(json.dumps(cfg))
        # 抹掉 token —— 前端只拿得到 hasToken
        if BOTS[bot]["token_from"].startswith("config."):
            field = BOTS[bot]["token_from"].split(".", 1)[1]
            if field in safe:
                safe[field] = "" if not safe[field] else "__UNCHANGED__"
        wl = read_json(paths["whitelist"], {}) if paths["whitelist"] else None
        return self._json(200, {
            "ok": True,
            "bot": bot,
            "config": safe,
            "whitelist": wl,
            "hasToken": bool(bot_token(bot)),
            "guildId": bot_guild_id(bot),
            "path": str(paths["config"]),
        })

    def _api_save_config(self, bot: str):
        if not self._require_admin():
            return
        try:
            payload = self._read_body()
        except Exception as e:  # noqa: BLE001
            return self._json(400, {"ok": False, "error": "请求体解析失败：%s" % e})

        paths = bot_paths(bot)
        current = read_json(paths["config"], None)
        if current is None:
            return self._json(500, {"ok": False, "error": "读不到配置文件，拒绝覆盖"})

        incoming = payload.get("config") or {}
        if not isinstance(incoming, dict):
            return self._json(400, {"ok": False, "error": "config 必须是对象"})

        # 关键字段校验（在落盘前拦掉会写坏配置的输入）
        errs = []
        if bot == "guard":
            if "brandPattern" in incoming:
                try:
                    re.compile(str(incoming["brandPattern"]))
                except re.error as e:
                    errs.append("brandPattern 正则无效：%s" % e)
            if incoming.get("action") not in (None, "kick", "ban", "timeout", "none"):
                errs.append("action 只能是 kick / ban / timeout / none")
            if incoming.get("matchMode") not in (None, "strict", "loose"):
                errs.append("matchMode 只能是 strict / loose")
            for f in ("whitelistRoleIds", "whitelistUserIds", "extraStartsWith"):
                if f in incoming and not isinstance(incoming[f], list):
                    errs.append("%s 必须是数组" % f)
            if "dryRun" in incoming and not isinstance(incoming["dryRun"], bool):
                errs.append("dryRun 必须是布尔值")
            if "brandTokenMatch" in incoming and not isinstance(incoming["brandTokenMatch"], bool):
                errs.append("brandTokenMatch 必须是布尔值")
            if "brandCore" in incoming and not isinstance(incoming["brandCore"], str):
                errs.append("brandCore 必须是字符串")
            bf = incoming.get("brandTokenFuzzy")
            if bf is not None and (isinstance(bf, bool) or not isinstance(bf, (int, float)) or bf < 0 or bf > 2):
                errs.append("brandTokenFuzzy 必须是 0~2 的数字")
        elif bot == "shugo":
            if "news_boards" in incoming and not isinstance(incoming["news_boards"], list):
                errs.append("news_boards 必须是数组")
            for f in ("faction_roles", "class_roles"):
                if f in incoming and not isinstance(incoming[f], list):
                    errs.append("%s 必须是数组" % f)
            pm = incoming.get("news_poll_minutes")
            if pm is not None and (not isinstance(pm, int) or pm < 5):
                errs.append("news_poll_minutes 必须是不小于 5 的整数")
        if errs:
            return self._json(400, {"ok": False, "error": "；".join(errs)})

        # ---- Token 处理 ----
        #   guard：token 存在 config.json 的 token 字段 -> 作为普通字段并入
        #   shugo：token 存在 token.txt -> 单独原子写，权限 600
        # 前端永不回显 token；payload.token 为空 = 不修改。
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        token_field = None
        if BOTS[bot]["token_from"].startswith("config."):
            token_field = BOTS[bot]["token_from"].split(".", 1)[1]

        incoming.pop("token", None)          # 防止前端误把 token 塞进 config
        token_written = False
        token_in = payload.get("token")
        if isinstance(token_in, str) and token_in.strip():
            token_in = token_in.strip()
            tf = bot_paths(bot)["token_file"]
            if tf:
                try:
                    if tf.exists():
                        shutil.copy2(tf, CFG["data_dir"] / "backups" / ("%s-token-%s.txt" % (bot, stamp)))
                    fd = os.open(str(tf), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(token_in + "\n")
                        fh.flush()
                        os.fsync(fh.fileno())
                    os.chmod(str(tf), 0o600)
                    token_written = True
                except OSError as e:
                    return self._json(500, {"ok": False, "error": "Token 写入失败：%s" % e})
            elif token_field:
                incoming[token_field] = token_in
                token_written = True

        merged = deep_merge(current, incoming)

        # ---- 备份（先备份，再落盘）----
        bak = CFG["data_dir"] / "backups" / ("%s-config-%s.json" % (bot, stamp))
        try:
            shutil.copy2(paths["config"], bak)
        except OSError as e:
            return self._json(500, {"ok": False, "error": "备份失败，已中止：%s" % e})

        try:
            atomic_write_json(paths["config"], merged)
        except OSError as e:
            return self._json(500, {"ok": False, "error": "写入失败：%s" % e})

        # ---- 白名单（守卫单独文件）----
        wl_saved = None
        wl_in = payload.get("whitelist")
        if wl_in is not None and paths["whitelist"]:
            if not isinstance(wl_in, dict):
                return self._json(400, {"ok": False, "error": "whitelist 必须是对象"})
            cur_wl = read_json(paths["whitelist"], {}) or {}
            new_wl = deep_merge(cur_wl, {
                "roleIds": wl_in.get("roleIds", cur_wl.get("roleIds", [])),
                "userIds": wl_in.get("userIds", cur_wl.get("userIds", [])),
            })
            new_wl.setdefault("note", cur_wl.get("note", ""))
            try:
                shutil.copy2(paths["whitelist"], CFG["data_dir"] / "backups" / ("%s-wl-%s.json" % (bot, stamp)))
            except OSError:
                pass
            try:
                atomic_write_json(paths["whitelist"], new_wl)
                wl_saved = {
                    "roleIds": len(new_wl.get("roleIds") or []),
                    "userIds": len(new_wl.get("userIds") or []),
                }
            except OSError as e:
                return self._json(500, {"ok": False, "error": "白名单写入失败：%s" % e})

        changed = sorted(set(incoming.keys()))
        if token_written:
            changed.append("token")
        audit(self.user, "save_config", bot,
              "fields=%s backup=%s" % (",".join(changed), bak.name))

        result = {
            "ok": True,
            "bot": bot,
            "backup": bak.name,
            "changed_fields": changed,
            "whitelist": wl_saved,
            "token_updated": token_written,
            "restarted": False,
        }
        if payload.get("restart"):
            act = service_action(bot, "restart")
            result["restarted"] = act.get("ok", False)
            result["restart_detail"] = act
            audit(self.user, "service", bot, "restart (after config save)")
        result["status"] = service_status(bot)
        return self._json(200, result)

    def _api_service(self, bot: str):
        if not self._require_admin():
            return
        try:
            payload = self._read_body()
        except Exception as e:  # noqa: BLE001
            return self._json(400, {"ok": False, "error": "请求体解析失败：%s" % e})
        action = str(payload.get("action") or "").strip().lower()
        if action == "purge":
            action = "restart"
        res = service_action(bot, action)
        audit(self.user, "service", bot, "%s ok=%s" % (action, res.get("ok")))
        return self._json(200 if res.get("ok") else 500, res)

    def _api_test(self):
        if not self._require_login():
            return
        try:
            payload = self._read_body()
        except Exception as e:  # noqa: BLE001
            return self._json(400, {"ok": False, "error": "请求体解析失败：%s" % e})

        names = payload.get("names")
        if isinstance(names, str):
            names = [x.strip() for x in names.splitlines() if x.strip()]
        if not isinstance(names, list):
            return self._json(400, {"ok": False, "error": "names 必须是数组或换行文本"})
        names = [str(n) for n in names][:500]

        real = read_json(bot_paths("guard")["config"], {}) or {}
        override = payload.get("overrides") or {}
        cfg = {
            "matchMode": override.get("matchMode") or real.get("matchMode") or "strict",
            "brandPattern": override.get("brandPattern") or real.get("brandPattern") or DEFAULT_BRAND_PATTERN,
            "extraStartsWith": override.get("extraStartsWith")
            if isinstance(override.get("extraStartsWith"), list)
            else (real.get("extraStartsWith") or []),
            "brandTokenMatch": override.get("brandTokenMatch")
            if isinstance(override.get("brandTokenMatch"), bool)
            else bool(real.get("brandTokenMatch", True)),
            "brandCore": override.get("brandCore") or real.get("brandCore") or "mmoexp",
            "brandTokenFuzzy": override.get("brandTokenFuzzy")
            if isinstance(override.get("brandTokenFuzzy"), (int, float))
            else real.get("brandTokenFuzzy", 1),
        }

        results = []
        for n in names:
            hit = classify(n, cfg)
            results.append({
                "name": n,
                "squashed": squash(canon(n)),
                "hit": bool(hit and not hit.get("error")),
                "error": (hit or {}).get("error"),
                "via": (hit or {}).get("via"),
                "tail": (hit or {}).get("tail"),
            })
        return self._json(200, {"ok": True, "effective": cfg, "results": results})

    # ---------------- 访问日志（收敛） ----------------

    def log_message(self, fmt, *args):  # noqa: A003
        if os.environ.get("BOTCONSOLE_QUIET"):
            return
        sys.stderr.write("[%s] %s %s\n" % (
            datetime.now().strftime("%H:%M:%S"), self.address_string(), fmt % args))


def main():
    sys.stderr.write(
        "BotConsole %s 启动：http://%s:%d/  服务=%s\n"
        % (VERSION, CFG["bind"], CFG["port"], ", ".join(b["service"] for b in BOTS.values()))
    )
    sys.stderr.write(
        "  解释器=%s  HTTPS=%s\n"
        % (sys.executable, "stdlib(urllib)" if _https_available() else "curl 回退")
    )
    srv = ThreadingHTTPServer((CFG["bind"], CFG["port"]), Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("收到中断，退出。\n")


if __name__ == "__main__":
    main()
