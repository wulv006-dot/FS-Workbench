# -*- coding: utf-8 -*-
"""
IGGM 全站全品类价格抓取核心模块
================================
原理（2026-09-03 实测逆向）：
- IGGM 所有品类页价格均由 JS 异步加载，统一走 GET /goods/goods_ajax
- 页面内联变量: template_name（items/golds/eav_boosting）、goods_game_sku
- server_id: .server.device-server 下每个 ul 的 hidden input[data-id]，
  ul 顺序与 .device.device-server 的平台 li（PC/PS/Xbox）一一对应
- items 模板: data.goods 分页列表（cate 选 "All" 一次拿全）
- golds 模板: data.result_goods 直接返回全部档位（num/all/price/unit），无需点击
- eav_boosting 模板: 价格前端计算，配置在页面 #goodsJson 隐藏域（HTML 转义 JSON），
  price_start_at.USD 为起始价；/boosting 索引页是子页链接 hub，需逐个子页解析
"""
import html as html_lib
import http.cookiejar
import json
import re
import time
import urllib.parse
import urllib.request

BASE = "https://www.iggm.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 品类链接里常见的非商品路径，发现品类时要排除
NOISE_PATHS = ("news", "sell-to-us", "affiliate", "login", "register")


class IGGMCrawler:
    def __init__(self, log=print, delay=0.8, progress=None, cancel=None):
        """
        progress: 可选回调 progress(frac: float 0~1, label: str)，在子任务内报告进度
        cancel:   可选回调 cancel() -> bool，返回 True 时中止抓取
        """
        self.log = log
        self.delay = delay
        self.progress = progress
        self.cancel = cancel
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj))
        self.opener.addheaders = [("User-Agent", UA)]

    # ---------- 基础请求 ----------
    def get(self, url, referer=None, ajax=False):
        headers = {}
        if referer:
            headers["Referer"] = referer
        if ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"
        req = urllib.request.Request(url, headers=headers)
        last_err = None
        for attempt in range(3):
            try:
                with self.opener.open(req, timeout=30) as r:
                    return r.read().decode("utf-8", errors="replace")
            except Exception as e:
                last_err = e
                time.sleep(2 * (attempt + 1))
        raise last_err

    def get_json(self, url, referer=None):
        return json.loads(self.get(url, referer=referer, ajax=True))

    # ---------- 进度 / 取消 ----------
    def _progress(self, frac, label=""):
        """向 UI 报告当前子任务进度（0~1），任何异常都不影响抓取"""
        if not self.progress:
            return
        try:
            self.progress(max(0.0, min(1.0, float(frac))), label)
        except Exception:
            pass

    def _cancelled(self):
        if not self.cancel:
            return False
        try:
            return bool(self.cancel())
        except Exception:
            return False

    # ---------- 品类发现 ----------
    def discover_game(self, game_url):
        """从游戏主页发现全部品类页 URL，如 /arc-raiders/items|coins|boosting|carry-run"""
        game_url = game_url.rstrip("/")
        m = re.match(r"(https?://[^/]+)/([^/?#]+)", game_url)
        if not m:
            raise ValueError("无法识别的游戏 URL: " + game_url)
        slug = m.group(2)
        page = self.get(game_url)
        links = set()
        for sub in re.findall(r'href="https?://[^/]+/' + re.escape(slug) + r'/([^"?#]+)"', page):
            sub = sub.strip("/")
            # 只保留一级品类（/slug/xxx），跳过更深层级与噪音
            if sub and sub.count("/") == 0 and not any(n in sub for n in NOISE_PATHS):
                links.add(sub)
        return [f"{BASE}/{slug}/{sub}" for sub in sorted(links)]

    # ---------- 页面参数解析 ----------
    def parse_product_page(self, url):
        """抓取品类页，解析模板/平台/服务器/分类等参数"""
        page = self.get(url)
        info = {"url": url, "template": None, "game_sku": None,
                "servers": [], "cates": [], "boost_links": []}

        m = re.search(r"template_name\s*=\s*'([^']+)'", page)
        s = re.search(r"goods_game_sku\s*=\s*'([^']+)'", page)
        if s:
            info["game_sku"] = s.group(1)
        if m:
            info["template"] = m.group(1)

        # 平台列表（PC/PS/Xbox），顺序与 server ul 对应
        platforms = re.findall(
            r'<li data-device_id=\d+ class="[^"]*">\s*<i[^>]*></i>\s*<span>([^<]+)</span>',
            page)
        # 每个 server ul 里的 hidden input data-id
        server_ids = re.findall(
            r'<ul[^>]*>\s*<input data-id=(\d+) type="hidden"', page)
        servers = []
        for i, sid in enumerate(server_ids):
            name = platforms[i] if i < len(platforms) else ""
            servers.append({"platform": name, "server_id": sid})
        info["servers"] = servers

        # 父级分类（items 模板用），优先选 All
        cates = re.findall(
            r'<li data-cate-id=(\d+)>\s*<input[^>]*>\s*<label></label>\s*<p>([^<]*)</p>',
            page)
        info["cates"] = [{"id": cid, "name": name} for cid, name in cates]

        # boosting 索引页：无 template，收集子页链接
        if not info["template"]:
            base = url.rstrip("/")
            subs = set()
            for sub in re.findall(r'href="' + re.escape(base) + r'/([^"?#]+)"', page):
                sub = sub.strip("/")
                if sub and sub.count("/") == 0 and not any(n in sub for n in NOISE_PATHS):
                    subs.add(base + "/" + sub)
            info["boost_links"] = sorted(subs)
            if subs:
                info["template"] = "boosting_index"

        return info

    # ---------- goods_ajax ----------
    def goods_ajax(self, info, template, server_id, cate_id, page=1):
        qs = urllib.parse.urlencode({
            "template_type": template,
            "server_id": server_id,
            "cate_id": cate_id,
            "game_sku": info["game_sku"],
            "sort": 0, "goods_name": "", "tag": "", "page": page,
        })
        return self.get_json(BASE + "/goods/goods_ajax?" + qs,
                             referer=info["url"])

    # ---------- items 模板 ----------
    def scrape_items(self, info):
        """items 模板：遍历 平台×服务器，cate 优先 All；展开为统一行"""
        rows = []
        cates = info["cates"]
        all_cate = next((c for c in cates if c["name"].lower() == "all"), None)
        cate_list = [all_cate] if all_cate else (cates or [{"id": 0, "name": ""}])
        servers = info["servers"] or [{"platform": "", "server_id": ""}]
        units = max(1, len(servers) * len(cate_list))
        done_units = 0.0

        for srv in servers:
            for cate in cate_list:
                if self._cancelled():
                    self._progress(done_units / units, "已中止")
                    return rows
                seen, page_no, total = {}, 1, None
                base = f"items · {srv['platform'] or '默认'} · {cate['name'] or 'All'}"
                while True:
                    # 每一页都检查一次取消：items 常只有 1 个平台×1 个分类，
                    # 若只在单元边界检查，长列表点了停止也会跑完全部才停
                    if self._cancelled():
                        self.log(f"  [{srv['platform'] or '默认'}] 已中止，"
                                 f"已抓 {len(seen)}/{total}")
                        break
                    data = self.goods_ajax(info, "items", srv["server_id"],
                                           cate["id"], page_no)
                    d = data.get("data", {})
                    if total is None:
                        total = d.get("count", 0)
                        self.log(f"  [{srv['platform'] or '默认'}] 分类 {cate['name']}: "
                                 f"共 {total} 条")
                    goods = d.get("goods", [])
                    if not goods:
                        break
                    for g in goods:
                        key = (srv["server_id"], g.get("goods_no"))
                        if key in seen:
                            continue
                        seen[key] = 1
                        rows.append({
                            "page_type": "items",
                            "platform": srv["platform"],
                            "category": cate["name"] if not all_cate else "",
                            "title": g.get("title", ""),
                            "quantity": g.get("min_num", 1),
                            "unit": g.get("unit") or "",
                            "unit_price": g.get("true_price", ""),
                            "total_price": g.get("true_price", ""),
                            "sales": g.get("sales", 0),
                            "goods_no": g.get("goods_no", ""),
                            "image": g.get("images", ""),
                            "updated": g.get("update_time", ""),
                            "source_url": info["url"],
                        })
                    self._progress((done_units + (len(seen) / total if total else 1)) / units,
                                   f"{base}  {len(seen)}/{total}")
                    if len(seen) >= total:
                        break
                    page_no += 1
                    time.sleep(self.delay)
                done_units += 1
                self._progress(done_units / units, f"{base}  完成 {len(seen)} 条")
        return rows

    # ---------- golds 模板 ----------
    def scrape_golds(self, info):
        """golds 模板：result_goods 每元素即一个档位，全部展开"""
        rows = []
        servers = info["servers"] or [{"platform": "", "server_id": ""}]
        units = max(1, len(servers))
        for i, srv in enumerate(servers):
            if self._cancelled():
                self._progress(i / units, "已中止")
                return rows
            label = f"coins · {srv['platform'] or '默认'}"
            self._progress(i / units, label)
            data = self.goods_ajax(info, "golds", srv["server_id"], 0)
            d = data.get("data", {})
            goods = d.get("result_goods", [])
            self.log(f"  [{srv['platform'] or '默认'}] {len(goods)} 个档位")
            for g in goods:
                rows.append({
                    "page_type": "coins",
                    "platform": srv["platform"] or g.get("type", ""),
                    "category": g.get("min_title") or g.get("sku", ""),
                    "title": g.get("title", ""),
                    "quantity": g.get("num", ""),
                    "unit": g.get("unit") or "",
                    "unit_price": g.get("price", ""),
                    "total_price": g.get("all", ""),
                    "sales": g.get("sales", 0),
                    "goods_no": g.get("goods_no", ""),
                    "image": g.get("images", ""),
                    "updated": g.get("update_time", ""),
                    "source_url": info["url"],
                })
            self._progress((i + 1) / units, f"{label}  {len(goods)} 个档位")
            time.sleep(self.delay)
        return rows

    # ---------- boosting ----------
    def scrape_boosting_index(self, info):
        """boosting 索引页：逐个子页解析 goodsJson 起始价"""
        rows = []
        links = info["boost_links"]
        self.log(f"  发现 {len(links)} 个 boosting 子页")
        for i, link in enumerate(links, 1):
            if self._cancelled():
                self._progress((i - 1) / max(1, len(links)), "已中止")
                return rows
            self._progress((i - 1) / max(1, len(links)),
                           f"boosting ({i}/{len(links)}) {link.rsplit('/', 1)[-1]}")
            try:
                row = self.scrape_boosting_page(link)
                if row:
                    rows.append(row)
                    self.log(f"  ({i}/{len(links)}) {row['title']} -> "
                             f"${row['total_price']}")
                else:
                    self.log(f"  ({i}/{len(links)}) {link} 无 goodsJson，跳过")
            except Exception as e:
                self.log(f"  ({i}/{len(links)}) {link} 失败: {e}")
            self._progress(i / max(1, len(links)),
                           f"boosting ({i}/{len(links)}) 完成")
            time.sleep(self.delay)
        return rows

    def scrape_boosting_page(self, url):
        """单个 eav_boosting 页：解析 #goodsJson 的起始价与基础信息"""
        page = self.get(url)
        m = re.search(r'id="goodsJson" value="(.*?)"', page, re.S)
        if not m:
            return None
        try:
            d = json.loads(html_lib.unescape(m.group(1)))
        except Exception:
            return None
        # 商品名优先取 goodItem 的 data-title（与前端购物车一致），
        # goodsJson 里的 title 是第一个选项组名，不是商品名
        mt = re.search(r'goodItem[^>]*data-title="([^"]+)"', page)
        if mt:
            title = mt.group(1)
        else:
            mh = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
            if mh:
                title = re.sub(r"<[^>]+>", "", mh.group(1)).strip()
            else:
                title = d.get("title", {})
                title = title.get("en", "") if isinstance(title, dict) else str(title)
        psa = d.get("price_start_at") or {}
        start_usd = psa.get("USD", "")
        try:
            start_usd = round(float(start_usd), 2)
        except (TypeError, ValueError):
            pass
        opts = d.get("options") or []
        opt_names = []
        for o in opts:
            t = o.get("title", {})
            opt_names.append(t.get("en", "") if isinstance(t, dict) else str(t))
        return {
            "page_type": "boosting",
            "platform": "",
            "category": " / ".join([n for n in opt_names if n])[:120],
            "title": title,
            "quantity": "",
            "unit": "",
            "unit_price": "",
            "total_price": start_usd,  # 起始价（from $X）
            "sales": "",
            "goods_no": str(d.get("goods_no", "")),
            "image": "",
            "updated": "",
            "source_url": url,
        }

    # ---------- 统一入口 ----------
    def scrape_url(self, url):
        """抓取单个品类页 URL，自动识别模板。返回 (info, rows)"""
        self._progress(0.0, "解析页面 " + url.rstrip("/").rsplit("/", 1)[-1])
        info = self.parse_product_page(url)
        tpl = info["template"]
        self.log(f"页面模板: {tpl or '未知'} | 平台: "
                 f"{[s['platform'] for s in info['servers']] or ['默认']}")
        if tpl == "items":
            return info, self.scrape_items(info)
        if tpl == "golds":
            return info, self.scrape_golds(info)
        if tpl == "boosting_index":
            return info, self.scrape_boosting_index(info)
        if tpl == "eav_boosting":
            row = self.scrape_boosting_page(url)
            self._progress(1.0, "完成")
            return info, [row] if row else []
        self.log(f"未支持的模板 {tpl}，跳过 {url}")
        self._progress(1.0, "未支持，已跳过")
        return info, []
