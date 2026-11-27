"""Opening announcements for every session in the live Carnival schedule."""
import asyncio
from datetime import datetime, timezone, timedelta

import aiohttp
import discord

EVENT = 'https://www.mmoexp.com/events/Carnival.html'
FC27_ROLE_ID = 1568664882650288159
SCHEDULE = 'http://127.0.0.1:8949/events/api/carnival/schedule'


async def run(client, guild_id, channel_id):
    await client.wait_until_ready()
    sent = set()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as http:
        while not client.is_closed():
            delay = 60
            try:
                async with http.get(SCHEDULE) as response:
                    response.raise_for_status()
                    data = await response.json()
                if data.get('test'):
                    raise ValueError('test schedule')
                now = datetime.now(timezone.utc)
                if now >= datetime.fromisoformat(data['ends_at']):
                    return
                for row in data['sessions']:
                    raw = row['starts_at']
                    if raw in sent:
                        continue
                    start = datetime.fromisoformat(raw)
                    end = datetime.fromisoformat(row['ends_at'])
                    if now < start:
                        delay = min(delay, max(1, (start - now).total_seconds()))
                        continue
                    if row['status'] != 'live' or now >= min(end, start + timedelta(minutes=10)):
                        continue
                    products = [p['name'] for p in row['products'] if p.get('game') == 'FC 27']
                    if not products:
                        continue
                    channel = client.get_channel(channel_id)
                    if channel is None or channel.guild.id != guild_id:
                        raise RuntimeError('FC chat unavailable')
                    marker = 'MMOEXP Carnival | ' + raw
                    already_sent = False
                    async for msg in channel.history(after=start - timedelta(seconds=5), limit=None):
                        if msg.author.id == client.user.id and any(
                                e.footer.text == marker for e in msg.embeds):
                            already_sent = True
                            break
                    if not already_sent:
                        embed = discord.Embed(title='⚡ Black Friday flash sale is live',
                            description='Featured in FC 27 today:\n' + '\n'.join('• ' + p for p in products[:4])
                            + '\n\nEnds <t:{}:R>. Check the event for availability.'.format(int(end.timestamp())),
                            color=0xf5aa36)
                        embed.set_footer(text=marker)
                        view = discord.ui.View()
                        view.add_item(discord.ui.Button(label='Open Black Friday sale', url=EVENT))
                        await channel.send(content=f'<@&{FC27_ROLE_ID}>', embed=embed, view=view,
                            allowed_mentions=discord.AllowedMentions(
                                everyone=False, users=False, roles=[discord.Object(id=FC27_ROLE_ID)],
                                replied_user=False))
                    sent.add(raw)
            except (aiohttp.ClientError, asyncio.TimeoutError, discord.DiscordException,
                    KeyError, TypeError, ValueError, RuntimeError) as exc:
                print('Carnival reminder: {}'.format(type(exc).__name__), flush=True)
            await asyncio.sleep(delay)
