"""Daily topic scheduling for the FC27 community chat bot. Offline-safe."""

import datetime
import random
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/London')


def seconds_until_next(hour, now=None):
    now = (now or datetime.datetime.now(TZ)).astimezone(TZ)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return max(1.0, (target.astimezone(datetime.timezone.utc) -
                     now.astimezone(datetime.timezone.utc)).total_seconds())


def pick_topic(pool=None, rng=None):
    topics = [item.strip() for item in (pool or []) if isinstance(item, str) and item.strip()]
    return (rng or random).choice(topics) if topics else None
