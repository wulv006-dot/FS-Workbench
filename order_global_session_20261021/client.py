"""Order session client: no passwords, login retries or disk cookie cache."""
import http.cookiejar
import json
import os
import socket
from time import monotonic

SOCKETS = ('/run/fs-order-session/session.sock',
           '/var/lib/fc27-cloud/browser/lootbar/fs-order-session.sock',
           '/opt/madden-workbench/.fs-order-session.sock',
           '/srv/.fs-order-session.sock')


def cookies(*, timeout=None):
    deadline = monotonic() + timeout if timeout is not None else None
    path = next((p for p in SOCKETS if os.path.exists(p)), None)
    if not path:
        raise RuntimeError('global_order_unavailable')
    try:
        with socket.socket(socket.AF_UNIX) as stream:
            def set_remaining_timeout():
                remaining = 40 if deadline is None else deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError
                stream.settimeout(remaining)

            set_remaining_timeout()
            stream.connect(path)
            set_remaining_timeout()
            stream.sendall(b'cookies\n')
            chunks = bytearray()
            while not chunks.endswith(b'\n'):
                set_remaining_timeout()
                part = stream.recv(16384)
                if not part or len(chunks) + len(part) > 65536:
                    raise ValueError()
                chunks.extend(part)
        result = json.loads(chunks)
        rows = result.get('cookies')
        if not result.get('ready') or not isinstance(rows, list) or not rows:
            raise ValueError()
        for row in rows:
            if (not isinstance(row, dict) or row.get('domain', '').lstrip('.') != 'order.p2pah.cn'
                    or not isinstance(row.get('name'), str) or not row['name']
                    or any(c in row['name'] for c in '=;\r\n ')
                    or not isinstance(row.get('value'), str)
                    or any(c in row['value'] for c in ';\r\n')):
                raise ValueError()
        return rows
    except (OSError, ValueError, TypeError, KeyError):
        raise RuntimeError('global_order_unavailable') from None


def apply(context):
    rows = cookies()
    context.add_cookies(rows)
    return len(rows)


def new_page(context):
    apply(context)
    return context.new_page()


def fill_jar(jar, *, timeout=None):
    rows = cookies(timeout=timeout)
    jar.clear()
    for row in rows:
        jar.set_cookie(http.cookiejar.Cookie(
            0, row['name'], row['value'], None, False, row['domain'], True,
            row['domain'].startswith('.'), row.get('path', '/'), True,
            bool(row.get('secure')), None, True, None, None, {}, False))
    return len(rows)
