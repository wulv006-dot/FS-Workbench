"""SEO-local capacity, retention and verified base backups; AI is optional."""
import datetime as dt
import json
import os
import shutil
import sqlite3
import uuid
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
            completed = backups / ('backup-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
            os.replace(candidate, completed)
            verified = True
            # Rotate only after the new copy passes restore checks; preserve two trusted copies.
            old = sorted(backups.glob('backup-*'), reverse=True)
            for directory in old[2:]:
                verify_backup(directory)
                shutil.rmtree(checked_child(backups, directory.name))
            return dict(verified=True, path=str(completed), bytes=footprint(completed))
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
        # No shared databases, WAL files, full VACUUM or system cache operations.
        return dict(logical_rows_deleted=deleted, physical_bytes_before=before,
                    physical_bytes_after=footprint(store.root), sqlite_free_pages_reusable=True)
