"""Validate bot identity, connect and sync test-guild commands; sends no messages."""
import asyncio
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from community import CommunityStore
from content_bot import TEST_GUILD, build_client, load_config


async def check(token):
    config = load_config(ROOT / 'content.config.json')
    (ROOT / 'var').mkdir(exist_ok=True)
    client = build_client(config, CommunityStore(ROOT / 'var/community.sqlite3', config['staff_user_ids']))
    @client.event
    async def on_ready():
        guild = client.get_guild(TEST_GUILD)
        print(json.dumps({'connected': True, 'bot_id': client.user.id,
                          'test_guild_present': guild is not None, 'guild_id': TEST_GUILD}), flush=True)
        await client.close()
    try:
        await asyncio.wait_for(client.start(token), timeout=60)
    finally:
        await client.close()


def main():
    try:
        lines = (ROOT / '.secrets/discord.env').read_text(encoding='utf-8').splitlines()
        token = next(line.split('=', 1)[1] for line in lines if line.startswith('DISCORD_BOT_TOKEN='))
        request = urllib.request.Request('https://discord.com/api/v10/users/@me',
                                         headers={'Authorization': 'Bot ' + token, 'User-Agent': 'MMOEXP-FC-Pilot/1.0'})
        with urllib.request.urlopen(request, timeout=15) as response:
            identity = json.load(response)
        if identity.get('id') != '1568239618111832094' or not identity.get('bot'):
            raise ValueError('wrong identity')
        print('New application identity verified.', flush=True)
        asyncio.run(check(token))
    except Exception as exc:
        print('Connection check failed: ' + type(exc).__name__, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
