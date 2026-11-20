"""Publish the two VIP views from the last verified production sources and menu alias."""
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import vip_release as release
from vip_active_script_release import CONFIG, TARGET, check_route


release.SCOPE = 'hermes-vip-preferred-20261120'
release.PRIOR = '/opt/fs-release-stage/hermes-vip-maintenance-20261120-c56c0af64bfa/approved-manifest.json'
release.TARGETS['source/page.js'] = TARGET
release.BEFORE = {'source/' + name: digest for name, digest in {
    'tracking_controller.py': 'a316c7cfddf182e20a19015fd35ec2f182c0fcf1ef1e8e351c3649572b98169b',
    'vip_maintenance.py': 'ab4131f6f971dc953663fa9b40e64a1dec77b6ba7b278ef85690f59a230ce2fa',
    'vip_followup.py': '213a26a0e265a342c74a261f46ee5560e3db8bd2cbe636ded8280ee210510248',
    'vip_query.py': '94240a88293690cb331a62da951ea750c52e85031304d0cc3281ee94bda80b75',
    'nightly_data.py': 'c0e29ecc6f03a1d0aa25b3b83c4a9c74da8beda996353025ad6084c30884e485',
    'index.html': 'bef7efa5333520e738e8c68b65c34716114317e2616a77ab3738783fe3473861',
    'page.css': '01ed387c4ba69c179255fd1a7f7c934f3303687f5106bac571a3e3effd3fb9ac',
    'page.js': 'b1d737c40d7e8fa3c619937cc96a1cf00fca855706bafeba1c6190b1f40f524e',
}.items()}


def main(action, *args):
    if action == 'bundle':
        repo, output, commit = args
        proof = release.bundle(Path(repo), Path(output), commit)
        with ZipFile(output, 'a') as archive:
            for name in ('vip_active_script_release.py', 'vip_preferred_release.py'):
                source = f'{commit}:{release.RELEASE}/deploy/{name}'
                archive.writestr(name, subprocess.check_output(['git', '-C', repo, 'cat-file', 'blob', source]))
        proof['archiveSha256'] = release.sha(Path(output).read_bytes())
        print(json.dumps(proof))
        return
    check_route(release.checked_file(Path(CONFIG)).read_text(encoding='utf-8'))
    release.main(action, *args)


if __name__ == '__main__':
    main(*sys.argv[1:])
