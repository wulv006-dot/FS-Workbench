# -*- coding: utf-8 -*-
"""防冒充 / 竞品关键词守卫 —— 逻辑逐条移植自原 GuardBot（node index.js）。

移植对照
--------
  canon()          NFKC 全角→半角 + 去零宽 + 异体字归一 + 转小写
  squash()         去掉一切非 [a-z0-9]
  tokenMatch()     「独立片段」匹配品牌核心词，允许 1 字符拼写容错（少一个/换一个）
  classify()       ① extraStartsWith ② 片段匹配 ③ 前缀正则 + matchMode(strict/loose)
  SUFFIX_OK        品牌词后接 official/support/bot… 视为官方类后缀，不算冒充

为什么这套比「只匹配开头」强
--------------------------
  nick.mmoexp / service_mmoex 这类品牌词不在开头的名字，旧前缀正则全部放行；
  而 mmoexpert / mmoexpfan 这类粘连名**不会**被误伤（只认独立片段）。

安全纪律
--------
  ① 启动时只做一次全量扫描**报告**，绝不批量处置（防止误封老成员）
  ② dry_run=true 时只记日志不动人；false 才真 ban
  ③ 白名单：用户 id / 角色 id / 自己 / 服务器所有者
"""
import logging
import re
import unicodedata

import discord

from .base import Module, PASS

log = logging.getLogger("wf.guard")

ZERO_WIDTH = re.compile("[\u200b-\u200d\u2060\ufeff\u00ad\u180e\u034f]")

HOMOGLYPH = {
    "\u041c": "m", "\u043c": "m", "\u217f": "m", "\uff4d": "m", "\uff2d": "m",
    "\u039c": "m", "\u03bc": "m", "\u041e": "o", "\u043e": "o", "\u039f": "o",
    "\u03bf": "o", "\u0585": "o", "\u0586": "o", "\uff4f": "o", "\uff2f": "o",
    "\u0415": "e", "\u0435": "e", "\u0395": "e", "\u03b5": "e", "\uff45": "e",
    "\uff25": "e", "\u212e": "e", "\u0425": "x", "\u0445": "x", "\u03a7": "x",
    "\u03c7": "x", "\u00d7": "x", "\u2573": "x", "\uff58": "x", "\uff38": "x",
    "\u0420": "p", "\u0440": "p", "\u03a1": "p", "\u03c1": "p", "\uff50": "p",
    "\uff30": "p",
}
HOMO_RE = re.compile("[" + "".join(HOMOGLYPH.keys()) + "]")

SUFFIX_OK = [
    "support", "official", "admin", "team", "service", "help", "cs", "staff",
    "store", "sale", "sales", "gift", "giveaway", "airdrop", "claim", "reward",
    "promo", "bot", "mod", "manager", "agent", "online", "shop", "market",
    "trade", "vip", "global", "hq", "inc", "llc", "top", "buy", "sell",
]

DEFAULT_BRANDS = [
    {"label": "MMOEXP", "core": "mmoexp", "official": True, "fuzzy": 1,
     "matchMode": "loose", "token": True, "prefix": True,
     "pattern": r"^(?:the)?(?:mm[o0]+)exp([a-z0-9]*)$"},
    {"label": "U4GM", "core": "u4gm", "official": False, "fuzzy": 1,
     "matchMode": "strict", "token": True, "prefix": True,
     "pattern": r"^(?:the)?(?:u4gm)([a-z0-9]*)$"},
    {"label": "IGGM", "core": "iggm", "official": False, "fuzzy": 1,
     "matchMode": "strict", "token": True, "prefix": True,
     "pattern": r"^(?:the)?(?:iggm)([a-z0-9]*)$"},
    {"label": "LOOTBAR", "core": "lootbar", "official": False, "fuzzy": 1,
     "matchMode": "strict", "token": True, "prefix": True,
     "pattern": r"^(?:the)?(?:lootbar)([a-z0-9]*)$"},
]


# ------------------------------------------------------------------ 归一化
def canon(raw):
    s = "" if raw is None else str(raw)
    s = unicodedata.normalize("NFKC", s)
    s = ZERO_WIDTH.sub("", s)
    s = HOMO_RE.sub(lambda m: HOMOGLYPH.get(m.group(0), m.group(0)), s)
    return s.lower()


# leet / 符号替换：l00tbar / L00TB4R / 1ggm / ig9m / u4gm 都归一到正常拼写。
# 关键点：**名字与品牌词本体用同一套映射**，所以 U4GM 自身含 4 也不会被自己打歪
# （u4gm → uagm，品牌词 core 也 → uagm，两边一致）。
# 而 lootbag / lootbox / lootbarn 归一到 lootbag/lootbox/lootbarn ≠ lootbar，不会误伤。
LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
                      "7": "t", "9": "g", "8": "b", "$": "s", "@": "a",
                      "|": "l", "+": "t"})


def norm(raw):
    return canon(raw).translate(LEET)


def squash(s):
    return re.sub(r"[^a-z0-9]+", "", s)


def drop_one_char(a, b):
    """a 删掉恰好 1 个字符后是否等于 b"""
    if len(a) - len(b) != 1:
        return False
    return any(a[:i] + a[i + 1:] == b for i in range(len(a)))


def one_char_diff(a, b):
    if len(a) != len(b):
        return False
    return sum(1 for x, y in zip(a, b) if x != y) == 1


def token_match(raw_name, core, fuzzy):
    core_s = squash(norm(core))
    if len(core_s) < 4:
        return None
    parts = [p for p in re.split(r"[^a-z0-9]+", norm(raw_name)) if p]
    for p in parts:
        if len(p) < 4:
            continue
        if p == core_s:
            return {"tail": "", "via": "token", "token": p}
        if fuzzy >= 1 and (drop_one_char(core_s, p) or one_char_diff(core_s, p)):
            return {"tail": "", "via": "token-approx", "token": p}
    return None


def classify(raw_name, brands, extra_starts=None):
    """命中返回 {brand, tail, via, official}，否则 None。

    长度门槛由原版的 6 降到 4：原版按 mmoexp(6 字符) 定这个数，导致 `U4GM` / `IGGM`
    这种 4 字符竞品名**裸奔**（实测语料确认）。降到 4 后短品牌也能命中，
    而 3 字符以内的碎片（u4g / ig / 6）仍然放行，不会误伤。
    """
    sq = squash(norm(raw_name))
    sq_raw = squash(canon(raw_name))
    if len(sq_raw) < 4:
        return None
    same_len = len(sq) == len(sq_raw)

    def tail_of(start):
        """后缀判定必须用**未做 leet 的原始形**，否则 U4GM2026 会变成 uagm2o26、
        u4gm88 会变成 uagmbb，数字后缀判定直接失效（实测踩过）。"""
        if same_len:
            return sq_raw[start:]
        return sq[start:]

    for token in (extra_starts or []):
        t = squash(norm(token))
        if t and sq.startswith(t):
            return {"brand": token, "tail": tail_of(len(t)), "via": "extraStartsWith",
                    "official": True}

    for brand in brands:
        core = brand.get("core") or ""
        fuzzy = int(brand.get("fuzzy") or 0)
        if brand.get("token", True):
            tk = token_match(raw_name, core, fuzzy)
            if tk:
                tk["brand"] = brand.get("label") or core
                tk["official"] = bool(brand.get("official"))
                return tk

        if not brand.get("prefix", True):
            continue
        pattern = brand.get("pattern") or (
            "^(?:the)?(?:%s)([a-z0-9]*)$" % re.escape(squash(norm(core))))
        m = re.match(pattern, sq, re.I)
        if not m:
            continue
        tail = tail_of(m.start(1)) if m.start(1) >= 0 else (m.group(1) or "")
        mode = brand.get("matchMode", "strict")
        if mode == "loose":
            via = "loose"
        elif tail == "":
            via = "exact"
        elif tail.isdigit():
            via = "digits"
        elif any(tail.startswith(s) for s in SUFFIX_OK):
            via = "suffix"
        else:
            continue
        return {"brand": brand.get("label") or core, "tail": tail, "via": via,
                "official": bool(brand.get("official"))}
    return None


def assess_member(member, brands, extra_starts=None):
    """按 username / 全局名 / 昵称 / 显示名 依次判定。"""
    candidate = [
        ("username", getattr(member, "name", None)),
        ("global_name", getattr(member, "global_name", None)),
        ("nickname", getattr(member, "nick", None)),
        ("display_name", getattr(member, "display_name", None)),
    ]
    for field, value in candidate:
        if not value:
            continue
        hit = classify(value, brands, extra_starts)
        if hit:
            hit["field"] = field
            hit["value"] = value
            return hit
    return None


class GuardModule(Module):
    name = "guard"
    priority = 10
    channels = set()          # 不读消息，只处理成员事件

    # ------------------------------------------------------------ 配置
    @property
    def brands(self):
        return self.feature.get("brandList") or DEFAULT_BRANDS

    @property
    def dry_run(self):
        return bool(self.feature.get("dry_run", True))

    @property
    def action(self):
        return (self.feature.get("action") or "ban").lower()

    def _wl(self):
        wl = self.feature.get("whitelist") or {}
        return (set(str(x) for x in wl.get("user_ids") or []),
                set(str(x) for x in wl.get("role_ids") or []))

    def exempt_reason(self, member):
        users, roles = self._wl()
        if member.id == self.bot.user.id:
            return "self"
        if str(member.id) in users:
            return "user-id"
        if member.guild and member.id == member.guild.owner_id:
            return "guild-owner"
        for r in getattr(member, "roles", []):
            if str(r.id) in roles:
                return "role:%s" % r.name
        return None

    # ------------------------------------------------------------ 生命周期
    async def setup(self):
        if not self.enabled:
            return
        log.info("守卫已启用 action=%s dry_run=%s 品牌=%s",
                 self.action, self.dry_run, [b.get("label") for b in self.brands])
        await self.scan_report()

    async def scan_report(self):
        """启动时全量扫描，只报告不处置。"""
        guild = self.bot.guild
        if guild is None:
            return
        # READY 时 guild.members 还不全（实测只看到 1 个），必须先拉全成员表，
        # 否则守卫等于瞎的 —— 新成员事件能收到，但存量冒充者永远扫不出来。
        try:
            if guild.member_count and len(guild.members) < guild.member_count:
                async for _m in guild.fetch_members(limit=None):
                    pass
        except Exception:                                     # noqa: BLE001
            log.exception("拉取成员列表失败，扫描结果可能不完整")
        hits = []
        for m in guild.members:
            if m.bot:
                continue
            if self.exempt_reason(m):
                continue
            hit = assess_member(m, self.brands, self.feature.get("extra_starts"))
            if hit:
                hits.append((m, hit))
        log.info("全量扫描：%d 成员，命中 %d 个", len(guild.members), len(hits))
        for m, hit in hits[:20]:
            log.info("  命中 %s (%s) field=%s value=%r brand=%s via=%s",
                     m, m.id, hit["field"], hit["value"], hit["brand"], hit["via"])
        if hits:
            await self._log_embed(
                "scan",
                "Startup scan: **%d** member(s) match a blocked brand." % len(hits),
                [("%s" % m, "%s = `%s` → %s (%s)" % (hit["field"], hit["value"],
                                                     hit["brand"], hit["via"]))
                 for m, hit in hits[:10]])

    # ------------------------------------------------------------ 事件
    async def on_member_join(self, member):
        if not self.enabled:
            return PASS
        await self.judge(member, "join")
        return PASS

    async def on_member_update(self, before, after):
        if not self.enabled:
            return PASS
        if before.nick == after.nick and before.name == after.name:
            return PASS
        await self.judge(after, "rename")
        return PASS

    async def judge(self, member, source):
        if member.bot:
            return
        reason = self.exempt_reason(member)
        if reason:
            log.info("豁免 %s (%s) 原因=%s", member, member.id, reason)
            return
        hit = assess_member(member, self.brands, self.feature.get("extra_starts"))
        if not hit:
            return

        acted = "dry-run"
        if not self.dry_run:
            try:
                if self.action == "ban":
                    await member.ban(reason="brand name policy: %s (%s)"
                                     % (hit["brand"], hit["via"]))
                    acted = "banned"
                elif self.action == "kick":
                    await member.kick(reason="brand name policy: %s" % hit["brand"])
                    acted = "kicked"
                elif self.action == "timeout":
                    import datetime as dt
                    mins = int(self.feature.get("timeout_minutes") or 10080)
                    await member.timeout(dt.timedelta(minutes=mins),
                                         reason="brand name policy: %s" % hit["brand"])
                    acted = "timeout"
                else:
                    acted = "logged-only"
            except discord.Forbidden:
                acted = "forbidden (role hierarchy)"
                log.warning("处置被拒（层级或权限）%s", member)
            except discord.HTTPException:
                acted = "http-error"
                log.exception("处置异常 %s", member)

        log.info("命中处置 source=%s user=%s(%s) field=%s value=%r brand=%s via=%s -> %s",
                 source, member, member.id, hit["field"], hit["value"],
                 hit["brand"], hit["via"], acted)
        await self._log_embed(
            "hit",
            "**%s** — `%s` = `%s`\nmatched **%s** (%s) · action: **%s**"
            % (member.mention if acted in ("banned", "kicked", "timeout") else member,
               hit["field"], hit["value"], hit["brand"], hit["via"], acted),
            [("user", "%s (`%s`)" % (member, member.id)),
             ("trigger", source),
             ("dry-run", str(self.dry_run))])

    # ------------------------------------------------------------ 日志
    async def _log_embed(self, kind, body, fields):
        ch_id = self.resolve_feature_channel("log_channel")
        channel = self.bot.get_channel(int(ch_id)) if ch_id else None
        if channel is None:
            return
        colour = 0xE24B4A if kind == "hit" else 0xBA7517
        embed = discord.Embed(title="Guard · %s" % ("blocked" if kind == "hit" else "scan"),
                              description=body, colour=colour)
        for k, v in fields:
            embed.add_field(name=k, value=v or "—", inline=True)
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.exception("守卫日志发送失败")
