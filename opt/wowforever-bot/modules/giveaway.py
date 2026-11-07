# -*- coding: utf-8 -*-
"""🎁│giveaway 抽奖 —— 老虎机 + 背包登记 + 优惠券发码。

奖品分两类（config 的 `type` 决定分支）
--------------------------------------
  bag     抽中后弹窗收集「服务器 / 子区 / 角色名」，落库并推给客服频道，
          由频道里的 Ryan Brooks 游戏内邮寄。用户侧提示「稍等，久没动静找他」。
  coupon  当场生成唯一折扣码写入 state + 日志，并给一个下单跳转按钮
          （与 🪙│gold-price 看板共用 config.shop 的链接，改一处两边同步）。

展示限制（实测，别踩）
--------------------
`##` 标题语法**只在 embed description 里生效**，放进 field 值会原样显示；
按钮字号由 Discord 固定，无法调大，只能靠留白让整体不拥挤。
"""
import asyncio
import json
import logging
import random
import secrets
import string
import time

import discord

from .base import Module, PASS

log = logging.getLogger("wf.giveaway")

SPIN_CID = "wf:giveaway:spin"
DELIVER_CID = "wf:giveaway:deliver"
GOLD = 0xC69B3F
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def weighted_pick(prizes):
    """按 chance(百分比) 抽取。不按格子数均分，抽到哪个就整体停在哪个。"""
    pool = [p for p in prizes if float(p.get("chance") or 0) > 0]
    if not pool:
        return None
    total = sum(float(p["chance"]) for p in pool)
    r = random.uniform(0, total)
    upto = 0.0
    for p in pool:
        upto += float(p["chance"])
        if r <= upto:
            return p
    return pool[-1]


def gen_code(prize_key):
    """兜底随机码。奖池里配了 `code` 的走固定码，不用这个。"""
    tag = {"coupon5": "5P", "coupon8": "8P"}.get(prize_key, "GN")
    body = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
    return "WOWF-%s-%s" % (tag, body)


class GiveawayModule(Module):
    name = "giveaway"
    priority = 50

    def __init__(self, bot, config, store):
        super().__init__(bot, config, store)
        ch = self.resolve_feature_channel("channel")
        self.channels = {ch} if ch else set()

    # ------------------------------------------------------------ 配置
    @property
    def prizes(self):
        return self.feature.get("prizes") or []

    @property
    def cooldown_hours(self):
        return float(self.feature.get("cooldown_hours") or 0)

    def total_chance(self):
        return sum(float(p.get("chance") or 0) for p in self.prizes)

    def bypass(self, user_id):
        return str(user_id) in set(str(x) for x in
                                   (self.feature.get("bypass_users") or []))

    def shop(self, key, default=""):
        """购物链接/文案统一从顶层 config.shop 取，和金币看板共用一份。"""
        return (self.config.get("shop") or {}).get(key) or default

    # ------------------------------------------------------------ 视图
    def views(self):
        # DeliveryView 必须一起持久化注册：它是用户中包后唯一的登记入口，
        # 不能因为超时或重启就点不开（自定义 id 固定，重启后仍能命中）。
        return [GiveawayView(self), DeliveryView(self)]

    # ------------------------------------------------------------ 面板
    def stock_line(self, prize, left):
        """库存行：🟢 充足 / 🟡 过半 / 🔴 见底。Discord 没有文字颜色，只能用色点。"""
        if left is None:
            return "♾️ **unlimited**"
        total = int(prize.get("stock") or 0)
        if left <= 0:
            return "🔴 **sold out**"
        ratio = (left / float(total)) if total else 1.0
        dot = "🟢" if ratio > 0.5 else ("🟡" if ratio > 0.2 else "🔴")
        return "%s **%d / %d left**" % (dot, left, total)

    def panel_payload(self):
        total = self.total_chance()
        cap = self.spins_allowed()
        spins = ("**%d free spins**" % cap) if cap else "**as many spins as you like**"

        hero = discord.Embed(
            title=self.feature.get("panel_title") or "WOW FOREVER · Lucky Loot",
            colour=GOLD)
        hero.description = (
            "## Two spins. Zero gold. No catch.\n\n"
            "This disgustingly handsome bot just handed you %s — "
            "pull the lever and see what the Light drops in your bag.\n\n"
            "## Prize pool" % spins)
        hero.set_footer(text="One prize per spin · stock is real, not infinite")
        if abs(total - 100) > 0.01:
            hero.set_footer(text="⚠️ prize odds add up to %.0f%% (config error)" % total)

        # 每个奖品一张独立卡片：色条不同 + 卡片间距天然留白，不再挤成一段
        embeds = [hero]
        for p in self.prizes:
            left = self.stock_left(p["key"])
            embeds.append(discord.Embed(
                title="%s %s" % (p.get("emoji") or "•", p.get("label") or p["key"]),
                description="**%.0f%%** chance · %s"
                            % (float(p.get("chance") or 0), self.stock_line(p, left)),
                colour=int(str(p.get("color") or "#8B6914").lstrip("#"), 16)))
        return embeds

    def staff_mention(self):
        sid = self.feature.get("staff_contact")
        return "<@%s>" % sid if sid else "our staff"

    def staff_name(self):
        """公开面板用纯文本名字，不嵌 <@id> —— 免得每次重启编辑面板都把运营拽一遍。"""
        return (self.feature.get("staff_name")
                or self.feature.get("staff_label") or "our staff")

    async def setup(self):
        if not self.enabled:
            return
        total = self.total_chance()
        if abs(total - 100) > 0.01:
            log.warning("奖品概率合计 %.1f%% != 100%%，请检查 config", total)
        ch_id = self.resolve_feature_channel("channel")
        channel = self.bot.get_channel(int(ch_id)) if ch_id else None
        if channel is None:
            log.warning("抽奖频道 %s 取不到", ch_id)
            return
        embeds = self.panel_payload()
        view = GiveawayView(self)
        key = "giveaway_msg"
        mid = self.store.get(key)
        if mid:
            try:
                msg = await channel.fetch_message(int(mid))
                await msg.edit(embeds=embeds, view=view)
                self.bot.add_exempt(msg.id)
                log.info("抽奖面板原位更新 message_id=%s", msg.id)
                return
            except (discord.NotFound, discord.Forbidden, ValueError):
                log.warning("旧抽奖面板不可用，重新发布")
        msg = await channel.send(embeds=embeds, view=view)
        self.store.set(key, str(msg.id))
        self.bot.add_exempt(msg.id)
        log.info("抽奖面板已发布 message_id=%s", msg.id)

    async def refresh_panel(self):
        """库存变化后同步公开面板上的「还剩 N 个」。失败不影响抽奖本身。"""
        ch_id = self.resolve_feature_channel("channel")
        channel = self.bot.get_channel(int(ch_id)) if ch_id else None
        mid = self.store.get("giveaway_msg")
        if channel is None or not mid:
            return
        try:
            msg = await channel.fetch_message(int(mid))
            await msg.edit(embeds=self.panel_payload(), view=GiveawayView(self))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
            log.debug("抽奖面板刷新失败（不影响抽奖）")

    # ------------------------------------------------------- 次数 / 冷却
    def spins_allowed(self):
        """每人可抽次数；0 = 不限。"""
        return int(self.feature.get("spins_per_user") or 0)

    def spins_used(self, user_id):
        return int((self.store.get("giveaway_spins") or {}).get(str(user_id)) or 0)

    def spins_left(self, user_id):
        if self.bypass(user_id):
            return -1                       # 白名单：无限
        cap = self.spins_allowed()
        if cap <= 0:
            return -1                       # 不限次
        return max(0, cap - self.spins_used(user_id))

    def cooldown_left(self, user_id):
        if self.bypass(user_id):
            return 0
        cd = self.cooldown_hours
        if cd <= 0:
            return 0
        last = (self.store.get("giveaway_last") or {}).get(str(user_id)) or 0
        return max(0, int(last + cd * 3600 - time.time()))

    def mark_spin(self, user_id):
        cur = dict(self.store.get("giveaway_last") or {})
        cur[str(user_id)] = int(time.time())
        self.store.set("giveaway_last", cur)
        spins = dict(self.store.get("giveaway_spins") or {})
        spins[str(user_id)] = int(spins.get(str(user_id), 0)) + 1
        self.store.set("giveaway_spins", spins)

    # ------------------------------------------------------------ 库存
    def stock_left(self, key):
        """返回剩余数量；该奖品没配 stock 则返回 None（不限量）。"""
        prize = self.prize_by_key(key)
        if prize is None or "stock" not in prize:
            return None
        st = self.store.get("giveaway_stock") or {}
        if key in st:
            return int(st[key] or 0)
        # 首次运行：用 config 的初始值播种，不改写 store（首次消耗时落盘）
        return int(prize.get("stock") or 0)

    def take_stock(self, key):
        """扣一件库存；没货返回 False。"""
        prize = self.prize_by_key(key)
        if prize is None or "stock" not in prize:
            return True                     # 不限量
        st = dict(self.store.get("giveaway_stock") or {})
        cur = int(st.get(key, prize.get("stock") or 0))
        if cur <= 0:
            st[key] = 0
            self.store.set("giveaway_stock", st)
            return False
        st[key] = cur - 1
        self.store.set("giveaway_stock", st)
        return True

    def draw(self):
        """抽一次。抽到没库存的奖品就按 config 降级（默认 5% 券）。"""
        prize = weighted_pick(self.prizes)
        if prize is None:
            return None
        if "stock" not in prize:
            return prize
        if self.take_stock(prize["key"]):
            return prize
        fb_key = self.feature.get("fallback_prize") or "coupon5"
        fb = self.prize_by_key(fb_key)
        log.warning("奖品 %s 已发完，降级为 %s", prize.get("key"), fb_key)
        return fb

    def record_win(self, user_id, prize, code=None):
        stat = dict(self.store.get("giveaway_stats") or {})
        stat[prize["key"]] = int(stat.get(prize["key"], 0)) + 1
        self.store.set("giveaway_stats", stat)
        if code:
            # 固定码（wowexp / wowexp10）会被所有人共用，不能用 code 当键，
            # 否则每发一次就把上一个人的记录覆盖掉 → 追加式的发放流水才有意义。
            logs = list(self.store.get("giveaway_coupon_log") or [])
            logs.append({"user": str(user_id), "prize": prize["key"],
                         "code": code, "ts": int(time.time())})
            self.store.set("giveaway_coupon_log", logs[-1000:])
            if not prize.get("code"):          # 唯一码才登记到 codes 表
                codes = dict(self.store.get("giveaway_codes") or {})
                codes[code] = {"user": str(user_id), "prize": prize["key"],
                               "ts": int(time.time())}
                self.store.set("giveaway_codes", codes)

    def add_claim(self, claim):
        claims = list(self.store.get("giveaway_claims") or [])
        claims.append(claim)
        self.store.set("giveaway_claims", claims[-500:])

    # ------------------------------------------------- 待登记（持久化登记入口）
    def add_pending(self, user_id, prize):
        """中包先落一条待登记记录 —— 按钮靠它找回「中的是哪个奖」。"""
        items = list(self.store.get("giveaway_pending") or [])
        pid = "%s-%s" % (prize["key"][:8], secrets.token_hex(3))
        items.append({"id": pid, "user": str(user_id), "prize": prize["key"],
                      "ts": int(time.time()), "status": "awaiting_details"})
        self.store.set("giveaway_pending", items[-300:])
        return pid

    def find_pending(self, user_id):
        """取该用户最早一条还没登记的记录；没有则返回 None。"""
        for it in (self.store.get("giveaway_pending") or []):
            if (str(it.get("user")) == str(user_id)
                    and it.get("status") == "awaiting_details"):
                return it
        return None

    def close_pending(self, pid):
        items = list(self.store.get("giveaway_pending") or [])
        for it in items:
            if it.get("id") == pid:
                it["status"] = "submitted"
        self.store.set("giveaway_pending", items)

    def prize_by_key(self, key):
        return next((p for p in self.prizes if p.get("key") == key), None)

    # ------------------------------------------------------------ 抽
    def reel_embed(self, frame):
        reels = " | ".join(random.choice(["🎒", "🎟️", "💎", "✨", "🪙"]) for _ in range(3))
        embed = discord.Embed(title="🎰 Spinning…", colour=GOLD,
                              description="## | %s |" % reels)
        embed.set_footer(text="rolling…" if frame == 0 else "still rolling…")
        return embed

    async def do_spin(self, itx):
        if not self.enabled:
            await _reply(itx, "Giveaway is not active right now.")
            return
        left = self.spins_left(itx.user.id)
        if left == 0:
            await _reply(itx, "You have burned both spins, champion. "
                              "Come back when we restock the loot table.")
            return
        cd = self.cooldown_left(itx.user.id)
        if cd > 0:
            await _reply(itx, "Easy there — try again in <t:%d:R>."
                         % int(time.time() + cd))
            return

        await itx.response.defer(ephemeral=True, thinking=True)
        try:
            for frame in range(3):
                await itx.edit_original_response(embed=self.reel_embed(frame))
                await asyncio.sleep(0.55)

            prize = self.draw()
            if prize is None:
                await itx.edit_original_response(
                    embed=discord.Embed(description="Prize pool is empty — tell staff.",
                                        colour=GOLD))
                return

            self.mark_spin(itx.user.id)
            kind = (prize.get("type") or "coupon").lower()

            if kind == "bag":
                pid = self.add_pending(itx.user.id, prize)
                await itx.edit_original_response(embed=self.bag_win_embed(prize))
                await itx.followup.send(
                    "Tap below to tell us where to deliver it. "
                    "You can come back to this message later — the button stays live.",
                    view=DeliveryView(self), ephemeral=True)
                self.record_win(itx.user.id, prize)
                log.info("抽奖(背包) user=%s(%s) prize=%s pending=%s",
                         itx.user, itx.user.id, prize.get("key"), pid)
                await self.refresh_panel()        # 库存变了，公开面板要跟着走
            else:
                # 奖池里配了固定码（wowexp / wowexp10）就用它，否则兜底生成唯一码
                code = prize.get("code") or gen_code(prize["key"])
                self.record_win(itx.user.id, prize, code)
                await itx.edit_original_response(
                    embed=self.coupon_win_embed(prize, code),
                    view=CouponView(self, code))
                log.info("抽奖(券) user=%s(%s) prize=%s code=%s",
                         itx.user, itx.user.id, prize.get("key"), code)
        except discord.HTTPException:
            log.exception("抽奖交互异常")

    # ------------------------------------------------------------ 中奖卡
    def bag_win_embed(self, prize):
        embed = discord.Embed(
            title="🎉 You won a bag!",
            colour=int(str(prize.get("color") or "#7F77DD").lstrip("#"), 16))
        embed.description = ("## %s\n\nTap **Add delivery details** below and enter "
                             "your **server**, **sub-realm** and **character name**."
                             % (prize.get("label") or prize["key"]))
        embed.add_field(name="Odds", value="%.0f%%" % float(prize.get("chance") or 0),
                        inline=True)
        embed.add_field(name="Delivery", value="In game, by %s" % self.staff_name(),
                        inline=True)
        embed.set_footer(text="We'll mail it — give it a little time. "
                              "Nothing after a day? Ping staff.")
        return embed

    def coupon_win_embed(self, prize, code):
        fixed = bool(prize.get("code"))
        embed = discord.Embed(
            title="🎉 You won a coupon!",
            colour=int(str(prize.get("color") or "#EF9F27").lstrip("#"), 16))
        embed.description = (
            "## %s\n\n%s" % (
                prize.get("label") or prize["key"],
                "Paste this at checkout. Same code for this tier — "
                "it's yours to use, no rush." if fixed else
                "Your code is below — it's unique to you."))
        embed.add_field(name="Your code", value="```\n%s\n```" % code, inline=False)
        embed.add_field(name="Odds", value="%.0f%%" % float(prize.get("chance") or 0),
                        inline=True)
        embed.add_field(name="Where to use it", value="At checkout on the shop",
                        inline=True)
        embed.set_footer(text="Screenshot this — the panel won't show your code again.")
        return embed

    # ------------------------------------------------------------ 落库 / 通知
    async def submit_delivery(self, itx, prize, server, realm, char, pending_id=None):
        claim = {"user": str(itx.user.id), "name": str(itx.user),
                 "prize": prize["key"], "label": prize.get("label"),
                 "server": server, "realm": realm, "char": char,
                 "ts": int(time.time()), "status": "pending",
                 "pending_id": pending_id}
        self.add_claim(claim)
        if pending_id:
            self.close_pending(pending_id)
        log.info("背包登记 user=%s(%s) %s / %s / %s pending=%s",
                 itx.user, itx.user.id, server, realm, char, pending_id)
        await self._notify_claim(claim, prize)
        await itx.followup.send(
            "Logged it — **%s** · %s · **%s**. %s will mail it in game; "
            "if nothing shows up after a day, ping him here."
            % (server, realm, char, self.staff_mention()),
            ephemeral=True)

    async def _notify_claim(self, claim, prize):
        ch_id = self.resolve_feature_channel("claim_channel")
        channel = self.bot.get_channel(int(ch_id)) if ch_id else None
        if channel is None:
            log.warning("登记频道 %s 取不到，登记只落库未通知", ch_id)
            return
        embed = discord.Embed(
            title="Bag delivery request",
            description="%s won **%s**" % ("<@%s>" % claim["user"],
                                           prize.get("label") or prize["prize"]),
            colour=int(str(prize.get("color") or "#7F77DD").lstrip("#"), 16))
        embed.add_field(name="Server", value=claim["server"], inline=True)
        embed.add_field(name="Sub-realm", value=claim["realm"], inline=True)
        embed.add_field(name="Character", value=claim["char"], inline=True)
        embed.add_field(name="user", value="`%s`" % claim["user"], inline=True)
        if claim.get("pending_id"):
            embed.add_field(name="Ref", value="`%s`" % claim["pending_id"], inline=True)
        embed.set_footer(text="Mail the item in game, then delete this message.")

        # 运营必须被叫醒，否则只能靠人肉盯频道
        staff = str(self.feature.get("staff_contact") or "")
        users = [discord.Object(id=int(claim["user"]))]
        content = None
        if staff:
            content = "<@%s> new bag delivery request" % staff
            users.append(discord.Object(id=int(staff)))
        try:
            await channel.send(content=content, embed=embed,
                               allowed_mentions=discord.AllowedMentions(users=users))
        except discord.HTTPException:
            log.exception("登记通知发送失败")


# ---------------------------------------------------------------- 组件
class SpinButton(discord.ui.Button):
    def __init__(self, module):
        self.module = module
        super().__init__(label="SPIN", emoji="🎰",
                         style=discord.ButtonStyle.success, custom_id=SPIN_CID)

    async def callback(self, itx):
        await self.module.do_spin(itx)


class GiveawayView(discord.ui.View):
    def __init__(self, module):
        super().__init__(timeout=None)
        self.add_item(SpinButton(module))


class DeliveryButton(discord.ui.Button):
    """背包奖：点开弹窗登记服务器 / 子区 / 角色名。

    `custom_id` 固定 → 随 DeliveryView 一起持久化注册，机器人重启或超过 15 分钟
    依然点得开。按钮不携带奖品，靠「该用户最早一条待登记记录」反查，所以同一个人
    中多次包时按先后顺序一个个登记。
    """

    def __init__(self, module):
        self.module = module
        super().__init__(label="Add delivery details", emoji="📦",
                         style=discord.ButtonStyle.primary, custom_id=DELIVER_CID)

    async def callback(self, itx):
        pending = self.module.find_pending(itx.user.id)
        if not pending:
            await _reply(itx, "No bag is waiting for details — spin again to win one.")
            return
        prize = self.module.prize_by_key(pending["prize"])
        if prize is None:
            await _reply(itx, "That prize is no longer configured — tell staff.")
            return
        await itx.response.send_modal(
            DeliveryModal(self.module, prize, pending.get("id")))


class DeliveryModal(discord.ui.Modal, title="Where should we deliver?"):
    server = discord.ui.TextInput(
        label="Server", placeholder="US / EU / Asia / KR", max_length=20,
        required=True)
    realm = discord.ui.TextInput(
        label="Sub-realm", placeholder="e.g. Normal - Alliance", max_length=60,
        required=True)
    char = discord.ui.TextInput(
        label="Character name", placeholder="Your in-game character", max_length=40,
        required=True)

    def __init__(self, module, prize, pending_id=None):
        super().__init__()
        self.module = module
        self.prize = prize
        self.pending_id = pending_id

    async def on_submit(self, itx):
        await self.module.submit_delivery(
            itx, self.prize, str(self.server.value).strip(),
            str(self.realm.value).strip(), str(self.char.value).strip(),
            self.pending_id)


class DeliveryView(discord.ui.View):
    """timeout=None + 固定 custom_id → 可以持久化注册，重启后按钮仍然有效。"""

    def __init__(self, module):
        super().__init__(timeout=None)
        self.add_item(DeliveryButton(module))


class CouponView(discord.ui.View):
    """券奖：给一个下单跳转，链接与金币看板共用 config.shop。"""

    def __init__(self, module, code):
        super().__init__(timeout=None)
        url = module.shop("url")
        if url:
            super().add_item(discord.ui.Button(
                label=module.shop("label", "Buy Cheap Gold Now"), url=url,
                style=discord.ButtonStyle.link, emoji="🛒"))


async def _reply(itx, text):
    try:
        if itx.response.is_done():
            await itx.followup.send(text, ephemeral=True)
        else:
            await itx.response.send_message(text, ephemeral=True)
    except discord.HTTPException:
        log.debug("应答失败")
