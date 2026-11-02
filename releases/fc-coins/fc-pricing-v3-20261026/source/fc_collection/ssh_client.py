"""187 control side. The configured SSH account has only the collector forced command."""
from datetime import datetime, timezone
from pathlib import Path
import os
import queue
import re
import stat
import subprocess
import threading
import time

from .contracts import instant
from .protocol import handle_callback, read_message, write_message


class Session:
    def __init__(self, command, *, max_seconds=120):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL)
        self.end = time.monotonic() + max_seconds
        self.messages = queue.Queue(maxsize=2)
        def receive():
            try:
                while True:
                    self.messages.put(read_message(self.process.stdout), timeout=max_seconds)
            except (EOFError, OSError, ValueError, queue.Full):
                try:
                    self.messages.put(None, timeout=1)
                except queue.Full:
                    pass
        self.reader = threading.Thread(target=receive, daemon=True)
        self.reader.start()

    def read(self):
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('collection_session_timeout')
        try:
            result = self.messages.get(timeout=remaining)
        except queue.Empty:
            raise TimeoutError('collection_session_timeout') from None
        if result is None:
            raise OSError('collection_peer_unavailable')
        return result

    def send(self, value):
        write_message(self.process.stdin, value)

    def health(self, expected_node, expected_digest, *, margin=2):
        started = datetime.now(timezone.utc)
        self.send(dict(method='health'))
        value = self.read()
        finished = datetime.now(timezone.utc)
        if (set(value) != {'kind', 'protocol', 'node_id', 'node_boot_id', 'worker_digest', 'adapters', 'clock_utc', 'uid'}
                or value['kind'] != 'health' or value['protocol'] != 1 or value['node_id'] != expected_node
                or value['worker_digest'] != expected_digest or not re.fullmatch('[a-f0-9]{32}', value['node_boot_id'])
                or expected_node == '183' and (type(value['uid']) is not int or value['uid'] <= 0)
                or not started.timestamp() - margin <= instant(value['clock_utc']).timestamp() <= finished.timestamp() + margin):
            raise ValueError('collection_peer_health_invalid')
        return value

    def run(self, task, identity, coordinator, clock=lambda: datetime.now(timezone.utc), *, guard=None):
        return self._exchange(dict(method='run', task=task), task, identity, coordinator, clock, guard)

    def resend(self, identity, coordinator, clock=lambda: datetime.now(timezone.utc)):
        return self._exchange(dict(method='resend'), None, identity, coordinator, clock)

    def _exchange(self, request, task, identity, coordinator, clock, guard=None):
        self.send(request)
        sequence = 0
        while True:
            value = self.read()
            if value.get('kind') == 'done' and set(value) == {'kind', 'result'}:
                return value['result']
            sequence += 1
            if sequence > 64 or value.get('id') != sequence:
                raise ValueError('collection_callback_sequence_invalid')
            if guard is not None and value.get('method') == 'reserve_request':
                try:
                    guard()
                except (ValueError, OSError):
                    self.send(dict(kind='reply', id=sequence, error='collection_routing_changed'))
                    continue
            self.send(handle_callback(coordinator, identity, task, value, clock))

    def close(self):
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        self.process.stdout.close()
        self.reader.join(timeout=1)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def ssh_command(config):
    if set(config) != {'host', 'user', 'identity_file', 'known_hosts', 'worker_digest'}:
        raise ValueError('collection_ssh_config_invalid')
    if config['host'] != '172.18.108.183' or config['user'] != 'fs-fc-collector':
        raise ValueError('collection_ssh_target_invalid')
    for key in ('identity_file', 'known_hosts'):
        path = Path(config[key])
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ValueError('collection_ssh_file_invalid')
        if os.name == 'posix':
            info = path.stat()
            if (info.st_uid != 0 or info.st_nlink != 1 or not stat.S_ISREG(info.st_mode)
                    or stat.S_IMODE(info.st_mode) & (0o077 if key == 'identity_file' else 0o022)):
                raise ValueError('collection_ssh_file_permissions_invalid')
    if not re.fullmatch('[a-f0-9]{64}', config['worker_digest']):
        raise ValueError('collection_worker_digest_invalid')
    return ['/usr/bin/ssh', '-F', '/dev/null', '-T', '-i', config['identity_file'],
        '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none',
        '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + config['known_hosts'],
        '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'HostKeyAlias=fs-fc-183',
        '-o', 'ForwardAgent=no', '-o', 'ClearAllForwardings=yes', '-o', 'PasswordAuthentication=no',
        '-o', 'KbdInteractiveAuthentication=no', '-o', 'ConnectTimeout=10', '-o', 'ConnectionAttempts=1',
        config['user'] + '@' + config['host']]
