"""Official Forever news and r/wowforever top-day picks, at most two posts/day.

Uses public Blizzard HTML and Reddit Atom. No login, paid service or browser.
Quota reservations are saved BEFORE sending; ambiguous sends are not replayed.
"""
import asyncio
import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import json
import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import discord
from discord.ext import tasks

from .base import Module

log = logging.getLogger("wf.news")
CST = dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")
OFFICIAL = "https://news.blizzard.com/en-us/feed/world-of-warcraft"
REDDIT = "https://www.reddit.com/r/wowforever/top/.rss?t=day&limit=20"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
MAX_BYTES = 6 * 1024 * 1024


def clean(value, limit=320):
    value = html.unescape(html.unescape(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else value[:limit - 1].rstrip() + "…"


def epoch(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def get_text(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": "Blingtron9000/1.0 (WOW FOREVER Discord news reader)",
        "Accept": "text/html, application/atom+xml, application/xml"})
    with urllib.request.urlopen(request, timeout=25) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("News response exceeds size limit")
    return body.decode("utf-8", "replace")


class BlizzardLinks(HTMLParser):
    """Read actual article cards, ignoring scripts/styles inside shadow templates."""
    def __init__(self):
        super().__init__()
        self.links, self.link, self.bits, self.skip = [], None, [], 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        if tag == "a":
            self.link = attrs.get("href")
            self.bits = []

    def handle_data(self, value):
        if self.link and not self.skip:
            self.bits.append(value)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        if tag == "a" and self.link:
            url = urllib.parse.urljoin(OFFICIAL, self.link)
            text = clean(" ".join(self.bits), 2000)
            parsed = urllib.parse.urlparse(url)
            if (parsed.hostname == "news.blizzard.com" and
                    parsed.path.startswith("/en-us/article/") and
                    "forever" in text.lower()):
                self.links.append(url)
            self.link = None


class ArticleMeta(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.jsonld, self.inside = {}, [], False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            self.meta[attrs.get("property") or attrs.get("name")] = attrs.get("content", "")
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.inside = True

    def handle_data(self, value):
        if self.inside:
            self.jsonld.append(value)

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False


def official_items(page, fetch=get_text):
    links = BlizzardLinks()
    links.feed(page)
    if not links.links:
        raise ValueError("No Forever article cards found in Blizzard response")
    items = []
    errors = []
    # Featured cards are followed by recent cards. Inspect a bounded relevant set.
    for url in list(dict.fromkeys(links.links))[:8]:
        try:
            article = ArticleMeta()
            article.feed(fetch(url))
            metadata = [json.loads(value) for value in article.jsonld]
            dates = [obj.get("dateModified") or obj.get("datePublished")
                     for obj in metadata if isinstance(obj, dict)]
            date = next(value for value in dates if value)
            title = article.meta.get("og:image:alt") or article.meta.get("og:title", "").split(" — ")[0]
            summary = article.meta.get("og:description") or article.meta.get("description")
            if not title or "forever" not in (title + " " + (summary or "")).lower():
                continue
            version = hashlib.sha256((title + (summary or "") + date).encode()).hexdigest()[:12]
            aid = re.search(r"/article/(\d+)/", url).group(1)
            items.append({"key": "blizzard:%s:%s" % (aid, version), "source": "official",
                          "title": clean(title, 240), "summary": clean(summary),
                          "url": url, "epoch": epoch(date), "image": article.meta.get("og:image")})
        except Exception as exc:
            errors.append("%s: %s" % (url, type(exc).__name__))
    if not items:
        raise ValueError("No readable Blizzard article metadata: " + "; ".join(errors))
    # Never fill the channel with an old backlog: only the most recent announcement.
    return sorted(items, key=lambda item: item["epoch"], reverse=True)[:1]


def reddit_items(feed):
    root = ET.fromstring(feed)
    if root.tag != "{http://www.w3.org/2005/Atom}feed":
        raise ValueError("Reddit did not return an Atom feed")
    items = []
    for entry in root.findall("a:entry", ATOM):
        title = clean(entry.findtext("a:title", default="", namespaces=ATOM), 240)
        if re.search(r"nsfw|spoiler|megathread|recruitment", title, re.I):
            continue
        link = entry.find("a:link", ATOM)
        url = link.get("href", "") if link is not None else ""
        parsed = urllib.parse.urlparse(url)
        if (parsed.scheme != "https" or parsed.hostname != "www.reddit.com" or
                not parsed.path.lower().startswith("/r/wowforever/comments/")):
            continue
        body = entry.findtext("a:content", default="", namespaces=ATOM)
        paragraphs = re.findall(r"<p>(.*?)</p>", body, re.S)
        excerpt = clean(paragraphs[0]) if paragraphs else "A popular community post from today's top threads."
        published = entry.findtext("a:published", namespaces=ATOM) or entry.findtext("a:updated", namespaces=ATOM)
        items.append({"key": entry.findtext("a:id", namespaces=ATOM), "source": "reddit",
                      "title": title, "summary": excerpt, "url": url,
                      "epoch": epoch(published), "image": None})
    # RSS is already ordered by Reddit's top/day ranking. Preserve that order.
    return items


def fetch_candidates():
    found = {}
    for source, url, parse in (("official", OFFICIAL, official_items), ("reddit", REDDIT, reddit_items)):
        try:
            found[source] = parse(get_text(url))
        except Exception:
            log.exception("News source unavailable: %s", source)
            found[source] = []
    return found


def make_embed(item):
    official = item["source"] == "official"
    embed = discord.Embed(title=item["title"], url=item["url"],
                          description=discord.utils.escape_markdown(item["summary"]),
                          colour=0xC69B3F if official else 0xFF6B35,
                          timestamp=dt.datetime.fromtimestamp(item["epoch"], dt.timezone.utc))
    embed.set_author(name="WOW FOREVER · " + ("OFFICIAL NEWS" if official else "COMMUNITY PICK"))
    image = item.get("image")
    if image and urllib.parse.urlparse(image).hostname == "bnetcmsus-a.akamaihd.net":
        embed.set_image(url=image)
    embed.set_footer(text="Blizzard Entertainment" if official else "r/wowforever · Top today · Community discussion")
    return embed


class NewsModule(Module):
    name = "news"
    priority = 60

    def __init__(self, bot, config, store):
        super().__init__(bot, config, store)
        self._lock = asyncio.Lock()
        self.channels = {self.resolve_feature_channel("channel")}

    async def setup(self):
        if self.enabled and not self.poll.is_running():
            self.poll.start()

    @tasks.loop(minutes=30)
    async def poll(self):
        try:
            await self.run_once()
        except Exception:
            log.exception("News check failed; saved quota reservations retained")

    async def run_once(self, now=None):
        now = now or dt.datetime.now(CST)
        day = now.astimezone(CST).date().isoformat()
        slots = self.feature.get("publish_hours") or [12, 20]
        # Config can reduce the allowance; it can never raise the hard two-post cap.
        limit = min(2, max(0, int(self.feature.get("daily_limit", 2))))
        target = min(limit, sum(now.astimezone(CST).hour >= int(hour) for hour in slots))
        async with self._lock:
            state = self.store.get("news_state") or {"seen": [], "posts": []}
            posts = list(state.get("posts") or [])
            used = [p for p in posts if p["day"] == day]
            if not self.enabled or len(used) >= target:
                return 0
            channel_id = self.resolve_feature_channel("channel")
            channel = self.bot.get_channel(int(channel_id)) if channel_id else None
            if channel is None:
                raise RuntimeError("Configured news channel is unavailable")
            found = await asyncio.to_thread(fetch_candidates)
            sent = 0
            for source in ("official", "reddit"):
                if len(used) >= target or any(p["source"] == source for p in used):
                    continue
                age_limit = (7 * 86400) if source == "official" else (2 * 86400)
                item = next((item for item in found.get(source, [])
                             if item["key"] and item["key"] not in state["seen"]
                             and -900 <= now.timestamp() - item["epoch"] <= age_limit), None)
                if item is None:
                    continue
                record = {"day": day, "key": item["key"], "source": source,
                          "status": "reserved", "url": item["url"]}
                posts.append(record)
                used.append(record)
                state = {"seen": (state["seen"] + [item["key"]])[-1000:], "posts": posts[-120:]}
                self.store.set("news_state", state)
                try:
                    message = await channel.send(embed=make_embed(item), allowed_mentions=discord.AllowedMentions.none())
                except Exception:
                    # A timeout can mean delivery succeeded. Never blindly replay it.
                    log.exception("News send failed/unknown; quota reserved: %s", item["key"])
                    record["status"] = "unknown"
                    self.store.set("news_state", state)
                    continue
                record.update(status="posted", message_id=str(message.id),
                              day=message.created_at.astimezone(CST).date().isoformat())
                self.store.set("news_state", state)
                sent += 1
                log.info("News posted source=%s message=%s quota_day=%s", source, message.id, record["day"])
                # If a send straddled midnight, end this batch; next check counts its actual day.
                if record["day"] != day:
                    break
            return sent
