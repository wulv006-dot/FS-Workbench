"""Exact batch recovery delta on the original Players publisher; no policy change."""
import fcntl,hashlib,importlib.util,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
original=HERE/'upgrade_direct_json.py'
if not original.is_file():original=HERE.parent/'direct-json-20261029/publisher/upgrade_direct_json.py'
assert hashlib.sha256(original.read_bytes()).hexdigest()=='37b2b48020be180f2b2b00ab3ff2a51766edd8cfd9c7843096b9c623e6d5c1ea'
spec=importlib.util.spec_from_file_location('players_existing_publisher',original)
P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)
MANIFEST_SHA='7dc20f95690515d1ed1eca4808e97c0ffd9c1c32ec8d155878ef1d3dcd640f73'
def validate_manifest(value):
    raw=(HERE/'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=MANIFEST_SHA or value!=json.loads(raw):raise RuntimeError('Publication manifest changed')
    if value.get('_fixture_only'):raise RuntimeError('Fixture cannot deploy')
P.validate_manifest=validate_manifest
manifest=json.loads((HERE/'manifest.json').read_text(encoding='utf-8'));validate_manifest(manifest)
P.VERSION=manifest['version'];P.BASE_VERSION=manifest['base_version']
P.RELEASE=P.ROOT/'releases'/P.VERSION;P.BASE_IMAGE='fc27-player-tool:'+P.BASE_VERSION
P.IMAGE='fc27-player-tool:'+P.VERSION;P.BASE_IMAGE_ID=manifest['base_image_id']
P.PATCHES={name:(P.ROOT/'releases'/P.BASE_VERSION/name,manifest['baseline'][name]) for name in ('player_web/shared_session.py','球员维护工具/admin_client.py')}
original_unit=P.updated_unit
def updated_unit(text):
    if text.count('--env MANUAL_EXISTING_ADD_TAGS_ENABLED=true')!=1:raise RuntimeError('Existing manual tag flag changed')
    return original_unit(text)
P.updated_unit=updated_unit
if __name__=='__main__':
    with open(P.ROOT/'deployment.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);P.main()
