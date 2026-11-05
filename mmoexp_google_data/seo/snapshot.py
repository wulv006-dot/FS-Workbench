"""Verified immutable SQLite packages; read paths never import sources or Hermes."""
import contextlib
import datetime as dt
import hashlib
import json
import itertools
import os
import re
import sqlite3
import uuid
from pathlib import Path

from .contracts import GAMES, SCHEMA, SNAPSHOT_ID, BUSINESS_TZ, RANK_CONTRACT, game
from .metrics import compute_metrics
from .store import encode


def digest_file(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as inp:
        for chunk in iter(lambda: inp.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('x', encoding='utf-8') as out:
            out.write(encode(value))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
        if os.name != 'nt':
            fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


@contextlib.contextmanager
def batch_lock(root):
    with (Path(root) / 'batch.lock').open('a+b') as lock:
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            if lock.read(1) == b'':
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def current(root):
    path = Path(root) / 'current.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def daily_metrics(db, scope, day):
    measures, states = {}, {}
    for source in ('gsc', 'ga4', 'admin', 'orders'):
        coverage = db.execute('SELECT status,source_timezone,error,quality FROM coverage WHERE game=? AND source=? AND source_date=?', (scope,source,day)).fetchone()
        quality = json.loads(coverage[3]) if coverage else {}
        quality.pop('property_quota',None)
        states[source] = dict(status=coverage[0],source_timezone=coverage[1],error=coverage[2],quality=quality) if coverage else dict(status='missing')
        values = (json.loads(r[0])['metrics'] for r in db.execute('SELECT payload FROM facts WHERE game=? AND source=? AND source_date=? ORDER BY row_key',(scope,source,day)))
        first = next(values,None)
        zero = source == 'orders' and coverage and coverage[0] == 'available' and quality.get('expected_total') == 0
        measures[source] = compute_metrics(itertools.chain([first],values),source) if first is not None else compute_metrics([],source) if zero else None
    from .estimates import calculate
    return dict(source_date=day,metrics=measures,source_status=states,estimate=calculate(measures['ga4'],measures['admin']))


def facts_digest(db):
    result=hashlib.sha256()
    ordering=dict(facts='source,game,source_date,row_key',coverage='source,game,source_date',daily_metrics='game,source_date',reminders='game,row_key')
    for table,order in ordering.items():
        for row in db.execute('SELECT * FROM '+table+' ORDER BY '+order):
            if table=='coverage':
                quality=json.loads(row[6]);quality.pop('property_quota',None)
                projection=[row[0],row[1],row[2],row[3],row[4],quality]
            else:projection=list(row)
            result.update((encode([table,projection])+'\n').encode('utf-8'))
    return result.hexdigest()


def build(store, context, source_names=()):
    directory = store.root / 'snapshots'
    directory.mkdir(exist_ok=True)
    ident = 'seo-' + context.publication_date
    candidate = directory / (ident + '.' + uuid.uuid4().hex + '.tmp')
    connection = sqlite3.connect(str(candidate))
    try:
        with connection:
            # Fresh export prevents deleted working rows surviving in SQLite free pages.
            with store.db() as db:
                for table in ('facts','coverage'):
                    sql = db.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?',('table',table)).fetchone()[0]
                    connection.execute(sql)
                    fields = 5 if table == 'facts' else 8
                    for row in db.execute('SELECT * FROM '+table+' WHERE source_date BETWEEN ? AND ?',(context.history_start,context.report_date)):
                        connection.execute('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in range(fields))+')',tuple(row))
            connection.execute('CREATE TABLE daily_metrics(game TEXT,source_date TEXT,payload TEXT,PRIMARY KEY(game,source_date))')
            connection.execute('CREATE TABLE reminders(game TEXT,row_key INTEGER,payload TEXT,PRIMARY KEY(game,row_key))')
            from .rules import evaluate
            for scope in GAMES:
                history = []
                day = dt.date.fromisoformat(context.history_start)
                while day.isoformat() <= context.report_date:
                    row = daily_metrics(connection,scope,day.isoformat())
                    history.append(row)
                    connection.execute('INSERT INTO daily_metrics VALUES (?,?,?)',(scope,day.isoformat(),encode(row)))
                    day += dt.timedelta(days=1)
                for index, reminder in enumerate(evaluate(history)):
                    connection.execute('INSERT INTO reminders VALUES (?,?,?)',(scope,index,encode(reminder)))
            if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('INVALID_SNAPSHOT_DB')
            unknown = connection.execute('SELECT DISTINCT game FROM facts').fetchall()
            if any(row[0] not in GAMES for row in unknown):
                raise ValueError('INVALID_SNAPSHOT_SCOPE')
            facts = facts_digest(connection)
            status = 'partial' if connection.execute("SELECT 1 FROM coverage WHERE status NOT IN ('available','provisional') LIMIT 1").fetchone() else 'available'
            complete_days = connection.execute("SELECT COUNT(*) FROM coverage WHERE source IN ('gsc','ga4','admin') AND status IN ('available','provisional')").fetchone()[0]
            if complete_days < 30*len(GAMES)*3 or not {'gsc', 'ga4', 'admin'} <= set(source_names):
                status = 'partial'
    except BaseException:
        connection.close()
        candidate.unlink(missing_ok=True)
        raise
    connection.close()
    with candidate.open('r+b') as inp:
        os.fsync(inp.fileno())
    manifest = dict(schema_version=SCHEMA, snapshot_id=ident, publication_date=context.publication_date,
                    report_date=context.report_date, history_start=context.history_start, history_end=context.report_date,
                    business_timezone='Asia/Shanghai', games=list(GAMES), facts_hash=facts,
                    metric_contract='seo-metrics-v2-native-admin-estimate', rule_contract='seo-rules-v1',rank_contract=RANK_CONTRACT,
                    data_status=status, frozen=True, daytime_collection_enabled=False, sha256=digest_file(candidate),
                    sources={name:('configured' if name in source_names else 'not_configured') for name in ('gsc','ga4','admin','orders','serp','pages','calendar')})
    return candidate, manifest


def build_manual(store, base_ident, run_id):
    original,base=open_snapshot(store.root,base_ident)
    day=base['publication_date']
    if not isinstance(run_id,str) or not re.fullmatch('manual-seo-'+day.replace('-','')+r'T\d{6}Z',run_id):
        original.close();raise ValueError('INVALID_MANUAL_RUN')
    ident='seo-'+day+'-manual-'+hashlib.sha256(run_id.encode()).hexdigest()[:12]
    candidate=store.root/'snapshots'/(ident+'.'+uuid.uuid4().hex+'.tmp')
    connection=sqlite3.connect(str(candidate))
    try:
        original.backup(connection)
        with connection,store.db() as db:
            coverage=[r for r in db.execute("SELECT * FROM coverage WHERE source IN ('serp','calendar') AND source_date=?",(day,)) if json.loads(r['quality']).get('manual_run_id')==run_id]
            if not coverage:raise ValueError('MANUAL_OBSERVATIONS_NOT_FOUND')
            for row in coverage:
                key=(row['source'],row['game'],day)
                connection.execute('DELETE FROM facts WHERE source=? AND game=? AND source_date=?',key)
                for fact in db.execute('SELECT * FROM facts WHERE source=? AND game=? AND source_date=?',key):
                    observed=dt.datetime.fromisoformat(json.loads(fact['payload'])['observed_at'])
                    if observed.tzinfo is None or observed.astimezone(BUSINESS_TZ).date().isoformat()!=day:
                        raise ValueError('MANUAL_OBSERVATION_DATE_MISMATCH')
                    connection.execute('INSERT INTO facts VALUES (?,?,?,?,?)',tuple(fact))
                connection.execute('INSERT OR REPLACE INTO coverage VALUES (?,?,?,?,?,?,?,?)',tuple(row))
            if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('INVALID_SNAPSHOT_DB')
            facts=facts_digest(connection)
            ident='seo-'+day+'-manual-'+hashlib.sha256((run_id+':'+facts).encode()).hexdigest()[:12]
        meta=dict(base,sources=dict(base['sources']),snapshot_id=ident,facts_hash=facts,sha256=digest_file(candidate),
                  publication_mode='manual_observation',observation_date=day,manual_run_id=run_id,
                  base_snapshot_id=base.get('base_snapshot_id',base_ident),base_facts_hash=base.get('base_facts_hash',base['facts_hash']),
                  parent_snapshot_id=base_ident,rank_contract=RANK_CONTRACT,published_at=dt.datetime.now(dt.timezone.utc).isoformat())
        for source in {r['source'] for r in coverage}:meta['sources'][source]='configured'
        if any(r['status'] not in ('available','provisional') for r in coverage):meta['data_status']='partial'
    except BaseException:
        connection.close();candidate.unlink(missing_ok=True);raise
    finally:original.close()
    connection.close()
    with candidate.open('r+b') as stream:os.fsync(stream.fileno())
    return candidate,meta


def publish_once(root, candidate, manifest):
    root = Path(root)
    target = root / 'snapshots' / (manifest['snapshot_id'] + '.sqlite')
    meta = target.with_suffix('.json')
    if meta.exists():
        candidate.unlink(missing_ok=True)
        return json.loads(meta.read_text(encoding='utf-8'))
    if digest_file(candidate) != manifest['sha256']:
        raise ValueError('CANDIDATE_HASH_MISMATCH')
    os.replace(candidate, target)
    atomic_json(meta, manifest)
    atomic_json(root / 'current.json', manifest)
    return manifest


def open_snapshot(root, ident):
    if not re.fullmatch(SNAPSHOT_ID, ident):
        raise ValueError('INVALID_SNAPSHOT_ID')
    target = Path(root) / 'snapshots' / (ident + '.sqlite')
    if target.is_symlink():
        raise ValueError('SNAPSHOT_SYMLINK')
    meta = json.loads(target.with_suffix('.json').read_text(encoding='utf-8'))
    if meta['snapshot_id'] != ident or digest_file(target) != meta['sha256']:
        raise ValueError('SNAPSHOT_HASH_MISMATCH')
    db = sqlite3.connect(target.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    db.row_factory = sqlite3.Row
    return db, meta


def read(root, ident, kind, scope, cursor=0, limit=100):
    game(scope)
    if kind not in ('summary', 'history', 'sources', 'rankings', 'markets', 'calendar', 'pages', 'orders', 'rules') or not 0 <= cursor or not 1 <= limit <= 100:
        raise ValueError('INVALID_SNAPSHOT_QUERY')
    db, meta = open_snapshot(root, ident)
    try:
        if kind == 'sources':
            rows = [dict(r, quality=json.loads(r['quality'])) for r in db.execute(
                'SELECT * FROM coverage WHERE game=? ORDER BY source,source_date LIMIT ? OFFSET ?', (scope, limit + 1, cursor))]
        elif kind in ('summary', 'history'):
            query = 'SELECT payload FROM daily_metrics WHERE game=?'
            parameters = [scope]
            if kind == 'summary':
                query += ' AND source_date=?';parameters.append(meta['report_date'])
            query += ' ORDER BY source_date LIMIT ? OFFSET ?';parameters.extend([limit+1,cursor])
            rows = [json.loads(r[0]) for r in db.execute(query,parameters)]
        elif kind == 'rules':
            rows = [json.loads(r[0]) for r in db.execute('SELECT payload FROM reminders WHERE game=? ORDER BY row_key LIMIT ? OFFSET ?',(scope,limit+1,cursor))]
        else:
            source = dict(rankings='serp', markets='serp', calendar='calendar', pages='pages', orders='orders')[kind]
            latest = ' AND source_date=(SELECT MAX(b.source_date) FROM facts b WHERE b.source=a.source AND b.game=a.game'+(' AND b.row_key=a.row_key' if kind=='calendar' else '')+')' if kind in ('markets','calendar') else ''
            rows = [dict(source_date=r['source_date'], **json.loads(r['payload'])) for r in db.execute(
                'SELECT source_date,payload FROM facts a WHERE game=? AND source=?'+latest+' ORDER BY source_date DESC,row_key LIMIT ? OFFSET ?',
                (scope, source, limit + 1, cursor))]
        result=dict(snapshot_id=ident, facts_hash=meta['facts_hash'], game=scope, rows=rows[:limit],next_cursor=cursor+limit if len(rows)>limit else None)
        if kind=='markets':
            state=db.execute("SELECT source_date,status,error FROM coverage WHERE source='serp' AND game=? ORDER BY source_date DESC LIMIT 1",(scope,)).fetchone()
            result['source_state']=dict(state) if state else dict(status='missing')
        return result
    finally:
        db.close()
