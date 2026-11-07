# -*- coding: utf-8 -*-
"""入群欢迎 + 四级反应式身份组选择（参考 AION2 面板的做法）。

交互模型
--------
公共消息只放一个按钮 → 点开是**私密面板**，面板里逐级解锁：
  1 国家/地区 → 2 阵容 → 3 规则集 → 4 职业
每选一级，下一级的菜单才出现，选完四级一次性把 4 个组挂上。
再次点已选菜单可以直接改答案，下面的级别保留。

为什么不用「公共消息上并排几个下拉」
------------------------------------
公共下拉会把频道刷得很杂，而且 4 个下拉只能同屏堆着，选完才知道选了什么。
私密面板 + 占位文字（`Region — English`）能让人一眼看到当前四级的答案。

状态存哪
--------
按**私密消息 id** 存进 state（`rolehub_<message_id>`），不依赖内存，
机器人重启后已打开的面板仍然能继续点（和金币看板同一套做法）。
"""
import logging

import discord

from .base import Module, PASS

log = logging.getLogger("wf.welcome")

# custom_id 供持久化 View 按 id 分派，一旦发布就改不动（历史消息里还留着旧值）。
# 注意 `role` 是历史短名，路由靠 bot.py 的 MODULE_ALIAS 映射回 welcome，
# 改这里必须同步改那张表，否则点击会落到「模块不存在」分支。
START_CID = "wf:welcome:start"
GROUP_CID = {"regions": "wf:role:r", "factions": "wf:role:f",
             "rulesets": "wf:role:s", "classes": "wf:role:c"}
GROUP_ORDER = ["regions", "factions", "rulesets", "classes"]
GROUP_TITLE = {"regions": "Region", "factions": "Faction",
               "rulesets": "Ruleset", "classes": "Class"}
GROUP_HINT = {"regions": "choose", "factions": "choose",
              "rulesets": "choose", "classes": "choose"}


class WelcomeModule(Module):
    name = "welcome"
    priority = 40

    def __init__(self, bot, config, store):
        super().__init__(bot, config, store)
        ch = self.resolve_feature_channel("panel_channel")
        self.channels = {ch} if ch else set()

    # ------------------------------------------------------------ 视图
    def views(self):
        return [WelcomeView(self), RoleHubView(self)]

    def groups(self):
        return self.feature.get("role_hub") or {}

    def group_items(self, group):
        return (self.groups().get(group) or [])

    def label_of(self, group, key):
        for it in self.group_items(group):
            if it["key"] == key:
                return it.get("label") or key
        return None

    # ------------------------------------------------------------ 公共面板
    def _panel_payload(self):
        f = self.feature
        embed = discord.Embed(
            title=f.get("panel_title") or "Get your roles · WOW FOREVER",
            description=(f.get("panel_body") or
                         "Pick your **region**, **faction**, **ruleset** and **class** — "
                         "each answer unlocks the next menu.\n\n"
                         "It only takes a few taps and you can change it any time."),
            colour=0xC69B3F)
        embed.add_field(name="What you get",
                        value="Language channels · faction and ruleset channels · "
                              "a class badge next to your name",
                        inline=False)
        embed.set_footer(text="Read 📋│community-rules before your first post.")
        return embed

    async def setup(self):
        ch_id = self.resolve_feature_channel("panel_channel")
        if not ch_id:
            log.warning("welcome panel_channel 未配置，跳过面板")
            return
        channel = self.bot.get_channel(int(ch_id))
        if channel is None:
            log.warning("welcome 频道 %s 取不到", ch_id)
            return
        key = "welcome_panel_msg"
        stored = self.store.get(key)
        payload = self._panel_payload()
        view = WelcomeView(self)

        if stored:
            try:
                msg = await channel.fetch_message(int(stored))
                await msg.edit(embed=payload, view=view)
                self.bot.add_exempt(msg.id)
                log.info("面板已原位更新 message_id=%s", msg.id)
                return
            except (discord.NotFound, discord.Forbidden, ValueError) as e:
                log.warning("旧面板不可用(%s)，重新发布", type(e).__name__)

        msg = await channel.send(embed=payload, view=view)
        self.store.set(key, str(msg.id))
        self.bot.add_exempt(msg.id)
        log.info("面板已发布 message_id=%s", msg.id)

    # ------------------------------------------------------------ 私密面板
    def hub_embed(self, state, done=False, error=None):
        lines = []
        for i, g in enumerate(GROUP_ORDER, 1):
            key = state.get(g)
            val = self.label_of(g, key) if key else "—"
            mark = "✓" if key else "·"
            lines.append("**%d %s**　%s　%s" % (i, GROUP_TITLE[g], mark, val))
        embed = discord.Embed(
            title="Your roles",
            description="\n".join(lines),
            colour=0x57F287 if done else 0xC69B3F)
        if error:
            embed.description = "%s\n\n⚠️ %s" % ("\n".join(lines), error)
        if done:
            embed.add_field(name="Done",
                            value="All four roles are on your account. "
                                  "Change any answer above whenever you like.",
                            inline=False)
        else:
            embed.set_footer(text="Pick the next one below · changes apply instantly")
        return embed

    def unlocked_groups(self, state):
        """逐级解锁：上一级没选，下一级就不出现。"""
        out = []
        for g in GROUP_ORDER:
            out.append(g)
            if not state.get(g):
                break
        return out

    def hub_view(self, state):
        unlocked = self.unlocked_groups(state)
        view = RoleHubView(self, unlocked)
        for sel in view.children:
            group = next((g for g, c in GROUP_CID.items()
                          if c == getattr(sel, "custom_id", None)), None)
            if group is None:
                continue
            items = self.group_items(group)
            cur = state.get(group)
            sel.options = [discord.SelectOption(
                label=it.get("label") or it["key"],
                value=it["key"],
                emoji=it.get("emoji"),
                default=(it["key"] == cur)) for it in items][:25]
            sel.placeholder = ("%d · %s — %s" % (GROUP_ORDER.index(group) + 1,
                                                 GROUP_TITLE[group],
                                                 self.label_of(group, cur))
                               if cur else
                               "%d · %s — %s" % (GROUP_ORDER.index(group) + 1,
                                                 GROUP_TITLE[group], GROUP_HINT[group]))
        return view

    def state_key(self, message_id):
        return "rolehub_%s" % message_id

    async def on_pick(self, itx, group, value):
        key = self.state_key(getattr(itx.message, "id", "x"))
        state = dict(self.store.get(key) or {})
        state[group] = value
        # 改上层答案时，把下层清空，避免出现 Region=EU + Faction 配不上之类的错位
        idx = GROUP_ORDER.index(group)
        for lower in GROUP_ORDER[idx + 1:]:
            if lower in state and group == "regions":
                state.pop(lower, None)
        self.store.set(key, state)

        complete = all(state.get(g) for g in GROUP_ORDER)
        error = None
        if complete:
            error = await self.apply_roles(itx.user, state)
        await itx.response.edit_message(
            embed=self.hub_embed(state, done=complete and not error, error=error),
            view=self.hub_view(state))

    async def apply_roles(self, member, state):
        """把四级答案换成 4 个身份组；返回错误文案（成功返回 None）。"""
        guild = member.guild if hasattr(member, "guild") else None
        if guild is None:
            return "Could not resolve the server."
        wanted, drop = [], []
        for group in GROUP_ORDER:
            key = state.get(group)
            item = next((x for x in self.group_items(group) if x["key"] == key), None)
            if item is None:
                continue
            role = guild.get_role(int(item["role_id"]))
            if role is None:
                return "Role **%s** is missing — ping an admin." % item.get("label")
            wanted.append(role)
            for other in self.group_items(group):
                if other["key"] != key:
                    r = guild.get_role(int(other["role_id"]))
                    if r and r in member.roles:
                        drop.append(r)
        try:
            if drop:
                await member.remove_roles(*drop, reason="role hub: switch")
            add = [r for r in wanted if r not in member.roles]
            if add:
                await member.add_roles(*add, reason="role hub: apply")
        except discord.Forbidden:
            log.warning("角色挂载被拒（层级/权限）user=%s", member.id)
            return ("I can't assign these yet — my role sits below them. "
                    "An admin needs to move `Blingtron-9000` up.")
        except discord.HTTPException:
            log.exception("角色挂载异常")
            return "Discord rejected that — try again in a moment."
        log.info("角色已应用 user=%s(%s) %s", member, member.id, state)
        return None

    # ------------------------------------------------------------ 入群
    async def on_member_join(self, member):
        if not self.feature.get("send_join_message"):
            return PASS
        ch_id = self.resolve_feature_channel("panel_channel")
        channel = self.bot.get_channel(int(ch_id)) if ch_id else None
        if channel is None:
            return PASS
        embed = discord.Embed(
            title="Welcome to WOW FOREVER",
            description=("%s — glad to have you here.\n\n"
                         "Hit **Pick your roles** below to choose your region, faction, "
                         "ruleset and class." % member.mention),
            colour=0xC69B3F)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Member #", value=str(member.guild.member_count), inline=True)
        embed.set_footer(text="Read 📋│community-rules before your first post.")
        try:
            await channel.send(content=member.mention, embed=embed,
                               allowed_mentions=discord.AllowedMentions(users=[member]))
        except discord.HTTPException:
            log.exception("欢迎消息发送失败")
        return PASS


# ---------------------------------------------------------------- 组件
class StartButton(discord.ui.Button):
    def __init__(self, module):
        self.module = module
        super().__init__(label="Pick your roles", emoji="🎭",
                         style=discord.ButtonStyle.primary, custom_id=START_CID)

    async def callback(self, itx):
        state = {}
        key = self.module.state_key("pending")
        await itx.response.send_message(
            embed=self.module.hub_embed(state),
            view=self.module.hub_view(state),
            ephemeral=True)
        sent = await itx.original_response()
        self.module.store.set(self.module.state_key(sent.id), state)


class WelcomeView(discord.ui.View):
    def __init__(self, module):
        super().__init__(timeout=None)
        self.add_item(StartButton(module))


class HubSelect(discord.ui.Select):
    def __init__(self, module, group):
        self.module = module
        self.group = group
        items = module.group_items(group)
        super().__init__(
            placeholder="%s — choose" % GROUP_TITLE[group],
            min_values=1, max_values=1,
            custom_id=GROUP_CID[group],
            options=[discord.SelectOption(
                label=(items[0].get("label") if items else "—"), value=(
                    items[0]["key"] if items else "x"))])

    async def callback(self, itx):
        await self.module.on_pick(itx, self.group, self.values[0])


class RoleHubView(discord.ui.View):
    def __init__(self, module, unlocked=None):
        super().__init__(timeout=None)
        for group in (unlocked if unlocked is not None else GROUP_ORDER):
            self.add_item(HubSelect(module, group))
