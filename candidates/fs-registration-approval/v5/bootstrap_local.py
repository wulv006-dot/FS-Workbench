"""Recoverable synthetic initialization only. Caller holds Namespace.fence."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from contextlib import closing
from auth_candidate import SCHEMA
from schema_contract import validate as validate_schema


def atomic_write(path, content, staged=lambda: None):
    fd, name = tempfile.mkstemp(prefix='synthetic-init-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(content); fh.flush(); os.fsync(fh.fileno())
        staged()
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def initialize(root, portal, password, checkpoint=lambda phase: None):
    root = Path(root); journal = root/'synthetic-init.json'; dbpath = root/'candidate.sqlite3'
    for p in [journal, dbpath, *map(Path, portal.GROUPS.values())]:
        if p.is_symlink(): raise ValueError('synthetic initialization link rejected')
    encoded = portal.apr1_md5(password, 'local123')
    expected = {}
    for group, path in portal.GROUPS.items():
        names = sorted(portal._fs_policy.ADMINS) + (['synthetic.native.reader'] if group == 'dashboard' else [])
        expected[Path(path).name] = ''.join(n+':'+encoded+'\n' for n in names).encode()
    hashes = {n:hashlib.sha256(b).hexdigest() for n,b in expected.items()}
    if not journal.exists():
        if dbpath.exists():
            # Frozen schema2/3 sandboxes predate the journal: preserve every byte.
            # Registry validates the version; no missing source is repaired here.
            if not all(Path(p).is_file() for p in portal.GROUPS.values()):
                raise ValueError('existing database has incomplete identity sources')
            return False
        if any((root/n).exists() for n in expected):
            raise ValueError('unowned initialization files; explicit recovery required')
        state = {'version':1, 'kind':'local-synthetic-only', 'phase':'creating', 'files':hashes}
        atomic_write(journal, (json.dumps(state,sort_keys=True)+'\n').encode(),lambda:checkpoint('journal_staged'))
    else:
        state = json.loads(journal.read_text(encoding='utf-8'))
        if state.get('version') != 1 or state.get('kind') != 'local-synthetic-only' or state.get('phase') not in ('creating','ready'):
            raise ValueError('unknown initialization state')
        if state['phase'] == 'ready':
            if not dbpath.is_file() or not all(Path(p).is_file() for p in portal.GROUPS.values()):
                raise ValueError('ready sandbox incomplete; no automatic reseed')
            return False
        if state.get('files') != hashes: raise ValueError('initialization source contract changed')
    checkpoint('journal')
    for group, path in portal.GROUPS.items():
        p = Path(path); content = expected[p.name]
        if p.exists():
            if not p.is_file() or p.read_bytes() != content:
                raise ValueError('unknown partial identity contents; no overwrite')
        else: atomic_write(p, content,lambda:checkpoint('group_'+group+'_staged'))
        checkpoint('group_'+group)
    with closing(sqlite3.connect(dbpath, timeout=10)) as db:
        checkpoint('database_opened')
        db.execute('PRAGMA synchronous=FULL')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if version == 0 and not tables:
            # Transactional DDL survives real process death as empty or complete.
            db.executescript('BEGIN IMMEDIATE;\n'+SCHEMA)
            checkpoint('schema_before_commit')
            db.commit()
        elif version not in (2,3): raise ValueError('unknown partial database; no overwrite')
        elif not {'users','requests','sessions','audit','limits'} <= {row[0] for row in tables}:
            raise ValueError('incomplete database schema; no overwrite')
        validate_schema(db, SCHEMA, db.execute('PRAGMA user_version').fetchone()[0])
    checkpoint('schema_committed')
    return True


def mark_ready(root, checkpoint=lambda phase: None):
    p = Path(root)/'synthetic-init.json'
    state = json.loads(p.read_text(encoding='utf-8'))
    state['phase'] = 'ready'
    atomic_write(p,(json.dumps(state,sort_keys=True)+'\n').encode())
    checkpoint('ready')
