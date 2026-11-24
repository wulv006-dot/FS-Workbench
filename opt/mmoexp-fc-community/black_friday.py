"""FC27 Black Friday 2026. Inputs are normalized, complete server-side order records."""
import sqlite3
from contextlib import closing
from datetime import datetime

ORDER_START = datetime.fromisoformat('2026-10-01T00:00:00+08:00')


def reward_tier(orders, as_of):
    paid, completed = set(), set()
    for row in orders:
        if row['site'] != 266:
            continue
        if type(row['paid']) is not bool or row['status'] not in ('open','complete','refunded','cancelled'):
            raise ValueError('Unknown order state')
        if not row['paid'] or row['status'] in ('refunded','cancelled'):
            continue
        stamp = datetime.fromisoformat(row['paid_at'].replace('Z','+00:00'))
        if ORDER_START <= stamp <= as_of:
            paid.add(row['id'])
            if row['status'] == 'complete':
                completed.add(row['id'])
    if len(completed) >= 5:
        return 'bonus'
    return 'two' if paid else 'one'


class ClaimStore:
    """One DB per campaign and environment. No emails or raw orders are stored."""
    def __init__(self, path):
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS claims (discord_id INTEGER PRIMARY KEY, '
                       'member_id INTEGER UNIQUE NOT NULL, tier TEXT NOT NULL)')

    def claim(self, discord_id, member_id, tier):
        if any(type(i) is not int or i <= 0 for i in (discord_id,member_id)) or tier not in ('one','two','bonus'):
            raise ValueError('Invalid claim')
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT discord_id, member_id, tier FROM claims '
                             'WHERE discord_id=? OR member_id=?', (discord_id,member_id)).fetchone()
            if row is not None:
                if row[:2] == (discord_id,member_id):
                    return row[2], False
                raise ValueError('This account already participated')
            db.execute('INSERT INTO claims VALUES(?,?,?)', (discord_id,member_id,tier))
            return tier, True
