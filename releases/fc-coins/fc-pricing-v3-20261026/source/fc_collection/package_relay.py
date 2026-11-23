"""One IGGM request/response per SSH forced-command connection."""
from pathlib import Path
import socket
import subprocess
import sys
from threading import Timer
import time
import uuid

from .protocol import read_message, write_message

ROOT = Path('/run/fs-fc-iggm-local')
ALIAS = 'fs-fc-iggm-readback'


def request_local(request, *, root=ROOT, timeout=12):
    if request['source'] != 'IGGM' or str(uuid.UUID(request['run_id'])) != request['run_id']:
        raise ValueError('local_iggm_scope')
    if not hasattr(socket, 'AF_UNIX') or not root.is_dir():
        raise OSError('local_relay_unavailable')
    path = root / (request['run_id']+'.sock')
    # The publisher owns the directory and grants only the collector relay group access.
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        try:
            path.chmod(0o660)
            server.listen(1)
            server.settimeout(timeout)
            conn, _ = server.accept()
            with conn, conn.makefile('rwb', buffering=0) as stream:
                conn.settimeout(timeout)
                write_message(stream, request)
                return read_message(stream)
        finally:
            path.unlink(missing_ok=True)


def relay(root=ROOT):
    # No user-supplied paths, commands or source URLs on the 187 side.
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        for path in sorted(root.glob('*.sock')):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(12)
                try:
                    conn.connect(str(path))
                except (FileNotFoundError, ConnectionRefusedError):
                    continue
                with conn.makefile('rwb', buffering=0) as stream:
                    write_message(sys.stdout.buffer, read_message(stream))
                    write_message(stream, read_message(sys.stdin.buffer))
                return
        time.sleep(1)
    write_message(sys.stdout.buffer, {'status':'idle'})


def local_once():
    from .package_reader import run_request
    cmd = ['ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=7',
           '-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2','-o','ForwardAgent=no','-o','ClearAllForwardings=yes',ALIAS]
    with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE) as ssh:
        watchdog = Timer(55, ssh.kill)
        watchdog.start()
        try:
            task = read_message(ssh.stdout)
            if task == {'status':'idle'}:
                return
            if task.get('source')!='IGGM':
                raise ValueError('local_iggm_scope')
            write_message(ssh.stdin, run_request(task))
        finally:
            watchdog.cancel()
            ssh.stdin.close()
            try:
                ssh.wait(timeout=4)
            except subprocess.TimeoutExpired:
                ssh.kill()


if __name__ == '__main__':
    if sys.argv[1:] == ['relay']:
        relay()
    elif sys.argv[1:] == ['local']:
        while True:
            try:
                local_once()
            except (EOFError, OSError, ValueError, subprocess.SubprocessError):
                time.sleep(10)
    else:
        raise SystemExit('expected relay or local')
