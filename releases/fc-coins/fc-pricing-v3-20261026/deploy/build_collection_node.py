"""Export the source-limited node role. Coordinator/SSH client/credentials stay on187."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('__init__.py', 'contracts.py', 'worker.py', 'adapters.py', 'protocol.py', 'public_sources.py', 'server.py')
CONTROL_MODULES = ('__init__.py', 'contracts.py', 'coordinator.py', 'protocol.py', 'ssh_client.py', 'public_sources.py', 'pilot.py')
ENTRY = b'''from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from fc_collection.server import main
main(ROOT)
'''
CONTROL_ENTRY = b'''from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from fc_collection.pilot import main
main()
'''


def build(output, role='node'):
    if role not in ('node', 'control'):
        raise ValueError('collection_role_invalid')
    files = {'fc_collection/' + name: (ROOT / 'source/fc_collection' / name).read_bytes().replace(b'\r\n', b'\n')
             for name in (MODULES if role == 'node' else CONTROL_MODULES)}
    files['entry.py'] = ENTRY if role == 'node' else CONTROL_ENTRY
    manifest = dict(schema_version=1, role='limited_fc_collector' if role == 'node' else 'fc_collection_controller', production_consume=False,
        sources=['ArabUT'], credentials=[], business_runtime=False,
        sha256={name: hashlib.sha256(body).hexdigest() for name, body in files.items()})
    files['manifest.json'] = json.dumps(manifest, sort_keys=True, indent=2).encode('utf-8')
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(files.items()):
            archive.writestr(name, body)
    return manifest


if __name__ == '__main__':
    build(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) == 3 else 'node')
