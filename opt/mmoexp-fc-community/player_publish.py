"""Operator-attested EasySBC batches; only the fixed Discord test destination.

This does not execute EasySBC commands. API/CLI callers own authorization and
the final callback owns sending an ordinary PlayerHomeView, not a targeted card.
"""
import copy
import json
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from player_config import validate_player_config

TEST_GUILD = 1565922092518613064
TEST_CHANNEL = 1568260661010497627
EASYSBC_AUTHOR = 1167033335256731658


def _now():
    return datetime.now(timezone.utc).isoformat()


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Use a canonical UUID')
    return value


def _message(url):
    match = re.fullmatch(r'https://discord\.com/channels/(\d+)/(\d+)/(\d+)', url or '')
    if (not match or int(match[1]) != TEST_GUILD or int(match[2]) != TEST_CHANNEL
            or not 10**16 <= int(match[3]) < 10**20):
        raise ValueError('Receipt must be a message in the fixed test channel')
    return match[3]


def _identity(value):
    value = copy.deepcopy(value)
    if not isinstance(value, dict) or set(value) != {
        'easysbc_id', 'easysbc_role_id', 'easysbc_url', 'autocomplete_label'
    }:
        raise ValueError('Complete selected EasySBC identity is required')
    ident, role, url, label = (value[k] for k in (
        'easysbc_id', 'easysbc_role_id', 'easysbc_url', 'autocomplete_label'))
    if not isinstance(ident, str) or not re.fullmatch(r'[1-9][0-9]{0,11}', ident):
        raise ValueError('Invalid EasySBC player ID')
    if not isinstance(role, str) or role and not re.fullmatch(r'[1-9][0-9]{0,11}', role):
        raise ValueError('Invalid EasySBC role ID')
    if not isinstance(url, str) or len(url) > 600 or any(c.isspace() for c in url):
        raise ValueError('Invalid EasySBC player URL')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in ('easysbc.io', 'www.easysbc.io')
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment or not parsed.path.startswith('/players/')
            or parsed.path.rstrip('/').split('/')[-1] != ident):
        raise ValueError('Player URL must match the recorded EasySBC ID')
    url_roles = parse_qs(parsed.query).get('player-role-id', [])
    if len(url_roles) > 1 or (url_roles and url_roles[0] != role):
        raise ValueError('Player URL role mismatch')
    if not isinstance(label, str) or not 1 <= len(label.strip()) <= 300 or any(ord(c) < 32 for c in label):
        raise ValueError('Record the exact selected autocomplete label')
    return value


def _match_mapping(mapping, identity):
    if not mapping:
        return
    for key in ('easysbc_id', 'easysbc_role_id'):
        if mapping.get(key) and mapping[key] != identity[key]:
            raise ValueError('Recorded identity conflicts with the saved mapping')
    if mapping.get('easysbc_url'):
        saved = urlsplit(mapping['easysbc_url'])
        selected = urlsplit(identity['easysbc_url'])
        # EasySBC accepts a short /players/{id} URL and emits descriptive slugs.
        # Stable resource and role IDs, not marketing URL slugs, identify a card.
        if saved.path.rstrip('/').split('/')[-1] != selected.path.rstrip('/').split('/')[-1]:
            raise ValueError('Recorded URL conflicts with the saved mapping')
        roles = parse_qs(saved.query).get('player-role-id', [])
        if roles and roles != [identity['easysbc_role_id']]:
            raise ValueError('Recorded URL role conflicts with the saved mapping')


class PlayerPublishStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _lock(self):
        with (self.path / '.lock').open('a+b') as handle:
            if os.name == 'nt':
                import msvcrt
                if handle.seek(0, 2) == 0:
                    handle.write(b'0')
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == 'nt':
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _file(self, batch_id):
        return self.path / (_uuid(batch_id) + '.json')

    def _read(self, batch_id):
        return json.loads(self._file(batch_id).read_text(encoding='utf-8'))

    def _write(self, batch):
        target = self._file(batch['batch_id'])
        temp = target.with_suffix('.tmp')
        with temp.open('w', encoding='utf-8') as handle:
            json.dump(batch, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
        if os.name != 'nt':
            descriptor = os.open(str(self.path), os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def create(self, config, request_id, title_provider, match_provider=None):
        """Same request UUID resumes the snapshot; new UUID permits a new batch."""
        batch_id = _uuid(request_id)
        with self._lock():
            if self._file(batch_id).exists():
                return self._read(batch_id)
            config = copy.deepcopy(validate_player_config(config))
            if not config['featured_model_ids']:
                raise ValueError('Save a nonempty featured list first')
            easy = config.get('easysbc', {})
            if easy.get('selection', 'featured') != 'featured':
                raise ValueError('This pilot accepts the saved featured list only')
            mappings = {m['model_id']: m for m in easy.get('mappings', [])}
            items = []
            for mid in config['featured_model_ids']:
                title = title_provider(mid)
                if not isinstance(title, str) or not title.strip() or len(title) > 300:
                    raise ValueError('Cannot resolve saved model title')
                mapping = copy.deepcopy(mappings.get(mid))
                match = ({'status': 'matched', 'mapping': mapping} if mapping else
                         match_provider(mid) if match_provider else None)
                items.append({'model_id': mid, 'title': title,
                              'mapping': mapping, 'match': copy.deepcopy(match), 'receipt': None})
            batch = {'schema': 1, 'batch_id': batch_id, 'request_id': request_id,
                     'guild_id': TEST_GUILD, 'channel_id': TEST_CHANNEL,
                     'template': easy.get('template', 'card'), 'with_card': easy.get('with_card', False),
                     'created_at': _now(), 'items': items, 'status': 'pending',
                     'final_receipt': None}
            self._write(batch)
            return copy.deepcopy(batch)

    def get(self, batch_id):
        with self._lock():
            return self._read(batch_id)

    def record(self, batch_id, model_id, message_url, identity, operator_id,
               author_id=EASYSBC_AUTHOR):
        """Record an operator's observed receipt, not independent API verification."""
        message_id = _message(message_url)
        identity = _identity(identity)
        if type(operator_id) is not int or not 10**16 <= operator_id < 10**20:
            raise ValueError('An explicit operator ID is required')
        if type(author_id) is not int or author_id != EASYSBC_AUTHOR:
            raise ValueError('Receipt must be authored by EasySBC')
        with self._lock():
            batch = self._read(batch_id)
            item = next((i for i in batch['items'] if i['model_id'] == model_id), None)
            if item is None or type(model_id) is not int:
                raise ValueError('Model is not in this batch snapshot')
            _match_mapping(item['mapping'], identity)
            candidates = (item.get('match') or {}).get('candidates', [])
            if not item['mapping'] and candidates and not any(
                    c.get('easysbc_id') == identity['easysbc_id'] and
                    c.get('easysbc_role_id') == identity['easysbc_role_id'] for c in candidates):
                raise ValueError('Recorded card is not a candidate for this player')
            receipt = {'message_id': message_id, 'message_url': message_url,
                       'identity': identity, 'operator_id': operator_id, 'author_id': author_id}
            if item['receipt']:
                if all(item['receipt'].get(k) == v for k, v in receipt.items()):
                    return batch
                raise ValueError('A receipt already exists; do not send this player again')
            if batch['status'] != 'pending':
                raise ValueError('Batch no longer accepts receipts')
            if any(i['receipt'] and i['receipt']['message_id'] == message_id for i in batch['items']):
                raise ValueError('One EasySBC message cannot confirm two players')
            receipt['recorded_at'] = _now()
            item['receipt'] = receipt
            self._write(batch)
            return batch

    def finalize(self, batch_id, send_callback):
        """Sync callback(snapshot) -> fixed-test-channel Discord message URL.

        Lock remains held through sending. Run in a worker if using an async bot;
        never call back into this store while sending. Any uncertain send needs
        manual reconciliation; neither an error nor a restart permits resending.
        """
        with self._lock():
            batch = self._read(batch_id)
            if batch['status'] == 'sent':
                return batch
            if batch['status'] in ('sending', 'unknown'):
                batch['status'] = 'unknown'
                self._write(batch)
                raise ValueError('Final send is uncertain; inspect Discord, do not retry')
            if not batch['items'] or any(i['receipt'] is None for i in batch['items']):
                raise ValueError('Every player needs an EasySBC receipt first')
            batch['status'], batch['send_started_at'] = 'sending', _now()
            self._write(batch)
            try:
                url = send_callback(copy.deepcopy(batch))
                message_id = _message(url)
                batch['status'] = 'sent'
                batch['final_receipt'] = {'message_url': url, 'message_id': message_id, 'sent_at': _now()}
                self._write(batch)
            except BaseException:
                batch['status'] = 'unknown'
                self._write(batch)
                raise
            return batch
