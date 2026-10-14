"""Exact supported SQLite structure, inspection only; no repair or data reads."""
from contextlib import closing
import re
import sqlite3

NATIVE_SCHEMA = 'CREATE TABLE IF NOT EXISTS native_revocations(token_hash TEXT PRIMARY KEY,expires INTEGER NOT NULL)'


def sql_tokens(sql):
    # Normalize formatting/keyword case, preserving quoted values and identifiers.
    return tuple(t if t[0] in "'\"`[" else t.lower() for t in
        re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^\]]*\]|[A-Za-z_][A-Za-z_0-9]*|\d+|[^\s]",sql or ''))


def fingerprint(db):
    objects = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE substr(name,1,7) != 'sqlite_' ORDER BY type,name").fetchall()
    result = {'objects':tuple((r[0],r[1],r[2],sql_tokens(r[3])) for r in objects),'tables':{}}
    # Names originate only from schema. Quote rather than interpolate as code.
    def quoted(name): return '"'+name.replace('"','""')+'"'
    for kind,name,table,sql in objects:
        if kind != 'table': continue
        indexes=[]
        for row in db.execute('PRAGMA index_list('+quoted(name)+')'):
            # seq is enumeration order, not structural identity.
            indexes.append((row[1],row[2],row[3],row[4],
                tuple(tuple(x) for x in db.execute('PRAGMA index_xinfo('+quoted(row[1])+')'))))
        result['tables'][name] = {
            'columns':tuple(tuple(r) for r in db.execute('PRAGMA table_xinfo('+quoted(name)+')')),
            'foreign_keys':tuple(sorted(tuple(r) for r in db.execute('PRAGMA foreign_key_list('+quoted(name)+')'))),
            'indexes':tuple(sorted(indexes))}
    return result


def validate(db, schema, version):
    """Reject unknown structure, including extra triggers/tables/indexes/views.

    Same version is not a compatibility proof. Explicit migration review is
    required for conflicts; this function issues only SELECT/PRAGMA inspection.
    """
    if version not in (2,3): raise ValueError('unsupported schema version; explicit migration required')
    with closing(sqlite3.connect(':memory:')) as reference:
        reference.executescript(schema)
        if version == 3: reference.execute(NATIVE_SCHEMA)
        expected=fingerprint(reference)
    actual=fingerprint(db)
    if actual != expected:
        differences=[]
        if actual['objects'] != expected['objects']: differences.append('objects/SQL constraints/triggers')
        for name in sorted(set(actual['tables'])|set(expected['tables'])):
            if actual['tables'].get(name) != expected['tables'].get(name): differences.append(name+' columns/keys/indexes')
        raise ValueError('schema conflict; explicit migration required: '+', '.join(differences))
