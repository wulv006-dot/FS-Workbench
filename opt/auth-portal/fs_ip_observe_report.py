#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FS 平台 · 白名单外来源观察报告（observe-only 模式配套）

数据源：/var/log/nginx/ip-denied.log
    —— 观察模式下，该文件记录的是「白名单外来源的全部请求」（不再等于"被拦截"）。
用途：把白名单外来源按 IP / /24 网段聚合，并自动做「疑似友军 / 扫描器」分类，
      便于据此决定白名单该补哪些 IP。
用法：python3 fs_ip_observe_report.py [--hours N] [--md PATH]
"""
import argparse
import collections
import datetime
import json
import os
import re
import sys
import time

LOG = "/var/log/nginx/ip-denied.log"
REPORT_MD = "/opt/auth-portal/data/ip-observe-report.md"
GEO_CACHE = "/opt/auth-portal/data/ip-geo-cache.json"
IPAPI = "http://ip-api.com/batch?fields=query,country,as,isp,hosting,proxy"

LINE_RE = re.compile(
    r'^(?P<ip>\d{1,3}(?:\.\d{1,3}){3}) - \S+ '
    r'\[(?P<ts>[^\]]+)\] "(?P<req>[^"]*)" (?P<status>\d{1,3}) (?P<n>\d+) '
    r'"(?P<ref>[^"]*)" "(?P<ua>[^"]*)"'
)
TS_FMT = "%d/%b/%Y:%H:%M:%S %z"

# 扫描器/攻击者偏好路径
ATTACK_PATH_RE = re.compile(
    r'/(\.env|\.git|\.svn|\.aws|\.ssh|wp-login|wp-admin|wp-content|phpmyadmin|'
    r'xmlrpc\.php|admin\.php|config\.(json|php)|\.DS_Store|shell\.php|actuator|'
    r'druid|solr|SDK/webLanguage|\.\./|\.well-known/security|vendor/phpunit)',
    re.I)
# 程序化 UA 特征（脚本友军常见）
PROG_UA_RE = re.compile(
    r'(python-requests|python-urllib|curl/|wget|Go-http-client|okhttp|Java/|'
    r'libwww|axios|node-fetch|httpclient|aiohttp|scrapy|guzzle|requests/)', re.I)
# 扫描/测绘 UA 特征
SCAN_UA_RE = re.compile(
    r'(sqlmap|nmap|masscan|zgrab|nikto|nuclei|dirbuster|gobuster|wpscan|hydra|'
    r'zmeu|xpanax|semrush|ahrefsbot|security research|goose\.softsec|censys|'
    r'shodan|leakix|internetmeasurement|paloalto|expanse|netsystemsresearch|'
    r'binaryedge|recon|vpnsemi)', re.I)
DING_UA_RE = re.compile(r'DingTalkBot', re.I)
BIN_REQ_RE = re.compile(r'(\\x[0-9a-fA-F]{2}){3,}|^\s*$|[^\x20-\x7e]')
BROWSER_UA_RE = re.compile(r'(Mozilla/|Chrome/|Safari/|Firefox/|Edg/)', re.I)


def ua_kind(ua):
    if not ua or ua == "-":
        return "程序(无UA)"
    if DING_UA_RE.search(ua):
        return "钉钉Bot"
    if PROG_UA_RE.search(ua):
        return "程序(UA)"
    if SCAN_UA_RE.search(ua):
        return "扫描器UA"
    if BROWSER_UA_RE.search(ua):
        return "浏览器"
    return "其他UA"


ROOTISH = {"/", "/favicon.ico", "/robots.txt"}


def classify(rec):
    """返回 (判定, 理由)"""
    paths = list(rec["paths"])
    ua = rec["uas"].most_common(1)[0][0] if rec["uas"] else ""
    refs = rec["refs"]
    # ★2026-10-16：前端反向代理中继 —— 它把外部流量代理进本机、不透传真实来源，
    #   $remote_addr 恒为代理地址。**绝不能加白**（加白等于给所有人开旁路）。
    #   判定为「未知 / 人工判断」，避免报告给出「核实后加白」这种危险建议。
    if rec.get("ip") in ("172.18.108.183",):
        return "未知", "★前端反向代理中继：真实来源不可见，禁止加白（见项目 MEMORY.md）"
    if any(ATTACK_PATH_RE.search(p) for p in paths):
        return "扫描器", "访问渗透路径"
    if SCAN_UA_RE.search(ua or ""):
        return "扫描器", "扫描器UA"
    bin_n = sum(1 for p in paths if BIN_REQ_RE.search(p))
    biz = [p for p in paths if p not in ROOTISH and p.startswith("/")
           and not BIN_REQ_RE.search(p)]
    if biz:
        if refs and any(r.startswith(("http://", "https://")) for r in refs):
            return "疑似友军", "站点内跳转+业务路径"
        if rec["uak"] in ("程序(无UA)", "程序(UA)"):
            return "疑似友军", "程序直连业务路径"
        if rec["uak"] == "钉钉Bot":
            return "友军(基础设施)", "钉钉链接预览"
        return "疑似友军", "访问业务路径"
    if bin_n:
        return "协议探测", "TLS/二进制乱码请求"
    if set(paths) <= ROOTISH:
        return "探测(待观察)", "仅探首页"
    return "未知", ""


def parse(path, since=None):
    per = {}
    bad = 0
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return {}, 0
    with fh:
        for line in fh:
            m = LINE_RE.match(line)
            if not m:
                bad += 1
                continue
            g = m.groupdict()
            try:
                t = datetime.datetime.strptime(g["ts"], TS_FMT)
            except ValueError:
                bad += 1
                continue
            if since and t < since:
                continue
            ip = g["ip"]
            r = per.get(ip)
            if r is None:
                r = per[ip] = {
                    "ip": ip, "n": 0, "first": t, "last": t,
                    "paths": collections.Counter(), "refs": set(),
                    "uas": collections.Counter(), "status": collections.Counter(),
                    "binreq": False, "reqs": [],
                }
            r["n"] += 1
            r["last"] = max(r["last"], t)
            r["first"] = min(r["first"], t)
            r["paths"][g["req"].split(" ")[1] if " " in g["req"] else g["req"]] += 1
            r["status"][g["status"]] += 1
            if g["ref"] and g["ref"] != "-":
                r["refs"].add(g["ref"])
            r["uas"][g["ua"]] += 1
            if BIN_REQ_RE.search(g["req"]):
                r["binreq"] = True
            if len(r["reqs"]) < 6:
                r["reqs"].append("%s %s -> %s" % (g["req"], g["status"], ""))
    for r in per.values():
        r["paths"] = list(r["paths"])
        r["pathcount"] = collections.Counter(
            [p for p in r["paths"]])
        r["uak"] = ua_kind(r["uas"].most_common(1)[0][0])
        r["verdict"], r["why"] = classify(r)
        r["ua_top"] = r["uas"].most_common(1)[0][0][:70]
    return per, bad


ORDER = {"疑似友军": 0, "友军(基础设施)": 1, "探测(待观察)": 2, "未知": 3,
         "协议探测": 4, "扫描器": 5}


def load_geo():
    try:
        with open(GEO_CACHE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_geo(geo):
    try:
        os.makedirs(os.path.dirname(GEO_CACHE), exist_ok=True)
        tmp = GEO_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(geo, fh, ensure_ascii=False)
        os.replace(tmp, GEO_CACHE)
    except OSError:
        pass


def enrich_geo(ips, geo):
    """用 ip-api.com（http，免 key）补齐 IP 归属；结果落缓存，之后离线可用。"""
    import urllib.request
    todo = [ip for ip in ips if ip not in geo]
    for i in range(0, len(todo), 100):
        chunk = todo[i:i + 100]
        try:
            req = urllib.request.Request(
                IPAPI, data=json.dumps(chunk).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                arr = json.loads(resp.read().decode("utf-8"))
            for it in arr:
                geo[it.get("query", "")] = {
                    "cc": it.get("country", ""),
                    "as": it.get("as", ""),
                    "isp": it.get("isp", ""),
                    "hosting": bool(it.get("hosting")),
                    "proxy": bool(it.get("proxy")),
                }
        except Exception as exc:          # 网络异常不影响报告生成
            sys.stderr.write("geo lookup failed: %r\n" % exc)
        time.sleep(1.5)                   # ip-api 免费版约 45 次/分钟
    save_geo(geo)
    return geo


def geo_txt(geo, ip):
    g = geo.get(ip)
    if not g:
        return "-"
    bits = [g.get("cc") or "?"]
    a = (g.get("as") or "").split(" ", 1)
    if len(a) == 2:
        bits.append(a[1][:30])
    if g.get("proxy"):
        bits.append("proxy")
    if g.get("hosting"):
        bits.append("机房")
    return " · ".join(bits)


SUGGEST = {
    "疑似友军": "→ 核实后加白",
    "友军(基础设施)": "保持放行",
    "探测(待观察)": "继续观察",
    "协议探测": "可忽略",
    "扫描器": "无需处理",
    "未知": "人工判断",
}


def net24(ip):
    p = ip.split(".")
    return "%s.%s.%s.0/24" % (p[0], p[1], p[2])


def render(per, geo=None):
    geo = geo or {}
    rows = sorted(per.values(), key=lambda r: (ORDER.get(r["verdict"], 9), -r["n"]))
    L = []
    L.append("# FS 平台 · 白名单外来源观察报告")
    L.append("")
    L.append("生成时间：%s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    L.append("")
    L.append("> 观察模式（observe-only）下，本报告统计**所有白名单外来源**的访问，")
    L.append("> 不区分是否曾被拦截。目的是找出「被漏掉的友军脚本」与「真实扫描器」。")
    L.append("")
    # 汇总
    byk = collections.Counter(r["verdict"] for r in per.values())
    L.append("## 一、总览（%d 个来源）" % len(per))
    L.append("")
    L.append("| 判定 | 来源数 | 请求数 |")
    L.append("|---|---|---|")
    for k in sorted(byk, key=lambda x: ORDER.get(x, 9)):
        n = sum(r["n"] for r in per.values() if r["verdict"] == k)
        L.append("| %s | %d | %d |" % (k, byk[k], n))
    L.append("")
    # 明细
    L.append("## 二、按来源明细")
    L.append("")
    L.append("| # | IP | 归属（国家 · AS） | 次数 | 首见 → 末见 | 请求路径(样本) | UA类型 | 判定 | 建议 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        ps = "<br>".join(p for p, _ in collections.Counter(r["paths"]).most_common(3))
        L.append("| %d | `%s` | %s | %d | %s → %s | %s | %s | **%s** | %s |" % (
            i, r["ip"], geo_txt(geo, r["ip"]), r["n"],
            r["first"].strftime("%m-%d %H:%M"), r["last"].strftime("%m-%d %H:%M"),
            ps or "-", r["uak"], r["verdict"],
            SUGGEST.get(r["verdict"], "-")))
    L.append("")
    # 网段
    L.append("## 三、按 /24 网段聚合（脚本 IP 漂移视角）")
    L.append("")
    L.append("| /24 网段 | 来源数 | 请求数 | 该段归属 | 判定 |")
    L.append("|---|---|---|---|---|")
    agg = collections.defaultdict(lambda: {"ips": set(), "n": 0,
                                           "k": collections.Counter()})
    for r in per.values():
        a = agg[net24(r["ip"])]
        a["ips"].add(r["ip"])
        a["n"] += r["n"]
        a["k"][r["verdict"]] += r["n"]
    for net, a in sorted(agg.items(), key=lambda kv: (-kv[1]["n"])):
        rep_ip = sorted(a["ips"])[0]
        L.append("| %s | %d | %d | %s | %s |" % (
            net, len(a["ips"]), a["n"], geo_txt(geo, rep_ip),
            a["k"].most_common(1)[0][0] if a["k"] else "-"))
    L.append("")
    L.append("---")
    L.append("")
    L.append("**加白名单建议**：把上表判定为「疑似友军」的 IP 逐一核对归属（是否本公司出口），")
    L.append("确认后在 /etc/nginx/conf.d/fs-ip-allowlist.conf 对应区加一行 `<IP>/32  1;`。")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=0, help="只统计最近 N 小时")
    ap.add_argument("--md", default=REPORT_MD)
    ap.add_argument("--print", action="store_true", help="同时在终端打印")
    args = ap.parse_args()

    since = None
    if args.hours:
        since = datetime.datetime.now(datetime.timezone.utc) - \
            datetime.timedelta(hours=args.hours)

    per, bad = parse(LOG, since)
    if not per:
        md = ("# FS 平台 · 白名单外来源观察报告\n\n"
              "生成时间：%s\n\n"
              "观察期内暂无白名单外来源访问记录。\n"
              % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        try:
            os.makedirs(os.path.dirname(args.md), exist_ok=True)
            with open(args.md, "w", encoding="utf-8") as fh:
                fh.write(md)
        except OSError:
            pass
        print("无数据（%s），已写入空报告" % LOG)
        return 0
    geo = enrich_geo(sorted(per), load_geo())
    md = render(per, geo)
    try:
        os.makedirs(os.path.dirname(args.md), exist_ok=True)
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write(md)
    except OSError as exc:
        print("写报告失败：%r" % exc, file=sys.stderr)
    if args.print:
        sys.stdout.write(md)
    else:
        print("报告已写入 %s（%d 个来源，跳过 %d 行无法解析）" % (args.md, len(per), bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())
