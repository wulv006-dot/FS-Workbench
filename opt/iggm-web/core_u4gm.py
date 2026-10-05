# -*- coding: utf-8 -*-
"""
U4GM 抓取核心（www.u4gm.com）
============================
实测结论（2026-09-05），四种页面形态，自动识别：
1. listing 列表页（/items /accounts 等）：
   - 商品名 <p class="... js-item-name" title="...">、id 隐藏域 name="id" value
   - 分类路径 name="cart_name" value="大分类 / 小分类 / 商品名"
   - 价格 <span class="js-unit-price-{id}">$ 7.99</span>
   - 分页 ?category_id=N&page=M（pagination 里最后一页数字为总页数）
2. 金币配置页（/coins /gold 等）：
   - name="id" 隐藏域带 data-unit-price / data-qty-min / data-qty-max / data-qty-per / data-level(JSON)
   - 档位按钮 data-qty；平台单选 name="server_code"（pc/ps/xbox），换平台用 ?server_code=xx
   - 价格 = unit_price * qty * (1 - 该档折扣/100)，与前端 qtySetCalc 公式一致（离线复算）
3. boosting 索引页（/boost /boosting）：卡片列表（分页），每卡一个子页链接，无价格
4. boosting 子页：h1 商品名 + .js-pl-amount[data-amount] 基准价
纯 urllib 可抓，无需浏览器。
"""
import http.cookiejar
import json
import re
import time
import urllib.parse
import urllib.request
from url_guard import safe_opener, parsed_destination
from html import unescape as _unescape

BASE = "https://www.u4gm.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

NOISE = ("blog", "tag-", "guide", "news")


class U4gmCrawler:
    def __init__(self, log=print, delay=0.8, progress=None, cancel=None):
        self.log = log
        self.delay = delay
        self.progress = progress
        self.cancel = cancel
        self.cj = http.cookiejar.CookieJar()
        self.op = safe_opener(self.cj)
        self.op.addheaders = [("User-Agent", UA)]

    # ---------- 基础请求 ----------
    def get(self, url, tries=4):
        parsed_destination(url)
        last = None
        for i in range(tries):
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": UA, "Accept": "text/html",
                    "Referer": BASE + "/"})
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

    # ---------- 页面形态识别 ----------
    @staticmethod
    def page_kind(url, html):
        path = urllib.parse.urlparse(url).path.rstrip("/")
        depth = len([p for p in path.split("/") if p])
        if "js-item-name" in html:
            return "listing"
        if 'data-unit-price="' in html:
            return "gold"
        if "js-pl-amount" in html:
            return "boost_sub"
        if depth <= 1:
            return "landing"
        return "boost_index"

    _SMALL = {"of", "the", "and", "for", "a", "an", "to", "in", "on", "with"}

    def game_name(self, html, slug=""):
        # U4GM 的 slug 规整（/arc-raiders /diablo-4），直接美化 slug 最可靠，
        # 标题里常带站点品牌与品类词（"Buy ARC Raiders Coins Cheap ... | U4GM"）
        s = re.sub(r"[-_]+", " ", slug or "").strip()
        if s:
            out = []
            for i, w in enumerate(s.split()):
                if w.isupper() or any(c.isdigit() for c in w):
                    out.append(w)
                elif i > 0 and w.lower() in self._SMALL:
                    out.append(w.lower())
                else:
                    out.append(w[:1].upper() + w[1:])
            return " ".join(out)[:60]
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        t = re.sub(r"<[^>]+>", " ", m.group(1)) if m else ""
        t = re.sub(r"\|\s*U4GM\s*$", "", t, flags=re.I)
        t = re.sub(r"^U4GM[:\s]*", "", t, flags=re.I).strip()
        return t[:60]

    # ---------- 品类发现 ----------
    def discover(self, url):
        """游戏主页 → 全部品类页；品类页 → 单品类"""
        html = self.get(url)
        kind = self.page_kind(url, html)
        path = urllib.parse.urlparse(url).path.rstrip("/")
        slug = path.split("/")[1] if len(path.split("/")) > 1 else ""
        if kind != "landing":
            return {"game": self.game_name(html, slug),
                    "categories": [url.rstrip("/")]}
        links = set()
        for m in re.finditer(
                r'href="(https://www\.u4gm\.com/' + re.escape(slug) + r'/([^"?#]+))"', html):
            full, sub = m.group(1), m.group(2).strip("/")
            if sub and sub.count("/") == 0 and not any(n in sub for n in NOISE):
                links.add(full)
        return {"game": self.game_name(html, slug),
                "categories": sorted(links)}

    # ---------- listing 列表页 ----------
    def _parse_listing_page(self, html):
        """解析一页商品，返回 [{title, price, cart, goods_id, img}]"""
        items = []
        # 每个商品块以 js-item-name 的 <p> 为锚点，向前后取窗口
        for m in re.finditer(
                r'<p[^>]*class="[^"]*js-item-name[^"]*"[^>]*title="([^"]*)"[^>]*>([^<]*)</p>',
                html):
            title = _unescape(m.group(1).strip() or m.group(2).strip())
            seg = html[m.end():m.end() + 1200]
            gid = re.search(r'name="id" value="(\d+)"', seg)
            cart = re.search(r'name="cart_name" value="([^"]*)"', seg)
            gid = gid.group(1) if gid else ""
            price = ""
            if gid:
                pm = re.search(
                    r'class="js-unit-price-' + re.escape(gid) + r'">\s*\$?\s*([\d,]+(?:\.\d+)?)',
                    seg)
                if pm:
                    price = pm.group(1).replace(",", "")
            if not price:
                pm = re.search(r'\$\s*([\d,]+(?:\.\d+)?)', seg)
                if pm:
                    price = pm.group(1).replace(",", "")
            back = html[max(0, m.start() - 1500):m.start()]
            img = ""
            im = list(re.finditer(r'<img[^>]*src="(https://image\.u4gm\.com/[^"]+)"', back))
            if im:
                img = im[-1].group(1)
            items.append({"title": title, "price": price,
                          "cart": cart.group(1) if cart else "",
                          "goods_id": gid, "img": img})
        return items

    def _page_urls(self, url, html):
        """从分页栏提取全部页 URL（href 里 & 被转义成 &amp;，先还原）。
        返回有序去重的 URL 列表；无分页则只有当前页。"""
        h = html.replace("&amp;", "&")
        tpl = None
        m = re.search(r'href="([^"]*[?&]page=2[^"]*)"', h)
        if m:
            tpl = m.group(1)
        nums = [int(n) for n in re.findall(r'[?&]page=(\d+)', h)]
        last = max(nums) if nums else 1
        if tpl:
            base_url = re.sub(r'page=\d+', 'page={}', tpl)
            return [base_url.format(p) for p in range(1, last + 1)]
        sep = "&" if "?" in url else "?"
        return [f"{url}{sep}page={p}" for p in range(1, last + 1)]

    def _last_page(self, html):
        nums = [int(n) for n in re.findall(r'[?&]page=(\d+)', html.replace("&amp;", "&"))]
        return max(nums) if nums else 1

    def _scrape_listing(self, url, html):
        rows = []
        urls = self._page_urls(url, html)
        last = len(urls)
        seen = {}
        for page_no, page_url in enumerate(urls, 1):
            if self._cancelled():
                self.log(f"  已中止，已抓 {len(seen)}")
                break
            if page_no == 1:
                page_html = html
            else:
                page_html = self.get(page_url)
                time.sleep(self.delay)
            items = self._parse_listing_page(page_html)
            if not items:
                break
            for it in items:
                key = it["goods_id"] or (it["title"], it["price"])
                if key in seen:
                    continue
                seen[key] = 1
                cart = it["cart"]
                cat = cart.split(" / ")[0] if cart else ""
                rows.append({
                    "page_type": "items",
                    "platform": "",
                    "category": cat,
                    "title": it["title"],
                    "quantity": 1,
                    "unit": "",
                    "unit_price": it["price"],
                    "total_price": it["price"],
                    "sales": "",
                    "goods_no": it["goods_id"],
                    "image": it["img"],
                    "updated": "",
                    "source_url": url,
                })
            self._progress(page_no / last, f"items 第 {page_no}/{last} 页 · {len(seen)} 条")
        return rows

    # ---------- 金币配置页 ----------
    def _tier_rows(self, url, html, platform):
        """按前端 qtySetCalc 公式离线复算所有档位"""
        m = re.search(r'<input[^>]*name="id"[^>]*>', html)
        if not m:
            return []
        tag = m.group(0)
        gid = re.search(r'value="(\d+)"', tag)
        up = re.search(r'data-unit-price="([\d.]+)"', tag)
        lv = re.search(r'data-level="(.+?)"\s*(?:data-|/>|>)', tag)
        if not up:
            return []
        unit_price = float(up.group(1))
        levels = {}
        if lv:
            raw = lv.group(1)
            raw = raw.replace("&quot;", '"').strip()
            raw = raw.lstrip("'\"").rstrip("'\"")
            try:
                levels = json.loads(raw)
            except Exception:
                m2 = re.search(r"\{.*\}", raw, re.S)
                if m2:
                    try:
                        levels = json.loads(m2.group(0))
                    except Exception:
                        levels = {}
        unit = re.search(r'date-unit="([^"]+)"', html)
        unit = unit.group(1) if unit else ""
        # 档位按钮
        tiers = re.findall(r'data-qty="(\d+)"[^>]*>\s*([\d,]+\s*[KkMmBb]?)', html)
        if not tiers:
            tiers = [(k, k + " " + unit) for k in sorted(
                levels.keys(), key=lambda x: int(x))] if levels else []
        # 商品名
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
        title = _unescape(re.sub(r"<[^>]+>", "", h1.group(1))).strip() if h1 else ""
        title = re.sub(r"^U4GM\s*", "", title, flags=re.I).strip()

        rows = []
        for qty_s, label in tiers:
            qty = int(qty_s)
            discount = 0.0
            cur = 0
            for k, v in levels.items():
                try:
                    ki = int(k)
                except Exception:
                    continue
                if qty >= ki and ki >= cur:
                    cur = ki
                    if v.get("type") == "discount" and v.get("feature") == "percent":
                        discount = float(v.get("value", 0)) / 100.0
            amount = unit_price * qty * (1 - discount)
            amount = int(amount * 100) / 100.0
            rows.append({
                "page_type": "golds",
                "platform": platform,
                "category": label or f"{qty}{unit}",
                "title": title,
                "quantity": qty,
                "unit": unit,
                "unit_price": round(unit_price * (1 - discount), 6),
                "total_price": round(amount, 2),
                "sales": "",
                "goods_no": gid.group(1) if gid else "",
                "image": "",
                "updated": "",
                "source_url": url,
            })
        return rows

    def _scrape_gold(self, url, html):
        rows = []
        # 平台单选：server_code radios（name 与 value 可能换行分隔，用宽松匹配）
        servers = re.findall(r'name="server_code"[^>]*value="(\w+)"', html)
        servers = list(dict.fromkeys(servers)) or [""]
        for i, srv in enumerate(servers):
            if self._cancelled():
                self._progress(i / len(servers), "已中止")
                break
            if srv and i > 0:
                html2 = self.get(url + ("&" if "?" in url else "?")
                                 + f"server_code={srv}")
                time.sleep(self.delay)
            else:
                html2 = html
            part = self._tier_rows(url, html2, srv.upper() if srv else "")
            rows.extend(part)
            self._progress((i + 1) / len(servers),
                           f"golds · {srv.upper() or '默认'} {len(part)} 个档位")
        return rows

    # ---------- boosting ----------
    def _boost_card_links(self, html, base_url):
        """从 .js-product-list 容器里提取卡片链接。
        注意子页路径不统一：/diablo-4/boosting/xxx 与顶层 /d4-renown-boosting-season-1 都有，
        只能按容器提取，不能按 URL 前缀猜。"""
        i = html.find("js-product-list")
        if i < 0:
            return []
        seg = html[i:]
        j = seg.find('class="pagination"')
        if j > 0:
            seg = seg[:j]
        links = []
        for m in re.finditer(r'<a\s+href="(https://www\.u4gm\.com/[^"]+)"', seg):
            u = m.group(1)
            if any(n in u for n in ("/tag-", "/blog", "page=")):
                continue
            if u.rstrip("/") == base_url.rstrip("/"):
                continue
            links.append(u)
        return sorted(set(links))

    def _scrape_boost_index(self, url, html):
        rows = []
        links = self._boost_card_links(html, url)
        # 索引页本身也可能分页，把各分页的卡片链接都收进来
        for purl in self._page_urls(url, html)[1:]:
            if self._cancelled():
                break
            h2 = self.get(purl)
            links = sorted(set(links) | set(self._boost_card_links(h2, url)))
            time.sleep(self.delay)
        self.log(f"  boosting 子页 {len(links)} 个")
        total = max(len(links), 1)
        for i, link in enumerate(links, 1):
            if self._cancelled():
                self._progress(i / total, "已中止")
                break
            try:
                h3 = self.get(link)
                kind = self.page_kind(link, h3)
                if kind == "gold":
                    part = self._scrape_gold(link, h3)
                elif kind == "listing":
                    part = self._scrape_listing(link, h3)
                else:
                    part = self._scrape_boost_sub(link, h3)
                for r in part:
                    r["category"] = "boosting"
                    r["page_type"] = "boosting"
                rows.extend(part)
                self._progress(i / total,
                               f"boosting ({i}/{total}) {(part[0]['title'] if part else link)[:30]}")
            except Exception as e:
                self.log(f"  ({i}/{total}) {link} 失败: {e}")
            time.sleep(self.delay)
        return rows

    def _scrape_boost_sub(self, url, html):
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
        title = _unescape(re.sub(r"<[^>]+>", "", h1.group(1))).strip() if h1 else ""
        am = re.search(r'data-amount="([\d.]+)"', html)
        amount = am.group(1) if am else ""
        self._progress(1.0, f"{title} ${amount}")
        return [{
            "page_type": "boosting", "platform": "", "category": "boosting",
            "title": title, "quantity": 1, "unit": "",
            "unit_price": amount, "total_price": amount,
            "sales": "", "goods_no": "", "image": "", "updated": "",
            "source_url": url,
        }]

    # ---------- 入口 ----------
    def scrape_url(self, url):
        url = url.rstrip("/")
        html = self.get(url)
        kind = self.page_kind(url, html)
        self.log(f"U4GM 页面形态: {kind}")
        if kind == "listing":
            return {"kind": kind, "url": url}, self._scrape_listing(url, html)
        if kind == "gold":
            return {"kind": kind, "url": url}, self._scrape_gold(url, html)
        if kind == "boost_index":
            return {"kind": kind, "url": url}, self._scrape_boost_index(url, html)
        if kind == "boost_sub":
            return {"kind": kind, "url": url}, self._scrape_boost_sub(url, html)
        # landing 页被直接提交：展开为多个品类？交给调用方先 discover
        raise ValueError(f"游戏主页不能直接抓取，请先解析品类: {url}")
