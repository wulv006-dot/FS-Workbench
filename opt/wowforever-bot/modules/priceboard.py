# -*- coding: utf-8 -*-
"""金币查价看板 —— 数据源：后台 `/game/admin_game_price/index.html?gid=1364`

口径（2026-11-07 实测，不猜）
------------------------------
`b2c` 列**就是玩家价**，单位 **USD / 1000 金**，直接展示不做反算，避免口径漂移。
旁证：采购成本 15.02634 元 ≈ 1000 金；`b2c = 成本 ÷ 6.65 ÷ 0.8`，40 行比值恒定 0.188。

设计纪律（照抄 AION2 看板的经验）
--------------------------------
① 频道里**永远只有 1 条**看板消息，每次原位编辑，不新发
② 组件 custom_id 固定并持久化注册 → 机器人重启后旧面板点下去仍然有反应
③ 面板状态存在 state 里（按消息 id），**不依赖内存**，重启不失效
④ 抓失败 ≠ 没数据：保留上一轮并打 stale 标记，绝不把「抓失败」渲染成「没货」
"""
import asyncio
import json
import logging
import os
import re
import sys
import time

import discord
from discord.ext import tasks

from .base import Module, PASS

log = logging.getLogger("wf.priceboard")

# `price` 是历史短名（模块真名 priceboard），路由靠 bot.py 的 MODULE_ALIAS 映射，
# 改这里必须同步改那张表；custom_id 一经发布即被历史消息固化，不能随意重命名。
BOARD_CID = "wf:price:rg"
PANEL_RG_CID = "wf:price:prg"
PANEL_TY_CID = "wf:price:pty"

GOLD = 0xC69B3F
PRICE_FILE = "/opt/wowforever-bot/state/gold_prices.json"
P2P_CFG = "/opt/d4follow/config.json"

REGION_LABEL = {"US": "North America", "EU": "Europe", "KR": "Korea",
                "ASIA": "Asia", "TW": "Taiwan", "UNKNOWN": "Other"}
REGION_ORDER = ["US", "EU", "KR", "ASIA", "TW", "UNKNOWN"]
TYPE_LABEL = {"NORMAL": "Normal", "PVP": "PvP", "RP": "Roleplay",
              "RP_PVP": "Roleplay-PvP", "HC": "Hardcore", "UNKNOWN": "Other"}
TYPE_ORDER = ["NORMAL", "PVP", "RP", "RP_PVP", "HC", "UNKNOWN"]
FACTION_LABEL = {"A": "Alliance", "H": "Horde", "?": "—"}


# ---------------------------------------------------------------- 取数（同步）
def parse_backend_name(s):
    low = (s or "").lower()
    if re.search(r"美服|north|^us|\(us\)|america", low) or "美服" in s:
        region = "US"
    elif re.search(r"欧服|europe|^eu", low) or "欧服" in s:
        region = "EU"
    elif re.search(r"韩服|korea|^kr", low) or "韩服" in s:
        region = "KR"
    elif re.search(r"亚服|asia", low) or "亚服" in s:
        region = "ASIA"
    elif re.search(r"台服|taiwan|^tw", low) or "台服" in s:
        region = "TW"
    else:
        region = "UNKNOWN"

    fac = "H" if "horde" in low else ("A" if "alliance" in low else "?")
    if re.search(r"roleplay\s*[- ]?\s*pvp|rp\s*[- ]?pvp", low):
        t = "RP_PVP"
    elif re.search(r"roleplay|(?<![a-z])rp(?![a-z])", low):
        t = "RP"
    elif "hardcore" in low:
        t = "HC"
    elif "normal" in low or "pve" in low:
        t = "NORMAL"
    elif "pvp" in low:
        t = "PVP"
    else:
        t = "UNKNOWN"
    return region, t, fac


def fetch_rows(gid="1364"):
    """（已废弃）直接读后台价表。现在数据来自 183 改价系统的台账，
    由 /opt/wowforever-bot/sync_wow_gold.py 每 10 分钟写成快照，本模块只读快照。"""
    raise RuntimeError("priceboard 不再直连后台，请用 state/gold_prices.json 快照")


# ---------------------------------------------------------------- 渲染
def money(v):
    if v is None:
        return "—"
    return ("$%.2f" % v) if v >= 1 else ("$%.3f" % v)


class PriceBoardModule(Module):
    name = "priceboard"
    priority = 20

    def __init__(self, bot, config, store):
        super().__init__(bot, config, store)
        ch = self.resolve_feature_channel("channel")
        self.channels = {ch} if ch else set()
        self.rows = []
        self.fetched_at = 0
        self.ledger_ts = ""
        self.ledger = ""
        self._mtim = 0
        self._loop = None

    # ------------------------------------------------------------ 视图
    def views(self):
        return [BoardView(self), PanelView(self)]

    # ------------------------------------------------------------ 数据
    def _load_cache(self):
        """快照由 sync_wow_gold.py 从 183 台账写入，这里只读。"""
        if os.path.exists(PRICE_FILE):
            try:
                d = json.load(open(PRICE_FILE, encoding="utf-8"))
                self.rows = d.get("rows") or []
                self.fetched_at = int(d.get("fetched_at") or 0)
                self.ledger_ts = d.get("ledger_ts") or ""
                self.ledger = d.get("ledger") or ""
                try:
                    self._mtim = os.path.getmtime(PRICE_FILE)
                except OSError:
                    self._mtim = 0
                return True
            except (ValueError, OSError):
                return False
        return False

    def stale(self):
        """台账超过 25 分钟没更新（= 2.5 个改价周期）就标记为陈旧。"""
        if not self.fetched_at:
            return True
        return (time.time() - self.fetched_at) > 25 * 60

    def regions(self):
        seen = [r["region"] for r in self.rows]
        return [x for x in REGION_ORDER if x in seen]

    def types_in(self, region):
        seen = [r["type"] for r in self.rows if r["region"] == region]
        return [x for x in TYPE_ORDER if x in seen]

    def pick(self, region, tkey):
        return [r for r in self.rows if r["region"] == region and r["type"] == tkey]

    # ------------------------------------------------------------ 渲染
    # ------------------------------------------------------------ 单位
    def unit(self):
        """价格单位。后台 b2c 是**每 1 金**的价，不是每 1000 金 —— 别自己换算。"""
        return self.feature.get("unit_label") or "1 Gold"

    def price_suffix(self):
        """价格后面跟的短单位，显示成 `$2.69 /G`。"""
        return self.feature.get("price_suffix") or "/G"

    def board_payload(self):
        embed = discord.Embed(title="WOW FOREVER · Gold Price Board", colour=self.accent())
        url = self.shop_url()
        if url:
            embed.url = url
        if not self.rows:
            embed.description = "Price data is not available yet — retrying shortly."
            return embed, None

        minutes = int(self.feature.get("refresh_minutes") or 10)
        # ⚠️ Discord 规则：`##` 标题语法**只在 description 生效**，
        # 放进 field 值里会原样显示（实测踩过）；footer 也不吃 `<t:>` 时间戳。
        # 所以大字号价格和更新时间全部塞进 description。
        lines = ["-# Lowest price per region · USD per 1 Gold · pick one below"]
        for region in self.regions():
            rs = [r for r in self.rows if r["region"] == region and r["b2c"]]
            if not rs:
                continue
            best = min(rs, key=lambda r: r["b2c"])
            lines.append("**%s** · %d servers" % (REGION_LABEL.get(region, region), len(rs)))
            lines.append("## %s %s" % (money(best["b2c"]), self.price_suffix()))
        if self.stale():
            lines.insert(0, "⚠️ No new price run for a while — numbers may be stale.")
        nxt = self.fetched_at + minutes * 60
        lines.append("-# Updated <t:%d:R> · next <t:%d:R>" % (self.fetched_at, nxt))
        embed.description = "\n".join(lines)
        embed.set_footer(text="Source: reprice system · refreshed every 10 min")
        return embed, self.regions()

    # ------------------------------------------------------------ 商店跳转
    def shop_url(self):
        """优先 feature 级配置，否则用顶层 config.shop（与抽奖页共用一份）。"""
        return (self.feature.get("shop_url")
                or (self.config.get("shop") or {}).get("url") or "")

    def shop_label(self):
        return (self.feature.get("shop_label")
                or (self.config.get("shop") or {}).get("label")
                or "Buy Cheap Gold Now")

    def accent(self):
        """卡片左色条颜色。注意：按钮颜色 Discord 不给设（链接按钮恒灰），
        能自定义颜色的只有 embed 的 color 这一处。"""
        raw = str(self.feature.get("accent") or "#8B6914").lstrip("#")
        try:
            return int(raw, 16)
        except ValueError:
            return GOLD

    def panel_embed(self, region, tkey):
        rows = self.pick(region, tkey)
        url = self.shop_url()
        embed = discord.Embed(
            title="%s · %s" % (REGION_LABEL.get(region, region), TYPE_LABEL.get(tkey, tkey)),
            url=url or None,
            colour=self.accent())
        if not rows:
            embed.description = "No listing for this combination."
            return embed

        # 同样受「标题语法只在 description 生效」限制，两方价格竖排放大
        desc = ["-# USD per %s · prices you pay at checkout" % self.unit()]
        for fac in ("A", "H"):
            rs = [r for r in rows if r["faction"] == fac and r["b2c"]]
            if not rs:
                continue
            desc.append("**%s**" % FACTION_LABEL.get(fac, fac))
            desc.append("## %s %s" % (money(rs[0]["b2c"]), self.price_suffix()))
        desc.append("-# Updated <t:%d:R>" % self.fetched_at)
        embed.description = "\n".join(desc)

        if url:
            # field 值里不放 `-#`（子文本语法只在 description 保证生效）
            embed.add_field(name="\u200b",
                            value="[**%s**](%s)" % (self.shop_label(), url),
                            inline=False)
        embed.set_footer(text="Source: reprice system")
        return embed

    def board_view(self, regions):
        v = BoardView(self)
        for item in v.children:
            if isinstance(item, discord.ui.Select):
                item.options = [discord.SelectOption(
                    label=REGION_LABEL.get(r, r), value=r,
                    description="%d servers" % len([x for x in self.rows if x["region"] == r]))
                    for r in (regions or ["US"])]
        return v

    def panel_view(self, region, tkey):
        v = PanelView(self)
        for item in v.children:
            if not isinstance(item, discord.ui.Select):
                continue
            if item.custom_id == PANEL_RG_CID:
                item.options = [discord.SelectOption(
                    label=REGION_LABEL.get(r, r), value=r,
                    default=(r == region)) for r in self.regions()] or \
                    [discord.SelectOption(label="North America", value="US")]
            else:
                types = self.types_in(region) or ["NORMAL"]
                item.options = [discord.SelectOption(
                    label=TYPE_LABEL.get(t, t), value=t,
                    default=(t == tkey)) for t in types]
        return v

    # ------------------------------------------------------------ 生命周期
    async def setup(self):
        if not self.enabled:
            return
        ch_id = self.resolve_feature_channel("channel")
        channel = self.bot.get_channel(int(ch_id)) if ch_id else None
        if channel is None:
            log.warning("看板频道 %s 取不到", ch_id)
            return
        if not self.rows:
            ok = self._load_cache()
            log.info("快照加载 %s：%d 行 ledger=%s",
                     "成功" if ok else "失败", len(self.rows), self.ledger_ts)
        await self.publish(channel)
        if self._loop is None:
            # 60 秒看一次快照 mtime，改价系统一写新台账就立刻刷看板
            self._loop = tasks.loop(seconds=60)(self._watch)
            self._loop.start()

    async def _watch(self):
        try:
            m = os.path.getmtime(PRICE_FILE)
        except OSError:
            return
        if m == self._mtim:
            return
        prev = self.ledger_ts
        if not self._load_cache():
            return
        log.info("检测到新台账 %s -> %s，刷新看板", prev, self.ledger_ts)
        ch_id = self.resolve_feature_channel("channel")
        channel = self.bot.get_channel(int(ch_id)) if ch_id else None
        if channel is not None:
            await self.publish(channel)

    async def publish(self, channel):
        embed, regions = self.board_payload()
        view = self.board_view(regions)
        key = "priceboard_msg"
        mid = self.store.get(key)
        if mid:
            try:
                msg = await channel.fetch_message(int(mid))
                await msg.edit(embed=embed, view=view)
                self.bot.add_exempt(msg.id)
                log.info("看板原位更新 message_id=%s", msg.id)
                return
            except (discord.NotFound, discord.Forbidden, ValueError):
                log.warning("旧看板不可用，重新发布")
        msg = await channel.send(embed=embed, view=view)
        self.store.set(key, str(msg.id))
        self.bot.add_exempt(msg.id)
        log.info("看板已发布 message_id=%s", msg.id)


# ---------------------------------------------------------------- 组件
class BoardRegionSelect(discord.ui.Select):
    def __init__(self, module):
        self.module = module
        super().__init__(placeholder="Choose a region", min_values=1, max_values=1,
                         custom_id=BOARD_CID,
                         options=[discord.SelectOption(label="North America", value="US")])

    async def callback(self, itx):
        m = self.module
        region = self.values[0]
        types = m.types_in(region) or ["NORMAL"]
        await itx.response.send_message(
            embed=m.panel_embed(region, types[0]),
            view=m.panel_view(region, types[0]),
            ephemeral=True)
        try:
            sent = await itx.original_response()
            m.store.set("panel_%s" % sent.id, {"region": region, "type": types[0]})
        except Exception:                                     # noqa: BLE001
            log.debug("面板状态写入失败（不影响使用）")


class ShopLinkButton(discord.ui.Button):
    """链接按钮：Discord 里点得动的 CTA，不需要 custom_id 也不用回调。

    ⚠️ 平台限制：带 url 的按钮**只能是 link 样式（灰色）**，API 不提供颜色参数。
    想要有颜色的按钮只能换成 success(绿)/primary(蓝紫)，那样就必须带 custom_id
    走回调、点击后由机器人再回一条带链接的私密消息 —— 也就是多一步点击。
    """

    def __init__(self, label, url):
        super(ShopLinkButton, self).__init__(label=label, url=url,
                                             style=discord.ButtonStyle.link,
                                             emoji="🛒", row=None)


class GreenBuyButton(discord.ui.Button):
    """有颜色的替代方案：点击后私密回一条带链接的消息（两次点击）。"""

    def __init__(self, label, url, suffix):
        self._url = url
        super(GreenBuyButton, self).__init__(
            label=label, style=discord.ButtonStyle.success, emoji="🛒",
            custom_id="wf:price:buy:%s" % suffix)

    async def callback(self, itx):
        view = discord.ui.View(timeout=180)
        view.add_item(discord.ui.Button(label="Open shop", url=self._url,
                                        style=discord.ButtonStyle.link))
        if not itx.response.is_done():
            await itx.response.send_message(
                "Tap **Open shop** to pick your realm and check out.",
                view=view, ephemeral=True)


def make_shop_button(module, suffix):
    """按 config 的 shop_button_style 产出按钮：link(灰,一键) / green(绿,两击)。"""
    style = str(module.feature.get("shop_button_style") or "link").lower()
    if style == "green":
        return GreenBuyButton(module.shop_label(), module.shop_url(), suffix)
    return ShopLinkButton(module.shop_label(), module.shop_url())


class BoardView(discord.ui.View):
    def __init__(self, module):
        super().__init__(timeout=None)
        self.add_item(BoardRegionSelect(module))
        if module.shop_url():
            self.add_item(make_shop_button(module, "b"))


class PanelRegionSelect(discord.ui.Select):
    def __init__(self, module):
        self.module = module
        super().__init__(placeholder="Region", min_values=1, max_values=1,
                         custom_id=PANEL_RG_CID,
                         options=[discord.SelectOption(label="North America", value="US")])

    async def callback(self, itx):
        m = self.module
        region = self.values[0]
        types = m.types_in(region) or ["NORMAL"]
        mid = str(getattr(itx.message, "id", ""))
        prev = m.store.get("panel_%s" % mid) or {}
        tkey = prev.get("type") if prev.get("type") in types else types[0]
        m.store.set("panel_%s" % mid, {"region": region, "type": tkey})
        await itx.response.edit_message(embed=m.panel_embed(region, tkey),
                                        view=m.panel_view(region, tkey))


class PanelTypeSelect(discord.ui.Select):
    def __init__(self, module):
        self.module = module
        super().__init__(placeholder="Mode", min_values=1, max_values=1,
                         custom_id=PANEL_TY_CID,
                         options=[discord.SelectOption(label="Normal", value="NORMAL")])

    async def callback(self, itx):
        m = self.module
        tkey = self.values[0]
        mid = str(getattr(itx.message, "id", ""))
        prev = m.store.get("panel_%s" % mid) or {}
        region = prev.get("region") if prev.get("region") in m.regions() else (
            m.regions() or ["US"])[0]
        m.store.set("panel_%s" % mid, {"region": region, "type": tkey})
        await itx.response.edit_message(embed=m.panel_embed(region, tkey),
                                        view=m.panel_view(region, tkey))


class PanelView(discord.ui.View):
    def __init__(self, module):
        super().__init__(timeout=None)
        self.add_item(PanelRegionSelect(module))
        self.add_item(PanelTypeSelect(module))
        if module.shop_url():
            self.add_item(make_shop_button(module, "p"))
