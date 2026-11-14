"""Daily topic scheduling for the FC27 community chat bot. Offline-safe."""

import datetime
import random
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')

DEFAULT_TOPICS = [
    'Morning everyone, come say hi and tell me what you are working on this week.',
    'I am around for the next few hours, ask me anything about FC 27.',
    'Quick one: what is the first thing you check when you log in?',
    'Anyone stuck on something? Squads, SBCs, evolutions, just ask.',
    'Drop a question and let us figure it out together.',
    'What are you grinding for right now? Tell me and I will jump in.',
    'New here? Say hello and ask me anything, no question is too basic.',
]


def seconds_until_next(hour, now=None):
    now = now or datetime.datetime.now(TZ)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return max(1.0, (target - now).total_seconds())


def pick_topic(pool=None, rng=None):
    topics = [item.strip() for item in (pool or []) if isinstance(item, str) and item.strip()]
    if not topics:
        topics = DEFAULT_TOPICS
    return (rng or random).choice(topics)
