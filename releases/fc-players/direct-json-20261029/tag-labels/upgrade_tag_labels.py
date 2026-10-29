"""Exact cloud15 -> cloud16 adapter; reuse the original Players publisher unchanged."""
import importlib.util
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing

HERE = Path(__file__).resolve().parent
ORIGINAL_SHA = '37b2b48020be180f2b2b00ab3ff2a51766edd8cfd9c7843096b9c623e6d5c1ea'
MAP_SHA = '3006b2fc38b431d9eef67d416970f9fcd8a9881b72ddccdf98cb977a1576fe48'


def pinned_text(path, expected):
    text = path.read_text(encoding='utf-8')
    if hashlib.sha256(text.encode('utf-8')).hexdigest() != expected:
        raise RuntimeError('Publisher dependency changed: ' + str(path))
    return text


original = HERE / 'upgrade_direct_json.py'
if not original.is_file():
    original = HERE.parent / 'publisher/upgrade_direct_json.py'
pinned_text(original, ORIGINAL_SHA)
spec = importlib.util.spec_from_file_location('players_cloud16_original_publisher', original)
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
CONTRACT = json.loads(pinned_text(HERE / 'SOURCE-MAP.json', MAP_SHA))
P.VERSION = CONTRACT['version']
P.BASE_VERSION = CONTRACT['base_version']
P.RELEASE = P.ROOT / 'releases' / P.VERSION
P.BASE_IMAGE = 'fc27-player-tool:' + P.BASE_VERSION
P.BASE_IMAGE_ID = CONTRACT['base_image_id']
P.IMAGE = 'fc27-player-tool:' + P.VERSION
P.STAGE = P.ROOT / 'staging/tag-labels-20261029'
BASELINE = {**CONTRACT['protected'], **{name: item['baseline_sha256'] for name, item in CONTRACT['files'].items()}}
FILES = {name: item['candidate_sha256'] for name, item in CONTRACT['files'].items()}
P.PATCHES = {name: (P.ROOT / 'releases' / P.BASE_VERSION / name, BASELINE[name])
             for name in ('player_web/shared_session.py', '球员维护工具/admin_client.py')}
CONFIG_SHA = {
    'base_env_sha256': '165451691cdb2f0e93590fb1120c488cef85ed3498efaa4df6afdb926ca107ab',
    'base_unit_sha256': '91f2fcee26451bac22480424ecb3c63fc263f8c760ffd22ff86871d4e17afba5',
    'base_on_demand_sha256': '50fc07e2a959bb0bcc68423ce7d85217a1b4eeb86dc9f77da4750fd76febd76b',
    'base_source_manifest_sha256': CONTRACT['base_source_manifest_sha256'],
}


def validate_manifest(manifest):
    if manifest.get('_fixture_only'):
        raise RuntimeError('Fixture cannot be deployed')
    expected = {'version': P.VERSION, 'base_version': P.BASE_VERSION,
                'base_image_id': P.BASE_IMAGE_ID, 'manual_flag': P.MANUAL_FLAG,
                'baseline': BASELINE, 'files': FILES, **CONFIG_SHA}
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise RuntimeError('Only exact cloud15 -> cloud16 three-target label delta is allowed')
    for key in ('archive_sha256', 'dockerfile_sha256'):
        value = manifest.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(ch not in '0123456789abcdef' for ch in value):
            raise RuntimeError('Invalid SHA256: ' + key)


def db_state():
    # Protect the complete existing store, including saved image plans and snapshots.
    with closing(sqlite3.connect('file:' + str(P.DB) + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        if not all(name.replace('_', '').isascii() and name.replace('_', '').isalnum() for name in names):
            raise RuntimeError('Unexpected database table name')
        return {'active': db.execute("SELECT COUNT(*) FROM executions WHERE status IN ('queued','running','waiting_price_lock')").fetchone()[0],
                'executions': db.execute('SELECT COUNT(*) FROM executions').fetchone()[0],
                'legacy': db.execute('SELECT COUNT(*) FROM legacy_unresolved').fetchone()[0],
                'schema': list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")),
                'ledger': {name: P.ledger_digest(db, name) for name in names},
                'admin_tasks_sha256': P.sha(P.ADMIN_TASKS)}


P.validate_manifest = validate_manifest
P.db_state = db_state


def validate_dockerfile(text):
    version_check = "import hashlib; from pathlib import Path; assert hashlib.sha256(Path('/app/VERSION').read_bytes()).hexdigest() == '" + FILES['VERSION'] + "'"
    expected = ['FROM '+P.BASE_IMAGE, 'USER root', 'WORKDIR /app',
                'COPY player_web /app/player_web',
                'COPY ["球员维护工具", "/app/球员维护工具"]',
                'COPY VERSION /app/VERSION',
                'RUN '+json.dumps(['python3', '-B', '-c', version_check])]
    if text.splitlines() != expected:
        raise RuntimeError('Only explicit VERSION copy and exact Git-byte build assertion are allowed')


P.validate_dockerfile = validate_dockerfile


def main():
    # Original lock/CAS/config/backup/rollback flow. No alternative deployment path.
    with open(P.ROOT / 'deployment.lock', 'a') as handle:
        P.fcntl.flock(handle.fileno(), P.fcntl.LOCK_EX | P.fcntl.LOCK_NB)
        P.main()


if __name__ == '__main__':
    main()
