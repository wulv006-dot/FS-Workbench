"""SEO-local capacity, retention and verified base backups; AI is optional."""
import datetime as dt
import json
import os
import shutil
import sqlite3
import uuid
import tempfile
import re
from dataclasses import dataclass
from pathlib import Path

from .snapshot import atomic_json, batch_lock, current, digest_file


@dataclass(frozen=True)
class ResourcePolicy:
    warning_bytes: int
    operating_ceiling_bytes: int
    emergency_stop_bytes: int
    host_reserve_bytes: int
    measured_basis: str

    def __post_init__(self):
        if not 0 < self.warning_bytes <= self.operating_ceiling_bytes < self.emergency_stop_bytes or self.host_reserve_bytes <= 0 or not self.measured_basis:
            raise ValueError('RESOURCE_BASELINE_REQUIRED')

    def admit(self, *, used, free, estimate=0):
        if min(used, free, estimate) < 0:
            raise ValueError('INVALID_RESOURCE_MEASUREMENT')
        peak = used + estimate
        state = ('emergency' if peak >= self.emergency_stop_bytes or free-estimate < self.host_reserve_bytes else
                 'pressure' if peak > self.operating_ceiling_bytes else
                 'warning' if peak > self.warning_bytes else 'normal')
        return dict(allowed=state != 'emergency', state=state, projected_bytes=peak,
                    defer_optional_work=state in ('pressure', 'emergency'))


def checked_child(root, name):
    root = Path(root).absolute()
    path = root / name
    if root.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError('SEO_OWNED_PATH_REQUIRED')
    return path


def footprint(root):
    size = 0
    for base, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            path = Path(base) / name
            if path.is_symlink():
                raise ValueError('SEO_SYMLINK_NOT_ALLOWED')
        size += sum((Path(base)/name).stat().st_size for name in files)
    return size


def memory_admission(policy, *, rss_bytes=None, available_bytes=None):
    warning, operating, emergency, reserve = (policy[k] for k in ('warning_bytes','operating_ceiling_bytes','emergency_stop_bytes','host_reserve_bytes'))
    if not 0 < warning <= operating < emergency or reserve <= 0:
        raise ValueError('MEMORY_BASELINE_REQUIRED')
    if rss_bytes is None:
        status = dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
        rss_bytes = int(status['VmRSS'].split()[0])*1024
    if available_bytes is None:
        info = dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines() if ':' in line)
        if 'MemAvailable' not in info:
            raise ValueError('HOST_MEMORY_MEASUREMENT_UNAVAILABLE')
        available_bytes = int(info['MemAvailable'].split()[0])*1024
    state = 'emergency' if rss_bytes >= emergency or available_bytes < reserve else 'pressure' if rss_bytes > operating else 'warning' if rss_bytes > warning else 'normal'
    return dict(allowed=state != 'emergency', state=state, rss_bytes=rss_bytes, host_available_bytes=available_bytes)


def temporary_reserve(store, minimum):
    # New snapshot, backup and isolated restore coexist with both trusted backups.
    core = (store.root/'core.db').stat().st_size
    snapshots = sum(p.stat().st_size for p in (store.root/'snapshots').glob('seo-*.sqlite'))
    return max(minimum, 3*(core+snapshots)+minimum)


def cleanup_ai(root, today):
    root = Path(root)
    if not root.exists():
        return dict(status='not_created', rows_deleted=0)
    with batch_lock(root):
        before = footprint(root)
        path = checked_child(root, 'ai.db')
        deleted = 0
        if path.exists():
            db = sqlite3.connect(str(path), timeout=2)
            try:
                with db:
                    deleted = db.execute('DELETE FROM reports WHERE snapshot_id<?',('seo-'+(today-dt.timedelta(days=29)).isoformat(),)).rowcount
            finally:
                db.close()
        return dict(status='completed', rows_deleted=deleted, physical_bytes_before=before, physical_bytes_after=footprint(root))


def verify_backup(directory):
    directory = Path(directory)
    meta = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    for name, expected in meta['files'].items():
        path = checked_child(directory, name)
        if digest_file(path) != expected:
            raise ValueError('BACKUP_HASH_MISMATCH')
        if path.suffix in ('.db', '.sqlite'):
            db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
            try:
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('BACKUP_RESTORE_CHECK_FAILED')
            finally:
                db.close()
    return True


def restore_backup(directory, target):
    directory, target = Path(directory), Path(target)
    verify_backup(directory)
    target.mkdir(mode=0o700)  # Never overwrite an existing working database.
    meta = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    for name in meta['files']:
        source = checked_child(directory, name)
        destination = target/name
        if name.startswith('seo-'):
            (target/'snapshots').mkdir(exist_ok=True)
            destination = target/'snapshots'/name
        shutil.copyfile(source, destination)
        if digest_file(destination) != meta['files'][name]:
            raise ValueError('RESTORE_COPY_HASH_MISMATCH')
    from .store import Store
    restored = Store(target)
    active = current(target)
    if active:
        from .snapshot import read
        for scope in active['games']:
            if read(target,active['snapshot_id'],'history',scope)['facts_hash'] != active['facts_hash']:
                raise ValueError('RESTORE_SNAPSHOT_MISMATCH')
    return restored


def backup_verified(store):
    with batch_lock(store.root):
        backups = checked_child(store.root, 'backups')
        backups.mkdir(exist_ok=True)
        candidate = backups / ('candidate-' + uuid.uuid4().hex)
        candidate.mkdir()
        verified = False
        try:
            target = sqlite3.connect(str(candidate/'core.db'))
            try:
                with store.db() as source:
                    source.backup(target)
            finally:
                target.close()
            active = current(store.root)
            if active:
                snapshots = checked_child(store.root, 'snapshots')
                retained = sorted(snapshots.glob('seo-*.json'), reverse=True)[:2]
                for meta in retained:
                    for path in (meta, meta.with_suffix('.sqlite')):
                        shutil.copyfile(checked_child(snapshots, path.name), candidate/path.name)
                shutil.copyfile(store.root/'current.json', candidate/'current.json')
            manifest = dict(created_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                            files={p.name:digest_file(p) for p in candidate.iterdir()})
            atomic_json(candidate/'manifest.json', manifest)
            verify_backup(candidate)
            with tempfile.TemporaryDirectory(prefix='restore-check-',dir=backups) as check:
                restore_backup(candidate,Path(check)/'core')
            completed = backups / ('backup-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
            os.replace(candidate, completed)
            verified = True
            # Rotate only after the new copy passes restore checks; preserve two trusted copies.
            old = sorted(backups.glob('backup-*'), reverse=True)
            for directory in old[2:]:
                verify_backup(directory)
                shutil.rmtree(checked_child(backups, directory.name))
            return dict(verified=True, restore_checked=True, path=str(completed), bytes=footprint(completed))
        finally:
            if not verified and candidate.exists():
                shutil.rmtree(checked_child(backups, candidate.name))


def cleanup_owned_data(store, today):
    with batch_lock(store.root):
        before = footprint(store.root)
        cutoff = (today - dt.timedelta(days=34)).isoformat()
        with store.db() as db:
            deleted = 0
            for table in ('facts', 'coverage', 'stages', 'cursors'):
                deleted += db.execute('DELETE FROM ' + table + ' WHERE source_date<?', (cutoff,)).rowcount
        directory = checked_child(store.root, 'snapshots')
        active = current(store.root)
        if directory.exists():
            manifests = sorted(directory.glob('seo-*.json'), reverse=True)
            retained = {p.stem for p in manifests[:2]}
            if active:
                retained.add(active['snapshot_id'])
            for meta in manifests:
                if meta.stem not in retained:
                    for path in (meta, meta.with_suffix('.sqlite')):
                        checked_child(directory, path.name).unlink()
            for path in directory.iterdir():
                temporary = bool(re.fullmatch(r'seo-\d{4}-\d{2}-\d{2}\.[a-f0-9]{32}\.tmp',path.name))
                orphan = bool(re.fullmatch(r'seo-\d{4}-\d{2}-\d{2}\.sqlite',path.name)) and not path.with_suffix('.json').exists() and path.stem not in retained
                if temporary or orphan:
                    checked_child(directory,path.name).unlink()
        backups = checked_child(store.root,'backups')
        if backups.exists():
            for path in backups.iterdir():
                if path.is_dir() and path.name.startswith(('candidate-','restore-check-')):
                    shutil.rmtree(checked_child(backups,path.name))
        # No shared databases, WAL files, full VACUUM or system cache operations.
        return dict(logical_rows_deleted=deleted, physical_bytes_before=before,
                    physical_bytes_after=footprint(store.root), sqlite_free_pages_reusable=True)
