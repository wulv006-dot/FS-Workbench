"""Stored material metadata for connectors; never enter the execution/recovery path."""
from contextlib import closing, contextmanager
import json
from pathlib import Path
import re
import sqlite3
import time


@contextmanager
def _database(path):
    path = Path(path).absolute()
    if not path.is_file() or any(part.is_symlink() for part in (path, *path.parents)):
        raise OSError('material_read_store_unavailable')
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            yield db
    except sqlite3.Error:
        raise OSError('material_read_store_unavailable') from None


def _owned(service, user, cid, authorized):
    if not user or not authorized(user):
        raise PermissionError('material_read_denied')
    with _database(service.store.path) as db:
        service.store._owned(db, user, cid)


def _files(store, cid, generated):
    rows = []
    for item in generated:
        if not isinstance(item, dict) or not re.fullmatch('[a-f0-9]{32}', item.get('file_id', '')):
            raise ValueError('material_file_identity')
        row = {key: item[key] for key in ('file_id', 'sha256', 'parent_id', 'version', 'size') if key in item}
        row.update(status='missing', content_verified=False)
        directory = Path(store.root) / 'files' / cid
        path = directory / (item['file_id'] + '.json')
        if any(part.is_symlink() for part in (directory.parent, directory, path)):
            raise OSError('material_read_file_link')
        if path.is_file():
            try:
                receipt = json.loads(path.read_text('utf-8'))
                if (not isinstance(receipt, dict) or receipt.get('file_id') != item['file_id']
                        or any(receipt.get(key) != value for key, value in row.items()
                               if key not in ('status', 'content_verified'))
                        or not isinstance(receipt.get('filename'), str)
                        or not isinstance(receipt.get('mime'), str)
                        or type(receipt.get('expires_at')) not in (int, float)):
                    raise ValueError('material_file_metadata')
                row.update({key: receipt[key] for key in
                            ('sha256', 'parent_id', 'version', 'size', 'filename', 'mime',
                             'created_at', 'expires_at', 'generated') if key in receipt})
                content = directory / item['file_id']
                if content.is_symlink():
                    raise OSError('material_read_file_link')
                row['status'] = ('expired' if receipt['expires_at'] <= time.time()
                                 else 'metadata_only' if content.is_file() else 'missing')
            except (ValueError, UnicodeError, KeyError, TypeError):
                row['status'] = 'damaged'
        rows.append(row)
    return rows


def files_list(service, user, cid, authorized):
    if not isinstance(cid, str) or not re.fullmatch('[a-f0-9]{32}', cid):
        raise LookupError('conversation_not_found')
    _owned(service, user, cid, authorized)
    directory = Path(service.store.root) / 'files' / cid
    if any(part.is_symlink() for part in (directory.parent, directory)):
        raise OSError('material_read_file_link')
    if directory.exists() and not directory.is_dir():
        raise OSError('material_read_files_unavailable')
    items = _files(service.store, cid, [{'file_id': path.stem}
                   for path in sorted(directory.glob('*.json'))])
    _owned(service, user, cid, authorized)
    return dict(items=items, stored_only=True, refreshed=False)


def material_metadata(service, user, cid, request_id, authorized):
    if (not isinstance(cid, str) or not re.fullmatch('[a-f0-9]{32}', cid)
            or not isinstance(request_id, str) or not re.fullmatch('[A-Za-z0-9_-]{8,80}', request_id)):
        raise LookupError('material_not_found')
    _owned(service, user, cid, authorized)
    with _database(service.hermes.tasks.path) as db:
        saved = db.execute('''SELECT selection FROM conversation_material_selections_v1
                              WHERE owner=? AND cid=? AND request_id=?''', (user, cid, request_id)).fetchone()
        if saved is None:
            raise LookupError('material_not_found')
        selection = json.loads(saved['selection'])
        row = db.execute('''SELECT goal_id,task_id,run_id,attempted,generated,coverage,
                            context_receipt,official_status,runtime_error,observed_at
                            FROM conversation_material_runs_v1 WHERE owner=? AND cid=? AND request_id=?''',
                         (user, cid, request_id)).fetchone()
        task = db.execute('SELECT state,run_id FROM tasks WHERE id=? AND owner=?',
                          (row['task_id'], user)).fetchone() if row else None
    value = dict(request_id=request_id, goal_id=selection['goal_id'], status='unknown', files=[],
                 stored_only=True, refreshed=False, result_available=False, complete=False,
                 missing=['live_runtime_state', 'terminal_result'])
    if row:
        if task is None or row['goal_id'] != selection['goal_id'] or task['run_id'] != row['run_id']:
            raise OSError('material_read_binding_conflict')
        official = json.loads(row['official_status']) if row['official_status'] else {}
        status = official.get('status', 'unknown') if row['attempted'] else 'queued'
        if status not in {'queued', 'running', 'stopping', 'waiting_for_approval',
                          'completed', 'failed', 'cancelled', 'interrupted', 'unknown'}:
            status = 'unknown'
        if task['state'] in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
            status = {'SUCCEEDED': 'completed', 'FAILED': 'failed', 'CANCELLED': 'cancelled'}[task['state']]
        if row['runtime_error']:
            status = 'unavailable'
        value.update(task_id=row['task_id'], run_id=row['run_id'], task_state=task['state'], status=status,
                     files=_files(service.store, cid, json.loads(row['generated'])),
                     coverage=json.loads(row['coverage']), observed_at=row['observed_at'],
                     context_receipt=json.loads(row['context_receipt']) if row['context_receipt'] else None)
    _owned(service, user, cid, authorized)
    return value
