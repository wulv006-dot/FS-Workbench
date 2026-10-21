"""Narrow transform; original production source stays on the server."""
import ast
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'order_global_session_20261021'))
from admin_read_patch import transform as read_transform


def once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError('admin_source_drift')
    return source.replace(old, new, 1)


def continuity(source):
    source = once(source, '    manager = SessionManager(read_private_config())',
                  '''    manager = SessionManager(read_private_config())
    from session_state import restore
    restore(manager)''')
    source = once(source, '        self.customer_reads = PrivateReads(self)',
                  '''        self.customer_reads = PrivateReads(self)

    @staticmethod
    def state_now():
        return datetime.now(timezone.utc).isoformat()''')
    source = once(source, 'if self.token and time.monotonic() - self.last_refresh >= 1200:',
                  'if self.token and self.refresh_token and time.monotonic() - self.last_refresh >= 1200:')
    source = once(source, '            self.consecutive_failures = 0 if ok else self.consecutive_failures + 1',
                  '''            if ok:
                from session_state import save
                save(self)
            self.consecutive_failures = 0 if ok else self.consecutive_failures + 1''')
    compile(source, '<admin-continuity>', 'exec')
    return source


def transform(source):
    return continuity(read_transform(source))


def legacy_entry(source):
    return once(source,
                "        return collect_admin(lambda path, body:manager.request(path, data=body, token=manager.token), query, config, now)",
                "        token = manager.token\n    return collect_admin(lambda path, body:manager.request(path, data=body, token=token, timeout=90), query, config, now)")
