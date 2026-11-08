"""Operator-attested EasySBC batches with explicit, snapshotted destinations.

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
OFFICIAL_GUILD = 1041923524601851914
EASYSBC_AUTHOR = 1167033335256731658


def _now():
    return datetime.now(timezone.utc).isoformat()


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Use a canonical UUID')
    return value


def destination(batch):
    target = batch.get('target', 'test')
    guild = batch.get('guild_id', TEST_GUILD)
    channel = batch.get('channel_id', TEST_CHANNEL)
    if type(guild) is not int or type(channel) is not int or not 10**16 <= channel < 10**20:
        raise ValueError('Invalid batch destination')
    if target == 'test' and (guild, channel) == (TEST_GUILD, TEST_CHANNEL):
        return guild, channel
    if target == 'official' and guild == OFFICIAL_GUILD:
        return guild, channel
    raise ValueError('Destination is not an explicitly authorized target')


def _message(url, guild_id=TEST_GUILD, channel_id=TEST_CHANNEL):
    match = re.fullmatch(r'https://discord\.com/channels/(\d+)/(\d+)/(\d+)', url or '')
    if (not match or int(match[1]) != guild_id or int(match[2]) != channel_id
            or not 10**16 <= int(match[3]) < 10**20):
        raise ValueError('Receipt must be a message in the batch destination')
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


def _verified_cosmetic_fallback(item, identity):
    """Only the matcher's verified same-base candidates may vary resource ID.

    identity_compatible attests target name/rating/version/position in the matcher;
    require its verified anchor and shared asset as well, never just a name match.
    """
    match, mapping = item.get('match') or {}, item.get('mapping') or {}
    if match.get('status') != 'matched' or match.get('selection_policy') != 'same_base_standard_first_else_cosmetic':
        return False
    candidates = match.get('candidates', [])
    anchor = next((c for c in candidates if c.get('easysbc_id') == mapping.get('easysbc_id')
                   and c.get('easysbc_role_id') == mapping.get('easysbc_role_id')), None)
    selected = next((c for c in candidates if c.get('easysbc_id') == identity['easysbc_id']
                     and c.get('easysbc_role_id') == identity['easysbc_role_id']), None)
    if not anchor or not selected:
        return False
    asset = anchor.get('asset_id', '')
    if not isinstance(asset, str) or not asset.isdigit() or int(asset) <= 0 or selected.get('asset_id') != asset:
        return False
    for candidate in (anchor, selected):
        if (candidate.get('identity_compatible') is not True
                or candidate.get('model_id') != item['model_id']
                or candidate.get('season') != 27 or type(candidate.get('cosmetic')) is not bool):
            return False
    return (isinstance(anchor.get('name'), str) and bool(anchor['name'])
            and anchor['name'].casefold() == str(selected.get('name', '')).casefold()
            and type(anchor.get('rating')) is int and anchor['rating'] == selected.get('rating')
            and bool(anchor.get('version')) and anchor['version'] == selected.get('version'))


def execution_plan(batch):
    """Pure, machine-readable native-UI plan; never sends messages."""
    guild, channel = destination(batch)
    steps = []
    for item in batch['items']:
        match = item.get('match') or {}
        names = [item['title'].split('/')[0].strip()]
        names.extend(c['name'] for c in match.get('candidates', []) if c.get('name'))
        steps.append({'model_id': item['model_id'], 'title': item['title'],
            'search_terms': list(dict.fromkeys(names)),
            'command': '/player ' + batch['template'], 'template': batch['template'],
            'with_card': bool(batch.get('with_card')) if batch['template'] == 'info' else False,
            'known_mapping': copy.deepcopy(item.get('mapping')),
            'candidates': copy.deepcopy(match.get('candidates', [])),
            'match_status': match.get('status', 'unavailable'),
            'selection_policy': 'same_base_standard_first_else_cosmetic',
            'on_ambiguous': 'stop_and_verify_resource_and_role_not_visible_label_alone'})
    plan = {'version': 1, 'target': batch.get('target', 'test'), 'guild_id': guild,
        'channel_id': channel, 'channel_url': f'https://discord.com/channels/{guild}/{channel}',
        'items': steps, 'transport': 'authorized_visible_discord_ui',
        'receipt_rules': {'author_id': EASYSBC_AUTHOR, 'not_before': batch.get('created_at'),
            'fields': ['model_id', 'message_url', 'player_url', 'selected_label'],
            'verify_card_identity_in_ui': True, 'skip_existing_receipts': True,
            'unknown_result': 'inspect_before_retry', 'private_user_api': False},
        'final_action': {'command': 'finalize', 'view': 'PlayerHomeView', 'count': 1,
                         'require_all_receipts': True, 'no_mentions': True}}
    plan['text'] = dispatch_text(plan)
    return plan


def dispatch_text(plan):
    target = plan['target']
    return '\n'.join([
        '请使用已登录 mmoexp_vip 的可见 Discord 界面执行本次精选球员派发。优先DOM/可访问性文本；仅候选无法辨认、页面异常或最终必要验收才截图，不要每一步截图；始终遵守DSH自身工具与浏览器约束。',
        '不读取用户 Token、不调用私有 interactions API、不把普通 /player 文本当作原生命令。',
        '目标：' + plan['channel_url'] + '（' + target + '）。不要改到其他频道。',
        '先通过187现有受控SSH运行以下命令，读取FS最新已保存配置；此页面清单仅预览，以create快照为执行依据：',
        'python=/opt/mmoexp-fc-community/.venv-ssl/bin/python',
        'cli=/opt/mmoexp-fc-community/player_publish_cli.py',
        '$python "$cli" plan --target ' + target,
        '# 一次派发只生成一次UUID，恢复/重试必须沿用它；勿重新创建批次。',
        "request_id=$($python -c 'import uuid; print(uuid.uuid4())')",
        '$python "$cli" create --request-id "$request_id" --target ' + target,
        'batch_id=$request_id', '$python "$cli" show --batch-id "$batch_id"',
        '按快照items顺序，跳过已有receipt。搜索词/模板/with_card见execution_plan；逐项选择原生autocomplete。',
        '同基础身份普通优先；仅装饰版本差异允许cosmetic fallback，不换姓名/评分/基础版本。歧义先核对resourceID+role。',
        '等待EasySBC真正发卡，复制消息链接、球员链接与实际选项标签，逐项记录（替换占位符）：',
        '$python "$cli" record --batch-id "$batch_id" --model-id MODEL_ID --message-url "MESSAGE_URL" --player-url "PLAYER_URL" --selected-label "EXACT_SELECTED_LABEL"',
        '收到超时先检查频道，勿重复发球员卡。全部有receipt后，仅运行一次：',
        '$python "$cli" finalize --batch-id "$batch_id"',
        '最后只发一张普通PlayerHome报价入口卡。unknown停止并对账，禁止盲重试。',
        '预览球员：', *[str(i['model_id']) + ' | ' + i['title'] + ' | ' + i['command'] for i in plan['items']]])


def build_dispatch_plan(config, selection, target='test', matches=None):
    """Read-only FS preview; create later freezes fresh saved selection in a batch."""
    config = copy.deepcopy(validate_player_config(config))
    if target not in ('test', 'official'):
        raise ValueError('Unknown publication target')
    if target == 'official' and (not config['enabled'] or config['guild_id'] != OFFICIAL_GUILD):
        raise ValueError('Save and enable the official Player route first')
    if not config['featured_model_ids'] or config.get('easysbc', {}).get('selection', 'featured') != 'featured':
        raise ValueError('Save a nonempty featured list first')
    cards = {c['model_id']: c for c in selection}
    mappings = {m['model_id']: m for m in config.get('easysbc', {}).get('mappings', [])}
    items = []
    for mid in config['featured_model_ids']:
        card = cards.get(mid)
        if not card or not card.get('model_available') or not isinstance(card.get('title'), str) or not card['title'].strip():
            raise ValueError('Cannot resolve saved model title')
        match = copy.deepcopy((matches or {}).get(mid))
        mapping = copy.deepcopy(mappings.get(mid))
        if match and match.get('status') == 'matched' and match.get('mapping'):
            mapping = copy.deepcopy(match['mapping'])
        items.append({'model_id': mid, 'title': card['title'], 'mapping': mapping, 'match': match})
    easy = config.get('easysbc', {})
    return execution_plan({'target': target, 'guild_id': OFFICIAL_GUILD if target == 'official' else TEST_GUILD,
        'channel_id': config['channel_id'] if target == 'official' else TEST_CHANNEL,
        'template': easy.get('template', 'card'), 'with_card': easy.get('with_card', False), 'items': items})


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

    def create(self, config, request_id, title_provider, match_provider=None, target='test'):
        """Same request UUID resumes the snapshot; new UUID permits a new batch."""
        batch_id = _uuid(request_id)
        with self._lock():
            if self._file(batch_id).exists():
                existing = self._read(batch_id)
                if existing.get('target', 'test') != target:
                    raise ValueError('Request UUID already belongs to another target')
                return existing
            config = copy.deepcopy(validate_player_config(config))
            if target not in ('test', 'official'):
                raise ValueError('Unknown publication target')
            guild, channel = TEST_GUILD, TEST_CHANNEL
            if target == 'official':
                if not config['enabled'] or config['guild_id'] != OFFICIAL_GUILD:
                    raise ValueError('Save and enable the official Player route first')
                guild, channel = config['guild_id'], config['channel_id']
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
                source_mapping = copy.deepcopy(mapping)
                match = (match_provider(mid) if match_provider else
                         {'status': 'matched', 'mapping': mapping} if mapping else None)
                if match and match.get('status') == 'matched' and match.get('mapping'):
                    mapping = copy.deepcopy(match['mapping'])
                items.append({'model_id': mid, 'title': title,
                              'mapping': mapping, 'source_mapping': source_mapping,
                              'match': copy.deepcopy(match), 'receipt': None})
            batch = {'schema': 1, 'batch_id': batch_id, 'request_id': request_id,
                     'target': target, 'guild_id': guild, 'channel_id': channel,
                     'template': easy.get('template', 'card'), 'with_card': easy.get('with_card', False),
                     'created_at': _now(), 'items': items, 'status': 'pending',
                     'final_receipt': None}
            batch['execution_plan'] = execution_plan(batch)
            self._write(batch)
            return copy.deepcopy(batch)

    def get(self, batch_id):
        with self._lock():
            return self._read(batch_id)

    def record(self, batch_id, model_id, message_url, identity, operator_id,
               author_id=EASYSBC_AUTHOR):
        """Record an operator's observed receipt, not independent API verification."""
        identity = _identity(identity)
        if type(operator_id) is not int or not 10**16 <= operator_id < 10**20:
            raise ValueError('An explicit operator ID is required')
        if type(author_id) is not int or author_id != EASYSBC_AUTHOR:
            raise ValueError('Receipt must be authored by EasySBC')
        with self._lock():
            batch = self._read(batch_id)
            message_id = _message(message_url, *destination(batch))
            item = next((i for i in batch['items'] if i['model_id'] == model_id), None)
            if item is None or type(model_id) is not int:
                raise ValueError('Model is not in this batch snapshot')
            try:
                _match_mapping(item['mapping'], identity)
            except ValueError:
                if not _verified_cosmetic_fallback(item, identity):
                    raise
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
        """Sync callback(snapshot) -> message URL in the immutable batch destination.

        Lock remains held through sending. Run in a worker if using an async bot;
        never call back into this store while sending. Any uncertain send needs
        manual reconciliation; neither an error nor a restart permits resending.
        """
        with self._lock():
            batch = self._read(batch_id)
            guild, channel = destination(batch)
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
                message_id = _message(url, guild, channel)
                batch['status'] = 'sent'
                batch['final_receipt'] = {'message_url': url, 'message_id': message_id, 'sent_at': _now()}
                self._write(batch)
            except BaseException:
                batch['status'] = 'unknown'
                self._write(batch)
                raise
            return batch
