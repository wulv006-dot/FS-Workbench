import ast
from pathlib import Path
import subprocess
from deploy_fc import function, once, prefix, publish


def changes():
    result = {}
    path = '/opt/fc27-pack-bundles/vendor/p2pah_price.py'
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

    path = '/opt/dashboard-collect/profit_fetch.py'
    text = prefix(Path(path).read_text())
    text = function(text, '_load_session', '''def _load_session(self):
    self.cookies = {c['name']: c['value'] for c in _global_order.cookies()}
''', 'OrderBackend')
    text = function(text, '_save_session', '''def _save_session(self, *args, **kwargs):
    return None
''', 'OrderBackend')
    text = function(text, '_opener', '''def _opener(self):
    op, jar = self._make_opener(cookies={})
    _global_order.fill_jar(jar)
    return op
''', 'OrderBackend')
    text = function(text, 'login', '''def login(self, manual=True, tries=1):
    return self.probe()
''', 'OrderBackend')
    text = function(text, 'do_login', '''def do_login(self, captcha, opener, jar):
    _global_order.fill_jar(jar)
    return True, 'global_order'
''', 'OrderBackend')
    text = function(text, 'fetch_captcha', '''def fetch_captcha(self, *args, **kwargs):
    raise RuntimeError('order_login_managed_by_global_service')
''', 'OrderBackend')
    result[path] = text

    path = '/opt/nba-reprice/backend/server.js'
    text = Path(path).read_text()
    start = text.index('async function login() {')
    end = text.index('// ===== 读取发货记录', start)
    text = text[:start] + '''async function login() {
  const net = require('net');
  const rows = await new Promise((resolve, reject) => {
    const stream = net.createConnection('/run/fs-order-session/session.sock');
    let data = '';
    const fail = () => { stream.destroy(); reject(new Error('global_order_unavailable')); };
    stream.setTimeout(40000, fail);
    stream.on('error', fail);
    stream.on('connect', () => stream.write('cookies\\n'));
    stream.on('data', chunk => {
      data += chunk.toString('utf8');
      if (data.length > 65536) return fail();
      if (!data.endsWith('\\n')) return;
      try {
        const result = JSON.parse(data);
        if (!result.ready || !Array.isArray(result.cookies) || !result.cookies.length ||
            result.cookies.some(c => c.domain.replace(/^\\./, '') !== 'order.p2pah.cn' ||
              !/^[^=;\\s]+$/.test(c.name) || typeof c.value !== 'string' || /[;\\r\\n]/.test(c.value))) return fail();
        stream.destroy();
        resolve(result.cookies);
      } catch { fail(); }
    });
    stream.on('end', () => { if (!data.endsWith('\\n')) fail(); });
  });
  session.cookie = rows.map(c => `${c.name}=${c.value}`).join('; ');
  session.loggedIn = true;
  session.loginAt = Date.now();
  return true;
}

async function ensureLogin() {
  return login();
}

''' + text[end:]
    start = text.index('function persistCookie() {')
    end = text.index('// ===== 验证码识别', start)
    text = text[:start] + 'function persistCookie() {}\nfunction loadCookie() {}\n\n' + text[end:]
    subprocess.run(['/usr/local/node/bin/node', '--check'], input=text, text=True, check=True)
    result[path] = text

    path = '/opt/fc27-cloud-browser/fc27_cloud_api.py'
    text = Path(path).read_text()
    marker = '    runs = [path for path in (ROOT / "runs").glob("*.json") if valid_id(path.stem)]'
    text = once(text, marker, '''    result['order_session'] = 'missing'
    try:
        with urllib.request.urlopen('http://127.0.0.1:8768/health', timeout=8) as response:
            if json.load(response).get('ready'):
                result['order_session'] = 'ok'
    except (OSError, ValueError):
        pass
    if result['order_session'] != 'ok':
        result['p2pah_session'] = 'missing'
''' + marker)
    result[path] = text
    for name in ('probe_backend_page.py', 'probe_order_frontend_browser.py', 'probe_p2pah_rows.py'):
        path = '/opt/fc27-cloud-browser/collector/' + name
        text = prefix(Path(path).read_text())
        if 'b.contexts[0].new_page()' in text:
            text = once(text, 'b.contexts[0].new_page()', '_global_order.new_page(b.contexts[0])')
        else:
            raise RuntimeError('probe_shape_changed')
        result[path] = text
    return result


if __name__ == '__main__':
    publish(changes(), 'order-global-remaining-20261021-v1')
