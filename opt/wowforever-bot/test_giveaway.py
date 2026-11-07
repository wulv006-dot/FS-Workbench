"""Isolated giveaway tests. No Discord connection or production state."""
import asyncio
import copy
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from lib.store import Store
from modules.giveaway import GiveawayModule, GiveawayView, DeliveryView


class GiveawayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "state.json")
        with open(os.path.join(os.path.dirname(__file__), "config.example.json"), encoding="utf-8") as f:
            self.config = json.load(f)
        self.feature = self.config["features"]["giveaway"]
        self.feature["admin_users"] = ["42"]
        self.bot = SimpleNamespace(get_channel=lambda _: None)
        self.m = GiveawayModule(self.bot, self.config, Store(self.path))

    def message(self, text, uid=42):
        return SimpleNamespace(content=text, author=SimpleNamespace(id=uid, bot=False),
                               guild=None, channel=SimpleNamespace(id=123, send=AsyncMock()))

    def interaction(self, uid=55):
        return SimpleNamespace(user=SimpleNamespace(id=uid),
                               response=SimpleNamespace(defer=AsyncMock(), is_done=lambda: False,
                                                        send_message=AsyncMock()),
                               edit_original_response=AsyncMock())

    async def test_reset_persists_and_preserves_player_records(self):
        self.m.store.update(giveaway_stock={"bag10": 1, "bag8": 0},
                            giveaway_spins={"55": 2}, giveaway_last={"55": 123},
                            giveaway_pending=[{"id": "pending"}], giveaway_claims=[{"id": "claim"}],
                            giveaway_stats={"bag8": 12}, giveaway_coupon_log=[{"code": "old"}])
        before = copy.deepcopy(self.m.store._data)
        self.m.refresh_panel = AsyncMock(return_value=True)
        msg = self.message("!奖池 重置 20 60")
        await self.m.on_dm(msg)
        reloaded = GiveawayModule(self.bot, self.config, Store(self.path))
        self.assertEqual(reloaded.stock_left("bag10"), 20)
        self.assertEqual(reloaded.stock_left("bag8"), 60)
        self.assertIn("20 / 20", reloaded.stock_summary())
        for key, value in before.items():
            if key != "giveaway_stock":
                self.assertEqual(reloaded.store.get(key), value, key)
        self.assertEqual(reloaded.store.get("giveaway_stock_resets")[-1]["actor"], "42")
        self.assertEqual(reloaded.spins_left(55), 0)
        self.m.refresh_panel.assert_awaited_once()

    async def test_reset_defaults_and_zero(self):
        self.m.reset_stock(42, [0, 0])
        self.assertIn("sold out", self.m.stock_summary())
        await self.m.on_dm(self.message("!pool reset"))
        self.assertEqual(self.m.stock_left("bag10"), 10)
        self.assertEqual(self.m.stock_left("bag8"), 50)

    async def test_permission_and_invalid_input_never_change_state(self):
        for text, uid in [("!奖池 重置", 7), ("!pool reset 5 10", 7),
                          ("!奖池 重置 -1 50", 42), ("!奖池 重置 1", 42),
                          ("!奖池 重置 1 2 3", 42), ("!奖池 重置 1.5 2", 42),
                          ("!奖池 重置 100001 2", 42), ("!奖池 重置 abc 2", 42)]:
            msg = self.message(text, uid)
            await self.m.on_dm(msg)
            self.assertEqual(self.m.store._data, {}, text)
            msg.channel.send.assert_awaited_once()

    async def test_query_and_help_do_not_mutate(self):
        for text in ["!奖池", "!pool help", "hello"]:
            await self.m.on_dm(self.message(text))
            self.assertEqual(self.m.store._data, {})

    async def test_refresh_failure_is_reported_without_repeating_reset(self):
        self.m.refresh_panel = AsyncMock(return_value=False)
        msg = self.message("!奖池 重置")
        await self.m.on_dm(msg)
        self.assertIn("暂未刷新", msg.channel.send.call_args.args[0])
        self.assertEqual(len(self.m.store.get("giveaway_stock_resets")), 1)

    async def test_dm_route_and_server_message_is_not_reset(self):
        from bot import Client
        fake = SimpleNamespace(modules=[self.m], config=self.config, store=self.m.store)
        with patch.object(self.m, "on_dm", new_callable=AsyncMock) as handler:
            await Client.on_message(fake, self.message("!奖池 重置"))
            handler.assert_awaited_once()
            handler.reset_mock()
            msg = self.message("!奖池 重置")
            msg.guild = SimpleNamespace(id=1)
            await Client.on_message(fake, msg)
            handler.assert_not_awaited()

    async def test_animation_stops_in_order_and_reveals_real_prize(self):
        self.feature["bypass_users"] = []
        prize = self.m.prize_by_key("bag10")
        itx = self.interaction()
        self.m.refresh_panel = AsyncMock(return_value=True)
        with patch("modules.giveaway.weighted_pick", return_value=prize), \
                patch("modules.giveaway.asyncio.sleep", new_callable=AsyncMock):
            await self.m.do_spin(itx)
        calls = itx.edit_original_response.call_args_list
        self.assertEqual(len(calls), 9)
        for stopped in range(1, 4):
            desc = calls[4 + stopped].kwargs["embed"].description
            self.assertTrue(desc.startswith("### " + "　│　".join([prize["emoji"]] * stopped)))
        self.assertIsInstance(calls[-1].kwargs["view"], DeliveryView)
        self.assertIn("10-Slot Bag", calls[-1].kwargs["embed"].description)
        self.assertEqual(self.m.stock_left("bag10"), 9)
        self.assertEqual(self.m.spins_used(55), 1)
        self.assertEqual(self.m.find_pending(55)["prize"], "bag10")
        self.assertEqual(self.m._spinning, set())

    async def test_simultaneous_click_is_blocked_and_lock_released(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def running(_):
            entered.set()
            await release.wait()
        with patch.object(self.m, "_do_spin", side_effect=running) as action:
            task = asyncio.create_task(self.m.do_spin(self.interaction()))
            await entered.wait()
            second = self.interaction()
            await self.m.do_spin(second)
            second.response.send_message.assert_awaited_once()
            self.assertEqual(action.call_count, 1)
            release.set()
            await task
        self.assertEqual(self.m._spinning, set())

    async def test_empty_stock_falls_back_to_existing_coupon(self):
        self.m.reset_stock(42, [0, 0])
        with patch("modules.giveaway.weighted_pick", return_value=self.m.prize_by_key("bag10")):
            self.assertEqual(self.m.draw()["key"], "coupon5")

    async def test_panel_readable_and_all_prizes_present(self):
        panel, = self.m.panel_payload()
        self.assertIn("### 🎒 Bags", panel.description)
        self.assertIn("### 🎟️ Coupons", panel.description)
        for prize in self.m.prizes:
            self.assertIn(prize["label"], panel.description)
        self.assertLess(len(panel), 1500)
        self.assertNotIn("<@", str(panel.to_dict()))
        self.assertTrue(GiveawayView(self.m).is_persistent())
        self.assertTrue(DeliveryView(self.m).is_persistent())

    async def test_one_spin_wins_coupon_and_second_click_is_rejected(self):
        self.feature["bypass_users"] = []
        self.assertEqual(self.m.spins_allowed(), 1)
        self.m.refresh_panel = AsyncMock(return_value=True)
        with patch("modules.giveaway.weighted_pick", return_value=self.m.prize_by_key("coupon5")) as draw, \
                patch("modules.giveaway.asyncio.sleep", new_callable=AsyncMock):
            first = self.interaction()
            await self.m.do_spin(first)
            second = self.interaction()
            await self.m.do_spin(second)
        self.assertEqual(draw.call_count, 1)
        self.assertEqual(self.m.spins_left(55), 0)
        self.assertEqual(len(self.m.store.get("giveaway_coupon_log")), 1)
        self.assertIn("wowexp", first.edit_original_response.call_args.kwargs["embed"].fields[0].value)
        second.response.send_message.assert_awaited_once()
        panel = self.m.panel_payload()[0]
        self.assertIn("1 free spin", panel.description)
        self.assertIn("Every spin wins", panel.description)
        for prize in self.m.prizes:
            self.assertNotIn("· %g%%" % prize["chance"], panel.description)


if __name__ == "__main__":
    unittest.main()
