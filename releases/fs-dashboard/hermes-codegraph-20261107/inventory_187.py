"""Capture source provenance and selected code snapshots; never alter running sources."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from datetime import datetime, timezone

ROOT = Path('/var/lib/fs-hermes-fc/profile/cache/fs-codegraph')
REPOSITORY = Path('/var/lib/fs-hermes-fc/profile/cache/workspaces/FS-Workbench')
SOURCE_TYPES = {'.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css', '.sh', '.sql'}
SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', 'data', 'logs', 'cache', 'backups', '.cache', '.codegraph'}
SECRET = re.compile(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----|(?i:api[_-]?key|api[_-]?secret|password|passwd|access[_-]?token|secret[_-]?key)\s*[:=]\s*[\"\x27][^\"\x27\r\n]{8,}[\"\x27]')


def command(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True, timeout=25)
    if result.returncode:
        raise RuntimeError('Inventory command failed: '+' '.join(args)+' exit '+str(result.returncode)+' '+result.stderr.strip())
    return result.stdout.strip()


def fail_walk(error):
    raise error


def deployment_root(path):
    parts = Path(path).parts
    return str(Path(*parts[:3 if path.startswith('/opt/') else 4]))


def unit_properties(name):
    common = ['Id', 'ActiveState', 'SubState', 'FragmentPath', 'Triggers']
    return common+(['MainPID', 'WorkingDirectory', 'ExecStart'] if name.endswith('.service') else [])


def checkout_revision(root):
    gitdir = root/'.git'
    if gitdir.is_file():
        marker = gitdir.read_text().strip()
        if not marker.startswith('gitdir: '):
            return None
        gitdir = (root/marker[8:]).resolve()
    head = gitdir/'HEAD'
    if not head.is_file():
        return None
    value = head.read_text().strip()
    if re.fullmatch(r'[0-9a-f]{40}', value):
        return value
    if value.startswith('ref: refs/') and '..' not in Path(value[5:]).parts:
        ref = gitdir/value[5:]
        if ref.is_file():
            value = ref.read_text().strip()
            return value if re.fullmatch(r'[0-9a-f]{40}', value) else None
        packed = gitdir/'packed-refs'
        if packed.is_file():
            for line in packed.read_text().splitlines():
                parts = line.split()
                if len(parts)==2 and parts[1]==value[5:] and re.fullmatch(r'[0-9a-f]{40}',parts[0]):
                    return parts[0]
    return None


def source_files(root):
    for parent, dirs, files in os.walk(str(root), followlinks=False, onerror=fail_walk):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS and not (Path(parent)/name).is_symlink()]
        for name in files:
            path = Path(parent)/name
            if path.suffix.lower() in SOURCE_TYPES and not path.is_symlink():
                yield path


def copy_sources(source, target):
    copied, omitted = [], []
    target.mkdir(parents=True, exist_ok=True)
    for path in source_files(source):
        relative = path.relative_to(source)
        if 'config' in path.name.lower() or any(word in path.name.lower() for word in ('secret', 'credential')):
            omitted.append({'path': str(relative), 'reason': 'possible_runtime_configuration'})
            continue
        if path.stat().st_size > 2_000_000 or '.min.' in path.name:
            omitted.append({'path': str(relative), 'reason': 'large_or_minified_asset'})
            continue
        raw = path.read_bytes()
        if SECRET.search(raw):
            omitted.append({'path': str(relative), 'reason': 'possible_embedded_secret'})
            continue
        destination = target/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.read_bytes() != raw:
            raise RuntimeError('Snapshot already exists with different content: '+str(relative))
        destination.write_bytes(raw)
        if path.read_bytes() != raw:
            raise RuntimeError('Source changed while capturing: '+str(path))
        copied.append({'path': str(relative), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
    return {'files': copied, 'omitted': omitted, 'partial_snapshot': bool(omitted)}


def collect():
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    units = []
    names = set()
    for kind in ['service', 'timer']:
        text = command(['systemctl', 'list-units', '--all', '--type='+kind, '--no-legend', '--no-pager'])
        for line in text.splitlines():
            match = re.search(r'([A-Za-z0-9_.@-]+\.'+kind+r')\s', line)
            if match and re.match(r'(?:fs-|fc27|hermes|rpg|d4follow|g2gfollow)', match.group(1)):
                names.add(match.group(1))
    references = set()
    for name in sorted(names):
        properties = unit_properties(name)
        args = ['systemctl', 'show', name]
        for prop in properties:
            args.extend(['-p', prop])
        fields = dict(line.split('=', 1) for line in command(args).splitlines() if '=' in line)
        entry = fields.pop('ExecStart', '')
        paths = set(re.findall(r'/(?:opt|var/www)/[^\s;\}\]\"\x27]+', entry))
        if fields.get('WorkingDirectory', '').startswith(('/opt/', '/var/www/')):
            paths.add(fields['WorkingDirectory'])
        fields['source_path_references'] = sorted(path for path in paths if not re.search(r'(?i)secret|credential|\.pem|\.key|\.env', path))
        for path in fields['source_path_references']:
            references.add(deployment_root(path))
        units.append(fields)
    containers = []
    for name in command(['docker', 'ps', '--format', '{{.Names}}']).splitlines():
        item = json.loads(command(['docker', 'inspect', name]))[0]
        mounts = []
        for mount in item.get('Mounts', []):
            source = mount.get('Source', '')
            if source.startswith('/opt/') and not re.search(r'(?i)secret|credential|\.pem|\.key|\.env', source):
                references.add(deployment_root(source))
                mounts.append({'source': source, 'destination': mount.get('Destination'), 'writable': mount.get('RW')})
        containers.append({'name': name, 'running': item['State']['Running'], 'source_mounts': mounts})
    git_hashes = {}
    revision = None
    if REPOSITORY.is_dir():
        revision = checkout_revision(REPOSITORY)
        for path in source_files(REPOSITORY):
            name = str(path.relative_to(REPOSITORY))
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in SOURCE_TYPES and path.stat().st_size <= 2_000_000:
                git_hashes.setdefault(hashlib.sha256(path.read_bytes()).hexdigest(), []).append(name)
    captured = datetime.now(timezone.utc).isoformat()
    report = {'captured_at': captured, 'repository_revision': revision, 'checkout_tracking_verification': 'Git CLI unavailable; content matches are against checkout files, not proof of committed or deployed state', 'units': units, 'containers': containers,
              'classification': [], 'snapshots': {}, 'confirmed_safe_to_delete': [],
              'snapshot_scope': {'included_extensions': sorted(SOURCE_TYPES), 'excluded_directories': sorted(SKIP_DIRS),
                                 'purpose': 'Selected code navigation snapshot; not a complete deployment or data backup'},
              'rule': 'No reference found is not deletion authorization; launcher, timer, Docker, frontend, restore and rollback dependencies require review.'}
    for path in sorted(Path('/opt').iterdir()):
        if path.is_dir():
            report['classification'].append({'path': str(path), 'real_path': str(path.resolve()),
                'category': 'runtime_referenced' if str(path) in references else 'unverified_keep',
                'git_checkout': (path/'.git').exists()})
    projects = {}
    sources = {'hermes-runtime': '/opt/fs-hermes-fc', 'fc-coins': '/opt/fc27-cloud-browser',
               'hermes-desktop': '/opt/fs-hermes-desktop', 'fs-data': '/opt/fs-exact-range-20261001'}
    for key, value in sources.items():
        source = Path(value)
        if not source.is_dir():
            continue
        target = ROOT/'sources'/key
        snapshot = copy_sources(source, target)
        for entry in snapshot['files']:
            matches = git_hashes.get(entry['sha256'], [])
            entry['matching_checkout_paths'] = matches
            entry['checkout_content_match'] = bool(matches)
        report['snapshots'][key] = {'source_path': value, **snapshot}
        projects[key] = {'path': '/profile/cache/fs-codegraph/sources/'+key, 'source_kind': 'production_snapshot',
                         'source_path': value, 'source_files': len(snapshot['files']), 'partial_snapshot': snapshot['partial_snapshot']}
    ui = REPOSITORY/'ui-system'
    if ui.is_dir():
        projects['fs-ui'] = {'path': '/profile/cache/workspaces/FS-Workbench/ui-system', 'source_kind': 'git_development_checkout',
                             'recorded_revision': revision, 'source_files': sum(1 for _ in source_files(ui))}
    (ROOT/'inventory-187.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (ROOT/'projects.json').write_text(json.dumps({'captured_at': captured, 'projects': projects,
        'inventory_report': '/profile/cache/fs-codegraph/inventory-187.json'}, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'captured_at': captured, 'units': len(units), 'containers': len(containers), 'opt_directories': len(report['classification']),
            'runtime_referenced_directories': sum(row['category']=='runtime_referenced' for row in report['classification']),
            'projects': projects, 'production_files_changed': False, 'confirmed_safe_to_delete': []}


if __name__ == '__main__':
    print(json.dumps(collect(), ensure_ascii=False))
