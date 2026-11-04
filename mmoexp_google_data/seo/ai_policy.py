"""Local FS controls and audit survive Hermes outages; no model imports."""
import contextlib
import datetime as dt
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .contracts import GAMES, game
from .store import encode


@dataclass(frozen=True)
class Actor:
    id: str
    games: tuple
    manage: bool = False
    analyze: bool = False


class PolicyStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS policy(id INTEGER PRIMARY KEY,body TEXT);'
                             'CREATE TABLE IF NOT EXISTS audit(revision INTEGER PRIMARY KEY,actor TEXT,at TEXT,patch TEXT);')
            initial = dict(revision=0, ai_enabled=False, generation=0,
                           projects={g:dict(ai_enabled=False, generation=0) for g in GAMES})
            db.execute('INSERT OR IGNORE INTO policy VALUES (1,?)', (encode(initial),))

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(str(self.root/'policy.db'), timeout=2)
        try:
            with db:
                yield db
        finally:
            db.close()

    def read(self):
        with self.db() as db:
            return json.loads(db.execute('SELECT body FROM policy WHERE id=1').fetchone()[0])

    def token(self, scope):
        policy = self.read()
        return policy['generation'], policy['projects'][game(scope)]['generation']

    def allowed(self, scope, actor, token=None):
        game(scope)
        if not actor.analyze or scope not in actor.games:
            return False
        try:
            policy = self.read()
        except (OSError, sqlite3.Error, ValueError):
            return False
        project = policy['projects'][scope]
        return bool(policy['ai_enabled'] and project['ai_enabled'] and
                    (token is None or tuple(token) == (policy['generation'], project['generation'])))

    def update(self, patch, expected_revision, actor):
        if not actor.id or not actor.manage:
            raise PermissionError('SEO_SETTINGS_DENIED')
        if not isinstance(patch, dict) or set(patch)-{'ai_enabled', 'projects'} or type(expected_revision) is not int:
            raise ValueError('INVALID_POLICY_PATCH')
        projects = patch.get('projects', {})
        if not isinstance(projects, dict) or set(projects)-set(actor.games) or any(type(v) is not bool for v in projects.values()) or ('ai_enabled' in patch and type(patch['ai_enabled']) is not bool):
            raise ValueError('INVALID_POLICY_SCOPE')
        if 'ai_enabled' in patch and set(actor.games) != set(GAMES):
            raise PermissionError('SEO_GLOBAL_SETTINGS_DENIED')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            policy = json.loads(db.execute('SELECT body FROM policy WHERE id=1').fetchone()[0])
            if policy['revision'] != expected_revision:
                raise ValueError('POLICY_REVISION_CONFLICT')
            if 'ai_enabled' in patch and patch['ai_enabled'] != policy['ai_enabled']:
                policy['ai_enabled'] = patch['ai_enabled']
                policy['generation'] += 1
            for scope, enabled in projects.items():
                project = policy['projects'][game(scope)]
                if project['ai_enabled'] != enabled:
                    project['ai_enabled'] = enabled
                    project['generation'] += 1
            policy['revision'] += 1
            db.execute('UPDATE policy SET body=? WHERE id=1', (encode(policy),))
            db.execute('INSERT INTO audit VALUES (?,?,?,?)',
                       (policy['revision'], actor.id, dt.datetime.now(dt.timezone.utc).isoformat(), encode(patch)))
            return policy
