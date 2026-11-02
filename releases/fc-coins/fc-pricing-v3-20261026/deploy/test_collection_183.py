"""Run a whitelisted FC test ZIP on 183; no host installs or business mounts.

Upload this file and the ZIP through the existing server_183 access wrapper.
Usage on 183: python3 -B test_collection_183.py /var/tmp/BUNDLE.zip SHA256
The official image must already exist locally; this runner never pulls an image.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile

IMAGE = 'python:3.9.18-slim@sha256:aa7b73608abcfb021247bbb4c111435234a0459298a6da610681097a54ca2c2a'
FILES = {'source/fc_collection/' + name for name in
         ('__init__.py', 'contracts.py', 'coordinator.py', 'adapters.py', 'worker.py',
          'protocol.py', 'public_sources.py', 'server.py', 'ssh_client.py', 'pilot.py', 'client.py', 'failover.py')}
FILES.add('source/fc_pricing_v3/sources.py')
FILES.add('source/server_quote_job.py')
# The publisher enumerates these source filenames; tests never load business sessions or data.
FILES |= {'source/fc_pricing_v3/' + name for name in ('__init__.py', 'api.py', 'business_source.py',
          'ledger.py', 'monitoring.py', 'observations.py', 'regional_public.py', 'runtime.py', 'scheduler.py',
          'shadow_worker.py', 'simulation.py', 'selective_sources.py', 'daily.py')}
FILES |= {'tests/' + name for name in ('collection_cases.py', 'test_collection_contracts.py',
          'test_collection_leases.py', 'test_collection_limits.py', 'test_collection_worker.py',
          'test_collection_public_source.py', 'test_collection_protocol.py', 'test_collection_service.py',
          'test_collection_node_package.py', 'test_collection_pilot.py', 'test_collection_install.py',
          'test_collection_routing.py', 'test_collection_failover.py', 'test_collection_release.py')} | {
          'deploy/build_collection_node.py', 'deploy/install_collection_node.py', 'deploy/prepare_collection_control.py',
          'deploy/target_map.py', 'deploy/fc_v3_release_adapter.py', 'deploy/prepare_manifest.py', 'deploy/release_readiness.py'}


def extract(bundle, target):
    with zipfile.ZipFile(bundle) as archive:
        members = archive.infolist()
        if (not members or len({item.filename for item in members}) != len(members)
                or any(item.filename not in FILES or item.file_size > 1048576 for item in members)
                or sum(item.file_size for item in members) > 8388608):
            raise ValueError('test_bundle_not_whitelisted')
        for item in members:
            path = target / item.filename
            path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            path.write_bytes(archive.read(item))
            path.chmod(0o644)


def main():
    if sys.platform != 'linux' or len(sys.argv) != 3:
        raise ValueError('run_on_183_with_bundle_and_sha256')
    bundle = Path(sys.argv[1])
    if bundle.is_symlink() or bundle.stat().st_size > 8388608 or hashlib.sha256(bundle.read_bytes()).hexdigest() != sys.argv[2]:
        raise ValueError('test_bundle_hash_invalid')
    available = [line for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')][0]
    if int(available.split()[1]) < 1048576 or os.statvfs('/var/tmp').f_bavail * os.statvfs('/var/tmp').f_frsize < 1073741824:
        raise ValueError('test_resource_budget_unavailable')
    image = subprocess.check_output(['docker', 'image', 'inspect', IMAGE, '--format', '{{.Id}}'], text=True).strip()
    ident = uuid.uuid4().hex
    name = 'fs-fc-test-' + ident
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='fs-fc-tests-', dir='/var/tmp') as folder:
        target = Path(folder)
        target.chmod(0o755)
        extract(bundle, target)
        print(json.dumps(dict(host=socket.gethostname(), bundle_sha256=sys.argv[2], image=image,
            image_ref=IMAGE, target_python='3.9.18', network='none', user='65534:65534',
            cpu_quota='0.25', memory_bytes=268435456, pids=64, temporary_bytes=33554432,
            max_seconds=180, business_mounts=[], persistent_identity_created=False)), flush=True)
        command = ['docker', 'run', '--rm', '--pull=never', '--name', name, '--label', 'fs.fc.isolated_test=' + ident,
            '--network=none', '--user=65534:65534', '--read-only', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--cpus=0.25', '--memory=256m', '--memory-swap=256m',
            '--pids-limit=64', '--ulimit', 'fsize=33554432:33554432',
            '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777',
            '--mount', 'type=bind,source=' + folder + ',target=/work,readonly', '--workdir=/work', IMAGE,
            'python', '-I', '-B', '-c',
            "import json,sys,unittest;print(json.dumps(dict(actual_python=sys.version,platform=sys.platform)),flush=True);"
            "assert sys.version_info[:3]==(3,9,18);"
            "r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests',pattern='test_collection_*.py'));"
            "sys.exit(0 if r.testsRun and r.wasSuccessful() and not r.skipped else 1)"]
        try:
            result = subprocess.run(command, timeout=180)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
        finally:
            check = subprocess.run(['docker', 'inspect', name, '--format', '{{index .Config.Labels "fs.fc.isolated_test"}}'],
                                   capture_output=True, text=True, timeout=10)
            if check.returncode == 0:
                if check.stdout.strip() != ident:
                    raise ValueError('test_container_identity_conflict')
                subprocess.run(['docker', 'rm', '-f', name], check=True, timeout=15)
        print(json.dumps(dict(exit_code=code, elapsed_seconds=round(time.monotonic() - started, 3),
                              temporary_directory_removed_on_exit=True)), flush=True)
        return code


if __name__ == '__main__':
    sys.exit(main())
