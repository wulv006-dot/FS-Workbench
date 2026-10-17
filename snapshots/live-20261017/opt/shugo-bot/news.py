# -*- coding: utf-8 -*-
"""AION 2 官方资讯 —— 抓取 + 发帖（供 bot.py 调用；也可单独跑做回填）。

数据源：plaync 全球社区 JSON 接口。**无需登录、无需鉴权**，只要请求头。

    列表  {API}/board/{alias}/article?page=1&size=10      ← 最新在前，单页最多 10 条
    原文  {SITE}/board/{path}/view?articleId={id}
    板块  {API}/board/{alias}                             ← 拿 boardUrlPattern / boardName

⚠️ 两个坑：
  1. 不带 `x-nc-service: aion2_global` 请求头会返回**空壳 JSON**
     （`{"board":null,"contentList":[]}`），看起来像"没数据"，其实是没带头。
  2. 板块别名必须带 `_en` 后缀（`notice_en`），写成 `notice` 同样返回空壳。
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import html as _html
import json
import logging
import os
import re
import urllib.request

import discord

API = "https://api-global-community.plaync.com/aion2_global"
SITE = "https://aion2.plaync.com/en-us/board"
ICON = "https://assets.playnccdn.com/uikit/ncommunity/aion2_global/admin.png"

# alias -> (显示名, 频道内标签, 原文路径, 颜色, emoji)
BOARD_META = {
    "notice_en":     ("Announcements", "ANNOUNCEMENT", "notice",     0x60A5FA, "📢"),
    "update_en":     ("Patch Notes",   "PATCH NOTES",  "update",     0xA855F7, "🛠️"),
    "movie_clip_en": ("Media",         "MEDIA",        "movie_clip", 0xEF4444, "🎬"),
    # EN 站目前没有 event 板块（/board/event/list 会 302 到 404 页）。
    # 一旦官方开通，把 "event_en" 填进 config.json 的 news_boards 即可自动生效。
    "event_en":      ("Events",        "EVENT",        "event",      0xF59E0B, "🎉"),
}
DEFAULT_BOARDS = ["notice_en", "update_en", "movie_clip_en"]

log = logging.getLogger("shugo.news")

_TAG = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------- 文本清洗
def sanitize(s, limit=0):
    """去 HTML 标签 / 反转义实体 / 折叠空白；limit>0 时按句末断句截断。"""
    if not s:
        return ""
    s = _html.unescape(str(s))
    s = _TAG.sub(" ", s)
    s = s.replace("\u00a0", " ").replace("\u200b", "")
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        cut = s[:limit]
        for p in (". ", "! ", "? "):
            i = cut.rfind(p)
            if i > limit * 0.55:
                cut = cut[: i + 1]
                break
        s = cut.rstrip() + "…"
    return s


# ---------------------------------------------------------------- HTTP
def _http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; ShugoBot/1.0; +https://www.aion2kinah.com/)",
        "Accept": "application/json, text/plain, */*",
        "x-nc-service": "aion2_global",
        "Referer": SITE + "/notice/list",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_board(alias, size=10):
    """抓单个板块的最新文章（已按时间倒序）。"""
    meta = BOARD_META.get(alias)
    if not meta:
        raise ValueError("未知板块别名: %r（可选: %s）" % (alias, ", ".join(BOARD_META)))
    label, tag, path, color, emoji = meta
    data = _http_json("%s/board/%s/article?page=1&size=%d" % (API, alias, int(size)))
    out = []
    for it in (data.get("contentList") or []):
        ts = it.get("timestamps") or {}
        epoch = int(ts.get("postedEpoch") or 0)
        aid = it.get("id")
        if not epoch or not aid:
            continue
        thumbs = it.get("thumbnailUrlList") or []
        out.append({
            "id": aid,
            "board": alias,
            "label": label,
            "tag": tag,
            "color": color,
            "emoji": emoji,
            "title": sanitize(it.get("title")) or "(untitled)",
            "summary": sanitize(it.get("summary"), 380),
            "epoch": epoch,
            "url": "%s/%s/view?articleId=%s" % (SITE, path, aid),
            "image": thumbs[0] if thumbs else None,
        })
    return out


def fetch_all(boards, size=10):
    """多板块合并，按发布时间倒序。返回 (items, errors)。"""
    items, errs = [], []
    for a in boards:
        try:
            items += fetch_board(a, size)
        except Exception as e:
            errs.append("%s: %r" % (a, e))
    # 同一篇文章可能同时挂在多个板块，按 id 去重（保留先出现的）
    seen, uniq = set(), []
    for it in sorted(items, key=lambda x: x["epoch"], reverse=True):
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        uniq.append(it)
    return uniq, errs


# ---------------------------------------------------------------- 渲染
def make_embed(item):
    e = discord.Embed(
        color=discord.Color(item["color"]),
        title=item["title"][:250],
        url=item["url"],
        description=item["summary"] or None,
        timestamp=_dt.datetime.fromtimestamp(item["epoch"], _dt.timezone.utc),
    )
    e.set_author(name="AION 2 Official  ·  %s" % item["label"], icon_url=ICON)
    if item.get("image"):
        e.set_image(url=item["image"])
    e.set_footer(text="%s %s  ·  aion2.plaync.com" % (item["emoji"], item["tag"]))
    return e


# ---------------------------------------------------------------- 已读状态
class State:
    """记录已推送过的文章 id，避免重启后重复刷屏。"""

    def __init__(self, path, cap=600):
        self.path = str(path)
        self.cap = cap
        self.initialized = False
        self.ids = []
        try:
            if os.path.exists(self.path):
                d = json.loads(open(self.path, encoding="utf-8").read())
                self.initialized = bool(d.get("initialized"))
                self.ids = [x for x in (d.get("seen") or []) if x]
        except Exception as e:
            log.warning("news state 读取失败，按空状态处理: %r", e)

    def _index(self):
        return set(self.ids)

    def is_new(self, item):
        return item["id"] not in self._index()

    def mark(self, *ids):
        have = self._index()
        for i in ids:
            if i and i not in have:
                self.ids.append(i)
                have.add(i)
        if len(self.ids) > self.cap:
            self.ids = self.ids[-self.cap:]

    def save(self, initialized=None):
        if initialized is not None:
            self.initialized = bool(initialized)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"initialized": self.initialized, "seen": self.ids}, f,
                      ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)


# ---------------------------------------------------------------- 发帖
async def post_item(channel, item):
    await channel.send(embed=make_embed(item))


async def poll_and_post(client, cfg, state, delay=1.2):
    """一轮轮询：把没有推送过的官方帖发到资讯频道。返回本次新增条数。"""
    ch_id = int(cfg.get("news_channel_id") or 0)
    if not ch_id:
        return 0
    ch = client.get_channel(ch_id)
    if ch is None:
        log.warning("news_channel_id=%s 找不到频道（检查 config.json）", ch_id)
        return 0

    boards = cfg.get("news_boards") or DEFAULT_BOARDS
    items, errs = await asyncio.to_thread(fetch_all, boards, 10)
    for e in errs:
        log.warning("资讯抓取失败 %s", e)
    if not items:
        return 0

    # 首次启动（setup 脚本没跑过）→ 静默认领现状，不倒灌历史
    if not state.initialized:
        state.mark(*[i["id"] for i in items])
        state.save(initialized=True)
        log.info("资讯首次初始化：认领 %d 条既有文章，不补发。", len(items))
        return 0

    fresh = [i for i in items if state.is_new(i)]
    fresh.sort(key=lambda x: x["epoch"])          # 旧的先发，频道里时间线才是正的
    sent = 0
    for it in fresh:
        try:
            await post_item(ch, it)
            state.mark(it["id"])
            state.save()
            sent += 1
            log.info("资讯推送 %s | %s", it["id"], it["title"][:70])
        except discord.HTTPException as e:
            log.warning("资讯推送失败 %s: %r", it["id"], e)
        await asyncio.sleep(delay)
    return sent


# ---------------------------------------------------------------- 单独跑：干跑
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    boards = sys.argv[1:] or DEFAULT_BOARDS
    items, errs = fetch_all(boards, 10)
    print("板块:", ", ".join(boards))
    for e in errs:
        print("  !! 抓取失败", e)
    print("共 %d 条：\n" % len(items))
    for it in items:
        d = _dt.datetime.fromtimestamp(it["epoch"], _dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
        print("[%s] %s  %s" % (d, it["tag"].ljust(12), it["title"][:80]))
        print("      ", it["url"])
        if it["summary"]:
            print("      ", it["summary"][:110])
        print()
