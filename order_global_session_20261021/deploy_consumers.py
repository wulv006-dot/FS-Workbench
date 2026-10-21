"""Migrate active Order consumers; do not change Admin functions or business rules."""
import ast
from pathlib import Path
import re
from deploy_fc import function, once, prefix, publish


def changes():
    result = {}
    readers = ['/opt/fs-exact-range-20261001/range_primary_reader.py',
               '/opt/fs-exact-range-20261001/fc_order_reader.py',
               '/opt/fs-transaction-snapshot/primary_reader.py',
               '/opt/fs-transaction-snapshot/profit_daily_reader.py',
               '/opt/fs-transaction-snapshot/fc_category_reader.py',
               '/opt/fc27-ops/order_query.py']
    for path in readers:
        text = prefix(Path(path).read_text())
        text, count = re.subn(r'([A-Za-z_]\w*)\.contexts\[0\]\.new_page\(\)', r'_global_order.new_page(\1.contexts[0])', text)
        if count != 1:
            raise RuntimeError('reader_shape_changed:' + path)
        result[path] = text

    path = '/opt/sales-dashboard/collector/p2pah_auth.py'
    text = prefix(Path(path).read_text())
    text = function(text, 'order_login', '''def order_login(s: Session, tries: int = ORDER_TRIES) -> bool:
    _global_order.fill_jar(s.order.cookies)
    return True
''')
    node = next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and n.name == 'get_order')
    lines = text.splitlines(keepends=True)
    # Insert after the method signature, before its existing bounded GET retries.
    lines.insert(node.body[0].lineno - 1, '        _global_order.fill_jar(self.order.cookies)\n')
    result[path] = ''.join(lines)

    path = '/opt/madden-workbench/madden_nfl_27/collect_cost.py'
    text = prefix(Path(path).read_text())
    text = function(text, '_login', '''def _login(page) -> str:
    _global_order.apply(page.context)
    page.goto(delivery_url(1), wait_until="domcontentloaded", timeout=45000)
    if 'login' in page.url.lower():
        raise RuntimeError('global_order_identity_unverified')
    return 'global_order'
''')
    result[path] = text

    path = '/opt/mlb-admin-write/src/p2pah_price.py'
    text = prefix(Path(path).read_text())
    text = function(text, 'login', '''def login(opener, user=None, password=None, *, tries=1):
    import urllib.request
    handler = next(h for h in opener.handlers if isinstance(h, urllib.request.HTTPCookieProcessor))
    _global_order.fill_jar(handler.cookiejar)
''')
    tree = ast.parse(text)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    branch = next(n for n in ast.walk(main) if isinstance(n, ast.If) and ast.unparse(n.test) == 'a.html')
    lines = text.splitlines(keepends=True)
    lines[branch.orelse[0].lineno-1:branch.orelse[-1].end_lineno] = [
        '            parsed = fetch_rows(user=None, password=None, gid=a.gid, timeout=a.timeout)\n']
    result[path] = ''.join(lines)
    path = '/opt/mlb-online/mlb_coins_rate.py'
    text = Path(path).read_text()
    node = next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.If) and 'c.get(\'cred\')' in ast.unparse(n.test))
    lines = text.splitlines(keepends=True)
    del lines[node.lineno-1:node.end_lineno]
    result[path] = ''.join(lines)

    path = '/opt/d4follow/core_p2pah.py'
    text = prefix(Path(path).read_text())
    text = function(text, '_load_session', '''def _load_session(self, path):
    _global_order.fill_jar(self.jar)
    return True
''', 'P2PAHClient')
    text = function(text, 'login', '''def login(self, captcha=None):
    try:
        _global_order.fill_jar(self.jar)
        self.logged_in = True
    except RuntimeError:
        self.logged_in = False
    return self.logged_in
''', 'P2PAHClient')
    text = function(text, 'fetch_captcha', '''def fetch_captcha(self, save_to=None, keep=False):
    raise RuntimeError('order_login_managed_by_global_service')
''', 'P2PAHClient')
    text = function(text, '_save', '''def _save(self, path, extra=None):
    return None
''', 'P2PAHClient')
    tree = ast.parse(text)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'P2PAHClient')
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'request')
    lines = text.splitlines(keepends=True)
    # Insert after a possible docstring.
    position = node.body[0].end_lineno if isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) else node.body[0].lineno-1
    lines.insert(position, '        _global_order.fill_jar(self.jar)\n')
    text = ''.join(lines)
    text = once(text, '        self.opener = urllib.request.build_opener(\n            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),',
                '        self.jar = http.cookiejar.CookieJar()\n        self.opener = urllib.request.build_opener(\n            urllib.request.HTTPCookieProcessor(self.jar),')
    text = once(text, '    def _get(self, path, data=None):\n', '    def _get(self, path, data=None):\n        if "order.p2pah.cn" in self.base:\n            _global_order.fill_jar(self.jar)\n')
    result[path] = text

    path = '/opt/d4follow/_p2pah_srv/p2pah_local.py'
    text = prefix(Path(path).read_text())
    text = function(text, '_inject_saved_cookies', '''def _inject_saved_cookies(self):
    return _global_order.apply(self.ctx)
''', 'Session')
    text = function(text, 'save_cookies', '''def save_cookies(self):
    return 0
''', 'Session')
    text = function(text, '_auto_relogin', '''def _auto_relogin(self):
    _global_order.apply(self.ctx)
    self.pg.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    return 'login.html' not in self.pg.url
''', 'Session')
    text = function(text, 'logged_in', '''def logged_in(self, auto=None):
    return self._auto_relogin()
''', 'Session')
    text = function(text, 'cmd_login', '''def cmd_login(a):
    return 0 if _global_order.cookies() else 1
''')
    text = function(text, 'dump_cookies', '''def dump_cookies(ctx, a):
    return None
''')
    result[path] = text
    path = '/opt/d4follow/_p2pah_srv/p2pah_autologin.py'
    text = prefix(Path(path).read_text())
    text = function(text, 'login_order_in', '''def login_order_in(pg, user=None, pw=None, tries=1, log=log_default, site=ORDER_SITE):
    _global_order.apply(pg.context)
    response = pg.goto(ORDER_SITE + '/admin/index/index.html', wait_until='domcontentloaded', timeout=45000)
    return response is not None and response.status == 200 and 'login' not in pg.url.lower()
''')
    result[path] = text
    return result


if __name__ == '__main__':
    publish(changes(), 'order-global-consumers-20261021-v1')
