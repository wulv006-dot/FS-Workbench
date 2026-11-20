"""Release changed VIP bulk-workflow files through the existing Range publication lane."""
import json
import re
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import vip_release as release
from vip_active_script_release import CONFIG, ROUTE, TARGET, check_route


SCOPE = 'hermes-vip-bulk-20261120'
PRIOR = '/opt/fs-release-stage/hermes-vip-preferred-20261120-635959a57b47/approved-manifest.json'
BASE = {
    'source/tracking_controller.py': '38d273aeab38da91e37d89cca7e274d9b004eedd1df640a517094f63aef0f7a7',
    'source/vip_maintenance.py': 'b4f10169d5c20c77ff7f6c3f8a143a5df4ae392d81ecd410c297e8bef5ee1108',
    'source/index.html': '657ff03a80f2dc20eb4c0a9d77a814cd51c2e72d91a11776a8dda9da4650afef',
    'source/page.js': '69c7e9e496b9d26b10c924aca5b98c297b5db896395601470448b2265781c3e1',
    'source/page.css': '99491baf15b535c274cdc7731a76b5da4f619ebc5d995ff4ef1d15e104dd6ae7',
}
TARGETS = {name: release.TARGETS[name] for name in BASE}
TARGETS['source/page.js'] = TARGET
SOURCES = {name: release.REPO_FILES[name] for name in BASE}
REQUIRED = {'source/tracking_controller.py', 'source/vip_maintenance.py', 'source/page.js'}


def configure(names):
    names = set(names)
    if not REQUIRED <= names <= BASE.keys():
        raise ValueError('vip_bulk_exact_file_scope_required')
    release.SCOPE, release.PRIOR = SCOPE, PRIOR
    release.TARGETS = {name: TARGETS[name] for name in BASE if name in names}
    release.BEFORE = {name: BASE[name] for name in BASE if name in names}
    release.REPO_FILES = {name: SOURCES[name] for name in BASE if name in names}


def bundle(repo, output, commit):
    commit = release.version(commit)

    def blob(path):
        return subprocess.check_output(['git', '-C', str(repo), 'cat-file', 'blob', f'{commit}:{path}'])

    configure(name for name, source in SOURCES.items() if release.sha(blob(source)) != BASE[name])
    proof = release.bundle(repo, output, commit)
    with ZipFile(output, 'a') as archive:
        for name in ('vip_active_script_release.py', 'vip_bulk_release.py'):
            archive.writestr(name, blob(release.RELEASE + '/deploy/' + name))
    return dict(proof, archiveSha256=release.sha(output.read_bytes()), sources=list(release.REPO_FILES))


def verify_routes(text):
    check_route(text)
    for name in ('index.html', 'page.css'):
        route = ROUTE.rsplit('/', 1)[0] + '/' + name
        blocks = re.findall(r'^location = ' + re.escape(route) + r' \{\n(.*?)^\}', text, re.MULTILINE | re.DOTALL)
        if (len(blocks) != 1 or 'auth_request /__nav_formal_native_session;' not in blocks[0]
                or re.findall(r'^\s*alias ([^;]+);', blocks[0], re.MULTILINE) != [TARGETS['source/' + name]]):
            raise ValueError('vip_bulk_active_route_drift: ' + name)


def composed_import(stage):
    candidate = stage / 'candidate/source'
    program = """import sys
from pathlib import Path
candidate = Path(sys.argv[1])
sys.path[:0] = [str(candidate), '/opt/fs-hermes-fc', '/opt/fs-exact-range-20261001']
import tracking_controller, vip_maintenance
assert Path(tracking_controller.__file__).parent == candidate
assert Path(vip_maintenance.__file__).parent == candidate
assert callable(tracking_controller.TrackingController.post)
assert callable(vip_maintenance.VipMaintenance.bulk_claim)
assert callable(vip_maintenance.read_weekly_report)
"""
    subprocess.run([sys.executable, '-I', '-B', '-c', program, str(candidate)], timeout=20, check=True)


def publisher():
    base = release.load_base()
    original_restart = base.restart_for
    original_guards = base.guards

    def activate(manifest, admission_fence=None):
        if manifest['scope'] != SCOPE or admission_fence is None:
            raise ValueError('vip_bulk_range_admission_fence_required')
        admission_fence.stop_then_unlock_database()
        original_restart(dict(manifest, scope=base.DEEP_SCOPE), admission_fence)

    def guards(manifest, root, **kwargs):
        original_guards(manifest, root, **kwargs)
        verify_routes(release.checked_file(release.path_in(root, CONFIG)).read_text(encoding='utf-8'))
        tracking = release.checked_file(release.path_in(root, release.TRACKING_DB))
        with release.closing(release.sqlite3.connect(tracking.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            if db.execute("SELECT 1 FROM vip_preferred_refresh WHERE status='pending' AND "
                          "datetime(attempted_at) > datetime('now','-30 minutes')").fetchone():
                raise ValueError('vip_preferred_refresh_in_flight')

    base.restart_for, base.guards = activate, guards
    return base


def main(action, *args):
    if action == 'bundle' and len(args) == 3:
        result = bundle(Path(args[0]), Path(args[1]), args[2])
    else:
        stage = release.HERE
        configure(json.loads((stage / 'source-proof.json').read_bytes())['sha256'])
        release.run_composed_import = composed_import
        verify_routes(release.checked_file(Path(CONFIG)).read_text(encoding='utf-8'))
        if action == 'prepare' and not args:
            result = release.prepare(stage)
        else:
            publisher().main()
            return
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main(*sys.argv[1:])
