# -*- coding: utf-8 -*-
"""工单模块 —— 骨架（enabled=false）。

设计：🎫│support 一条常驻面板 → 点按钮建私有线程 → 客服领取 → 关闭归档到 🧾│order-logs。
当前只占位，接口与路由已接好，实现时不需要动 bot.py。
"""
import logging

from .base import Module, PASS

log = logging.getLogger("wf.tickets")


class TicketsModule(Module):
    name = "tickets"
    priority = 30

    def __init__(self, bot, config, store):
        super().__init__(bot, config, store)
        self.channels = {self.resolve_feature_channel("panel_channel")} - {""}

    async def setup(self):
        if not self.enabled:
            return
        log.info("tickets 模块已启用（面板实现待接入）")
