"""Fail-closed external rollback witness; never exports database records.

Not a defense against an operator restoring DB and witness together. Such a
restore is prohibited; reviewed disaster recovery must retain latest ledger.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile


def state_digest(db):
    digest = hashlib.sha256()
    names = sorted(row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
    for name in names:
        quoted = '"' + name.replace('"', '""') + '"'
        # Only hashes are persisted; original rows never leave this process.
        rows = sorted(json.dumps(tuple(row), ensure_ascii=False, separators=(',', ':'))
            for row in db.execute('SELECT * FROM ' + quoted))
        digest.update(json.dumps([name, rows], ensure_ascii=False, separators=(',', ':')).encode())
    return digest.hexdigest()


def write(path, value, sync_dir):
    fd, stage = tempfile.mkstemp(prefix='.checkpoint-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(value, output, sort_keys=True, separators=(',', ':'))
            output.flush(); os.fsync(output.fileno())
        os.replace(stage, path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(stage): os.unlink(stage)


def read(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or set(value) != {'version', 'generation', 'status', 'digest'}
        or value['version'] != 1 or type(value['generation']) is not int
        or value['generation'] < 0 or value['status'] != 'ready'
        or not isinstance(value['digest'], str) or len(value['digest']) != 64):
        raise ValueError('uncommitted/conflicting checkpoint; reviewed recovery required')
    return value
