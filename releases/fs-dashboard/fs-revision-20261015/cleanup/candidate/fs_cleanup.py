"""FS maintenance: prune only verified, expired, unreferenced on-demand daily cache rows."""
import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import re
import stat
import subprocess
from threading import local
import uuid

CACHE = Path('/var/lib/fs-business-ranges/profit-days')
AUDIT = Path('/var/lib/fs-maintenance-cleanup')
RETENTION_DAYS = 7
WRITER_SHA = '0e89299020a723d674dd2ba1fc3b46c07c8591b9027147ab1302bf606cfb8da0'
REFERENCES = tuple(Path(p) for p in ['/var/www/dashboard/fs-home/transactions', '/opt/mmoexp-weekly-report', '/var/lib/fs-hermes-fc', '/var/lib/fs-boss-workspaces', '/var/lib/fs-business-ranges/fc-daily'])
SHANGHAI = timezone(timedelta(hours=8))
HELD = local()


def checked_path(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('path_outside_scope')
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('linked_path')
    return path


def directory_fd(path):
    checked_path(path)
    if os.name != 'posix':
        raise RuntimeError('posix_apply_required')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open('/', flags)
    try:
        for part in Path(path).parts[1:]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def cache_guard(path, blocking=True):
    """Readers, writers and maintenance share this reentrant per-thread file lock."""
    path = checked_path(path)
    key = str(path)
    held = getattr(HELD, 'locks', None)
    if held is None:
        held = HELD.locks = {}
    if key in held:
        yield held[key]
        return
    directory = directory_fd(path)
    fd = None
    try:
        import fcntl
        directory_info = os.fstat(directory)
        if directory_info.st_uid != os.geteuid() or directory_info.st_mode & 0o022:
            raise ValueError('unsafe_cache_directory')
        fd = os.open('.retention.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('unsafe_cache_lock')
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        held[key] = directory
        try:
            yield directory
        finally:
            held.pop(key)
    finally:
        if fd is not None:
            os.close(fd)
        os.close(directory)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def expired_row(data, name, now):
    row = json.loads(data)
    if not isinstance(row, dict):
        return False
    if row.get('collectionKind') != 'on-demand-native-day' or row.get('source') != 'order.p2pah.cn' or row.get('endpoint') != '/stats/admin_order/index.html':
        return False
    if row.get('status') != 'available' or row.get('latestAttemptStatus') != 'available' or row.get('stale') is not False:
        return False
    if row.get('timezone') != 'Asia/Shanghai' or row.get('currency') != 'USD' or row.get('profitUsd') is not None or row.get('costUsd') is not None:
        return False
    if row.get('marginUnit') != 'percent' or type(row.get('orders')) is not int or row['orders'] < 0:
        return False
    if any(type(row.get(key)) not in (int, float) or not isfinite(row[key]) for key in ['profitMarginPct', 'revenueUsd']) or row['revenueUsd'] < 0:
        return False
    stamp = datetime.fromisoformat(row['capturedAt'].replace('Z', '+00:00'))
    latest = datetime.fromisoformat(row['latestAttemptAt'].replace('Z', '+00:00'))
    if stamp.tzinfo is None or latest.tzinfo is None or stamp.utcoffset() != timedelta(0) or latest.utcoffset() != timedelta(0):
        return False
    if latest != stamp or not timedelta(days=RETENTION_DAYS) < now - stamp:
        return False
    day = date.fromisoformat(row['date'])
    if stamp.astimezone(SHANGHAI).date() <= day or row['period'] != {'start': str(day) + ' 00:00', 'end': str(day + timedelta(days=1)) + ' 00:00'}:
        return False
    scope = row['scope']
    if scope['sites'] != 'all-websites' or not isinstance(row['profileKey'], str):
        return False
    expected = dict(sites=scope['sites'], gid=scope['orderGameId'], tid=scope['orderProductType'], status=scope['orderStatus'])
    key = sha(json.dumps([row['profileKey'], row['date'], expected], sort_keys=True).encode())
    return name == key + '.json'


def references(roots=REFERENCES):
    result = set()
    for root in roots:
        checked_path(root)
        if not root.exists():
            continue
        count = 0
        for base, dirs, files in os.walk(str(root), followlinks=False):
            for name in list(dirs):
                if (Path(base) / name).is_symlink():
                    if name != 'current-files' or root != REFERENCES[0]:
                        raise ValueError('reference_scan_linked_directory')
                    dirs.remove(name)
            for name in files:
                count += 1
                if count > 30000:
                    raise ValueError('reference_scan_limit')
                path = Path(base) / name
                if path.is_symlink():
                    raise ValueError('reference_scan_linked_file')
                if path.suffix not in {'.json', '.jsonl', '.html', '.txt', '.md', '.log'}:
                    continue
                info = path.stat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 16 * 1024 * 1024:
                    raise ValueError('reference_file_limit')
                result.update(m.decode() for m in re.findall(rb'(?<![a-f0-9])[a-f0-9]{64}(?![a-f0-9])', path.read_bytes()))
    return result


def plan(root=CACHE, now=None, referenced=None):
    root = checked_path(root)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('aware_time_required')
    referenced = references() if referenced is None else referenced
    rows = []
    preserved = 0
    if root.exists():
        for path in sorted(root.iterdir()):
            if not re.fullmatch(r'[a-f0-9]{64}\.json', path.name):
                preserved += 1
                continue
            info = path.lstat()
            if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.stem in referenced or info.st_size > 1024 * 1024:
                preserved += 1
                continue
            data = path.read_bytes()
            try:
                eligible = expired_row(data, path.name, now)
            except (ValueError, KeyError, TypeError):
                eligible = False
            if not eligible:
                preserved += 1
                continue
            rows.append({'name': path.name, 'bytes': info.st_size, 'sha256': sha(data), 'device': info.st_dev, 'inode': info.st_ino, 'mtimeNs': info.st_mtime_ns})
    return {'schemaVersion': 1, 'root': str(root), 'capturedAt': now.isoformat(), 'retentionDays': RETENTION_DAYS, 'eligibleFiles': len(rows), 'eligibleBytes': sum(r['bytes'] for r in rows), 'preservedFiles': preserved, 'referencedIdentifiers': len(referenced), 'rows': rows}


def inside_window(now):
    local_time = now.astimezone(SHANGHAI)
    return local_time.hour < 7 and not (local_time.hour == 6 and local_time.minute >= 59)


def apply(preview, root=CACHE, now=None, referenced=None, clock=None, action=None):
    root = checked_path(root)
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = now or clock()
    if preview['root'] != str(root) or not inside_window(now):
        raise ValueError('scope_or_window_changed')
    referenced = references() if referenced is None else referenced
    removed = []
    with cache_guard(root, blocking=False) as directory:
        for row in preview['rows']:
            if not inside_window(clock()):
                break
            name = row['name']
            if not re.fullmatch(r'[a-f0-9]{64}\.json', name) or name[:-5] in referenced:
                continue
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (row['device'], row['inode'], row['bytes'], row['mtimeNs']):
                    continue
                with os.fdopen(os.dup(fd), 'rb') as stream:
                    data = stream.read(1024 * 1024 + 1)
                if sha(data) != row['sha256'] or not expired_row(data, name, now):
                    continue
                if action:
                    action('delete_planned', row)
                os.unlink(name, dir_fd=directory)
                removed.append({'name': name, 'bytes': row['bytes'], 'sha256': row['sha256']})
                if action:
                    action('deleted', row)
            finally:
                os.close(fd)
        os.fsync(directory)
    return {'removedFiles': len(removed), 'removedBytes': sum(r['bytes'] for r in removed), 'removed': removed}


def audit(record):
    checked_path(AUDIT)
    AUDIT.mkdir(mode=0o700, parents=True, exist_ok=True)
    if AUDIT.stat().st_mode & 0o077:
        raise ValueError('unsafe_audit_directory')
    path = AUDIT / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex + '.json')
    with path.open('x', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        json.dump(record, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    return str(path)


def append_action(path, event, row):
    with Path(path + '.actions.jsonl').open('a', encoding='utf-8') as stream:
        os.chmod(stream.name, 0o600)
        stream.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(), 'event': event, 'name': row['name'], 'sha256': row['sha256'], 'bytes': row['bytes']}, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def cooperating_writer_running():
    result = subprocess.run(['systemctl', 'show', 'fs-business-range.service', '--property=MainPID'], capture_output=True, text=True, timeout=5)
    pid = int(result.stdout.strip().split('=', 1)[1])
    if result.returncode or pid <= 1:
        return False
    raw = Path('/proc/{}/stat'.format(pid)).read_text()
    ticks = int(raw[raw.rindex(')') + 2:].split()[19])
    boot = int(next(line.split()[1] for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime ')))
    started = boot + ticks / os.sysconf('SC_CLK_TCK')
    return started > max(Path(__file__).stat().st_mtime, Path(__file__).with_name('profit_queries.py').stat().st_mtime)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    record = {'status': 'dryrun', 'apply': args.apply, 'protectedScope': ['all snapshots', 'reports and evidence', 'databases', 'audit', 'rollback', 'unknown directories'], 'removedFiles': 0}
    try:
        preview = plan()
        record['plan'] = preview
        if args.apply:
            source = Path(__file__).with_name('profit_queries.py').read_bytes()
            if sha(source) != WRITER_SHA or not cooperating_writer_running():
                raise ValueError('cooperating_cache_writer_missing')
            planned = audit({**record, 'status': 'planned', 'removedFiles': None})
            record.update(plannedAudit=planned, removedFiles=None)
            record.update(apply(preview, action=lambda event, row: append_action(planned, event, row)), status='applied')
    except Exception as error:
        record.update(status='skipped', reason=type(error).__name__)
    target = audit(record)
    print(json.dumps({'status': record['status'], 'removedFiles': record['removedFiles'], 'audit': target}, sort_keys=True))


if __name__ == '__main__':
    main()
