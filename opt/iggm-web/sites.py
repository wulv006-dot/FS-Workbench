# -*- coding: utf-8 -*-
"""
站点路由：按 URL 域名分发到对应抓取器
====================================
三个竞品站统一接口：
  detect_site(url) -> "iggm" | "aoeah" | "u4gm"
  discover(url, log) -> {"site", "game", "categories": [...]}
  scrape(url, log, progress, cancel) -> rows
"""
from url_guard import parsed_destination
from core import IGGMCrawler
from core_aoeah import AoeahCrawler
from core_u4gm import U4gmCrawler

SITES = {
    "iggm": {"name": "IGGM", "hosts": ("iggm.com",)},
    "aoeah": {"name": "AOEAH", "hosts": ("aoeah.com",)},
    "u4gm": {"name": "U4GM", "hosts": ("u4gm.com",)},
}


def detect_site(url):
    _, host, _ = parsed_destination(url)
    for key, s in SITES.items():
        if any(host == h or host.endswith("." + h) for h in s["hosts"]):
            return key
    return None


def site_name(key):
    return SITES.get(key, {}).get("name", key or "未知站点")


def discover(url, log=lambda m: None):
    site = detect_site(url)
    if site == "iggm":
        c = IGGMCrawler(log=log)
        parts = url.rstrip("/").split("/")
        if len(parts) >= 5:
            cats = [url.rstrip("/")]
        else:
            cats = c.discover_game(url)
        return {"site": site, "game": "", "categories": cats}
    if site == "aoeah":
        d = AoeahCrawler(log=log).discover(url)
        return {"site": site, "game": d["game"], "categories": d["categories"]}
    if site == "u4gm":
        d = U4gmCrawler(log=log).discover(url)
        return {"site": site, "game": d["game"], "categories": d["categories"]}
    raise ValueError("不支持的站点，仅支持 iggm.com / aoeah.com / u4gm.com")


def scrape(url, log=lambda m: None, progress=None, cancel=None, delay=0.8):
    site = detect_site(url)
    if site == "iggm":
        c = IGGMCrawler(log=log, delay=delay, progress=progress, cancel=cancel)
        return c.scrape_url(url)[1]
    if site == "aoeah":
        c = AoeahCrawler(log=log, delay=delay, progress=progress, cancel=cancel)
        return c.scrape_url(url)[1]
    if site == "u4gm":
        c = U4gmCrawler(log=log, delay=delay, progress=progress, cancel=cancel)
        return c.scrape_url(url)[1]
    raise ValueError("不支持的站点: " + url)
