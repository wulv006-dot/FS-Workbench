# -*- coding: utf-8 -*-
"""AION 2 Kinah price board — price lookup module for Shugo-bot.

Interaction model
-----------------
One board message in the channel (the only message there, edited in place by the
timer). Clicking its region menu opens **one private panel that holds everything**:

    Board (public, 1 message)
      +-- [Region menu]  ->  private panel:
                                [Region menu]     <- switch region
                                [Faction menu]    <- Elyos / Asmodian
                                [Server menu]     <- switch server (~23 per faction)
                                [< paging >]      <- only if one faction ever passes 25
                                live quote embed  <- unit price + 50/100/200 table

Why three menus, and why the faction menu is what removes paging
---------------------------------------------------------------
Discord caps a select at 25 options and has no grouped selects, so the 106 servers
cannot live in a single menu next to the 5 regions. Splitting the server list by
faction brings the largest list down to 23 (EU Elyos), i.e. under the cap, so no
second page is needed at all -- and it matches how players think ("my server, my
side"). Paging is kept in the code as a guard for a region that ever exceeds 25
servers inside one faction. Three menus plus the quote still fit in one panel:
Discord allows 5 component rows and this uses 3 (4 when a paging row is needed).

The panel edits itself in place on every change, so nothing accumulates.

Push pipeline
-------------
`aion2-watch.timer` (every 30 minutes) finishes -> this module's `--push` runs as
ExecStartPost:

  1. read the live price from the **front-end price API** (not from the DB — this
     guarantees "the price in Discord == the price the player actually pays")
  2. refresh the same message in place (PATCH, never POST a new one) -- the board is a
     signpost plus the region menu, and the region menu's "from $X/M" descriptions are
     what actually change between cycles
  3. the "last updated / next update" stamps live on the **quote card** (description,
     small grey subtext), anchored to the snapshot's own timestamp. Discord relative
     timestamps render in each viewer's own timezone and tick down by themselves.

The board menu carries a persistent View (fixed custom_id = kinah:region) so it
keeps working after the bot restarts.

Self-check:
    python kinah.py --selftest     # offline: validate embed/component build, no requests
    python kinah.py --push         # fetch prices and refresh the board (timer entry point)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import discord

HERE = Path(__file__).resolve().parent
PRICES_FILE = HERE / "kinah_prices.json"
STATE_FILE = HERE / "kinah_state.json"
TOKEN_FILE = HERE / "token.txt"

BASE = "https://www.aion2kinah.com"
PAGE_URL = BASE + "/Aion-2-Kinah.html"
API_URL = BASE + "/ajax/goods"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MMOEXP-KinahBoard/1.0"
BUY_URL = "https://www.aion2kinah.com/Aion-2-Kinah.html"

GID_SITE = "891"
TOP_CID, CID, SITE_ID = "1", "6527", "581"
PAGE_SIZE = 25                    # Discord hard cap on select options
UPDATE_INTERVAL_MIN = 30          # matches aion2-watch.timer
TIER_SHOWCASE = (50, 100, 200)    # only these quantity tiers are shown

REGION_COLOR = {
    "EU": 0x5865F2, "NA West": 0x57F287, "NA East": 0x3BA55D,
    "South America": 0xFEE75C, "Asia": 0xEB459E,
}
DEFAULT_COLOR = 0x99AAB5
REGION_ORDER = ["EU", "NA West", "NA East", "South America", "Asia"]

# The quote card spends its one colour cue (the side bar) on the price instead of the
# region: green = cheap, amber = normal, red = expensive.  The region is spelled out in
# a field right below, so nothing is lost.  First band whose ceiling the price falls
# under wins; a price above every band gets PRICE_HIGH_COLOR.
PRICE_BANDS = (
    (9.0, 0x57F287),      # <= $9.00/M  -> green
    (15.0, 0xFEE75C),     # <= $15.00/M -> amber
)
PRICE_HIGH_COLOR = 0xED4245   # above that -> red


# ============================================================ fetch


def _post_form(url, data, referer=None):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("User-Agent", UA)
    req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    req.add_header("X-Requested-With", "XMLHttpRequest")
    if referer:
        req.add_header("Referer", referer)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "ignore")


def _get(url):
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "ignore")


def parse_regions(html):
    i = html.find('"server":')
    if i < 0:
        raise RuntimeError("price page layout changed: 'server' block not found")
    seg = html[i:i + 300000]
    out = []
    for m in re.finditer(r'"(\d{3,6})":\{"id":\1,"gid":891,"title":"([^"]+)"', seg):
        sid, title = m.group(1), m.group(2)
        if sid in [x[0] for x in out]:
            continue
        blk = re.search(r'"%s":\{.*?"area":\{(.*?)\}\}' % sid, seg, re.S)
        areas = re.findall(
            r'"id":(\d+),"gid":891,"sid":%s,"title":"([^"]+)"' % sid,
            blk.group(1) if blk else "")
        out.append((sid, title, areas))
    return out


def fetch_price(sid, aid):
    """dict = quoted / None = API says no listing / raise = fetch failed (caller must retry)."""
    raw = _post_form(API_URL, {
        "gid": GID_SITE, "sid": sid, "aid": aid,
        "top_cid": TOP_CID, "cid": CID, "site_id": SITE_ID,
    }, referer=PAGE_URL)
    lst = ((json.loads(raw).get("goods") or {}).get("index") or {}).get("list") or []
    if not lst:
        return None
    it = lst[0]
    tiers = {}
    for k, v in (it.get("goods_list") or {}).items():
        try:
            tiers[int(k)] = float(v.get("price") or 0)
        except (TypeError, ValueError):
            continue
    return {
        "aid": aid,
        "name": it.get("game_area_format") or "",
        "unit_price": float(it.get("unit_price") or 0),
        "unit": it.get("unit") or "M",
        "min_qty": int(it.get("min_qty") or 0),
        "tiers": tiers,
    }


def fetch_with_retry(sid, aid, tries=3):
    last = None
    for i in range(tries):
        try:
            return fetch_price(sid, aid), None
        except Exception as e:                            # noqa: BLE001
            last = e
            if i < tries - 1:
                time.sleep(0.8 * (i + 1))
    return None, last


def fetch_all(prev=None):
    """Fetch every server. On failure reuse the previous price and flag it `stale`
    (never render "could not fetch" as "no listing")."""
    prev = prev or {}
    regions = parse_regions(_get(PAGE_URL))
    out = []
    for sid, title, areas in regions:
        servers, missing, failed = [], [], []
        for aid, aname in areas:
            rec, err = fetch_with_retry(sid, aid)
            if rec:
                rec["name"] = rec["name"] or aname
                servers.append(rec)
            elif err is None:
                missing.append(aname)
            else:
                old = prev.get(aid)
                if old:
                    o = dict(old)
                    o["stale"] = True
                    servers.append(o)
                    failed.append(aname)
                else:
                    failed.append(aname)
            time.sleep(0.12)
        out.append({"sid": sid, "region": title, "servers": servers,
                    "missing": missing, "failed": failed})
    return {"fetched_at": int(time.time()), "source": PAGE_URL, "regions": out}


# ============================================================ cache / state


def _read_json(p, default=None):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                     # noqa: BLE001
        return default if default is not None else {}


def _write_json(p, obj):
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def load_prices():
    return _read_json(PRICES_FILE, {"fetched_at": 0, "regions": []})


def load_state():
    return _read_json(STATE_FILE, {})


def find_region(data, sid):
    for r in data.get("regions") or []:
        if str(r["sid"]) == str(sid):
            return r
    return None


def find_server(data, sid, aid):
    r = find_region(data, sid)
    if not r:
        return None, None
    for s in r.get("servers") or []:
        if str(s["aid"]) == str(aid):
            return r, s
    return r, None


def ordered_regions(data):
    raw = data.get("regions") or []
    rank = {n: i for i, n in enumerate(REGION_ORDER)}
    return sorted(raw, key=lambda r: rank.get(r["region"], 99))


def sorted_servers(data, sid):
    r = find_region(data, sid)
    return sorted(r.get("servers") or [], key=lambda s: s["unit_price"]) if r else []


# ============================================================ board building


def region_min(r):
    vals = [s["unit_price"] for s in (r.get("servers") or []) if s.get("unit_price")]
    return min(vals) if vals else 0.0


def board_payload(data):
    """Board message: a short signpost + the region menu that opens the priced panel.

    The board carries **no card**.  Its old summary embed repeated two things that are
    already shown elsewhere: each region's "from $X/M" sits in the menu's option
    descriptions, and the last/next update stamps now sit on the quote card.  So the
    board is text + the menu only -- which is also why the menu option descriptions must
    keep carrying the from-price (asserted in the self-test).

    A freshness warning is appended only when the snapshot is badly overdue, so a dead
    timer is still visible on the public board without adding permanent clutter.
    """
    regs = ordered_regions(data)
    content = ("**AION 2 Kinah · Live Prices**\n"
               "Pick a region below — the price, the server list and the quantity table "
               "open in a private message only you can see. Rates are in **USD per 1M "
               "Kinah** and sync with aion2kinah.com.")
    ts = int(data.get("fetched_at") or 0)
    if ts and ts + UPDATE_INTERVAL_MIN * 60 < time.time() - 10 * 60:
        content += "\n⚠️ These prices are <t:%d:R> old — the next sync has not run yet." % ts
    return {
        "content": content,
        "embeds": [],
        "components": [{
            "type": 1,
            "components": [{
                "type": 3,
                "custom_id": "kinah:region",
                "placeholder": "Choose a region",
                "min_values": 1,
                "max_values": 1,
                "options": [{
                    "label": r["region"],
                    "value": str(r["sid"]),
                    "description": "from $%.3f/M · %d servers"
                                   % (region_min(r), len(r.get("servers") or [])),
                } for r in regs] or [{"label": "-", "value": "0"}],
            }],
        }],
    }


FACTIONS = ("Elyos", "Asmodian")


def split_faction(name):
    """'Siel - Elyos' -> ('Siel', 'Elyos').

    The site uses two spellings: `Siel - Elyos` and `Beritra-Asmodian` (no spaces around
    the hyphen, 4 Asia entries), so the separator has to be optional.  Anything without a
    known faction suffix comes back as (name, None).
    """
    m = re.match(r"^(.*?)\s*-\s*(Elyos|Asmodian)$", (name or "").strip())
    if m:
        return m.group(1).strip(), m.group(2)
    return (name or "").strip(), None


def faction_servers(data, sid, faction):
    """One region's servers that belong to one faction, cheapest first."""
    return [s for s in sorted_servers(data, sid)
            if split_faction(s["name"])[1] == faction]


def faction_options(data, sid):
    """(faction, count, min price) for the faction menu, in the canonical order."""
    out = []
    for fx in FACTIONS:
        srv = faction_servers(data, sid, fx)
        if srv:
            out.append((fx, len(srv), min(s["unit_price"] for s in srv)))
    return out


def server_options(data, sid, faction, page=0):
    """Options for the server menu of one faction, plus the number of pages.

    The faction filter is what removes paging in practice: the largest faction list is
    23 servers (EU Elyos), under Discord's 25 cap.  `page` is kept so a region that ever
    exceeds 25 servers inside one faction still works.
    """
    srv = faction_servers(data, sid, faction)
    total_pages = max(1, -(-len(srv) // PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    opts = []
    for s in srv[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
        desc = "$%.3f/M" % s["unit_price"]
        if s.get("min_qty"):
            desc += " · min %dM" % s["min_qty"]
        if s.get("stale"):
            desc += " · last cycle"
        # The faction is already chosen in the menu above, so the server label can drop
        # the ' - Elyos' suffix and stay scannable.
        opts.append(discord.SelectOption(label=split_faction(s["name"])[0][:100],
                                         value=str(s["aid"]), description=desc[:100]))
    return opts, total_pages


def page_bounds(n, page):
    """1-based inclusive [lo, hi] index range covered by one page of n servers."""
    return page * PAGE_SIZE + 1, min((page + 1) * PAGE_SIZE, n)


def aid_on_page(data, sid, faction, page, aid=None):
    """The server the panel should quote while this page is on screen.

    Keeps the current selection when it is still visible on the page, otherwise falls
    back to that page's cheapest server.  Without this the quote card keeps showing a
    server that has scrolled off the page, and pressing Next looks like it did nothing
    (only the tiny page counter changes) -- the card must always match what is visible.
    """
    opts, _ = server_options(data, sid, faction, page)
    vals = [o.value for o in opts]
    if aid is not None and str(aid) in vals:
        return str(aid)
    return vals[0] if vals else None


def panel_header(data, sid, faction, page, total_pages, auto=False):
    """The two lines above the quote inside the private panel."""
    r = find_region(data, sid)
    if not r:
        return "Region not found — please pick another one."
    srv = faction_servers(data, sid, faction) if faction else sorted_servers(data, sid)
    n = len(srv)
    cheapest = min((s["unit_price"] for s in srv), default=0.0)
    txt = "**%s · %s** · %d servers · from **$%.3f/M**" % (
        r["region"], faction or "-", n, cheapest)
    if total_pages > 1:
        lo, hi = page_bounds(n, page)
        txt += "\n**Servers %d–%d of %d** · page %d/%d" % (lo, hi, n, page + 1, total_pages)
    if auto:
        txt += "\n*Cheapest server shown — switch faction, region or server in the menus below.*"
    return txt


def _int_keys(tiers):
    out = {}
    for k, v in (tiers or {}).items():
        try:
            out[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def showcase_rows(s):
    """Only the 50 / 100 / 200 tiers — anything else is left out on purpose."""
    norm = _int_keys(s.get("tiers"))
    rows = [(q, norm[q]) for q in TIER_SHOWCASE if q in norm]
    if len(rows) < 2:                       # odd data: fall back to the smallest few
        rows = sorted(norm.items())[:3]
    return rows


def price_color(unit_price):
    """Side-bar colour for a unit price, so the number reads at a glance."""
    try:
        u = float(unit_price)
    except (TypeError, ValueError):
        return DEFAULT_COLOR
    for ceiling, col in PRICE_BANDS:
        if u <= ceiling:
            return col
    return PRICE_HIGH_COLOR


def update_line(data, prefix="-# "):
    """'Updated 19:07 (26 minutes ago) · next in 6 minutes' for the current snapshot.

    The 'next' estimate is anchored to the snapshot's own `fetched_at`, not to `now`:
    the card is rebuilt every time somebody clicks, so `now + 30 min` would always claim
    a fresh 30 minutes even when the snapshot is already 29 minutes old.  If the estimate
    has already gone by, the timer has simply not fired yet, so say so instead of
    printing a timestamp in the past.
    """
    ts = int(data.get("fetched_at") or 0)
    if not ts:
        return ""
    nxt = ts + UPDATE_INTERVAL_MIN * 60
    nxt_txt = "next update overdue" if nxt < time.time() - 120 else "next <t:%d:R>" % nxt
    return "%sUpdated <t:%d:t> (<t:%d:R>) · %s" % (prefix, ts, ts, nxt_txt)


def tier_embed(data, sid, aid):
    r, s = find_server(data, sid, aid)
    if not s:
        e = discord.Embed(title="No listing",
                          description="No listing for this server right now. "
                                      "Please pick another server or contact support.",
                          color=DEFAULT_COLOR)
        return e
    # The card leads with the two things people open the panel for, and they get the two
    # biggest slots Discord offers inside an embed:
    #   server name -> '# '-'heading 2' in the description (bigger than the old embed title)
    #   unit price  -> '# '-heading 1 in the description (the largest text an embed holds)
    # The card's colour bar carries the price band as well, so the number is both the
    # biggest and the most coloured thing on the card.  The server name keeps the site's
    # own spelling ('Israphel - Asmodian') so it can be matched on aion2kinah.com.
    # The freshness line goes right under the price as small grey subtext ('-# '), so
    # nobody has to open the board first to know how old the number is.
    e = discord.Embed(title="AION 2 Kinah", color=price_color(s["unit_price"]))
    desc = "## %s\n# $%.3f / 1M" % (s.get("name") or "-", s["unit_price"])
    stamp = update_line(data)
    if stamp:
        desc += "\n" + stamp
    e.description = desc

    norm = _int_keys(s.get("tiers"))
    min_m = min(norm) if norm else (s.get("min_qty") or 0)
    if min_m:
        e.add_field(name="Min order", value="%dM" % min_m, inline=True)
    e.add_field(name="Region", value=(r or {}).get("region", "-"), inline=True)

    rows = showcase_rows(s)
    if rows:
        qs = ["%dM" % q for q, _ in rows]
        vs = ["$%.2f" % v for _, v in rows]
        e.add_field(name="Price by quantity", value="```\n%s\n%s\n```" % (
            "  ".join(x.rjust(8) for x in qs),
            "  ".join(x.rjust(8) for x in vs)), inline=False)
    if s.get("stale"):
        e.add_field(name="Note", value="Live price was unavailable this cycle — "
                                       "showing the previous price.", inline=False)
    e.add_field(name="Buy now", value="[aion2kinah.com](%s)" % BUY_URL, inline=False)
    # Freshness already sits under the price, so the footer only carries the provenance.
    e.set_footer(text="Synced from aion2kinah.com · USD per 1M Kinah")
    return e


# ============================================================ interaction (discord.py View)


class PanelRegionSelect(discord.ui.Select):
    """Region menu inside the private panel."""

    def __init__(self, sid):
        data = load_prices()
        cur = find_region(data, sid)
        opts = [discord.SelectOption(
            label=x["region"], value=str(x["sid"]),
            description="from $%.3f/M · %d servers"
                        % (region_min(x), len(x.get("servers") or [])))
            for x in ordered_regions(data)] or [discord.SelectOption(label="-", value="0")]
        super().__init__(placeholder="Region — %s" % (cur["region"] if cur else "choose"),
                         custom_id="kinah:p:rg", min_values=1, max_values=1, options=opts)

    async def callback(self, itx: discord.Interaction):
        # Switching region re-picks the faction that holds the region's cheapest server,
        # so the panel always lands on a quote.
        data = load_prices()
        sid = self.values[0]
        v = PanelView(sid, None, None, 0, data)
        await itx.response.edit_message(
            content=panel_header(data, sid, v.faction, v.page, v.total_pages, auto=True),
            embeds=[tier_embed(data, sid, v.aid)] if v.aid else [],
            view=v)


class PanelFactionSelect(discord.ui.Select):
    """Faction menu inside the private panel (Elyos / Asmodian).

    This menu is also what removes paging: each faction list tops out at 23 servers,
    under Discord's 25-option cap, so the server menu below never needs a second page.
    """

    def __init__(self, sid, faction):
        data = load_prices()
        opts = [discord.SelectOption(
            label=fx, value=fx,
            description="%d servers · from $%.3f/M" % (cnt, lo))
            for fx, cnt, lo in faction_options(data, sid)] \
            or [discord.SelectOption(label="-", value="-")]
        super().__init__(placeholder="Faction — %s" % (faction or "choose"),
                         custom_id="kinah:p:fx:%s" % sid, min_values=1, max_values=1,
                         options=opts)
        self.sid = str(sid)

    async def callback(self, itx: discord.Interaction):
        data = load_prices()
        faction = self.values[0]
        v = PanelView(self.sid, faction, None, 0, data)
        await itx.response.edit_message(
            content=panel_header(data, self.sid, v.faction, v.page, v.total_pages, auto=True),
            embeds=[tier_embed(data, self.sid, v.aid)] if v.aid else [],
            view=v)


class PanelServerSelect(discord.ui.Select):
    """Server menu inside the private panel — one faction only."""

    def __init__(self, sid, faction, aid, page, data):
        opts, _ = server_options(data, sid, faction, page)
        r, s = find_server(data, sid, aid) if aid else (None, None)
        ph = "Server — %s" % split_faction(s["name"])[0] if s else "Server — choose"
        # The custom_id carries (sid, faction, page) so the panel can be rebuilt from the
        # interaction alone, even after this View expired or the bot restarted.
        super().__init__(placeholder=ph[:150],
                         custom_id="kinah:p:sv:%s:%s:%d" % (sid, faction, page),
                         min_values=1, max_values=1,
                         options=opts or [discord.SelectOption(label="-", value="0")])
        self.sid, self.faction, self.page = str(sid), faction, page

    async def callback(self, itx: discord.Interaction):
        data = load_prices()
        aid = self.values[0]
        v = PanelView(self.sid, self.faction, aid, self.page, data)
        await itx.response.edit_message(
            content=panel_header(data, self.sid, v.faction, v.page, v.total_pages),
            embeds=[tier_embed(data, self.sid, v.aid)] if v.aid else [],
            view=v)


class PanelPageButton(discord.ui.Button):
    """Only rendered if one faction ever holds more than 25 servers (none does today)."""

    def __init__(self, sid, faction, aid, target, label):
        # Same idea as the menus: state lives in the custom_id so paging keeps working
        # after a restart or once the View has timed out.  The label spells out which
        # servers the page holds, so the button says what it does.
        super().__init__(label=label, style=discord.ButtonStyle.secondary,
                         custom_id="kinah:p:pg:%s:%s:%s:%d"
                                    % (sid, faction, aid or 0, target))
        self.sid, self.faction, self.aid, self.target = str(sid), faction, aid, target

    async def callback(self, itx: discord.Interaction):
        data = load_prices()
        v = PanelView(self.sid, self.faction, self.aid, self.target, data)
        await itx.response.edit_message(
            content=panel_header(data, self.sid, v.faction, v.page, v.total_pages),
            embeds=[tier_embed(data, self.sid, v.aid)] if v.aid else [],
            view=v)


class PanelView(discord.ui.View):
    """The private panel: region menu + faction menu + server menu, quote alongside."""

    def __init__(self, sid, faction=None, aid=None, page=0, data=None):
        super().__init__(timeout=600)
        data = data if data is not None else load_prices()
        self.sid = str(sid)
        names = [fx for fx, _, _ in faction_options(data, sid)]
        if faction not in names:
            # Default to the faction that holds the region's cheapest server, so the
            # panel opens on a quote rather than an empty faction.
            cheapest = split_faction((sorted_servers(data, sid) or [{}])[0].get("name") or "")[1]
            faction = cheapest if cheapest in names else (names[0] if names else None)
        self.faction = faction
        n = len(faction_servers(data, sid, faction)) if faction else 0
        self.n_servers = n
        self.total_pages = max(1, -(-n // PAGE_SIZE))
        self.page = max(0, min(page, self.total_pages - 1))
        self.aid = aid_on_page(data, self.sid, faction, self.page, aid)
        self.add_item(PanelRegionSelect(self.sid))
        self.add_item(PanelFactionSelect(self.sid, self.faction))
        self.add_item(PanelServerSelect(self.sid, self.faction, self.aid, self.page, data))
        if self.total_pages > 1:
            if self.page > 0:
                lo, hi = page_bounds(n, self.page - 1)
                self.add_item(PanelPageButton(self.sid, self.faction, self.aid,
                                              self.page - 1, "◀ %d–%d" % (lo, hi)))
            if self.page < self.total_pages - 1:
                lo, hi = page_bounds(n, self.page + 1)
                self.add_item(PanelPageButton(self.sid, self.faction, self.aid,
                                              self.page + 1, "%d–%d ▶" % (lo, hi)))


class BoardRegionSelect(discord.ui.Select):
    """The single menu on the board — opens the private panel, already priced."""

    def __init__(self):
        data = load_prices()
        opts = [discord.SelectOption(
            label=r["region"], value=str(r["sid"]),
            description="from $%.3f/M · %d servers"
                        % (region_min(r), len(r.get("servers") or [])))
            for r in ordered_regions(data)] or [discord.SelectOption(label="-", value="0")]
        super().__init__(placeholder="Choose a region",
                         custom_id="kinah:region", min_values=1, max_values=1, options=opts)

    async def callback(self, itx: discord.Interaction):
        data = load_prices()
        v = PanelView(self.values[0], None, None, 0, data)
        await itx.response.send_message(
            content=panel_header(data, v.sid, v.faction, v.page, v.total_pages, auto=True),
            embeds=[tier_embed(data, v.sid, v.aid)] if v.aid else [],
            view=v, ephemeral=True)


class RegionView(discord.ui.View):
    """The single menu on the board — fixed custom_id, so it survives a restart."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(BoardRegionSelect())


def register(client):
    """Call from setup_hook: register the persistent View so old messages keep working."""
    client.add_view(RegionView())


async def revive(itx: discord.Interaction):
    """Answer a kinah component interaction that no live View handled.

    discord.py drops component interactions whose custom_id matches no registered View
    *silently* (discord/state.py: `if item is None: return`) -- it logs nothing and never
    answers, so Discord tells the user "The application did not respond".  That is what
    happens when the 10 minute panel View has expired or the bot restarted while a panel
    was still open.  Every panel custom_id carries its own state (region, faction, server,
    page), so the same panel can always be rebuilt here and answered normally instead of
    dying.

    Returns a short tag describing what was revived, or None if the custom_id is unknown.
    """
    data_obj = itx.data or {}
    parts = (data_obj.get("custom_id") or "").split(":")
    values = data_obj.get("values") or []
    data = load_prices()

    if parts[:3] == ["kinah", "p", "rg"] and values:            # region menu
        sid = values[0]
        v = PanelView(sid, None, None, 0, data)
        await itx.response.edit_message(
            content=panel_header(data, sid, v.faction, v.page, v.total_pages, auto=True),
            embeds=[tier_embed(data, sid, v.aid)] if v.aid else [],
            view=v)
        return "panel:region"

    if parts[:3] == ["kinah", "p", "fx"] and values:            # faction menu
        sid = parts[3] if len(parts) > 3 else "0"
        v = PanelView(sid, values[0], None, 0, data)
        await itx.response.edit_message(
            content=panel_header(data, sid, v.faction, v.page, v.total_pages, auto=True),
            embeds=[tier_embed(data, sid, v.aid)] if v.aid else [],
            view=v)
        return "panel:faction"

    if parts[:3] == ["kinah", "p", "sv"] and values:            # server menu
        # shape: kinah:p:sv:<sid>:<faction>:<page>.  Panels opened before the faction
        # menu existed carry kinah:p:sv:<sid>:<page>, so an unknown faction is tolerated
        # and PanelView falls back to the region's cheapest faction.
        sid = parts[3] if len(parts) > 3 else "0"
        faction = parts[4] if len(parts) > 4 else None
        page = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 0
        aid = values[0]
        v = PanelView(sid, faction, aid, page, data)
        await itx.response.edit_message(
            content=panel_header(data, sid, v.faction, v.page, v.total_pages),
            embeds=[tier_embed(data, sid, v.aid)] if v.aid else [],
            view=v)
        return "panel:server"

    if parts[:3] == ["kinah", "p", "pg"]:                       # paging buttons
        if len(parts) >= 7:                                     # <sid>:<fx>:<aid>:<page>
            sid, faction, aid, target = parts[3], parts[4], parts[5], int(parts[6])
        elif len(parts) >= 6:                                   # older <sid>:<aid>:<page>
            sid, faction, aid, target = parts[3], None, parts[4], int(parts[5])
        else:
            return None
        aid = None if aid in ("", "0") else aid
        v = PanelView(sid, faction, aid, target, data)
        await itx.response.edit_message(
            content=panel_header(data, sid, v.faction, v.page, v.total_pages),
            embeds=[tier_embed(data, sid, v.aid)] if v.aid else [],
            view=v)
        return "panel:page"

    if parts == ["kinah", "region"] and values:                 # the board menu itself
        v = PanelView(values[0], None, None, 0, data)
        await itx.response.send_message(
            content=panel_header(data, v.sid, v.faction, v.page, v.total_pages, auto=True),
            embeds=[tier_embed(data, v.sid, v.aid)] if v.aid else [],
            view=v, ephemeral=True)
        return "board"

    return None


# ============================================================ REST push (for the timer)


def _token():
    t = os.environ.get("SHUGO_TOKEN", "").strip()
    if t:
        return t
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    return ""


def _dc(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request("https://discord.com/api/v10" + path, data=data, method=method)
    req.add_header("Authorization", "Bot " + _token())
    req.add_header("User-Agent", "MMOEXP-KinahBoard/1.0")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:400]


def push(channel_id=None, force=False, quiet=False):
    st = load_state()
    channel_id = str(channel_id or st.get("channel_id") or "")
    if not channel_id:
        print("[kinah] no channel_id configured, skipping")
        return 1

    prev = {s["aid"]: s for r in (load_prices().get("regions") or [])
            for s in (r.get("servers") or [])}
    data = fetch_all(prev)
    payload = board_payload(data)
    body_sig = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    n_ok = sum(len(r["servers"]) for r in data["regions"])
    n_miss = sum(len(r["missing"]) for r in data["regions"])
    n_fail = sum(len(r["failed"]) for r in data["regions"])
    changed = body_sig != st.get("last_sig")

    # The header shows a live "next update" countdown, so the message is refreshed
    # on every cycle (editing a message never notifies anyone).
    mid = st.get("message_id")
    if mid:
        code, res = _dc("PATCH", "/channels/%s/messages/%s" % (channel_id, mid), payload)
        act = "updated in place"
    else:
        code, res = _dc("POST", "/channels/%s/messages" % channel_id, payload)
        act = "created"
    if code not in (200, 201) or not isinstance(res, dict):
        print("[kinah] push failed %s: %s" % (code, res))
        return 1

    st.update({"channel_id": channel_id, "message_id": res["id"],
               "last_sig": body_sig, "last_push": int(time.time())})
    _write_json(STATE_FILE, st)
    _write_json(PRICES_FILE, data)
    if not quiet:
        print("[kinah] %s ok message_id=%s prices_changed=%s "
              "(priced %d / no-listing %d / failed %d)"
              % (act, res["id"], changed, n_ok, n_miss, n_fail))
    return 0


# ============================================================ self-test


def selftest():
    data = load_prices()
    print("=== cache ===")
    print("regions=%d  fetched_at=%s" % (len(data.get("regions") or []), data.get("fetched_at")))

    p = board_payload(data)
    print("\n=== board payload (text + menu, no card) ===")
    print("embeds=%d  components=%d" % (len(p["embeds"]), len(p["components"])))
    print(p["content"])
    sel = p["components"][0]["components"][0]
    print("\nboard menu custom_id=%s options=%d" % (sel["custom_id"], len(sel["options"])))
    assert sel["custom_id"] == "kinah:region"
    assert len(sel["options"]) == 5, "expected 5 region options"
    assert not p["embeds"], "board must stay card-free: the quote card is the only card"
    assert "private message" in p["content"], "board must say where the price opens"
    for o in sel["options"]:
        assert o["description"].startswith("from $"), \
            "with the board card gone, each region's from-price must live in the menu"
        print("   %-15s %s" % (o["label"], o["description"]))

    print("\n=== private panel: one message holds all three menus + the quote ===")
    r0 = ordered_regions(data)[0]
    v = PanelView(r0["sid"], None, None, 0, data)
    for it in v.children:
        cid = getattr(it, "custom_id", None)
        ph = getattr(it, "placeholder", None)
        n = len(getattr(it, "options", []) or [])
        print("   %-18s custom_id=%-26s placeholder=%-24s options=%d"
              % (type(it).__name__, cid, ph, n))
    rows = [i for i in v.children if isinstance(i, discord.ui.Select)]
    assert len(rows) == 3, "panel must show region + faction + server menus at once"
    assert len(v.children) <= 5, "max 5 component rows per message"
    for it in rows:
        assert len(it.options) <= PAGE_SIZE
    for it in v.children:
        assert (getattr(it, "custom_id", "") or "").startswith("kinah:"), \
            "panel custom_ids must be self-describing so an expired panel can be revived"

    print("\n=== faction split: this is what removes paging ===")
    worst = 0
    for r in ordered_regions(data):
        fx_list = faction_options(data, r["sid"])
        cell = "  ".join("%s %2d (from $%.3f)" % (fx, cnt, lo) for fx, cnt, lo in fx_list)
        unknown = [s["name"] for s in r["servers"] if split_faction(s["name"])[1] is None]
        print("   %-15s total %2d | %s%s"
              % (r["region"], len(r["servers"]), cell,
                 "   UNPARSED: %s" % unknown if unknown else ""))
        assert not unknown, "every server name must carry a faction suffix"
        assert sum(c for _, c, _ in fx_list) == len(r["servers"]), "faction split must cover all"
        worst = max([worst] + [c for _, c, _ in fx_list])
    print("   largest faction list: %d servers (Discord cap %d) -> paging needed: %s"
          % (worst, PAGE_SIZE, worst > PAGE_SIZE))
    assert worst <= PAGE_SIZE, "a faction list over the cap would bring paging back"

    print("\n=== paging still works if a faction ever exceeds the cap (synthetic) ===")
    _real_page_size = PAGE_SIZE
    try:
        globals()["PAGE_SIZE"] = 5                       # pretend the cap is 5 to force it
        big = max(ordered_regions(data),
                  key=lambda r: len(faction_servers(data, r["sid"], "Elyos")))
        fx = "Elyos"
        srv = faction_servers(data, big["sid"], fx)
        first, nxt = str(srv[0]["aid"]), str(srv[5]["aid"])
        v0 = PanelView(big["sid"], fx, first, 0, data)
        v1 = PanelView(big["sid"], fx, first, 1, data)
        print("   forced cap 5 on %s · %s (%d servers, %d pages)"
              % (big["region"], fx, len(srv), v0.total_pages))
        print("   keep selection on page 0 :", aid_on_page(data, big["sid"], fx, 0, first) == first)
        print("   fall back when off page  :", aid_on_page(data, big["sid"], fx, 1, first) == nxt)
        for vv in (v0, v1):
            btns = [(c.label, c.custom_id) for c in vv.children
                    if isinstance(c, discord.ui.Button)]
            print("   page %d buttons           : %s" % (vv.page, btns))
            assert btns, "a multi-page faction must offer a paging button"
            assert any("–" in lbl for lbl, _ in btns), "paging label must name its range"
            assert len(vv.children) <= 5, "the paging row must still fit inside 5 rows"
        assert v1.aid != first and v1.aid == nxt, "card must follow the visible page"
        assert "Servers 1–5 of %d" % len(srv) in panel_header(
            data, big["sid"], fx, 0, v0.total_pages)
    finally:
        globals()["PAGE_SIZE"] = _real_page_size

    print("\n=== quote embed (sample) ===")
    s0 = sorted_servers(data, r0["sid"])[0]
    e = tier_embed(data, r0["sid"], s0["aid"])
    print("title:", e.title)
    print("description:", e.description.replace("\n", " || "))
    print("colour: #%06X" % e.color.value)
    assert e.description.startswith("## "), "server name must lead the card as a heading"
    assert "\n# $" in e.description, "unit price must be a level-1 heading (biggest text)"
    assert "\n-# Updated <t:" in e.description, "card must carry last-updated / next-update"
    assert e.color.value == price_color(s0["unit_price"]), "colour bar must encode the price"
    print("update line:", update_line(data))
    for f in e.fields:
        print("   [%s] %s" % (f.name, (f.value or "").replace("\n", " / ")[:120]))
    print("footer:", e.footer.text)
    t = _int_keys(s0.get("tiers"))
    print("   tiers in data     :", sorted(t))
    print("   tiers in showcase :", [q for q, _ in showcase_rows(s0)])
    assert [q for q, _ in showcase_rows(s0)] == [q for q in TIER_SHOWCASE if q in t]

    print("\n=== panel header ===")
    for fx in [f for f, _, _ in faction_options(data, r0["sid"])]:
        print("  %-9s auto  :" % fx,
              panel_header(data, r0["sid"], fx, 0, 1, auto=True).replace("\n", " || "))
    print("  manual  :", panel_header(data, r0["sid"], "Elyos", 0, 1,
                                     auto=False).replace("\n", " || "))

    print("\nSELFTEST OK")
    return 0


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest()
    if "--push" in args:
        ch = args[args.index("--channel") + 1] if "--channel" in args else None
        return push(ch, force="--force" in args)
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
