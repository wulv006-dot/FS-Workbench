"""Low-privilege collector service and SSH forced-command relay. No management API."""
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import socket
import stat
import sys
import threading
import time
import uuid

from .adapters import RestrictedHTTP
from .protocol import read_message, serve_replay, serve_task, utc, write_message
from .public_sources import REGISTRY, VERSIONS, arab_adapter, package_adapter


class Collector:
    def __init__(self, node_id, spool, digest):
        if node_id not in ('183', '187'):
            raise ValueError('node_invalid')
        self.identity = dict(node_id=node_id, node_boot_id=uuid.uuid4().hex)
        self.spool, self.digest = Path(spool), digest
        self.versions = dict(VERSIONS)
        try:
            from scrapling import Selector
        except ImportError:
            for source in ('U4GM', 'IGGM'):
                self.versions.pop(source)

    def handle(self, reader, writer):
        message = read_message(reader)
        if message == {'method': 'health'}:
            write_message(writer, dict(kind='health', protocol=1, **self.identity,
                worker_digest=self.digest, adapters=self.versions, clock_utc=utc().isoformat(),
                uid=os.getuid() if hasattr(os, 'getuid') else None))
        elif message == {'method': 'resend'}:
            serve_replay(self.identity, self.spool, reader, writer)
        elif set(message) == {'method', 'task'} and message['method'] == 'run':
            transport = RestrictedHTTP(REGISTRY)
            from .lootbar import lootbar_adapter, render_fetch
            task = message['task']
            def fetch(source, template, timeout):
                return render_fetch(task, template, timeout) if source == 'Lootbar' else transport.fetch(source, template, timeout)
            serve_task(task, self.identity, {'ArabUT': arab_adapter, 'Lootbar': lootbar_adapter, 'U4GM':package_adapter, 'IGGM':package_adapter}, self.versions,
                       self.spool, fetch, reader, writer)
        else:
            raise ValueError('method_not_allowed')


def verified_manifest(root):
    raw = (root / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    expected = {'fc_collection/' + name for name in ('__init__.py', 'contracts.py', 'worker.py',
        'adapters.py', 'protocol.py', 'public_sources.py', 'server.py', 'lootbar.py','package_reader.py')} | {'entry.py'}
    if set(manifest.get('sha256', {})) != expected:
        raise ValueError('worker_manifest_invalid')
    for relative, digest in manifest['sha256'].items():
        path = root / relative
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('worker_code_changed')
    return hashlib.sha256(raw).hexdigest()


def close_socket(connection):
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    connection.close()


def service(collector, socket_path):
    path = Path(socket_path)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
            raise ValueError('worker_socket_path_invalid')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as check:
            try:
                check.connect(str(path))
            except ConnectionRefusedError:
                current = path.lstat()
                if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                    raise ValueError('worker_socket_changed')
                path.unlink()
            else:
                raise ValueError('worker_already_running')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        path.chmod(0o600)
        listener.listen(4)
        while True:
            connection, _ = listener.accept()
            timer = threading.Timer(120, close_socket, args=(connection,))
            timer.daemon = True
            timer.start()
            try:
                connection.settimeout(10)
                with connection, connection.makefile('rwb', buffering=0) as stream:
                    collector.handle(stream, stream)
            except (ValueError, EOFError, OSError, KeyError, TypeError) as exc:
                # Source text, peer payloads and credentials never enter service logs.
                print(json.dumps(dict(event='collector_request_failed', error_type=type(exc).__name__)), flush=True)
            finally:
                timer.cancel()


def relay(socket_path):
    # This separate SSH process cannot linger on blocked stdout after the peer disappears.
    signal.alarm(125)
    info = Path(socket_path).lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('worker_socket_invalid')
    sent = received = 0
    until = time.monotonic() + 120
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(10)
        connection.connect(str(socket_path))
        while time.monotonic() < until:
            readable, _, _ = select.select([sys.stdin.buffer, connection], [], [], max(0, until - time.monotonic()))
            if not readable:
                return
            if sys.stdin.buffer in readable:
                data = os.read(sys.stdin.fileno(), 65536)
                if not data:
                    return
                sent += len(data)
                if sent > 1048576:
                    raise ValueError('relay_limit')
                connection.sendall(data)
            if connection in readable:
                data = connection.recv(65536)
                if not data:
                    return
                received += len(data)
                if received > 1048576:
                    raise ValueError('relay_limit')
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()


def main(root):
    if len(sys.argv) != 2 or sys.argv[1] not in ('service', 'relay', 'stdio'):
        raise ValueError('worker_entry_invalid')
    config = json.loads((root.parent / 'node.json').read_text())
    if set(config) != {'node_id', 'spool', 'socket'}:
        raise ValueError('node_config_invalid')
    digest = verified_manifest(root)
    if sys.argv[1] == 'service':
        python = root.parent / 'venv/bin/python'
        if python.is_file() and Path(sys.executable) != python:
            os.execv(str(python), [str(python), '-I', '-B', str(root / 'entry.py'), 'service'])
    if sys.argv[1] == 'relay':
        relay(config['socket'])
    else:
        collector = Collector(config['node_id'], config['spool'], digest)
        if sys.argv[1] == 'service':
            service(collector, config['socket'])
        else:
            while True:
                try:
                    collector.handle(sys.stdin.buffer, sys.stdout.buffer)
                except EOFError:
                    return
                except (ValueError, OSError, KeyError, TypeError):
                    write_message(sys.stdout.buffer, dict(kind='error', error='collector_request_rejected'))
                    return
