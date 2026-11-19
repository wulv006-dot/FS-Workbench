"""Apply an inspected FC project review bundle through the original FS release publisher."""
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path

from prepare_release import RUNTIME, SCOPE

BRIDGE = Path('/opt/fs-release-stage/traffic-source-tabs-20261019-v3/release_source_tabs.py')
BRIDGE_SHA = '78b4b054162a9cf578543f11bc6cea3b0041b535d49ea1c8f6059514f90e3466'
STAGE = Path(__file__).resolve().parent


def publisher(targets):
    raw = BRIDGE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BRIDGE_SHA:
        raise ValueError('Existing FS release bridge has changed.')
    source = raw.decode()
    runtime = "{'nginx.service':{'ActiveState':'active'},'fs-marketing-range.service':{'ActiveState':'active'}}"
    if source.count(runtime) != 1:
        raise ValueError('Existing FS release runtime validation changed.')
    bridge = types.ModuleType('fc_project_review_release_bridge')
    bridge.__file__ = str(BRIDGE)
    exec(compile(source.replace(runtime, repr(RUNTIME)), str(BRIDGE), 'exec'), bridge.__dict__)
    bridge.SCOPE = SCOPE
    bridge.TARGETS = targets
    release = bridge.publisher()
    live_lock = release.live_lock
    release.locks = release.ui_only_locks
    release.live_lock = lambda manifest, root: live_lock(dict(manifest, scope=release.DETAIL_SCOPE), root)

    def activate(manifest, _fence=None):
        if manifest.get('scope') != SCOPE:
            raise ValueError('Invalid release activation scope.')
        subprocess.run(['nginx', '-t'], check=True)
        subprocess.run(['systemctl', 'restart', 'fs-business-range.service'], check=True)
        subprocess.run(['systemctl', 'reload', 'nginx.service'], check=True)
        subprocess.run(['systemctl', 'is-active', '--quiet', 'nginx.service', 'fs-business-range.service'], check=True)

    release.restart_for = activate
    return release


def main(action, *args):
    raw = (STAGE / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    targets = json.loads((STAGE / 'targets.json').read_bytes())
    release = publisher(targets)
    if action == 'inspect' and not args:
        result = release.inspect(manifest, STAGE)
    elif action == 'apply' and len(args) == 2:
        result = release.apply(manifest, STAGE, args[0], raw, args[1])
    elif action == 'rollback' and len(args) == 2:
        result = release.rollback(Path(args[0]), args[1])
    else:
        raise ValueError('Use inspect, apply MANIFEST_SHA RELEASE_ID, or rollback BACKUP MANIFEST_SHA.')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main(*sys.argv[1:])
