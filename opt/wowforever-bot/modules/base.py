# -*- coding: utf-8 -*-
"""模块基类 + 路由约定。

约定（这三条是四个模块能共存的前提）：
  1. STOP —— on_message 返回它表示「已处理，后续模块不再收到」
  2. channels —— 模块只声明自己关心的频道；空集合 = 全频道（只有守卫用）
  3. on_component —— custom_id 必须以 `wf:<module>:` 开头，按前缀分派
"""

STOP = "stop"
PASS = "pass"


class Context(object):
    """一次消息事件的最小上下文，避免模块直接依赖 discord.py 内部对象。"""

    def __init__(self, message, guild, config, store, bot):
        self.message = message
        self.guild = guild
        self.config = config
        self.store = store
        self.bot = bot

    @property
    def channel_id(self):
        return str(self.message.channel.id)

    @property
    def author(self):
        return self.message.author

    @property
    def content(self):
        return self.message.content or ""


class Module(object):
    name = "unnamed"
    priority = 50
    channels = set()

    def __init__(self, bot, config, store):
        self.bot = bot
        self.config = config
        self.feature = (config.get("features") or {}).get(self.name) or {}
        self.store = store

    @property
    def enabled(self):
        return bool(self.feature.get("enabled"))

    def channel_id(self, key):
        """把 config.channels 的别名解析成真实 id。"""
        return str((self.config.get("channels") or {}).get(key) or "")

    def resolve_feature_channel(self, key="channel"):
        alias = self.feature.get(key)
        if not alias:
            return ""
        return str((self.config.get("channels") or {}).get(alias) or alias)

    def wants(self, channel_id):
        if not self.channels:
            return True
        return str(channel_id) in self.channels

    async def setup(self):
        """启动时调用：注册持久化视图、确保面板存在。"""

    async def on_message(self, ctx):
        return PASS

    async def on_member_join(self, member):
        return PASS

    def view(self):
        """返回单个持久化 View（没有则 None）。"""
        return None

    def views(self):
        """返回需要持久化注册的全部 View（多个面板的模块用这个）。"""
        v = self.view()
        return [v] if v is not None else []
