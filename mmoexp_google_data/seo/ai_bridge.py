"""Optional per-game worker. Production provider integration remains explicitly unconfigured."""
import contextlib
import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path

from .contracts import GAMES, make_daily_context
from .snapshot import read, batch_lock
from .store import encode


class Bridge:
    def __init__(self, core_root, root, policy, actor, provider=None,
                 clock=lambda: dt.datetime.now(dt.timezone.utc)):
        self.core_root, self.root = Path(core_root), Path(root)
        self.policy, self.actor, self.provider, self.clock = policy, actor, provider, clock
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS reports(snapshot_id TEXT,game TEXT,status TEXT,
                generation TEXT,facts_hash TEXT,text TEXT,provider_receipt TEXT,usage TEXT,
                provider_ref TEXT,report_hash TEXT, PRIMARY KEY(snapshot_id,game))''')

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(str(self.root/'ai.db'), timeout=2)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def status(self, ident, scope):
        with self.db() as db:
            row = db.execute('SELECT * FROM reports WHERE snapshot_id=? AND game=?', (ident, scope)).fetchone()
            return dict(row) if row else dict(status='not_run', text=None)

    def run(self, ident):
        context = make_daily_context(self.clock())
        if not context.publication_allowed:
            return dict(status='outside_night_window', ready=0)
        if ident != 'seo-' + context.publication_date:
            return dict(status='historical_auto_run_disabled', ready=0)
        if self.provider is None:
            return dict(status='not_configured', ready=0)
        ready = 0
        with batch_lock(self.root):
            for scope in GAMES:
                if not self.policy.allowed(scope, self.actor):
                    continue
                token = self.policy.token(scope)
                history = read(self.core_root, ident, 'history', scope)
                payload = dict(snapshot_id=ident, facts_hash=history['facts_hash'], game=scope,
                               facts=dict(game=scope, history=history['rows']))
                def gate():
                    if not make_daily_context(self.clock()).publication_allowed or not self.policy.allowed(scope, self.actor, token):
                        raise PermissionError('SEO_AI_CANCELLED')
                with self.db() as db:
                    if db.execute('SELECT 1 FROM reports WHERE snapshot_id=? AND game=?', (ident, scope)).fetchone():
                        continue
                    db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?,?)',
                               (ident, scope, 'running', encode(token), history['facts_hash'], None, None, None, None, None))
                try:
                    gate()
                    # The provider must use its existing permission/budget ledger and call gate before every tool/model request.
                    response = self.provider(payload, gate)
                    if not isinstance(response.get('text'), str) or not response.get('receipt'):
                        raise ValueError('AI_PROVIDER_RECEIPT_REQUIRED')
                    permitted = self.policy.allowed(scope, self.actor, token) and make_daily_context(self.clock()).publication_allowed
                    text = response['text'] if permitted else None
                    with self.db() as db:
                        db.execute('UPDATE reports SET status=?,text=?,provider_receipt=?,usage=?,provider_ref=?,report_hash=? WHERE snapshot_id=? AND game=?',
                            ('ready' if permitted else 'cancelled', text, response['receipt'], encode(response.get('usage')),
                             response.get('provider_ref'), hashlib.sha256(text.encode()).hexdigest() if text else None, ident, scope))
                    ready += int(permitted)
                except PermissionError:
                    with self.db() as db:
                        db.execute("UPDATE reports SET status='cancelled' WHERE snapshot_id=? AND game=?", (ident, scope))
                except (OSError, ValueError, RuntimeError):
                    # A submitted request with no receipt is UNKNOWN; never automatically replay it.
                    with self.db() as db:
                        db.execute("UPDATE reports SET status='unknown' WHERE snapshot_id=? AND game=?", (ident, scope))
        return dict(status='completed', ready=ready)
