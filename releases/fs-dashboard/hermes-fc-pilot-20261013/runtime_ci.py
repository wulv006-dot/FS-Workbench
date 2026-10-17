"""Build and test the official runtime on an isolated Linux CI runner."""
import hashlib
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler


SOURCES = (
    ('hermes-71d34bad.tar.gz', 'https://codeload.github.com/NousResearch/hermes-agent/tar.gz/71d34bad1045610252eda02ee79549436896e784',
     'a88ae3f634a3fd45050d3418d80b30ee5af51c89b9de40ec1ea3039d3024d77a'),
    ('sqlite-autoconf-3530400.tar.gz', 'https://sqlite.org/2026/sqlite-autoconf-3530400.tar.gz',
     '0e9483900e92cd5de8fd48d16bf9200145a61f7fd5be542a5ac81d8a9516eb9c'),
    ('uv-0.12.3.tar.gz', 'https://github.com/astral-sh/uv/releases/download/0.12.3/uv-x86_64-unknown-linux-gnu.tar.gz',
     '600cf9a742aca00d292673b16b5acffaa7b8c269a364ad0c2e79498dcb1fe101'))
HOSTS = {'codeload.github.com', 'sqlite.org', 'github.com', 'release-assets.githubusercontent.com'}


class ApprovedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if parsed.scheme != 'https' or parsed.hostname not in HOSTS:
            raise ValueError('unapproved_download_redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--test', action='store_true')
    args = parser.parse_args()
    if args.prepare == args.test:
        raise ValueError('choose_exactly_one_phase')
    if not shutil.which('docker'):
        raise RuntimeError('Linux Docker runner required; no silent skip')
    if args.prepare:
      with tempfile.TemporaryDirectory(prefix='hermes-official-ci-') as folder:
        context = Path(folder)
        shutil.copyfile(root/'Dockerfile', context/'Dockerfile')
        for name, url, expected in SOURCES:
            hasher = hashlib.sha256(); size = 0
            with build_opener(ApprovedRedirect).open(url, timeout=120) as source, (context/name).open('wb') as target:
                while chunk := source.read(1024*1024):
                    size += len(chunk)
                    if size > 250*1024*1024:
                        raise ValueError('source_size')
                    target.write(chunk); hasher.update(chunk)
            if hasher.hexdigest() != expected:
                raise ValueError('official_source_digest_changed: '+name)
        subprocess.run(['docker', 'build', '-t', 'fs-hermes-fc:ci', str(context)], check=True, timeout=900)
    if args.test:
      subprocess.run(['unshare','--net',sys.executable,'-B',str(root/'network_smoke.py')],check=True,timeout=45)
      for effort in ('high','max'):
        subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                        '--security-opt', 'no-new-privileges', '--user', '65534:65534',
                        '--tmpfs', '/tmp:rw,nosuid,nodev,size=268435456',
                        '-e', 'HOME=/tmp/hermes', '-e', 'HERMES_HOME=/tmp/hermes',
                        '-e', 'PYTHONPATH=/opt/hermes:/opt/pilot',
                        '-v', str(root)+':/opt/pilot:ro', 'fs-hermes-fc:ci', '/opt/pilot/runtime_smoke.py','--effort',effort],
                       check=True, timeout=180)


if __name__ == '__main__':
    main()
