"""Order session client: no passwords, login retries or disk cookie cache."""
import http.cookiejar
import json
import os
import socket
import time

SOCKETS = ('/run/fs-order-session/session.sock',
           '/var/lib/fc27-cloud/browser/lootbar/fs-order-session.sock',
           '/opt/madden-workbench/.fs-order-session.sock',
           '/srv/.fs-order-session.sock')

# 一次派单常有 4~5 张单连着跑，broker 的探针一次抖动会让整批单全挂
# （2026-10-22 五个时间窗共 11 张单就是这么死的）。所以取 cookie 要重试。
# broker 把探测结果（含失败）缓存 20 秒，退避必须跨过这个窗口才能拿到新结果。
ATTEMPTS = 3
BACKOFF_S = 21


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError()
    return remaining


def _cookies_once(deadline=None):
    path = next((p for p in SOCKETS if os.path.exists(p)), None)
    if not path:
        raise RuntimeError('global_order_unavailable:no_socket')
    try:
        with socket.socket(socket.AF_UNIX) as stream:
            stream.settimeout(40 if deadline is None else min(40, _remaining(deadline)))
            stream.connect(path)
            if deadline is not None:
                stream.settimeout(min(40, _remaining(deadline)))
            stream.sendall(b'cookies\n')
            chunks = bytearray()
            while not chunks.endswith(b'\n'):
                if deadline is not None:
                    stream.settimeout(min(40, _remaining(deadline)))
                part = stream.recv(16384)
                if not part or len(chunks) + len(part) > 65536:
                    raise ValueError()
                chunks.extend(part)
            if deadline is not None:
                _remaining(deadline)
        result = json.loads(chunks)
        rows = result.get('cookies')
        if not result.get('ready') or not isinstance(rows, list) or not rows:
            raise RuntimeError('global_order_unavailable:%s'
                               % (result.get('error') or 'not_ready'))
        for row in rows:
            if (not isinstance(row, dict) or row.get('domain', '').lstrip('.') != 'order.p2pah.cn'
                    or not isinstance(row.get('name'), str) or not row['name']
                    or any(c in row['name'] for c in '=;\r\n ')
                    or not isinstance(row.get('value'), str)
                    or any(c in row['value'] for c in ';\r\n')):
                raise ValueError()
        return rows
    except (OSError, ValueError, TypeError, KeyError) as e:
        if deadline is not None and isinstance(e, OSError):
            reason = 'timeout' if isinstance(e, (socket.timeout, TimeoutError)) else type(e).__name__
            raise RuntimeError('global_order_unavailable:transport:' + reason) from None
        raise RuntimeError('global_order_unavailable:%s' % type(e).__name__) from None


def cookies(*, timeout=None):
    deadline = time.monotonic() + timeout if timeout is not None else None
    last = ('global_order_unavailable' if deadline is None
            else 'global_order_unavailable:transport:timeout')
    for attempt in range(ATTEMPTS):
        if attempt:
            if deadline is not None and deadline - time.monotonic() <= BACKOFF_S:
                break
            time.sleep(BACKOFF_S)
        if deadline is not None and deadline <= time.monotonic():
            break
        try:
            return _cookies_once() if deadline is None else _cookies_once(deadline)
        except RuntimeError as e:
            last = str(e) or 'global_order_unavailable'
    raise RuntimeError(last) from None


def apply(context):
    rows = cookies()
    context.add_cookies(rows)
    return len(rows)


def new_page(context):
    apply(context)
    return context.new_page()


def fill_jar(jar, *, timeout=None):
    rows = cookies() if timeout is None else cookies(timeout=timeout)
    jar.clear()
    for row in rows:
        jar.set_cookie(http.cookiejar.Cookie(
            0, row['name'], row['value'], None, False, row['domain'], True,
            row['domain'].startswith('.'), row.get('path', '/'), True,
            bool(row.get('secure')), None, True, None, None, {}, False))
    return len(rows)
