"""Private, revocable opt-in for the current London prediction week.

Only a keyed digest of the Discord ID is persisted. A future partner handoff
can check a supplied ID against this ledger without exporting member lists.
"""

import datetime as dt
import hashlib
import hmac
import sqlite3
import time
from pathlib import Path
from zoneinfo import ZoneInfo


LONDON = ZoneInfo('Europe/London')
RETENTION_SECONDS = 35 * 86400


def current_week(now=None):
    instant = dt.datetime.fromtimestamp(time.time() if now is None else now,
                                        dt.timezone.utc).astimezone(LONDON)
    year, week, _ = instant.isocalendar()
    return '{}-W{:02d}'.format(year, week)


class WeeklyRewardConsent:
    def __init__(self, path, secret):
        if not isinstance(secret, str) or len(secret) < 32:
            raise ValueError('A separate weekly consent key is required')
        self.path = str(Path(path))
        self.key = secret.encode('utf-8')
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS weekly_reward_consent (
                guild_id TEXT NOT NULL,
                week_key TEXT NOT NULL,
                player_digest TEXT NOT NULL,
                agreed_at INTEGER NOT NULL,
                PRIMARY KEY (guild_id, week_key, player_digest)
            )''')
        self.purge_expired()

    def purge_expired(self, now=None):
        cutoff = int(time.time() if now is None else now) - RETENTION_SECONDS
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute('DELETE FROM weekly_reward_consent WHERE agreed_at<?', (cutoff,))

    def _digest(self, guild_id, player_id, week_key):
        if not (str(guild_id).isdigit() and str(player_id).isdigit()):
            raise ValueError('Discord IDs are required')
        value = '{}:{}:{}'.format(guild_id, week_key, player_id).encode('ascii')
        return hmac.new(self.key, value, hashlib.sha256).hexdigest()

    def agree(self, guild_id, player_id, now=None):
        week_key = current_week(now)
        digest = self._digest(guild_id, player_id, week_key)
        self.purge_expired(now)
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute('''INSERT OR IGNORE INTO weekly_reward_consent
                (guild_id, week_key, player_digest, agreed_at) VALUES (?,?,?,?)''',
                (str(guild_id), week_key, digest, int(time.time() if now is None else now)))
        return week_key

    def withdraw(self, guild_id, player_id, now=None):
        week_key = current_week(now)
        digest = self._digest(guild_id, player_id, week_key)
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute('''DELETE FROM weekly_reward_consent
                WHERE guild_id=? AND week_key=? AND player_digest=?''',
                (str(guild_id), week_key, digest))
        return week_key

    def has_consent(self, guild_id, player_id, week_key):
        digest = self._digest(guild_id, player_id, week_key)
        with sqlite3.connect(self.path, timeout=10) as db:
            return db.execute('''SELECT 1 FROM weekly_reward_consent
                WHERE guild_id=? AND week_key=? AND player_digest=?''',
                (str(guild_id), week_key, digest)).fetchone() is not None
