"""Customer-safe order projection and persistent Discord interaction limits.

The injected reader must perform an exact site/game/order-number query. Never pass
its raw result to Discord, logs, or persistent state. Email lookup is not supported.
"""
import re
import sqlite3
import time
from contextlib import closing

ORDER_NUMBER = re.compile(r'D[0-9]{18}', re.ASCII)
UNAVAILABLE = 'Order service is temporarily unavailable. Please try again shortly.'
NOT_FOUND = 'No matching FC27 order was found. Check the complete order number or contact support.'
PROBLEM_SUPPORT = (
    '🔐 This may be caused by incorrect account login details or backup codes, '
    'but the specific reason has not been confirmed. Please contact support promptly '
    'or check your email for updates. Never share passwords or backup codes in this channel.')
# Customer-safe constants only; internal risk/dispute and unknown labels never escape.
STATUS = {
    '客服协助': 'Needs support',
    '问题订单': 'Needs support', '问题单': 'Needs support',
    '已完成': 'Completed', '完成': 'Completed', '处理中': 'Processing',
    '发货·发货中': 'Delivering', '已支付': 'Paid',
    '验证·通过': 'Verification complete', '验证·未通过': 'Needs support',
    '申请退款': 'Refund requested', '已退款·部分退款': 'Partially refunded',
    '已退款·其他原因': 'Refunded', '已退款·验证未通过': 'Refunded',
}


def order_not_found(payload):
    """Only an explicit successful empty query means no match in the fixed scope."""
    if not isinstance(payload, dict) or type(payload.get('code')) is not int or payload['code'] != 1:
        return False
    data = payload.get('data')
    return (isinstance(data, dict) and type(data.get('total')) is int
            and data['total'] == 0 and data.get('list') == [])


def project_order(payload, number):
    """Validate upstream scope and cardinality before emitting constant text only."""
    if not isinstance(number, str) or not ORDER_NUMBER.fullmatch(number):
        return None
    if not isinstance(payload, dict) or type(payload.get('code')) is not int or payload['code'] != 1:
        return None
    data = payload.get('data')
    if not isinstance(data, dict) or type(data.get('total')) is not int or data['total'] != 1:
        return None
    rows = data.get('list')
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return None
    row = rows[0]
    if (row.get('order_no') != number or str(row.get('site_id')) != '266'
            or str(row.get('gid')) != '1327'):
        return None
    raw_label = row.get('status_format')
    label = STATUS.get(raw_label, 'Needs support') if isinstance(raw_label, str) else 'Needs support'
    if raw_label in ('问题订单', '问题单'):
        support = PROBLEM_SUPPORT
    elif label == 'Delivering':
        support = ('🚚 Your order is being delivered and is expected to be ready soon! '
                   'While you wait, why not explore the fun features in our channels? 🎮 '
                   'Thanks for choosing MMOEXP!')
    elif label == 'Needs support':
        support = 'Support review required. The specific reason is not yet verified; please contact support.'
    else:
        support = 'Contact support if you need help with this order.'
    return {'status': label, 'support': support}


class InteractionStore:
    """SQLite transactions serialize limits and deduplicate likes across restarts."""
    def __init__(self, path, clock=time.time):
        self.path, self.clock = str(path), clock
        with closing(self.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS order_attempts '
                       '(guild INTEGER, user INTEGER, at REAL)')
            db.execute('CREATE INDEX IF NOT EXISTS order_attempt_actor '
                       'ON order_attempts(guild,user,at)')
            db.execute('CREATE TABLE IF NOT EXISTS order_likes '
                       '(guild INTEGER, user INTEGER, PRIMARY KEY(guild,user))')

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    @staticmethod
    def actor(guild, user):
        if any(type(value) is not int or value <= 0 for value in (guild, user)):
            raise ValueError('Invalid actor')

    def permit(self, guild, user):
        self.actor(guild, user)
        now = self.clock()
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM order_attempts WHERE at <= ?', (now - 3600,))
            own = db.execute('SELECT COUNT(*) FROM order_attempts '
                             'WHERE guild=? AND user=? AND at>?',
                             (guild, user, now - 600)).fetchone()[0]
            total = db.execute('SELECT COUNT(*) FROM order_attempts WHERE at>?',
                               (now - 60,)).fetchone()[0]
            if own >= 3 or total >= 20:
                return False
            db.execute('INSERT INTO order_attempts VALUES (?,?,?)', (guild, user, now))
            return True

    def like(self, guild, user):
        self.actor(guild, user)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO order_likes VALUES (?,?)', (guild, user))
            return db.execute('SELECT COUNT(*) FROM order_likes WHERE guild=?',
                              (guild,)).fetchone()[0]

    def first_reward(self, guild, user):
        """Claim one DM attempt durably; failed delivery remains retrievable privately."""
        self.actor(guild, user)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS order_rewards '
                       '(guild INTEGER, user INTEGER, PRIMARY KEY(guild,user))')
            db.execute('INSERT OR IGNORE INTO order_likes VALUES (?,?)', (guild, user))
            return db.execute('INSERT OR IGNORE INTO order_rewards VALUES (?,?)',
                              (guild, user)).rowcount == 1

    def eligible(self, guild, user):
        self.actor(guild, user)
        with closing(self.connect()) as db:
            return db.execute('SELECT 1 FROM order_likes WHERE guild=? AND user=?',
                              (guild, user)).fetchone() is not None

    def count(self, guild):
        self.actor(guild, 1)
        with closing(self.connect()) as db:
            return db.execute('SELECT COUNT(*) FROM order_likes WHERE guild=?',
                              (guild,)).fetchone()[0]


class OrderService:
    def __init__(self, reader, store):
        self.reader, self.store = reader, store

    def lookup(self, guild, user, number):
        if not self.store.permit(guild, user):
            return {'message': 'Too many requests. Please try again later.'}
        if not isinstance(number, str) or not ORDER_NUMBER.fullmatch(number):
            return {'message': NOT_FOUND}
        try:
            payload = self.reader(number)
            if order_not_found(payload):
                return {'message': NOT_FOUND}
            result = project_order(payload, number)
        except Exception:
            # Exception messages may contain upstream customer data or credentials.
            result = None
        return result or {'message': UNAVAILABLE}
