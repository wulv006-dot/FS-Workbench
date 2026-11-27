"""Resolve a squad question to one public post in the current FC chat."""
import re
from datetime import timedelta

SQUAD = re.compile(r'\b(?:squad|line[ -]?up|formation|striker|forward|midfielder|defender|winger|upgrade|replace)\b|阵容|前锋|换谁', re.I)
ASK = re.compile(r'\?|\b(?:need|suggest|recommend|replace|rate|thoughts|better|upgrade|help)\b|建议|推荐|换谁', re.I)
POINTS_BACK = re.compile(r'\b(?:posted|shared|above|earlier|screenshot|line[ -]?up|picture|his|her|their)\b|刚发|上面|截图', re.I)


def picture(post):
    for a in getattr(post, 'attachments', ()):
        if (a.content_type in ('image/png','image/jpeg','image/webp') and
                0 < a.size <= 8_000_000 and a.width and a.height):
            return a


async def resolve(message, text):
    """Prioritize attached or replied-to images, then an unambiguous recent post."""
    if not SQUAD.search(text):
        return None
    if picture(message):
        return message
    ref = message.reference
    if ref and ref.channel_id == message.channel.id and ref.message_id:
        post = ref.resolved
        if post is None:
            post = await message.channel.fetch_message(ref.message_id)
        if getattr(post, 'author', None) and not post.author.bot and post.content:
            return post
    if not POINTS_BACK.search(text):
        return None
    candidates = []
    async for post in message.channel.history(limit=45, before=message,
            after=message.created_at - timedelta(minutes=30), oldest_first=False):
        if post.author.bot or not post.content or not (picture(post) or SQUAD.search(post.content)):
            continue
        names = (post.author.display_name, post.author.name)
        if (post.author in message.mentions or any(re.search(
                r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, re.I) for name in names if name)):
            return post
        if SQUAD.search(post.content or ''):
            candidates.append(post)
    return candidates[0] if len(candidates) == 1 else None
