"""Self-contained checks for the recorded recovery; no live config or Discord."""
import ast
import asyncio
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

import discord

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fcvip6_restore', ROOT / 'deploy/restore_fcvip6_20261115.py')
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


class RecoveryTests(unittest.TestCase):
    def test_precise_patch_and_config_preservation(self):
        order = ("REWARDS_PAUSED = True\n"
                 "description = str(('Discount rewards are temporarily paused.'))\n"
                 "COUPON = ('Thank you! Your code: **FCVIP6** · **6% off**. '\n"
                 "          'Final eligibility and price are confirmed at checkout.')\n")
        config = {'other': [1, 2], 'chat_bot': {'surprise': {'enabled': False,
            'codes': ['FCVIP6'], 'texts': ['Limited'], 'daily_limit': 3,
            'cooldown_seconds': 600}, 'staff_ids': ['123']}}
        original = {'order_panel.py': order.encode(), 'chat_service.py':
            b"description=text or 'Limited discount code'\ntext='Limited quantity, final price at checkout'\n",
            'content.chat.config.json': json.dumps(config).encode()}
        changed = restore.candidates(original)
        result = json.loads(changed['content.chat.config.json'])
        self.assertTrue(result['chat_bot']['surprise']['enabled'])
        self.assertEqual(result['chat_bot']['surprise']['texts'], [restore.TEXT])
        result['chat_bot']['surprise']['enabled'] = False
        result['chat_bot']['surprise']['texts'] = ['Limited']
        self.assertEqual(result, config)
        self.assertIn(b'REWARDS_PAUSED = False', changed['order_panel.py'])
        with self.assertRaises(ValueError):
            restore.candidates(changed)

    def test_rendered_drop_has_no_false_scarcity(self):
        tree = ast.parse((ROOT / 'chat_service.py').read_text(encoding='utf-8'))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
                      and n.name == 'post_surprise')
        namespace = {'discord': discord}
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'drop', 'exec'), namespace)
        channel = AsyncMock()
        asyncio.run(namespace['post_surprise'](None, channel, 'FCVIP6', restore.TEXT))
        embed = channel.send.await_args.kwargs['embed']
        self.assertEqual(embed.description, restore.TEXT)
        self.assertEqual(embed.footer.text, 'Eligibility and final price confirmed at checkout')
        self.assertEqual(embed.fields[0].value, '`FCVIP6`')


if __name__ == '__main__':
    unittest.main()
