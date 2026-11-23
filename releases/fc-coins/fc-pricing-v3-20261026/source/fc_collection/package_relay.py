"""One fixed-source ordinary package receipt per SSH forced-command connection."""
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
LOCAL_SOURCES = ('IGGM', 'U4GM')
WORKER_POLL_SECONDS = 30
RECEIPT_TIMEOUT_SECONDS = 30  # Three sequential public GETs at up to seven seconds each.


def request_local(request, *, root=ROOT, timeout=12):
    if request['source'] not in LOCAL_SOURCES or str(uuid.UUID(request['run_id'])) != request['run_id']:
        raise ValueError('local_package_scope')
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
                conn.settimeout(RECEIPT_TIMEOUT_SECONDS)
                write_message(stream, request)
                return read_message(stream)
        finally:
            path.unlink(missing_ok=True)


def relay(root=ROOT):
    # No user-supplied paths, commands or source URLs on the 187 side.
    deadline = time.monotonic()+WORKER_POLL_SECONDS
    while time.monotonic() < deadline:
        for path in sorted(root.glob('*.sock')):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(RECEIPT_TIMEOUT_SECONDS)
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


def local_once(ssh_config=None):
    from .package_reader import run_request
    cmd = ['ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=7',
           '-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2','-o','ForwardAgent=no','-o','ClearAllForwardings=yes',ALIAS]
    if ssh_config is not None:
        cmd[1:1] = ['-F', str(ssh_config)]
    with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as ssh:
        watchdog = Timer(7 + WORKER_POLL_SECONDS + RECEIPT_TIMEOUT_SECONDS + 8, ssh.kill)
        watchdog.start()
        try:
            task = read_message(ssh.stdout)
            if task != {'status':'idle'}:
                if task.get('source') not in LOCAL_SOURCES:
                    raise ValueError('local_package_scope')
                write_message(ssh.stdin, run_request(task))
        finally:
            watchdog.cancel()
            ssh.stdin.close()
            try:
                code = ssh.wait(timeout=4)
            except subprocess.TimeoutExpired:
                ssh.kill()
                ssh.wait()
                raise
        if code:
            raise subprocess.CalledProcessError(code,cmd)


if __name__ == '__main__':
    if sys.argv[1:] == ['relay']:
        relay()
    elif sys.argv[1:2] == ['local'] and len(sys.argv) in (2, 3):
        config = Path(sys.argv[2]).resolve(strict=True) if len(sys.argv) == 3 else None
        while True:
            try:
                local_once(config)
            except (EOFError, OSError, ValueError, subprocess.SubprocessError):
                time.sleep(10)
    else:
        raise SystemExit('expected relay or local')
