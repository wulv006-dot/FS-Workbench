"""Bounded conversation files. No model, arbitrary code execution or business IO.

Only this new files directory is subject to expiry; legacy artifacts are untouched.
The conversation DB write lock serializes file quota/version changes across workers.
"""
import csv
import hashlib
import html
import io
import json
import os
import re
import time
import zipfile
from contextlib import contextmanager

MAX_BYTES = 10 * 1024 * 1024
MAX_CELLS = 100_000
MIMES = {'csv': 'text/csv', 'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
         'html': 'text/html', 'txt': 'text/plain', 'md': 'text/markdown',
         'json': 'application/json', 'pdf': 'application/pdf', 'png': 'image/png',
         'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif', 'webp': 'image/webp',
         'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
         'zip': 'application/zip'}


def file_mime(filename):
    return MIMES.get(filename.rsplit('.', 1)[-1].lower(), 'application/octet-stream')


def parse_table(content, extension):
    """Return every accepted cell; oversized inputs fail rather than truncate."""
    if not content or len(content) > MAX_BYTES:
        raise ValueError('file_size')
    sheets = []
    cells = 0
    def collect(name, rows):
        nonlocal cells
        result = []
        for row in rows:
            cells += max(1, len(row))
            if cells > MAX_CELLS:
                raise ValueError('table_too_large')
            result.append([v if v is None or type(v) in (str, int, float, bool) else str(v) for v in row])
        sheets.append({'name': name, 'rows': result})
    if extension == 'csv':
        text = content.decode('utf-8-sig')
        if text.startswith('sep=,\r\n') or text.startswith('sep=,\n'):
            text = text.split('\n', 1)[1]
        collect('CSV', csv.reader(io.StringIO(text, newline=''), strict=True))
    elif extension == 'xlsx':
        # Bound XML expansion before openpyxl loads workbook metadata/shared strings.
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or sum(e.file_size for e in entries) > 32 * 1024 * 1024:
                raise ValueError('workbook_expansion')
            for entry in entries:
                if entry.filename.lower().endswith(('.xml', '.rels')):
                    xml = archive.read(entry)
                    if b'\x00' in xml or b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
                        raise ValueError('workbook_entities')
                if 'vbaproject' in entry.filename.lower():
                    raise ValueError('workbook_macros')
        from openpyxl import load_workbook
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=False)
        try:
            for sheet in book:
                sheet.reset_dimensions()  # Do not trust producer-supplied dimensions.
                collect(sheet.title, sheet.iter_rows(values_only=True))
        finally:
            book.close()
    else:
        raise ValueError('table_format')
    return {'sheets': sheets, 'complete': True, 'cells': cells,
            'formulas': 'expressions_preserved_not_evaluated', 'encoding': 'utf-8'}


class ConversationFiles:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def transaction(self, connection=None):
        if connection is not None:
            yield connection
        else:
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                yield db

    def directory(self, cid):
        if not isinstance(cid, str) or not re.fullmatch('[a-f0-9]{32}', cid):
            raise LookupError('conversation_not_found')
        directory = self.store.root
        for name in ('files', cid):
            directory = directory / name
            if directory.is_symlink():
                raise ValueError('linked_file_directory')
            directory.mkdir(mode=0o700, exist_ok=True)
        return directory

    @staticmethod
    def metadata(directory, fid):
        if not isinstance(fid, str) or not re.fullmatch('[a-f0-9]{32}', fid):
            raise LookupError('file_not_found')
        path = directory / (fid + '.json')
        if path.is_symlink():
            raise ValueError('linked_file_metadata')
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise LookupError('file_not_found') from None

    def _inventory(self, directory):
        items = []
        for path in directory.glob('*.json'):
            item = self.metadata(directory, path.stem)
            target = directory / item['file_id']
            if item['expires_at'] <= time.time():
                if target.is_symlink():
                    raise ValueError('linked_file')
                target.unlink(missing_ok=True)
                item = dict(item, expired=True)
            else:
                item = dict(item, expired=False)
            items.append(item)
        return items

    def listed(self, owner, cid, *, _db=None):
        with self.transaction(_db) as db:
            self.store._owned(db, owner, cid)
            return {'items': self._inventory(self.directory(cid))}

    def describe(self, owner, cid, fid, *, _db=None):
        """Metadata for UI, including terminal turns; grants no tool capability."""
        with self.transaction(_db) as db:
            self.store._owned(db, owner, cid)
            try:
                item = self.metadata(self.directory(cid), fid)
            except LookupError:
                return {'file_id': fid, 'status': 'missing'}
            except (ValueError, OSError):
                return {'file_id': fid, 'status': 'damaged'}
            # A readable JSON receipt may still have lost fields or field types.
            # Keep that attachment unavailable without hiding the conversation.
            fields = {'filename': str, 'mime': str, 'sha256': str, 'size': int,
                      'version': int, 'generated': bool}
            if (not isinstance(item, dict) or item.get('file_id') != fid
                    or any(type(item.get(key)) is not kind for key, kind in fields.items())
                    or any(type(item.get(key)) not in (int, float) for key in ('created_at', 'expires_at'))
                    or 'parent_id' not in item
                    or (item['parent_id'] is not None and
                        (not isinstance(item['parent_id'], str) or
                         not re.fullmatch('[a-f0-9]{32}', item['parent_id'])))
                    or not re.fullmatch('[a-f0-9]{64}', item['sha256'])
                    or not 0 < item['size'] <= MAX_BYTES or item['version'] < 1
                    or item['mime'] != file_mime(item['filename'])):
                return {'file_id': fid, 'status': 'damaged'}
            try:
                self.read(owner, cid, fid, _db=db)
                status = 'available'
            except (KeyError, TypeError, AttributeError):
                return {'file_id': fid, 'status': 'damaged'}
            except LookupError:
                status = 'expired' if item['expires_at'] <= time.time() else 'missing'
            except FileNotFoundError:
                status = 'missing'
            except ValueError:
                status = 'damaged'
            except OSError:
                status = 'unavailable'
            return {**{k: v for k, v in item.items() if k != 'recipe'}, 'status': status}

    def lookup(self, owner, cid, request_id):
        if not isinstance(request_id, str) or not re.fullmatch('[A-Za-z0-9_-]{8,80}', request_id):
            raise ValueError('request_id')
        fid = hashlib.sha256((cid + ':' + request_id).encode()).hexdigest()[:32]
        with self.transaction() as db:
            self.store._owned(db, owner, cid)
            self.metadata(self.directory(cid), fid)  # Absent request receipt is 404.
            return self.describe(owner, cid, fid, _db=db)

    def read(self, owner, cid, fid, *, _db=None):
        with self.transaction(_db) as db:
            self.store._owned(db, owner, cid)
            directory = self.directory(cid)
            self._inventory(directory)
            item = self.metadata(directory, fid)
            if item['expires_at'] <= time.time():
                raise LookupError('file_expired')
            target = directory / fid
            if target.is_symlink():
                raise ValueError('linked_file')
            try:
                with target.open('rb') as stream:
                    content = stream.read(MAX_BYTES + 1)
            except FileNotFoundError:
                raise LookupError('file_missing') from None
            if len(content) != item['size'] or hashlib.sha256(content).hexdigest() != item['sha256']:
                raise ValueError('file_integrity')
            return dict(item, content=content)

    def save(self, owner, cid, filename, content, request_id, parent_id=None, generated=False, recipe=None, *, _db=None):
        if (not isinstance(filename, str) or not 1 <= len(filename) <= 200 or
                len(filename.encode('utf-8')) > 240 or not filename.strip() or filename.startswith('.') or
                re.search(r'[/\\\x00-\x1f\x7f]',filename)):
            raise ValueError('file_name')
        if not isinstance(content, bytes) or not 0 < len(content) <= MAX_BYTES:
            raise ValueError('file_size')
        if not isinstance(request_id, str) or not re.fullmatch('[A-Za-z0-9_-]{8,80}', request_id):
            raise ValueError('request_id')
        # Upload stores the original bytes; tools parse a document only when asked.
        with self.transaction(_db) as db:
            self.store._owned(db, owner, cid)
        sha = hashlib.sha256(content).hexdigest()
        fid = hashlib.sha256((cid + ':' + request_id).encode()).hexdigest()[:32]
        with self.transaction(_db) as db:
            self.store._owned(db, owner, cid)
            directory = self.directory(cid)
            items = self._inventory(directory)
            old = next((i for i in items if i['file_id'] == fid), None)
            if old:
                if generated and old.get('recipe') != recipe:
                    raise ValueError('idempotency_conflict')
                same_recipe = generated and recipe is not None and old.get('recipe') == recipe
                if (not same_recipe and old['sha256'] != sha) or (old['filename'], old['parent_id'], old['generated']) != (filename, parent_id, generated):
                    raise ValueError('idempotency_conflict')
                return old
            parent = next((i for i in items if i['file_id'] == parent_id and not i['expired']), None)
            if parent_id is not None and parent is None:
                raise LookupError('parent_not_found')
            if len(items) >= 1000 or sum(i['size'] for i in items if not i['expired']) + len(content) > 100 * MAX_BYTES:
                raise ValueError('conversation_file_quota')
            item = {'file_id': fid, 'filename': filename, 'mime': file_mime(filename), 'sha256': sha,
                    'size': len(content), 'parent_id': parent_id, 'version': parent['version'] + 1 if parent else 1,
                    'generated': generated, 'recipe': recipe, 'created_at': time.time(),
                    'expires_at': time.time() + (90 if generated else 30) * 86400}
            target = directory / fid
            meta = directory / (fid + '.json')
            # Exclusive writes never replace a previous version or unknown outcome.
            with target.open('xb') as stream:
                os.chmod(target, 0o600)
                stream.write(content)
            try:
                with meta.open('x', encoding='utf-8') as stream:
                    os.chmod(meta, 0o600)
                    json.dump(item, stream, ensure_ascii=False)
            except Exception:
                target.unlink(missing_ok=True)
                raise
            return dict(item, expired=False)

    def parsed(self, owner, cid, fid, *, _db=None):
        item = self.read(owner, cid, fid, _db=_db)
        return dict(parse_table(item['content'], item['filename'].rsplit('.', 1)[-1].lower()),
                    file_id=fid, sha256=item['sha256'])

    def revise(self, owner, cid, fid, edits, output_format, request_id, *, _db=None):
        table = self.parsed(owner, cid, fid, _db=_db)
        if output_format not in {'csv', 'xlsx', 'html'} or not isinstance(edits, list) or len(edits) > 1000:
            raise ValueError('revision')
        recipe = hashlib.sha256(json.dumps({'parent': fid, 'edits': edits, 'format': output_format},
                                           sort_keys=True, allow_nan=False).encode()).hexdigest()
        for edit in edits:
            if not isinstance(edit, dict) or set(edit) != {'sheet', 'row', 'column', 'value'}:
                raise ValueError('edit')
            if any(type(edit[k]) is not int or edit[k] < 0 for k in ('sheet', 'row', 'column')):
                raise ValueError('edit_index')
            value = edit['value']
            if value is not None and type(value) not in (str, int, float, bool):
                raise ValueError('edit_value')
            try:
                table['sheets'][edit['sheet']]['rows'][edit['row']][edit['column']] = value
            except IndexError:
                raise ValueError('edit_range') from None
        if output_format == 'xlsx':
            from openpyxl import Workbook
            book = Workbook()
            book.remove(book.active)
            for sheet in table['sheets']:
                ws = book.create_sheet(sheet['name'])
                for row in sheet['rows']:
                    ws.append(row)
                    for cell in ws[ws.max_row]:
                        if isinstance(cell.value, str):
                            cell.data_type = 's'  # Never execute uploaded expressions on export.
            buffer = io.BytesIO()
            book.save(buffer)
            book.close()
            content = buffer.getvalue()
        elif output_format == 'csv':
            if len(table['sheets']) != 1:
                raise ValueError('csv_requires_one_sheet')
            buffer = io.StringIO(newline='')
            writer = csv.writer(buffer)
            for row in table['sheets'][0]['rows']:
                writer.writerow(["'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v for v in row])
            content = buffer.getvalue().encode('utf-8-sig')
        else:
            body = []
            for sheet in table['sheets']:
                body.append('<h2>' + html.escape(sheet['name']) + '</h2><table>')
                for row in sheet['rows']:
                    body.append('<tr>' + ''.join('<td>' + html.escape('' if v is None else str(v)) + '</td>' for v in row) + '</tr>')
                body.append('</table>')
            content = ('<!doctype html><html><meta charset="utf-8"><body>' + ''.join(body) + '</body></html>').encode()
        return self.save(owner, cid, 'result.' + output_format, content, request_id, fid, generated=True, recipe=recipe, _db=_db)
