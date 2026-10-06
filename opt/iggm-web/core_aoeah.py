# -*- coding: utf-8 -*-
"""
AOEAH 抓取核心（www.aoeah.com）
==============================
实测结论（2026-09-05）：
- 品类页 URL 形如 /{game-slug}-{suffix}，但 slug 不统一（diablo4-gold vs diablo-4-boosting），
  所以品类发现必须读页面导航 `.list_serverBox.gametype a[data-type]`，不能靠猜 URL。
- 商品数据走 POST /api/goods（urlencoded），参数：
    gamesort=<data-game>  type=<data-type>  servername=<servername>
    tmethod=  tmethod2=  sort=1  searchname=  pagesize=50  page=N
  返回 {items:[{name:[...], price, unitprice, oldprice, sendnum, token, img, ...}], count, pagesize, page}
  count <= pagesize 时一次拿全；items 为空或已抓够 count 即停。
- 平台/服务器列表在 `.activeserver li`：serverid + servername + span(All)。
- 服务器偶尔 chunked 传输中断（SSL record layer failure），所有请求必须带重试。
- 纯 urllib 可抓，无需浏览器。
"""
import http.cookiejar
import json
import re
import time
import urllib.parse
import urllib.request
from html import unescape as _unescape

BASE = "https://www.aoeah.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


class AoeahCrawler:
    def __init__(self, log=print, delay=0.8, progress=None, cancel=None):
        self.log = log
        self.delay = delay
        self.progress = progress
        self.cancel = cancel
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj))
        self.op.addheaders = [("User-Agent", UA)]

    # ---------- 基础请求（带重试，AOEAH 偶发 SSL 断流） ----------
    def get(self, url, referer=None, post=None, ajax=False, tries=4):
        last = None
        for i in range(tries):
            try:
                if post is None:
                    req = urllib.request.Request(url, headers={
                        "User-Agent": UA, "Accept": "text/html",
                        "Referer": referer or BASE + "/"})
                else:
                    req = urllib.request.Request(
                        url, data=urllib.parse.urlencode(post).encode(),
                        method="POST",
                        headers={"User-Agent": UA,
                                 "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                 "X-Requested-With": "XMLHttpRequest",
                                 "Referer": referer or BASE + "/"})
                return self.op.open(req, timeout=30).read().decode("utf-8", "ignore")
            except Exception as e:
                last = e
                self.log(f"  请求失败({i + 1}/{tries}): {e}")
                time.sleep(1.2 * (i + 1))
        raise last

    def _progress(self, frac, label=""):
        if self.progress:
            try:
                self.progress(frac, label)
            except Exception:
                pass

    def _cancelled(self):
        if not self.cancel:
            return False
        try:
            return bool(self.cancel())
        except Exception:
            return False

    # ---------- 页面解析 ----------
    def probe(self, url):
        """解析品类页：返回 {url, game, gtype, servers, navs}"""
        page = self.get(url)
        info = {"url": url, "game": "", "gtype": "", "servers": [], "navs": []}

        # 品类导航：.gametype 里的 a[data-id][class][data-type][data-game][href]
        # （属性顺序实测固定；导航链接同时是品类发现入口，slug 不统一不能靠猜 URL）
        navs = []
        for m in re.finditer(
                r'<a\s+data-id="([^"]*)"\s+class="([^"]*)"\s+data-type="([^"]*)"'
                r'\s+data-game="([^"]*)"\s+href="([^"]+)"', page):
            _id, cls, gtype, game, href = m.groups()
            navs.append({"type": gtype, "game": game,
                         "href": urllib.parse.urljoin(BASE, href),
                         "active": "active" in cls.split()})
        info["navs"] = navs

        cur = next((n for n in navs if n["active"]), None)
        if cur:
            info["gtype"] = cur["type"]
            info["game"] = cur["game"]
        else:
            # 单品类页找不到导航时退回 URL 推断
            info["gtype"] = ""
            info["game"] = ""

        # 平台/服务器
        for m in re.finditer(
                r'<li\s+class="([^"]*)"\s+serverid="([^"]*)"\s+servername="([^"]*)"[^>]*>'
                r'[\s\S]{0,120}?<span>([^<]*)</span>', page):
            cls, sid, sname, span = m.groups()
            info["servers"].append({"server_id": sid, "platform": sname,
                                    "label": span.strip() or sname,
                                    "active": "active" in cls.split()})
        if not info["servers"]:
            info["servers"] = [{"server_id": "", "platform": "", "label": "All"}]

        # 游戏名兜底：标题
        if not info["game"]:
            m = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
            t = re.sub(r"<[^>]+>", " ", m.group(1)) if m else ""
            t = re.split(r"\s*[|\-–—]\s*", t)[0]
            t = re.sub(r"^\s*(buy|cheap|get|sell|best)\s+", "", t, flags=re.I).strip()
            info["game"] = t[:60]
        return info

    def discover(self, url):
        """从一个品类页发现该游戏全部品类页 URL"""
        info = self.probe(url)
        cats = [n["href"] for n in info["navs"]]
        if url.rstrip("/") + "/" not in [c + "/" for c in cats]:
            cats.insert(0, url)
        # 去重保序
        seen, out = set(), []
        for c in cats:
            c = c.rstrip("/")
            if c not in seen:
                seen.add(c)
                out.append(c)
        return {"game": info["game"], "categories": out}

    # ---------- 抓取 ----------
    def api_goods(self, info, server, page_no, pagesize=50):
        post = {
            "gamesort": info["game"], "type": info["gtype"],
            "servername": server["platform"], "tmethod": "", "tmethod2": "",
            "sort": "1", "searchname": "", "pagesize": str(pagesize),
            "page": str(page_no), "ajaxtime": "0",
        }
        resp = self.get(BASE + "/api/goods", referer=info["url"], post=post)
        return json.loads(resp)

    def scrape_url(self, url):
        """抓取单个品类页，返回 (info, rows)"""
        info = self.probe(url)
        if not info["game"] or not info["gtype"]:
            raise ValueError(f"无法识别的 AOEAH 品类页: {url}")
        self.log(f"AOEAH | {info['game']} · {info['gtype']} | "
                 f"平台: {[s['platform'] for s in info['servers']]}")
        rows = self._scrape_page(info)
        return info, rows

    def _scrape_page(self, info):
        rows = []
        servers = info["servers"]
        done_srv = 0
        for srv in servers:
            if self._cancelled():
                self._progress(done_srv / len(servers), "已中止")
                return rows
            seen, page_no, total = {}, 1, None
            base = f"{info['gtype']} · {srv['platform'] or '默认'}"
            while True:
                if self._cancelled():
                    self.log(f"  [{srv['platform'] or '默认'}] 已中止，已抓 {len(seen)}")
                    break
                try:
                    d = self.api_goods(info, srv, page_no)
                except Exception as e:
                    self.log(f"  [{srv['platform'] or '默认'}] 第 {page_no} 页失败: {e}")
                    break
                items = d.get("items", [])
                if total is None:
                    total = d.get("count") or 0
                    self.log(f"  [{srv['platform'] or '默认'}] 共 {total} 条")
                if not items:
                    break
                for g in items:
                    token = str(g.get("token") or g.get("baseid") or "")
                    key = (srv["platform"], token)
                    if key in seen:
                        continue
                    seen[key] = 1
                    name = g.get("name", "")
                    if isinstance(name, list):
                        name = name[0] if name else ""
                    rows.append({
                        "page_type": info["gtype"],
                        "platform": srv["platform"],
                        "category": info["gtype"],
                        "title": _unescape(str(name)).strip(),
                        "quantity": g.get("sendnum", ""),
                        "unit": "",
                        "unit_price": g.get("unitprice", g.get("price", "")),
                        "total_price": g.get("price", ""),
                        "sales": "",
                        "goods_no": token,
                        "image": g.get("img", ""),
                        "updated": "",
                        "source_url": info["url"],
                    })
                frac_srv = done_srv / len(servers) + (len(seen) / max(total, 1)) / len(servers)
                self._progress(frac_srv, f"{base} {len(seen)}/{total}")
                if total and len(seen) >= total:
                    break
                if len(items) < 1:
                    break
                page_no += 1
                time.sleep(self.delay)
            done_srv += 1
            self._progress(done_srv / len(servers), f"{base} 完成 {len(seen)} 条")
        return rows
