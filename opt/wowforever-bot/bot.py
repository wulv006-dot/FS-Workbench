# -*- coding: utf-8 -*-
"""WOW FOREVER [MMO] · Blingtron-9000 —— 单进程多模块机器人。

模块按「频道白名单」绑定，互不监听全局：
  guard       全频道（优先级 10，最先跑，命中即短路）
  tickets     🎫│support
  priceboard  💱│the-exchange
  welcome     👋│welcome

三条共存纪律：
  ① 守卫最早跑，命中返回 STOP，后续模块看不到该消息
  ② 清理/删除类逻辑必须先查豁免表（看板/工单面板消息永不删）
  ③ 组件 custom_id 强制 `wf:<module>:<action>`，按前缀分派
"""
import argparse
import json
import logging
import logging.handlers
import os
import sys

import discord

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from lib.store import Store                                     # noqa: E402
from modules.base import Context, STOP, PASS                    # noqa: E402
from modules.guard import GuardModule                           # noqa: E402
from modules.giveaway import GiveawayModule                      # noqa: E402
from modules.news import NewsModule                              # noqa: E402
from modules.priceboard import PriceBoardModule                 # noqa: E402
from modules.tickets import TicketsModule                       # noqa: E402
from modules.welcome import WelcomeModule                       # noqa: E402

MODULE_CLASSES = [GuardModule, PriceBoardModule, TicketsModule, WelcomeModule,
                  GiveawayModule, NewsModule]

# custom_id 第 2 段 → 真实模块名。
# 不能省：历史面板（欢迎四级菜单、金币看板）当初用了短名 `wf:role:*` / `wf:price:*`，
# 而那些消息还在频道里，组件里的 custom_id 改不掉。没有这张表就会被判成「模块不存在」。
MODULE_ALIAS = {
    "role": "welcome",
    "price": "priceboard",
}
CONFIG_PATH = os.path.join(ROOT, "config.json")
STATE_PATH = os.path.join(ROOT, "state", "state.json")
TOKEN_PATH = os.path.join(ROOT, "secrets", "token.txt")
LOG_PATH = os.path.join(ROOT, "logs", "bot.log")

log = logging.getLogger("wf")


def setup_logging(verbose=True):
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)-14s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    d = os.path.dirname(LOG_PATH)
    if not os.path.isdir(d):
        os.makedirs(d)
    fh = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=2 * 1024 * 1024,
                                              backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class Client(discord.Client):
    def __init__(self, config, store, **kw):
        super(Client, self).__init__(**kw)
        self.config = config
        self.store = store
        self.modules = []
        self.guild = None
        self.prefix = (config.get("prefix") or "wf") + ":"
        self.exempt_messages = set(str(x) for x in
                                   (config.get("exempt") or {}).get("messages", []))
        self.exempt_messages |= set(str(x) for x in (store.get("exempt_messages") or []))

    # ------------------------------------------------------------- 生命周期
    async def setup_hook(self):
        for cls in MODULE_CLASSES:
            self.modules.append(cls(self, self.config, self.store))
        self.modules.sort(key=lambda m: m.priority)
        for m in self.modules:
            for v in m.views():
                self.add_view(v)                    # 持久化：重启后组件仍然有效
                log.info("注册持久化视图 module=%s view=%s", m.name, type(v).__name__)
        log.info("模块顺序: %s", " -> ".join(
            "%s(%d%s)" % (m.name, m.priority, "" if m.enabled else ",off")
            for m in self.modules))

    async def on_ready(self):
        gid = self.config.get("guild_id")
        self.guild = self.get_guild(int(gid)) if gid else None
        log.info("已登录 %s (id=%s)，服务器=%s",
                 self.user, self.user.id,
                 self.guild.name if self.guild else "未找到")
        for m in self.modules:
            if not m.enabled:
                continue
            try:
                await m.setup()
            except Exception:
                log.exception("模块 %s setup 失败", m.name)

    # ------------------------------------------------------------- 事件路由
    async def on_message(self, message):
        if message.author.bot:
            return
        if message.guild is None:
            giveaway = next((m for m in self.modules if m.name == "giveaway"), None)
            if giveaway and giveaway.enabled:
                try:
                    await giveaway.on_dm(message)
                except Exception:
                    log.exception("私聊奖池指令失败")
                    await message.channel.send("操作失败，请稍后查询奖池确认状态。")
            return
        ctx = Context(message, message.guild, self.config, self.store, self)
        for m in self.modules:
            if not m.enabled or not m.wants(ctx.channel_id):
                continue
            try:
                res = await m.on_message(ctx)
            except Exception:
                log.exception("模块 %s 处理消息异常", m.name)
                continue
            if res == STOP:
                log.debug("模块 %s 短路，channel=%s", m.name, ctx.channel_id)
                break

    async def on_member_join(self, member):
        if self.guild and member.guild.id != self.guild.id:
            return
        for m in self.modules:
            if not m.enabled:
                continue
            try:
                await m.on_member_join(member)
            except Exception:
                log.exception("模块 %s 处理入群异常", m.name)

    async def on_member_update(self, before, after):
        if self.guild and after.guild.id != self.guild.id:
            return
        for m in self.modules:
            if not m.enabled or not hasattr(m, "on_member_update"):
                continue
            try:
                await m.on_member_update(before, after)
            except Exception:
                log.exception("模块 %s 处理成员更新异常", m.name)

    async def on_interaction(self, interaction):
        data = interaction.data or {}
        cid = data.get("custom_id") or ""
        if not cid.startswith(self.prefix):
            return
        parts = cid.split(":")
        mod_name = parts[1] if len(parts) > 1 else ""
        # 历史面板的 custom_id 第 2 段是旧的短名，映射回真实模块名，
        # 否则这些组件会被判成「模块不存在」，弹出的还是错误提示。
        mod_name = MODULE_ALIAS.get(mod_name, mod_name)
        mod = next((m for m in self.modules if m.name == mod_name), None)
        log.info("interaction custom_id=%s user=%s module=%s enabled=%s",
                 cid, getattr(interaction.user, "id", "?"), mod_name,
                 bool(mod and mod.enabled))

        if mod is None:
            # 关键：这里**不能抢答**。不认识的 custom_id 一律交给 View 自己处理，
            # 一旦在这里 send_message，View 回调里的 itx.response.edit_message
            # 就会抛 InteractionResponded，面板永远刷不动（历史 bug）。
            log.debug("custom_id=%s 未匹配任何模块，交由 View 处理", cid)
            return

        if not mod.enabled:
            if not interaction.response.is_done():
                try:
                    await interaction.response.send_message(
                        "This panel is not active right now.", ephemeral=True)
                except discord.HTTPException:
                    pass

    # ------------------------------------------------------------- 工具
    def add_exempt(self, message_id):
        sid = str(message_id)
        if sid in self.exempt_messages:
            return
        self.exempt_messages.add(sid)
        cur = set(str(x) for x in (self.store.get("exempt_messages") or []))
        cur.add(sid)
        self.store.set("exempt_messages", sorted(cur))

    def is_exempt(self, message_id):
        return str(message_id) in self.exempt_messages


def read_token():
    tok = os.environ.get("WF_TOKEN", "").strip()
    if tok:
        return tok
    with open(TOKEN_PATH, "r", encoding="utf-8") as f:
        return f.read().strip()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验配置，不连 Discord")
    args = ap.parse_args(argv)

    setup_logging()
    config = load_config()
    store = Store(STATE_PATH)

    if args.check:
        names = [m.__name__ for m in MODULE_CLASSES]
        log.info("配置加载成功 guild_id=%s 频道别名=%d 模块=%s",
                 config.get("guild_id"), len(config.get("channels") or {}), names)
        for k, v in (config.get("features") or {}).items():
            log.info("  feature %-12s enabled=%s", k, v.get("enabled"))
        tok = read_token()
        log.info("令牌读取成功（长度 %d）", len(tok))
        return 0

    intents = discord.Intents.default()
    ints = config.get("intents") or {}
    intents.members = bool(ints.get("members"))
    intents.message_content = bool(ints.get("message_content"))
    log.info("特权意图 members=%s message_content=%s",
             intents.members, intents.message_content)
    client = Client(config, store, intents=intents)
    client.run(read_token(), log_handler=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
