"""Trigger routing and rate limits for the FC27 community chat bot. Offline-safe."""

import re
import time
from collections import OrderedDict

KINDS = ('mention', 'reply', 'topic', 'keyword')
DEFAULT_TRIGGER = '!drop'
ID_PATTERN = re.compile(r'[1-9][0-9]{16,19}')


def _is_id(value):
    return isinstance(value, str) and bool(ID_PATTERN.fullmatch(value))


def validate_chat_config(config):
    if not isinstance(config, dict):
        raise ValueError('Invalid chat config.')
    if not isinstance(config.get('enabled'), bool):
        raise ValueError('Invalid chat enabled flag.')
    routes = config.get('routes')
    if (not isinstance(routes, dict) or not 1 <= len(routes) <= 2
            or any(not _is_id(guild) for guild in routes)):
        raise ValueError('Invalid chat routes.')
    for guild, route in routes.items():
        if (not isinstance(route, dict) or set(route) - {'channels', 'keywords'}
                or not isinstance(route.get('channels'), dict) or not 1 <= len(route['channels']) <= 10):
            raise ValueError('Invalid chat guild route.')
        if any(not _is_id(channel) for channel in route['channels']):
            raise ValueError('Invalid chat channel id.')
        if not isinstance(route.get('keywords', []), list):
            raise ValueError('Invalid chat keywords.')
        for keyword in route.get('keywords', []):
            if not isinstance(keyword, str) or not 2 <= len(keyword) <= 32:
                raise ValueError('Invalid chat keyword.')
    per_user = config.get('per_user_seconds', 60)
    if not isinstance(per_user, int) or not 10 <= per_user <= 3600:
        raise ValueError('Invalid chat per_user_seconds.')
    per_channel = config.get('per_channel_per_minute', 6)
    if not isinstance(per_channel, int) or not 1 <= per_channel <= 30:
        raise ValueError('Invalid chat per_channel_per_minute.')
    budget = config.get('daily_budget', 400)
    if not isinstance(budget, int) or not 1 <= budget <= 10000:
        raise ValueError('Invalid chat daily_budget.')
    topic_channel = config.get('topic_channel')
    if topic_channel is not None and not _is_id(topic_channel):
        raise ValueError('Invalid chat topic_channel.')
    topic_channels = config.get('topic_channels')
    if topic_channels is not None and (
            not isinstance(topic_channels, list) or not 1 <= len(topic_channels) <= 2
            or any(not _is_id(channel) for channel in topic_channels)):
        raise ValueError('Invalid chat topic_channels.')
    topic_hour = config.get('topic_hour', 20)
    if not isinstance(topic_hour, int) or not 0 <= topic_hour <= 23:
        raise ValueError('Invalid chat topic_hour.')
    surprise = config.get('surprise')
    if surprise is not None:
        validate_surprise_config(surprise)
    return config


def topic_targets(config):
    """Channels that receive the daily topic. Falls back to the single key."""
    channels = config.get('topic_channels')
    if channels:
        return list(channels)
    single = config.get('topic_channel')
    return [single] if single else []


def validate_surprise_config(surprise):
    if surprise is None:
        return None
    if not isinstance(surprise, dict) or not isinstance(surprise.get('enabled'), bool):
        raise ValueError('Invalid chat surprise config.')
    if not surprise['enabled']:
        return surprise
    codes = surprise.get('codes')
    if not isinstance(codes, list) or not 1 <= len(codes) <= 20:
        raise ValueError('Invalid chat surprise codes.')
    if any(not isinstance(code, str) or not 3 <= len(code) <= 32 or not code.strip() or
           any(ch.isspace() for ch in code) for code in codes):
        raise ValueError('Invalid chat surprise code.')
    texts = surprise.get('texts', [])
    if not isinstance(texts, list) or len(texts) > 20:
        raise ValueError('Invalid chat surprise texts.')
    if any(not isinstance(text, str) or not 1 <= len(text) <= 200 for text in texts):
        raise ValueError('Invalid chat surprise text.')
    trigger = surprise.get('trigger', DEFAULT_TRIGGER)
    if (not isinstance(trigger, str) or not 2 <= len(trigger) <= 16
            or not trigger.startswith('!') or any(ch.isspace() for ch in trigger)):
        raise ValueError('Invalid chat surprise trigger.')
    limit = surprise.get('daily_limit', 3)
    if not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ValueError('Invalid chat surprise daily_limit.')
    cooldown = surprise.get('cooldown_seconds', 600)
    if not isinstance(cooldown, int) or not 0 <= cooldown <= 86400:
        raise ValueError('Invalid chat surprise cooldown_seconds.')
    return surprise



# Stickers: the club has a set of animated MMOEXP stickers. We never let the model choose
# asset ids; we only match a mood keyword in the finished reply against sticker names that
# actually exist in the guild. Commerce-style stickers stay out of automatic use so the bot
# never looks like it is selling something.
STICKER_RULES = (
    ('birthday', ('happy birthday',), ('happy birthday',)),
    ('holiday', ('happy holiday', 'merry christmas', 'new year'), ('happy holiday',)),
    ('brb', ('brb', 'back in a bit', 'be right back'), ('brb',)),
    ('laugh', ('ha!', 'haha', ' lol', 'lmao', 'kidding', 'joking'), ('lmao',)),
    ('sympathy', ('sorry', 'oof', 'rip ', 'bad luck', 'brutal', 'painful'), ('oof...',)),
    ('hype', ("let's go", 'lets go', 'pog', 'clutch', 'unreal', 'what a ', 'huge'), ('poggers', "let's go", 'nice!')),
    ('nice', ('nice', 'gj', 'well played', 'sweet'), ('nice!',)),
    ('pull', ('pulled', 'packed', 'got him', "it's in"), ("it's in",)),
    ('thinking', ('not sure', 'depends', 'no idea', 'hmm', 'maybe'), ('hmm...',)),
    ('working', ('checking', 'give me a sec', 'looking into', 'one sec'), ('working on it',)),
    ('greeting', ('hey ', 'hello', 'hi there', 'welcome'), ('hey there',)),
)

NEVER_AUTO = frozenset({'express delivery', "you're insured", 'hot deal'})


def pick_sticker_name(reply_text, available_names, rng=None):
    """Return the guild sticker name that fits the reply, or None.

    Matching is keyword based on purpose: the model never picks asset ids, and a
    sticker is only used when the guild really has one with that name.
    """
    by_lower = {}
    for name in available_names or ():
        clean = str(name).strip()
        low = clean.lower()
        if not clean or low in NEVER_AUTO:
            continue
        by_lower.setdefault(low, clean)
    text = ' ' + (reply_text or '').lower() + ' '
    for _mood, keywords, candidates in STICKER_RULES:
        for keyword in keywords:
            if keyword not in text:
                continue
            for candidate in candidates:
                if candidate in by_lower:
                    return by_lower[candidate]
            break
    return None


class ChatLimiter:
    """Per-user cooldown, per-channel minute window and a daily reply budget."""

    def __init__(self, per_user_seconds=60, per_channel_per_minute=6, daily_budget=400):
        self.per_user_seconds = per_user_seconds
        self.per_channel_per_minute = per_channel_per_minute
        self.daily_budget = daily_budget
        self.users = OrderedDict()
        self.channels = OrderedDict()
        self.day = None
        self.replies = 0

    def _roll_day(self, now):
        day = time.strftime('%Y%m%d', time.gmtime(now))
        if day != self.day:
            self.day = day
            self.replies = 0

    def allow(self, user_id, channel_id, now=None):
        now = time.time() if now is None else now
        self._roll_day(now)
        if self.replies >= self.daily_budget:
            return False
        last = self.users.get(user_id)
        if last is not None and now - last < self.per_user_seconds:
            return False
        window = [stamp for stamp in self.channels.get(channel_id, []) if now - stamp < 60]
        if len(window) >= self.per_channel_per_minute:
            return False
        return True

    def purge_user(self, user_id):
        """Forget one account's in-memory rate-limit state (privacy deletion)."""
        return self.users.pop(user_id, None) is not None

    def record(self, user_id, channel_id, now=None):
        now = time.time() if now is None else now
        self.users[user_id] = now
        window = [stamp for stamp in self.channels.get(channel_id, []) if now - stamp < 60]
        window.append(now)
        self.channels[channel_id] = window
        self.replies += 1


class ChatRouter:
    """Decides whether one message should get an AI reply, and under which trigger."""

    def __init__(self, config):
        validate_chat_config(config)
        self.routes = {guild: {'channels': set(route['channels']),
                               'keywords': [kw.lower() for kw in route.get('keywords', [])]}
                       for guild, route in config['routes'].items()}

    def route(self, guild_id, channel_id, author_id, is_bot, content, mentioned_bot=False,
              replied_to_bot=False, in_topic=False, content_intent=True):
        """Pick the trigger for one message.

        Without the MESSAGE_CONTENT privileged intent Discord only delivers the
        text of messages that mention the app (plus DMs and its own messages),
        so every other trigger is unusable then and must be ignored rather than
        silently replying to empty strings.
        """
        route = self.routes.get(str(guild_id))
        if route is None or is_bot:
            return None
        if str(channel_id) not in route['channels'] and not in_topic:
            return None
        if mentioned_bot:
            return 'mention'
        if not content_intent:
            return None
        if replied_to_bot:
            return 'reply'
        if in_topic:
            return 'topic'
        lowered = (content or '').lower()
        if route['keywords'] and any(keyword in lowered for keyword in route['keywords']):
            return 'keyword'
        return None

    def in_scope(self, guild_id, channel_id):
        """True when the channel is one this bot is configured to talk in."""
        route = self.routes.get(str(guild_id))
        return route is not None and str(channel_id) in route['channels']


class SurpriseDrop:
    """Staff-triggered, rate-limited coupon drop. Picks one configured code at random."""

    def __init__(self, config, staff_ids, rng=None):
        surprise = validate_surprise_config(config.get('surprise'))
        if surprise is None or not surprise['enabled']:
            raise ValueError('Chat surprise drop is not enabled.')
        self.trigger = surprise.get('trigger', DEFAULT_TRIGGER)
        self.codes = list(surprise['codes'])
        self.texts = list(surprise.get('texts', []))
        self.daily_limit = surprise.get('daily_limit', 3)
        self.cooldown = surprise.get('cooldown_seconds', 600)
        self.staff = {str(value) for value in staff_ids}
        self.rng = rng
        self.day = None
        self.count = 0
        self.last = 0.0

    def is_trigger(self, content):
        return (content or '').strip().lower() == self.trigger.lower()

    def is_staff(self, author_id):
        return str(author_id) in self.staff

    def _roll_day(self, now):
        day = time.strftime('%Y%m%d', time.gmtime(now))
        if day != self.day:
            self.day = day
            self.count = 0

    def allow(self, now=None):
        now = time.time() if now is None else now
        self._roll_day(now)
        if self.count >= self.daily_limit:
            return False
        return now - self.last >= self.cooldown

    def draw(self):
        choice = (self.rng or __import__('random')).choice
        code = choice(self.codes)
        text = choice(self.texts) if self.texts else ''
        return code, text

    def record(self, now=None):
        now = time.time() if now is None else now
        self._roll_day(now)
        self.count += 1
        self.last = now
