"""Verified recovery points only; no retention deletion without an enabled reviewed policy."""
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from user_contract import canonical, digest, stamp
from user_store import Store, safe

FILES = ('config.json', 'customers.sqlite3', 'identity.key', 'manifest.json')


def read_json(path):
    safe(path)
    with path.open('rb') as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError('backup_manifest_size')
    return json.loads(raw), raw


def private_directory(path):
    safe(path)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError('private_backup_directory_metadata')


def write(path, value):
    safe(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(canonical(value).encode()); stream.flush(); os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o600)
        os.replace(temporary, path)
        directory_sync(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def directory_sync(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def signature(path):
    safe(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_mode & 0o077:
        raise ValueError('private_backup_file_metadata')
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def backup_identity(folder):
    private_directory(folder)
    files = {name: signature(folder / name) for name in FILES}
    manifest, raw = read_json(folder / 'manifest.json')
    if (not isinstance(manifest, dict) or manifest.get('contract') not in ('fs-users-private-backup-v1', 'fs-users-private-backup-v2')
            or manifest.get('scope') != 'same_host_recovery_copy'
            or not isinstance(manifest.get('data_version'), str) or re.fullmatch(r'0|[1-9][0-9]{0,18}', manifest['data_version']) is None
            or int(manifest['data_version']) >= 2**63
            or stamp(manifest['captured_at']).date().isoformat() != folder.name):
        raise ValueError('backup_manifest_contract')
    if set(manifest['sha256']) != set(FILES) - {'manifest.json'} or any(re.fullmatch('[a-f0-9]{64}', value) is None for value in manifest['sha256'].values()):
        raise ValueError('backup_manifest_files')
    return dict(manifest_sha256=hashlib.sha256(raw).hexdigest(), files=files)


def restore_check(folder, integrity_checked=False):
    """Read the recovery copy with actual readers, including a frozen private snapshot."""
    before = {name: signature(folder / name) for name in FILES if name != 'manifest.json'}
    config = json.loads((folder / 'config.json').read_text('utf-8'))
    with (folder / 'identity.key').open('rb') as source:
        key = source.read(4097)
    if len(key) > 4096:
        raise ValueError('backup_identity_key_size')
    restored = Store(folder, key, config, read_only=True)
    with restored.db() as db:
        if not integrity_checked and db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('backup_integrity')
        counts = {table: db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                  for table in ('orders', 'identities', 'snapshots')}
        row = db.execute('SELECT id FROM snapshots ORDER BY rowid DESC LIMIT 1').fetchone()
    public, private = {}, dict(records={})
    if row:
        query, public, private = restored.snapshot(row[0])
        if public.get('metrics', {}).get('known_pool', {}).get('value') is not None:
            if len(private['members']['known_pool']) != public['metrics']['known_pool']['value']:
                raise ValueError('backup_private_public_mismatch')
    after = {name: signature(folder / name) for name in before}
    if after != before:
        raise ValueError('backup_changed_during_restore_check')
    return dict(status='passed', data_version=restored.revision(), sqlite_integrity='ok', frozen_snapshot_id=public.get('snapshot_id'),
                frozen_data_version=public.get('data_version'), private_records=len(private['records']),
                counts=counts, file_signatures=after, source_calls=0, database_writes=0)


def verify_existing(store, day):
    if date.fromisoformat(day).isoformat() != day:
        raise ValueError('backup_date_required')
    folder = store.root / 'backups' / day
    before = backup_identity(folder)
    manifest, _ = read_json(folder / 'manifest.json')
    from user_jobs import file_sha256
    for name, expected in manifest['sha256'].items():
        if file_sha256(folder / name) != expected:
            raise ValueError('backup_readback_mismatch')
    check = restore_check(folder)
    if check['data_version'] != manifest['data_version'] or backup_identity(folder) != before:
        raise ValueError('backup_restore_version_or_file_mismatch')
    value = dict(contract='fs-users-backup-restore-check-v1', signature=before, recovery=check)
    path = folder / 'restore-check.json'
    if path.exists() and read_json(path)[0] != value:
        raise ValueError('existing_restore_check_requires_reconciliation')
    if not path.exists():
        write(path, value)
    return value


def policy(store):
    value = store.config.get('backup_retention', dict(enabled=False, keep_verified=2, protected_dates=[]))
    if (not isinstance(value, dict) or set(value) != {'enabled', 'keep_verified', 'protected_dates'}
            or type(value['enabled']) is not bool or type(value['keep_verified']) is not int
            or not 2 <= value['keep_verified'] <= 31 or not isinstance(value['protected_dates'], list)
            or any(not isinstance(day, str) or date.fromisoformat(day).isoformat() != day for day in value['protected_dates'])):
        raise ValueError('backup_retention_policy')
    return value


def plan(store, now):
    settings = policy(store)
    root = store.root / 'backups'; safe(root)
    points, protected = [], []
    if root.exists():
        private_directory(root)
        for folder in sorted(root.iterdir()):
            reason = None
            try:
                safe(folder)
                if not folder.is_dir() or re.fullmatch(r'\d{4}-\d{2}-\d{2}', folder.name) is None or date.fromisoformat(folder.name).isoformat() != folder.name:
                    raise ValueError('special_or_unknown_recovery_material')
                if folder.name in settings['protected_dates']:
                    raise ValueError('explicitly_protected_recovery_point')
                if folder.name > now.date().isoformat():
                    raise ValueError('future_or_misdated_recovery_point')
                names = {p.name for p in folder.iterdir()}
                if names not in (set(FILES), set(FILES) | {'restore-check.json'}):
                    raise ValueError('partial_or_unknown_backup_files')
                identity = backup_identity(folder)
                manifest, _ = read_json(folder / 'manifest.json')
                recovery = manifest.get('recovery', {})
                if not isinstance(recovery, dict):
                    raise ValueError('backup_recovery_contract')
                verified = (recovery.get('status') == 'passed' and recovery.get('sqlite_integrity') == 'ok' and recovery.get('data_version') == manifest.get('data_version')
                            and recovery.get('file_signatures') == {name: identity['files'][name] for name in FILES if name != 'manifest.json'})
                if not verified and 'restore-check.json' in names:
                    signature(folder / 'restore-check.json')
                    check, _ = read_json(folder / 'restore-check.json')
                    if not isinstance(check, dict) or not isinstance(check.get('recovery'), dict):
                        raise ValueError('backup_recovery_contract')
                    verified = (check.get('contract') == 'fs-users-backup-restore-check-v1' and check.get('signature') == identity
                                and check.get('recovery', {}).get('status') == 'passed'
                                and check['recovery'].get('sqlite_integrity') == 'ok'
                                and check['recovery'].get('data_version') == manifest.get('data_version'))
                if not verified:
                    raise ValueError('restore_not_verified')
                signatures = {name: signature(folder / name) for name in sorted(names)}
                points.append(dict(day=folder.name, signature=identity, files=signatures,
                                   bytes=sum(v[2] for v in signatures.values())))
            except (OSError, ValueError, KeyError, TypeError) as error:
                reason = str(error) if isinstance(error, ValueError) else type(error).__name__
            if reason:
                protected.append(dict(name=folder.name, reason=reason))
    points.sort(key=lambda item: item['day'], reverse=True)
    kept = points[:settings['keep_verified']]
    ready = len(kept) >= settings['keep_verified'] and any(p['day'] == now.date().isoformat() for p in kept)
    candidates = points[settings['keep_verified']:] if ready else []
    value = dict(contract='fs-users-backup-retention-v1', day=now.date().isoformat(), policy=settings,
                 status='ready' if ready else 'waiting_for_current_verified_recovery_point',
                 keep=kept, protected=protected, candidates=candidates, candidate_bytes=sum(p['bytes'] for p in candidates))
    return dict(value, plan_sha256=digest(value))


def apply(store, now, approved):
    """Only a deployed, explicitly enabled policy may retire excess verified recovery points."""
    if not policy(store)['enabled']:
        raise ValueError('backup_retention_not_enabled')
    current = plan(store, now)
    if current != approved:
        raise ValueError('backup_retention_plan_drift')
    audit_root = store.root / 'backup-retention-audit'; safe(audit_root)
    if audit_root.exists():
        private_directory(audit_root)
        for old in audit_root.iterdir():
            if not old.is_file() or old.suffix != '.json':
                raise ValueError('backup_retention_requires_reconciliation')
            signature(old)
            if read_json(old)[0].get('status') != 'complete':
                raise ValueError('backup_retention_requires_reconciliation')
    if current['status'] != 'ready' or not current['candidates']:
        return dict(status='nothing_to_retire', removed_bytes=0)
    audit_root.mkdir(mode=0o700, exist_ok=True)
    audit = audit_root / (current['plan_sha256'] + '.json')
    if audit.exists():
        raise ValueError('backup_retention_already_attempted')
    record = dict(status='in_progress', plan=current, removed=[], removed_bytes=0)
    write(audit, record)
    for point in current['candidates']:
        for kept in current['keep']:
            anchor = store.root / 'backups' / kept['day']
            if (backup_identity(anchor) != kept['signature']
                    or {p.name for p in anchor.iterdir()} != set(kept['files'])
                    or any(signature(anchor / name) != expected for name, expected in kept['files'].items())):
                raise ValueError('retained_recovery_point_drift')
        folder = store.root / 'backups' / point['day']
        for name, expected in point['files'].items():
            path = folder / name
            if signature(path) != expected:
                raise ValueError('backup_retirement_file_drift')
            record['intent'] = dict(day=point['day'], name=name); write(audit, record)
            path.unlink(); directory_sync(folder)
            record['removed'].append(dict(day=point['day'], name=name)); record['removed_bytes'] += expected[2]
            record.pop('intent'); write(audit, record)
        folder.rmdir(); directory_sync(folder.parent)
    record['status'] = 'complete'; write(audit, record)
    return dict(status='complete', removed_bytes=record['removed_bytes'], audit=audit.name)
