# -*- coding: utf-8 -*-
"""
Shugo-bot — AION 2 Kinah 新成员引导机器人
  · 新成员加入 -> 私信欢迎（只有本人可见，频道零刷屏）
  · #get-roles 常驻卡片 -> 阵营按钮 + 职业下拉菜单
  · 点击回执 = ephemeral（只有点的人看得见）

启动:  set SHUGO_TOKEN=xxx  &&  python bot.py
"""
import json, os, sys, asyncio, datetime, logging
from pathlib import Path

import discord
from discord.ext import tasks

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import news  # noqa: E402  AION 2 官方资讯抓取/发帖

CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))


def _load_token() -> str:
    """优先环境变量 SHUGO_TOKEN；否则读同目录 token.txt。"""
    t = os.environ.get("SHUGO_TOKEN", "").strip()
    if t:
        return t
    f = HERE / "token.txt"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    return ""


TOKEN = _load_token()
LOG = HERE / "shugo-bot.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("shugo")

FACTION_BY_KEY = {f["key"]: f for f in CFG["faction_roles"]}
FACTION_ROLE_IDS = {int(f["role_id"]) for f in CFG["faction_roles"]}
CLASS_BY_ROLE = {int(c["role_id"]): c for c in CFG["class_roles"]}
CLASS_ROLE_IDS = set(CLASS_BY_ROLE)

# Discord 只提供 4 种按钮颜色，无法自定义任意色值
STYLE_MAP = {
    "primary": discord.ButtonStyle.primary,      # 蓝  #5865F2
    "secondary": discord.ButtonStyle.secondary,  # 灰
    "success": discord.ButtonStyle.success,      # 绿
    "danger": discord.ButtonStyle.danger,        # 红
}
LAYOUT = CFG.get("layout", {})

# ---- 宽度补偿 ----------------------------------------------------------------
# Discord 不给机器人任何宽度参数：按钮宽度由客户端按「内容」决定，所以字长的按钮更宽、
# 整行参差不齐。唯一可行的办法是给短标签补「不可折叠的空格」把内容撑到同样的像素宽。
# U+2002 EN SPACE 不属于 CSS 可折叠空白，客户端不会吃掉它；普通空格会被折叠，不能用。
#
# 实测结论（重要）：Discord **服务端会把按钮标签首尾的空白全部 strip 掉** ——
# 用普通空格 / U+2002 EN SPACE 补长都会被吃掉（API 回读为 0 个）。
# 必须用一个「不是空白字符、但渲染为空」的字符：
#   U+2800 BRAILLE PATTERN BLANK —— 是真正的字形（空白盲文点），不是 whitespace。
NS = "\u2800"
PAD_PX = 9.0          # U+2800 一个字符约占 9px（14px 字体下）
W_BASE, W_CHAR, W_DASH, GAP = 58.0, 4.5, 7.4, 12.0


def _pad_label(text: str, target: int) -> str:
    """把标签用 U+2800 居中补到 target 个字符位（左右各补一半，文字保持居中）。"""
    n = target - len(text)
    if n <= 0:
        return text
    left = n // 2
    return NS * left + text + NS * (n - left)


def _fit(text: str, btn_w: float, equal: bool) -> str:
    """把 text 补到「渲染宽度 ≈ btn_w 像素」。equal=False 时原样返回。"""
    if not equal or btn_w <= 0:
        return text
    need = btn_w - W_BASE - W_CHAR * len(text)
    pad = max(0, int(round(need / PAD_PX)))
    return _pad_label(text, len(text) + pad)


def _style(v, fallback=discord.ButtonStyle.primary):
    """把 config 里的字符串（或数字）转成 ButtonStyle。"""
    if isinstance(v, int):
        try:
            return discord.ButtonStyle(v)
        except ValueError:
            return fallback
    return STYLE_MAP.get(str(v or "").strip().lower(), fallback)


def _divider_label(spec, row_px: float) -> str:
    """把 {"emoji":..., "name":...} 渲染成 ────── ⚜️ FACTION ────── 。
    虚线数按名字长度反向补偿 → 任何两条分隔条的总宽度都一样，且约等于 row_px。"""
    if isinstance(spec, str):
        return spec
    name = spec.get("name", "")
    emoji = spec.get("emoji", "")
    total = int(round((row_px - 73 - W_CHAR * len(name)) / W_DASH)) if row_px > 0 else 16
    total = max(4, total)
    left = total // 2
    right = total - left
    return "─" * left + NS + emoji + NS + name + NS + "─" * right


# ----------------------------------------------------------------------------
# 常驻卡片（persistent view：机器人重启后按钮依然有效）
# ----------------------------------------------------------------------------
class Panel(discord.ui.View):
    """row0 = FACTION 分隔条 | row1 = 阵营按钮
       row2 = CLASS 分隔条   | row3+ = 职业按钮（每行 class_per_row 个）"""

    # Discord 硬限制：一条消息最多 5 行。已占用 3 行（2 条分隔条 + 1 行阵营），职业最多 2 行
    MAX_ROWS = 5
    RESERVED_ROWS = 3

    def __init__(self):
        super().__init__(timeout=None)
        lay = CFG.get("layout", {})
        n_cls = len(CFG["class_roles"])
        max_cls_rows = self.MAX_ROWS - self.RESERVED_ROWS
        min_per_row = max(1, -(-n_cls // max_cls_rows))
        per_row = max(1, min(5, int(lay.get("class_per_row", 4) or 4)))
        if per_row < min_per_row:
            log.warning("class_per_row=%s 放不下 %s 个职业（最多 %s 行），已自动提升为 %s",
                        per_row, n_cls, max_cls_rows, min_per_row)
            per_row = min_per_row

        t = CFG["texts"]
        div_style = _style(lay.get("divider_style"), discord.ButtonStyle.secondary)
        equal = bool(lay.get("equal_width", True))
        row_px = float(lay.get("row_px", 0) or 0)

        # ---- 目标行宽 -> 每行每个按钮的目标像素宽 ----
        def btn_w(n):
            if row_px <= 0 or n <= 0:
                return 0.0
            return (row_px - GAP * (n - 1)) / n

        f_w = btn_w(len(CFG["faction_roles"]))
        c_w = btn_w(min(len(CFG["class_roles"]), per_row))

        # ---- 第 1 行：FACTION 分隔条 ----
        self.add_item(discord.ui.Button(
            label=_divider_label(t.get("divider_faction", {"emoji": "⚜️", "name": "FACTION"}), row_px),
            row=0, style=div_style, disabled=True, custom_id="divider_faction",
        ))

        # ---- 第 2 行：阵营 ----
        for f in CFG["faction_roles"]:
            btn = discord.ui.Button(
                label=_fit(f["label"], f_w, equal), emoji=f.get("emoji") or None, row=1,
                style=_style(f.get("style") or lay.get("faction_style"),
                             discord.ButtonStyle.primary),
                custom_id=f"faction:{f['key']}",
            )
            btn.callback = self._faction_cb
            self.add_item(btn)

        # ---- 第 3 行：CLASS 分隔条 ----
        self.add_item(discord.ui.Button(
            label=_divider_label(t.get("divider_class") or t.get("divider", {"emoji": "⚔️", "name": "CLASS"}), row_px),
            row=2, style=div_style, disabled=True, custom_id="divider_class",
        ))

        # ---- 第 4 行起：职业按钮 ----
        for i, c in enumerate(CFG["class_roles"]):
            btn = discord.ui.Button(
                label=_fit(c["label"], c_w, equal), emoji=c.get("emoji") or None,
                row=self.RESERVED_ROWS + i // per_row,
                style=_style(c.get("style") or lay.get("class_style"),
                             discord.ButtonStyle.primary),
                custom_id=f"class:{c['label']}",
            )
            btn.callback = self._class_cb
            self.add_item(btn)

    # ---- 阵营 ----
    async def _faction_cb(self, itx: discord.Interaction):
        key = itx.data["custom_id"].split(":", 1)[1]
        f = FACTION_BY_KEY[key]
        target = itx.guild.get_role(int(f["role_id"]))
        if target is None:
            return await itx.response.send_message("⚠️ Role not found, ping an admin.", ephemeral=True)

        me = itx.user
        drop = [r for r in me.roles if r.id in FACTION_ROLE_IDS and r.id != target.id]
        try:
            if drop:
                await me.remove_roles(*drop, reason="faction switch")
            if target not in me.roles:
                await me.add_roles(target, reason="faction pick")
        except discord.Forbidden:
            return await itx.response.send_message(
                "⚠️ I don't have permission to assign that role. (Role hierarchy)", ephemeral=True)

        cls = next((r for r in me.roles if r.id in CLASS_ROLE_IDS), None)
        done = cls is not None
        e = discord.Embed(
            color=discord.Color.green(),
            title=f"{f['emoji']}  Faction set: {f['label']}",
            description=("🎉 **You're all set!**\n" if done else "Now pick your **class** from the menu below. ⬇️"),
        )
        e.add_field(name="Faction", value=f"{f['emoji']} {f['label']}", inline=True)
        e.add_field(name="Class", value=f"{cls.mention}" if cls else "—", inline=True)
        await itx.response.send_message(embed=e, ephemeral=True)

    # ---- 职业 ----
    async def _class_cb(self, itx: discord.Interaction):
        label = itx.data["custom_id"].split(":", 1)[1]
        c = next((x for x in CFG["class_roles"] if x["label"] == label), None)
        target = itx.guild.get_role(int(c["role_id"]))
        if target is None:
            return await itx.response.send_message("⚠️ Role not found, ping an admin.", ephemeral=True)

        me = itx.user
        drop = [r for r in me.roles if r.id in CLASS_ROLE_IDS and r.id != target.id]
        try:
            if drop:
                await me.remove_roles(*drop, reason="class switch")
            if target not in me.roles:
                await me.add_roles(target, reason="class pick")
        except discord.Forbidden:
            return await itx.response.send_message(
                "⚠️ I don't have permission to assign that role. (Role hierarchy)", ephemeral=True)

        fac = next((r for r in me.roles if r.id in FACTION_ROLE_IDS), None)
        done = fac is not None
        e = discord.Embed(
            color=discord.Color.green(),
            title=f"{c['emoji']}  Class set: {c['label']}",
            description=("🎉 **You're all set — welcome aboard!**" if done
                         else "Now pick your **faction** using the buttons above. ⬆️"),
        )
        e.add_field(name="Faction", value=f"{fac.mention}" if fac else "—", inline=True)
        e.add_field(name="Class", value=f"{c['emoji']} {c['label']}", inline=True)
        await itx.response.send_message(embed=e, ephemeral=True)


# ----------------------------------------------------------------------------
# Bot
# ----------------------------------------------------------------------------
class ShugoBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.guilds = True
        super().__init__(intents=intents)

    async def setup_hook(self):
        self.add_view(Panel())          # 让重启后的老按钮继续可用
        # AION 2 Kinah 价格看板：把「大区下拉」注册为持久化 View。
        # custom_id 固定为 kinah:region，所以机器人重启后，看板消息上那个下拉依然能用。
        # 这里用函数内 import，是为了让本功能对 bot.py 的改动只落一处（价格看板是可选模块）。
        import kinah                     # noqa: E402  同目录 kinah.py
        self.add_view(kinah.RegionView())
        self.news_state = news.State(HERE / "news_state.json")
        if not self.news_loop.is_running():
            self.news_loop.start()

    # ---- AION 2 Kinah 价格看板：兜底接住「面板 View 已失效」的交互 ----
    async def on_interaction(self, itx: discord.Interaction):
        """兜底处理没有被任何存活 View 接住的 kinah 组件交互。

        discord.py 对「custom_id 匹配不到 View」的组件交互是**静默丢弃**：
        不记日志、不应答（discord/state.py: `if item is None: return`），用户在客户端
        看到的就是 "Shugo-bot 未能及时响应"。价格面板的 View 只有 10 分钟寿命，机器人
        重启也会让它失效 —— 这些点击全都会掉进这个洞。因为每个面板 custom_id 都自带
        状态，kinah.revive() 能把同一条面板原样重建出来，所以这里接住并正常应答。
        """
        try:
            d = itx.data or {}
            cid = d.get("custom_id") or ""
            if itx.type is not discord.InteractionType.component or not cid.startswith("kinah:"):
                return
            # 复刻 ViewStore 的匹配逻辑（discord/ui/view.py: dispatch_view），判断这次
            # 交互是否已被某个存活 View 接住；接住了就不要重复应答。
            handled = False
            try:
                store = self._connection._view_store
                key = (d.get("component_type"), cid)
                mid = itx.message.id if itx.message else None
                handled = ((mid is not None and key in store._views.get(mid, {}))
                           or key in store._views.get(None, {}))
            except Exception:                 # 库内部结构变了就退化成「未接住」
                handled = False
            log.info("kinah interaction custom_id=%s user=%s view_matched=%s",
                     cid, itx.user, handled)
            if handled or itx.response.is_done():
                return
            import kinah                      # noqa: E402  同目录 kinah.py
            what = await kinah.revive(itx)
            log.info("kinah revive -> %s", what or "unknown custom_id")
            if not what and not itx.response.is_done():
                await itx.response.send_message(
                    "This menu is out of date — please pick a region again on the price board.",
                    ephemeral=True)
        except Exception:
            log.exception("kinah interaction fallback failed")

    # ---- 官方资讯轮询（config.json -> news_poll_minutes，默认 30 分钟）----
    @tasks.loop(minutes=max(5, int(CFG.get("news_poll_minutes", 30) or 30)))
    async def news_loop(self):
        try:
            n = await news.poll_and_post(self, CFG, self.news_state)
            if n:
                log.info("本轮推送 %d 条官方资讯", n)
        except Exception:
            log.exception("资讯轮询异常（下轮重试）")

    @news_loop.before_loop
    async def _news_wait(self):
        await self.wait_until_ready()

    async def on_ready(self):
        log.info("=" * 60)
        log.info("Logged in as %s (id=%s)", self.user, self.user.id)
        log.info("members intent active: %s", self.intents.members)
        for g in self.guilds:
            log.info("guild: %s  members=%s", g.name, g.member_count)
        ch_id = int(CFG.get("news_channel_id") or 0)
        ch = self.get_channel(ch_id) if ch_id else None
        log.info("news channel: %s", ("#%s (%s)" % (ch.name, ch.id)) if ch else "未配置/找不到")
        log.info("news boards : %s | every %s min", CFG.get("news_boards"), CFG.get("news_poll_minutes", 30))
        log.info("=" * 60)

    async def on_member_join(self, member: discord.Member):
        if member.guild.id != int(CFG["guild_id"]) or member.bot:
            return
        t = CFG["texts"]
        ch = member.guild.get_channel(int(CFG["menu_channel_id"]))
        link = ch.mention if ch else "#get-roles"
        # 序号 = 当前成员数
        nth = ordinal(member.guild.member_count or 0)
        body = t["dm_body"].format(name=f"**{member.display_name}**", ordinal=nth, link=link)
        e = discord.Embed(color=discord.Color.from_str("#60a5fa"), title=t["dm_title"], description=body)
        e.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
        try:
            await member.send(embed=e)
            log.info("DM welcome -> %s (%s)  OK", member, member.id)
        except discord.Forbidden:
            log.warning("DM welcome -> %s FAILED (DMs closed / blocked)", member)


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        s = "th"
    else:
        s = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{s}"


if __name__ == "__main__":
    if not TOKEN:
        print("ERROR: 请先设置环境变量 SHUGO_TOKEN"); sys.exit(1)
    ShugoBot().run(TOKEN, log_handler=None)
