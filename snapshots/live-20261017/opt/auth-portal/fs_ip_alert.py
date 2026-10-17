#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FS 平台 · 异常访问行为告警（behavior-based anomaly alert）
================================================================
与旧版的区别
------------
旧版：ip-denied.log 里「出现任何新 IP」就推一条 —— 实测每天几十条扫描器，
      属于噪音，无法区分「友军新出口」与「扫描器」。
新版：**只看行为**，命中下列规则才推，且把同一次运行的所有告警合并成
      一条消息（钉钉不刷屏）。

检测规则（在最近 WINDOW 秒的 access.log 上统计）
------------------------------------------------
  R1 攻击路径探测        访问 .env / .git / wp-config / phpMyAdmin 等渗透特征路径
  R2 扫描器/渗透工具       UA 直接暴露为扫描/渗透工具
  R3 高频访问             单个来源在窗口内请求数异常偏高（白名单/前端中继豁免）
  R4 登录尝试异常         单个来源在窗口内对登录接口的失败/尝试次数偏高
  R5 ★白名单外来源进入业务页面（HTTP 200）
                          = 非白名单来源**真的进了后台**，最可能是
                            「账号密码已泄漏」或「存在未受控的入口代理」。
                            （前端中继豁免，见 FRONT_PROXIES）

去重与降噪
----------
  同一 (规则, IP) 在 COOLDOWN 秒内只告警一次；状态存 STATE 文件，保留 KEEP_H 小时。

数据来源
--------
  /var/log/nginx/access.log（main 格式，含真实 $http_x_forwarded_for 字段）
  只读 access.log 即可 —— ip-denied.log 是它的子集，重复解析会造成计数翻倍。

运行
----
  由 fs-ip-alert.timer 每 2 分钟触发。
  运行解释器必须带 SSL：本机 /usr/bin/python3 缺 _ssl，发 HTTPS 会报
  unknown url type。用 /opt/python39/bin/python3。

  手动调试：
    /opt/python39/bin/python3 fs_ip_alert.py --dry-run        # 只打印，不发送
    /opt/python39/bin/python3 fs_ip_alert.py --dry-run --force --window 120

钉钉凭据
--------
  /etc/fc-ops-readonly-monitor/hooks-bot.json
  群「服务器及Github报警」（rc-ops 体系共用；**不是** AION2 金币机器人）。
  本脚本只读取、不打印、不复制凭据值。
"""
import argparse
import base64
import collections
import datetime
import hashlib
import hmac
import ipaddress
import json
import os
import re
import time
import urllib.parse
import urllib.request

ACCESS_LOG = "/var/log/nginx/access.log"
WL_CONF = "/etc/nginx/conf.d/fs-ip-allowlist.conf"
STATE = "/opt/auth-portal/data/anomaly-alert-state.json"
GEO_CACHE = "/opt/auth-portal/data/ip-geo-cache.json"
BOT_JSON = "/etc/fc-ops-readonly-monitor/hooks-bot.json"
BOT_GROUP = "服务器及Github报警"

WINDOW = 900          # 统计窗口（秒）
TAIL = 40000          # 最多回看多少行日志
COOLDOWN = 1800       # 同一 (规则, IP) 的告警冷却（秒）
RATE_N = 300          # R3 阈值：窗口内单来源请求数
BRUTE_N = 8           # R4 阈值：窗口内单来源登录尝试数
KEEP_H = 72           # state 保留小时
TOP_PER_RULE = 6      # 每条规则最多列几个来源

# 前端反向代理中继：经它进来的请求，$remote_addr 恒为代理地址、真实来源不可知。
#   → 对这种地址，R3（高频）/ R5（进入业务页）**必然误报**（同事正常浏览看板就是
#     高频 + 200），故豁免；但 R1（攻击路径）/ R2（扫描器 UA）/ R4（登录爆破）仍告警。
#   ⚠️ 2026-10-16 发现的 172.18.108.183（其公网出口 47.85.170.62）尚未与用户确认归属：
#     若确认是本公司前端 → 保留在此；若确认不是 → 删掉此条（并应立刻下线该入口）。
FRONT_PROXIES = {"172.18.108.183"}

# 日志行：$remote_addr - $remote_user [$time_local] "$request" $status $bytes "$ref" "$ua" "$xff"
LINE_RE = re.compile(
    r'^(?P<ip>[0-9A-Fa-f.:]+) - (?P<user>\S+) \[(?P<ts>[^\]]+)\] '
    r'"(?P<req>[^"]*)" (?P<status>\d{3}) (?P<bytes>\S+) '
    r'"(?P<ref>[^"]*)" "(?P<ua>[^"]*)"')

# R1：渗透特征路径
ATTACK_PATH_RE = re.compile(
    r'/(\.env|\.git|\.svn|\.ssh|\.aws|\.azure|\.pgpass|\.yarnrc|\.hx-|wp-admin|wp-login|wp-config'
    r'|xmlrpc\.php|phpmyadmin|pma|myadmin|adminer|druid|actuator|solr|jenkins|geoserver'
    r'|webui|owa/auth|boaform|HNAP1|cgi-bin|shell|eval-stdin|debug\.log|debug/default'
    r'|web\.config|config\.json|settings\.py|\.DS_Store|site\.zip|backup|dump\.sql|db\.sql'
    r'|vendor/phpunit|console\.php)', re.I)

# R2：扫描器 / 渗透工具 UA
SCAN_UA_RE = re.compile(
    r'Go Web Pentest Tool|l9tcpid|l9explore|libredtail|WebSiphon|c2scan|zgrab|masscan'
    r'|nuclei|sqlmap|Nikto|WPScan|Acunetix|Netsparker|CensysInspect|Stretchoid'
    r'|InternetMeasurement|Internet-measurement|Palo Alto Networks|Expanse|Shadowserver'
    r'|ApcosysBot|Infrawatch|research-scan|libwww-perl|SemrushBot|AhrefsBot|MJ12bot'
    r'|Bytespider|PetalBot|DotBot|Nmap Scripting Engine', re.I)

# R5：业务路径（非白名单来源拿到 200 = 真的进去了）
BIZ_RE = re.compile(
    r'^/(dashboard|d4|mlb|nfl|nba|cfb|fc27|deploy|api/fc27|poe2|dnd|warhammer)(/|$|\?)')
LOGIN_RE = re.compile(r'^/__auth/')
STATIC_RE = re.compile(r'\.(css|js|png|jpe?g|gif|svg|ico|woff2?|map|webp|json)($|\?)', re.I)

RULE_ORDER = ["R5", "R1", "R2", "R4", "R3"]
RULE_TITLE = {
    "R5": "★白名单外来源进入业务页面（疑似已登录 / 存在未受控入口）",
    "R1": "攻击路径探测",
    "R2": "扫描器 / 渗透工具",
    "R4": "登录尝试异常",
    "R3": "高频访问",
}


# --------------------------------------------------------------------------- #
# 钉钉
# --------------------------------------------------------------------------- #
def load_bot(path):
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    webhook = str(cfg.get("webhook", "") or "").strip()
    secret = str(cfg.get("secret", "") or "").strip()
    parts = urllib.parse.urlsplit(webhook)
    tokens = urllib.parse.parse_qs(parts.query).get("access_token", [])
    if (parts.scheme != "https" or parts.netloc != "oapi.dingtalk.com"
            or parts.path != "/robot/send" or len(tokens) != 1
            or not re.fullmatch(r"[a-fA-F0-9]{64}", tokens[0])):
        raise ValueError("bot_endpoint_invalid")
    if cfg.get("group") != BOT_GROUP:
        raise ValueError("bot_scope_invalid:%r" % cfg.get("group"))
    return webhook, secret


def dingtalk_sign(secret, ts_ms):
    s = "%s\n%s" % (ts_ms, secret)
    d = hmac.new(secret.encode("utf-8"), s.encode("utf-8"), hashlib.sha256).digest()
    return urllib.parse.quote_plus(base64.b64encode(d).decode("utf-8"))


def push(webhook, secret, text):
    ts = str(int(time.time() * 1000))
    url = webhook
    if secret:
        sep = "&" if "?" in url else "?"
        url = "%s%stimestamp=%s&sign=%s" % (url, sep, ts, dingtalk_sign(secret, ts))
    payload = json.dumps({"msgtype": "text", "text": {"content": text}},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------------------- #
# 白名单 / 归属地
# --------------------------------------------------------------------------- #
def load_whitelist():
    """从 nginx 配置里解析 geo $fs_ip_allowed 的放行网段（真源，无需手工同步）。"""
    nets = []
    try:
        with open(WL_CONF, "r", encoding="utf-8") as fh:
            txt = fh.read()
    except OSError:
        return nets
    m = re.search(r'geo\s+\$fs_ip_allowed\s*\{(.*?)\n\}', txt, re.S)
    if not m:
        return nets
    for line in m.group(1).splitlines():
        s = line.split("#", 1)[0].strip()
        if not s.endswith(";"):
            continue
        parts = s.rstrip(";").split()
        if len(parts) != 2 or parts[1] != "1":
            continue
        try:
            nets.append(ipaddress.ip_network(parts[0], strict=False))
        except ValueError:
            pass
    return nets


def load_geo():
    try:
        with open(GEO_CACHE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def load_state():
    try:
        with open(STATE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


# --------------------------------------------------------------------------- #
# 日志解析
# --------------------------------------------------------------------------- #
def tail_lines(path, limit):
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    chunk = min(size, max(limit * 400, 1 << 20))
    try:
        with open(path, "rb") as fh:
            fh.seek(max(0, size - chunk))
            data = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    lines = data.splitlines()
    return lines[-limit:] if len(lines) > limit else lines


def parse_request(req):
    parts = req.split(" ")
    if len(parts) < 2:
        return "", ""
    return parts[0], parts[1]


def scan(window, tail, log=ACCESS_LOG):
    """返回 agg[(rule, ip)] = {"n", "paths", "uas", "status"}"""
    now = time.time()
    cutoff = now - window
    agg = collections.defaultdict(lambda: {"n": 0,
                                           "paths": collections.Counter(),
                                           "uas": collections.Counter(),
                                           "status": collections.Counter()})
    totals = collections.Counter()          # 窗口内每个来源的总请求数
    logins = collections.Counter()          # 窗口内每个来源的登录尝试数

    for line in tail_lines(log, tail):
        m = LINE_RE.match(line)
        if not m:
            continue
        try:
            ts = datetime.datetime.strptime(
                m.group("ts")[:26], "%d/%b/%Y:%H:%M:%S %z").timestamp()
        except ValueError:
            continue
        if ts < cutoff:
            continue

        ip = m.group("ip")
        method, path = parse_request(m.group("req"))
        path = path.split("?", 1)[0]
        status = m.group("status")
        ua = m.group("ua")
        totals[ip] += 1

        if ATTACK_PATH_RE.search(path):
            r = agg[("R1", ip)]
            r["n"] += 1
            r["paths"][path] += 1
            r["uas"][ua] += 1

        if ua and SCAN_UA_RE.search(ua):
            r = agg[("R2", ip)]
            r["n"] += 1
            r["uas"][ua] += 1
            r["paths"][path] += 1

        if LOGIN_RE.search(path) and (method == "POST" or status in ("401", "403", "429")):
            logins[ip] += 1
            r = agg[("R4", ip)]
            r["paths"][path] += 1
            r["uas"][ua] += 1

        if status == "200" and BIZ_RE.match(path) and not STATIC_RE.search(path):
            r = agg[("R5", ip)]
            r["n"] += 1
            r["paths"][path] += 1
            r["uas"][ua] += 1

    for ip, n in totals.items():
        if n >= RATE_N:
            r = agg[("R3", ip)]
            r["n"] = n
    for ip, n in logins.items():
        if n >= BRUTE_N:
            r = agg[("R4", ip)]
            r["n"] = n

    return agg


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印，不推送")
    ap.add_argument("--force", action="store_true", help="忽略冷却，强制生成")
    ap.add_argument("--window", type=int, default=WINDOW)
    ap.add_argument("--tail", type=int, default=TAIL)
    ap.add_argument("--log", default=ACCESS_LOG, help="日志路径（调试用）")
    args = ap.parse_args()

    nets = load_whitelist()
    geo = load_geo()
    state = load_state()
    seen = state.setdefault("seen", {})

    def is_wl(ip):
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(a in n for n in nets)

    agg = scan(args.window, args.tail, args.log)
    now = int(time.time())

    # 冷却过滤 + 白名单过滤
    #   R3（高频）/ R5（进入业务页）只在「非白名单来源」上才有意义 —— 白名单内的
    #   机器本来就会高频轮询看板、正常登录后台，纳入只会产生噪音。
    #   R1/R2/R4 保留白名单内来源，但会标注「白名单内，可疑」以便排查。
    fresh = collections.defaultdict(list)
    for (rule, ip), r in agg.items():
        if r["n"] <= 0:                       # 未达阈值（如 R4 只累计了明细）
            continue
        wl = is_wl(ip)
        if rule in ("R3", "R5") and (wl or ip in FRONT_PROXIES):
            continue
        key = "%s|%s" % (rule, ip)
        last = int(seen.get(key, 0))
        if not args.force and now - last < COOLDOWN:
            continue
        fresh[rule].append((ip, r, key, wl))

    # 清理过期 state
    seen = {k: v for k, v in seen.items() if now - int(v) < KEEP_H * 3600}

    if not fresh:
        state["seen"] = seen
        state["last_run"] = now
        if args.dry_run:
            print("（无异常行为）")
        save_state(state)
        return

    lines = ["【FS平台·异常访问告警】%s" % time.strftime("%m-%d %H:%M")]
    for rule in RULE_ORDER:
        items = fresh.get(rule)
        if not items:
            continue
        items.sort(key=lambda t: -t[1]["n"])
        lines.append("")
        lines.append("%s · %d 个来源" % (RULE_TITLE[rule], len(items)))
        for ip, r, _k, wl in items[:TOP_PER_RULE]:
            tag = "（白名单内，可疑）" if wl else ""
            where = ""
            info = geo.get(ip)
            if info:
                where = info.get("country") or ""
                if info.get("as"):
                    where = (where + " · " + info["as"][:26]).strip(" ·")
            paths = "、".join(p for p, _ in r["paths"].most_common(2)) or "-"
            uas = r["uas"].most_common(1)
            ua = (uas[0][0] or "-")[:52] if uas else "-"
            lines.append("  · %s ×%d %s%s" % (ip, r["n"], ("[" + where + "] ") if where else "", tag))
            lines.append("      %s  UA=%s" % (paths, ua))
        if len(items) > TOP_PER_RULE:
            lines.append("  … 另有 %d 个来源" % (len(items) - TOP_PER_RULE))
    lines.append("")
    lines.append("说明：当前为观察模式（非白名单来源仍放行）。"
                 "确认是扫描器可在 nginx 配置 $fs_ip_deny 中封禁；"
                 "是友军出口则加入 $fs_ip_allowed。")
    lines.append("每小时统计：/opt/auth-portal/data/ip-observe-report.md")
    text = "\n".join(lines)

    if args.dry_run:
        print(text)
        for rule in RULE_ORDER:
            for _ip, _r, k, _wl in fresh.get(rule, []):
                seen[k] = now
        state["seen"] = seen
        state["last_run"] = now
        save_state(state)
        return

    try:
        webhook, secret = load_bot(BOT_JSON)
    except Exception as exc:
        state["seen"] = seen
        state["last_run"] = now
        save_state(state)
        print("bot config unavailable (%r); push skipped" % exc)
        return

    try:
        print("push:", push(webhook, secret, text))
        for rule in RULE_ORDER:
            for _ip, _r, k, _wl in fresh.get(rule, []):
                seen[k] = now
        state["seen"] = seen
    except Exception as exc:
        print("push failed:", repr(exc))       # 推送失败不写冷却，下次重试
    state["last_run"] = now
    save_state(state)


if __name__ == "__main__":
    main()
