"""Turn-scoped file capabilities, built from authenticated server context only."""
from contextlib import contextmanager
import json
import os
import re
import tempfile

from conversation_files import ConversationFiles


def normalize_file_ids(file_ids):
    if file_ids is None:
        return []
    if not isinstance(file_ids, list) or len(file_ids) > 10 or any(
            not isinstance(fid, str) or not re.fullmatch('[a-f0-9]{32}', fid) for fid in file_ids):
        raise ValueError('file_ids')
    return sorted(set(file_ids))


class FileBindings:
    def __init__(self, store):
        self.store = store
        self.files = ConversationFiles(store)

    def path(self, cid, turn_id):
        if not isinstance(turn_id, str) or not re.fullmatch('[a-f0-9]{32}', turn_id):
            raise LookupError('turn_not_found')
        directory = self.files.directory(cid) / 'bindings'
        if directory.is_symlink():
            raise ValueError('linked_bindings')
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / (turn_id + '.json')
        if path.is_symlink():
            raise ValueError('linked_binding')
        return path

    def bound(self, db, owner, cid, turn_id):
        self.store._owned(db, owner, cid)
        if db.execute('SELECT 1 FROM turns WHERE id=? AND conversation_id=?', (turn_id, cid)).fetchone() is None:
            raise LookupError('turn_not_found')
        path = self.path(cid, turn_id)
        if not path.exists():
            return {'inputs': [], 'generated': []}  # Legacy turns have no attachments.
        return json.loads(path.read_text(encoding='utf-8'))

    def write(self, cid, turn_id, value):
        path = self.path(cid, turn_id)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.binding-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def bind(self, db, owner, cid, turn_id, file_ids):
        # Called inside reserve_turn's write transaction. Validate all before writing.
        for fid in file_ids:
            self.files.read(owner, cid, fid, _db=db)
        self.write(cid, turn_id, {'inputs': file_ids, 'generated': []})


class BoundFiles:
    def __init__(self, store, owner, cid, turn_id, authorized):
        self.bindings = FileBindings(store)
        self.owner, self.cid, self.turn_id = owner, cid, turn_id
        self.authorized = authorized

    def receipt(self, item):
        return {**{k: v for k, v in item.items() if k != 'content'},
                'download_url': '/api/hermes/conversations/' + self.cid + '/files/' + item['file_id']}

    @contextmanager
    def current(self):
        with self.bindings.files.transaction() as db:
            if not self.authorized(self.owner):
                raise PermissionError('file_access_revoked')
            value = self.bindings.bound(db, self.owner, self.cid, self.turn_id)
            row = db.execute('SELECT state FROM turns WHERE id=? AND conversation_id=?',
                             (self.turn_id, self.cid)).fetchone()
            if row['state'] not in {'queued', 'running'}:
                raise PermissionError('file_turn_not_running')
            yield db, value

    def authorize(self, db, value, file_id):
        if file_id not in value['inputs'] + value['generated']:
            raise LookupError('file_not_bound')
        return self.bindings.files.read(self.owner, self.cid, file_id, _db=db)

    def catalog(self):
        with self.current() as (db, value):
            items = []
            for fid in value['inputs'] + value['generated']:
                item = self.authorize(db, value, fid)
                items.append(self.receipt(item))
            return {'items': items, 'scope': 'current_turn', 'complete': True}

    def read_table(self, file_id, sheet=None, offset=0, limit=None):
        with self.current() as (db, value):
            self.authorize(db, value, file_id)
            table = self.bindings.files.parsed(self.owner, self.cid, file_id, _db=db)
            if sheet is None:
                if offset != 0 or limit is not None:
                    raise ValueError('sheet_required_for_paging')
                return dict(table, scope='current_turn', truncated=False, next_offset=None,
                            coverage={'scope': 'workbook', 'total_sheets': len(table['sheets']),
                                      'returned_sheets': len(table['sheets']), 'complete': True})
            if type(sheet) is not int or not 0 <= sheet < len(table['sheets']):
                raise ValueError('sheet_index')
            rows = table['sheets'][sheet]['rows']
            if type(offset) is not int or not 0 <= offset <= len(rows) or (limit is not None and
                    (type(limit) is not int or not 1 <= limit <= 200)):
                raise ValueError('page_bounds')
            end = len(rows) if limit is None else min(len(rows), offset + limit)
            page = dict(table['sheets'][sheet], rows=rows[offset:end])
            return dict(table, sheets=[page], scope='current_turn', complete=offset == 0 and end == len(rows),
                        truncated=offset != 0 or end != len(rows), sheet=sheet, offset=offset,
                        total_rows=len(rows), returned_rows=end-offset,
                        coverage={'scope': 'selected_sheet', 'total_sheets': len(table['sheets']),
                                  'sheet': sheet, 'offset': offset, 'end_exclusive': end,
                                  'total_rows': len(rows), 'returned_rows': end-offset,
                                  'complete': offset == 0 and end == len(rows)},
                        next_offset=end if end < len(rows) else None)

    def revise(self, file_id, edits, format, request_id):
        with self.current() as (db, value):
            self.authorize(db, value, file_id)
            # Tool request IDs are local to this turn, never collide with HTTP uploads.
            import hashlib
            if not isinstance(request_id, str) or not re.fullmatch('[A-Za-z0-9_-]{8,80}', request_id):
                raise ValueError('request_id')
            scoped = hashlib.sha256((self.turn_id + ':' + request_id).encode()).hexdigest()
            item = self.bindings.files.revise(self.owner, self.cid, file_id, edits, format, scoped, _db=db)
            if item['file_id'] not in value['generated']:
                value['generated'].append(item['file_id'])
                self.bindings.write(self.cid, self.turn_id, value)
            return self.receipt(item)


def context_factory(store, owner, cid, turn_id, authorized):
    return BoundFiles(store, owner, cid, turn_id, authorized)
