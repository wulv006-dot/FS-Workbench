'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {identityOk, identityResponse, cookieChanges, toJar, rootCookies, orderCookies, verifyCommit, probe} = require('./source/raw_node_helper');
const RAW = (x = {}) => ({name: 'sid', value: 'synthetic-old', domain: 'order.p2pah.cn', path: '/', expires: -1,
  httpOnly: true, secure: true, sameSite: 'Lax', session: true, size: 16, priority: 'Medium', sourceScheme: 'Secure', sourcePort: 443, ...x});
const JAR = x => toJar(RAW(x));
const BODY = '<a href="/admin/public/logout.html">logout</a>';
const URL = 'https://order.p2pah.cn/admin/index/index.html';

test('Order request Jar includes parent domain cookies but excludes parent host-only; output remains exact Order', () => {
  const parent = RAW({name: 'parent', domain: '.p2pah.cn'});
  const hostOnly = RAW({name: 'parent-host-only', domain: 'p2pah.cn'});
  const unrelated = RAW({name: 'other', domain: '.example.test'});
  assert.deepEqual(orderCookies([parent, hostOnly, unrelated, RAW()], true), [parent, RAW()]);
  assert.equal(toJar(parent).domain, '.p2pah.cn');
  assert.deepEqual(rootCookies([parent, hostOnly, RAW()]), [toJar(RAW())]);
});

test('parent domain refresh/delete preserve attributes, conflict protection and commit readback', () => {
  const old = RAW({domain: '.p2pah.cn'}); const next = toJar({...old, value: 'rotated', sameSite: 'Strict'});
  const changes = cookieChanges([old], [toJar(old)], [next], [old]);
  assert.equal(changes[0].domain, '.p2pah.cn'); assert.equal(changes[0].value, 'rotated');
  assert.equal(changes[0].httpOnly, true); assert.equal(changes[0].priority, old.priority);
  verifyCommit(changes, [{...old, ...next}]);
  assert.throws(() => cookieChanges([old], [toJar(old)], [next], [{...old, value: 'concurrent'}]), /conflict/);
  assert.throws(() => verifyCommit(changes, [old]), /commit_unverified/);
  const deletion = cookieChanges([old], [toJar(old)], [], [old]);
  assert.equal(deletion[0].expires, 1); assert.equal(deletion[0].domain, '.p2pah.cn');
  verifyCommit(deletion, []); assert.throws(() => verifyCommit(deletion, [old]), /commit_unverified/);
});

function fixture({initial = [RAW()], before = initial.map(toJar), after = before, current = initial, final = current,
  responses = [{status: 200, url: URL, body: BODY}], contexts = []} = {}) {
  const calls = []; let opened = 0; let reads = 0; let got = 0; let disposed = 0; let closed = 0;
  return {
    calls,
    deps: {
      connect: async () => { const index = opened++; return {
        close: () => { closed++; },
        call: async (method, params) => {
          calls.push({method, params, index});
          if (method === 'Browser.getVersion') return {userAgent: 'synthetic-chrome-UA'};
          if (method === 'Target.getBrowserContexts') return {browserContextIds: contexts};
          if (method === 'Storage.getCookies') return {cookies: index === 0 ? initial : reads++ === 0 ? current : final};
          if (method === 'Storage.setCookies') return {};
          throw new Error('forbidden');
        }
      }; },
      request: {newContext: async options => {
        assert.deepEqual(options.storageState.cookies, initial.map(toJar));
        assert.equal(options.userAgent, 'synthetic-chrome-UA');
        let states = 0;
        return {
          storageState: async () => ({cookies: states++ === 0 ? before : after}),
          get: async (url, opts) => {
            assert.equal(url, responses[got]?.expectedUrl || URL); assert.equal(opts.failOnStatusCode, false); assert.equal(opts.maxRedirects, 0);
            assert.ok(opts.timeout <= (got ? 8000 : 12000));
            const response = responses[got++];
            if (response.error) throw new Error('transport');
            return {status: () => response.status, url: () => response.url, headersArray: () => response.headers || [], text: async () => response.body, dispose: async () => { disposed++; }};
          },
          dispose: async () => { disposed++; }
        };
      }}
    },
    counts: () => ({opened, got, disposed, closed})
  };
}

test('identity keeps status, HTTPS, exact host/path, logout and password guards', () => {
  assert.equal(identityOk(200, URL, BODY), true);
  for (const args of [[302, URL, BODY], [200, URL.replace('https:', 'http:'), BODY], [200, URL.replace('order.', 'other.'), BODY],
    [200, URL + '/bad', BODY], [200, URL, 'login'], [200, URL, BODY + '<input type=password>']]) assert.equal(identityOk(...args), false);
});
test('no change never rewrites normalized SameSite/session or concurrent unrelated cookie', () => {
  const original = RAW(); delete original.sameSite;
  assert.deepEqual(cookieChanges([original], [toJar(original)], [toJar(original)], [original, RAW({name: 'concurrent'})]), []);
});
test('value rotation preserves raw priority and source attributes', () => {
  const raw = RAW({priority: 'High', sourcePort: 8443});
  const changes = cookieChanges([raw], [toJar(raw)], [JAR({value: 'new'})], [raw]);
  assert.deepEqual(changes, [{name: 'sid', value: 'new', domain: 'order.p2pah.cn', path: '/', httpOnly: true, secure: true, sameSite: 'Lax', priority: 'High', sourceScheme: 'Secure', sourcePort: 8443}]);
});
test('deletion expires only the exact original domain/path key', () => {
  const nested = RAW({domain: '.order.p2pah.cn', path: '/admin', name: 'sid'});
  const c = cookieChanges([RAW(), nested], [JAR(), toJar(nested)], [JAR()], [RAW(), nested]);
  assert.equal(c.length, 1); assert.equal(c[0].expires, 1); assert.equal(c[0].domain, '.order.p2pah.cn'); assert.equal(c[0].path, '/admin');
});
test('persistent cookie becoming session omits expires; expiry rotation is retained', () => {
  assert.equal(cookieChanges([RAW({expires: 2000000000, session: false})], [JAR({expires: 2000000000})], [JAR()], [RAW({expires: 2000000000, session: false})])[0].expires, undefined);
  assert.equal(cookieChanges([RAW()], [JAR()], [JAR({expires: 2000000000})], [RAW()])[0].expires, 2000000000);
});
test('same-key concurrent value or attribute change rejects whole diff before writing', () => {
  for (const current of [RAW({value: 'concurrent'}), RAW({httpOnly: false}), RAW({priority: 'High'}), RAW({sourcePort: 8443})]) {
    assert.throws(() => cookieChanges([RAW()], [JAR()], [JAR({value: 'new'})], [current]), /order_cookie_conflict/);
  }
});
test('concurrent addition with same new key and concurrent original deletion reject', () => {
  assert.throws(() => cookieChanges([], [], [JAR()], [RAW()]), /order_cookie_conflict/);
  assert.throws(() => cookieChanges([RAW()], [JAR()], [], []), /order_cookie_conflict/);
});
test('partitioned cookies explicitly reject; unknown meaningful raw attributes reject', () => {
  for (const extra of [{partitionKey: {topLevelSite: 'https://example.com', hasCrossSiteAncestor: true}}, {partitionKeyOpaque: true}, {sameParty: true}]) {
    assert.throws(() => orderCookies([RAW(extra)], true), /unsupported/);
  }
  assert.equal(orderCookies([RAW({partitionKeyOpaque: false})], true).length, 1);
});
test('reject duplicate key and invalid enums/types', () => {
  assert.throws(() => orderCookies([RAW(), RAW()], true), /duplicate/);
  for (const extra of [{secure: 'true'}, {expires: NaN}, {sameSite: 'bad'}, {sourcePort: 65536}, {priority: 'bad'}]) assert.throws(() => orderCookies([RAW(extra)], true), /invalid/);
});
test('root issuance retains original root-path exact domain filtering', () => {
  assert.deepEqual(rootCookies([RAW(), RAW({path: '/admin'}), RAW({domain: 'other.example'})]), [JAR()]);
});
test('commit readback requires changed attributes and successful exact-key deletion', () => {
  verifyCommit([{...JAR({value: 'new'}), expires: undefined}], [RAW({value: 'new'})]);
  assert.throws(() => verifyCommit([{...JAR({value: 'new'})}], [RAW()]), /commit_unverified/);
  verifyCommit([{...JAR(), expires: 1}], []);
  assert.throws(() => verifyCommit([{...JAR(), expires: 1}], [RAW()]), /commit_unverified/);
});
test('successful HTTP identity has no page commands and disposes both connections and Jar', async () => {
  const f = fixture(); const result = await probe(f.deps);
  assert.deepEqual(result, {ready: true, cookies: [JAR()], error: null});
  assert.deepEqual(f.counts(), {opened: 2, got: 1, disposed: 2, closed: 2});
  assert.ok(f.calls.every(c => ['Browser.getVersion', 'Target.getBrowserContexts', 'Storage.getCookies'].includes(c.method)));
});
test('Set-Cookie update commits on second connection after current-cookie reread and verifies', async () => {
  const f = fixture({after: [JAR({value: 'rotated'})], final: [RAW({value: 'rotated'})]});
  assert.equal((await probe(f.deps)).cookies[0].value, 'rotated');
  const i = f.calls.findIndex(c => c.method === 'Storage.setCookies');
  assert.equal(f.calls[i].index, 1); assert.equal(f.calls[i - 1].method, 'Storage.getCookies'); assert.equal(f.calls[i + 1].method, 'Storage.getCookies');
});
test('Set-Cookie deletion and new cookie preserve complete HTTP Jar diff', async () => {
  const fresh = RAW({name: 'fresh', value: 'fresh'});
  const f = fixture({after: [toJar(fresh)], final: [fresh]});
  assert.equal((await probe(f.deps)).cookies[0].name, 'fresh');
  const changes = f.calls.find(c => c.method === 'Storage.setCookies').params.cookies;
  assert.equal(changes.length, 2); assert.equal(changes.find(c => c.name === 'sid').expires, 1);
});
test('redirect/login identity fails while HTTP cookie rotation is retained', async () => {
  const f = fixture({after: [JAR({value: 'rotated'})], final: [RAW({value: 'rotated'})], responses: [{status: 200, url: 'https://order.p2pah.cn/login', body: '<input type=password>'}]});
  assert.deepEqual(await probe(f.deps), {ready: false, cookies: [], error: 'order_identity_unverified'});
  assert.ok(f.calls.some(c => c.method === 'Storage.setCookies'));
});
test('original 12+8 transport/5xx retry and response disposal remain', async () => {
  const f = fixture({responses: [{status: 503, url: URL, body: ''}, {status: 200, url: URL, body: BODY}]});
  assert.equal((await probe(f.deps)).ready, true); assert.equal(f.counts().got, 2); assert.equal(f.counts().disposed, 3);
});
test('identity failure is not retried; both transport failures return unavailable', async () => {
  const f = fixture({responses: [{status: 200, url: URL, body: 'login'}]});
  assert.equal((await probe(f.deps)).ready, false); assert.equal(f.counts().got, 1);
  const g = fixture({responses: [{error: true}, {error: true}]});
  assert.equal((await probe(g.deps)).error, 'order_probe_transport_unavailable'); assert.equal(g.counts().got, 2);
});
test('CAS conflict writes nothing and always closes/disposes', async () => {
  const f = fixture({after: [JAR({value: 'rotated'})], current: [RAW({value: 'concurrent'})]});
  await assert.rejects(probe(f.deps), /order_cookie_conflict/);
  assert.equal(f.calls.some(c => c.method === 'Storage.setCookies'), false); assert.equal(f.counts().closed, 2);
});
test('multiple browser contexts reject before an HTTP request', async () => {
  const f = fixture({contexts: ['unexpected']});
  await assert.rejects(probe(f.deps), /order_context_ambiguous/); assert.equal(f.counts().got, 0);
});
test('intermediate Order redirect Partitioned header rejects before any browser commit', async () => {
  for (const flag of ['Partitioned', 'pArTiTiOnEd=1']) {
    const f = fixture({responses: [{status: 302, url: URL, body: '', headers: [{name: 'Set-Cookie', value: 'sid=new; Secure; ' + flag}, {name: 'Location', value: '/admin/index/index.html'}]}]});
    await assert.rejects(probe(f.deps), /order_cookie_partition_unsupported/);
    assert.equal(f.calls.some(c => c.method === 'Storage.setCookies'), false);
    assert.equal(f.counts().got, 1); assert.equal(f.counts().disposed, 2);
  }
});
test('cookie named Partitioned is ordinary; 20 redirects share original one-request budget', async () => {
  let count = 0; let disposed = 0; const budgets = [];
  const request = {get: async (url, options) => {
    const i = count++; budgets.push(options.timeout); assert.equal(options.maxRedirects, 0);
    return {url: () => url, status: () => i < 20 ? 302 : 200,
      headersArray: () => [{name: 'Set-Cookie', value: 'Partitioned=ordinary; Path=/'}, ...(i < 20 ? [{name: 'Location', value: '/admin/index/index.html?hop=' + i}] : [])],
      text: async () => BODY, dispose: async () => {disposed++;}};
  }};
  assert.equal((await identityResponse(request, 12000, Date.now() + 32000)).status, 200);
  assert.equal(count, 21); assert.equal(disposed, 21); assert.ok(budgets.every(t => t > 0 && t <= 12000));
  assert.ok(budgets.every((t, i) => i === 0 || t <= budgets[i - 1]));
});
test('redirect overflow and expired total request budget are bounded transport failures', async () => {
  let count = 0; let disposed = 0;
  const request = {get: async url => {count++; return {url: () => url, status: () => 302,
    headersArray: () => [{name: 'Location', value: '/again'}], dispose: async () => {disposed++;}};}};
  await assert.rejects(identityResponse(request, 12000, Date.now() + 32000), /transport_unavailable/);
  assert.equal(count, 21); assert.equal(disposed, 21);
  await assert.rejects(identityResponse(request, 12000, Date.now() - 1), /transport_unavailable/);
  assert.equal(count, 21);
});
test('source contains no browser driver/page attachment or cookie clearing commands', () => {
  const helper = fs.readFileSync(path.join(__dirname, 'source/raw_node_helper.js'), 'utf8');
  for (const forbidden of ['connect_over_cdp', 'connectOverCDP', 'createIsolatedWorld', 'attachToTarget', 'Runtime.', 'clearCookies', 'clearBrowserCookies']) assert.equal(helper.includes(forbidden), false, forbidden);
  assert.match(helper, /32000/); assert.match(helper, /12000, 8000/);
});

let packagePath = '/usr/local/lib/python3.10/dist-packages/playwright/driver/package';
if (!fs.existsSync(packagePath)) {
  try { packagePath = path.dirname(require.resolve('playwright/package.json')); }
  catch { packagePath = null; }
}
test('real stdin CLI explicit flag executes and produces one structured response', () => {
  assert.equal(process.env.WORLDLESS_ISOLATED_CLI, '1', 'requires explicit isolated test environment; no fallback network probe');
  const helper = fs.readFileSync(path.join(__dirname, 'source/raw_node_helper.js'), 'utf8');
  const result = require('node:child_process').spawnSync(process.execPath, ['-', '--order-probe'], {input: helper, encoding: 'utf8', timeout: 10000});
  assert.equal(result.status, 0); assert.equal(result.stderr, '');
  const lines = result.stdout.trim().split('\n'); assert.equal(lines.length, 1);
  assert.deepEqual(JSON.parse(lines[0]), {ready: false, cookies: [], error: 'order_probe_unavailable'});
});
test('installed original APIRequestContext parses redirect Set-Cookie/expiry/Domain/Path/session', async () => {
  assert.ok(packagePath, 'required Playwright dependency unavailable');
  const http = require('node:http');
  const server = http.createServer((req, res) => {
    if (req.url === '/start') {
      res.writeHead(302, {Location: '/finish', 'Set-Cookie': [
        'sid=new; Path=/; HttpOnly; SameSite=Strict', 'removed=; Max-Age=0; Path=/',
        'persistent=value; Max-Age=3600; Path=/scope; SameSite=Lax', 'scoped=v; Domain=127.0.0.1; Path=/scope']});
    } else { res.writeHead(200); res.write(req.headers.cookie || ''); }
    res.end();
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const context = await require(packagePath).request.newContext({storageState: {cookies: [
    {name: 'sid', value: 'old', domain: '127.0.0.1', path: '/', expires: -1, httpOnly: true, secure: false, sameSite: 'Lax'},
    {name: 'removed', value: 'old', domain: '127.0.0.1', path: '/', expires: -1, httpOnly: false, secure: false, sameSite: 'Lax'}], origins: []}});
  try {
    const response = await context.get(`http://127.0.0.1:${server.address().port}/start`, {timeout: 3000});
    assert.match(response.url(), /\/finish$/); assert.match(await response.text(), /sid=new/); await response.dispose();
    const cookies = (await context.storageState()).cookies;
    assert.equal(cookies.some(c => c.name === 'removed'), false);
    const sid = cookies.find(c => c.name === 'sid'); assert.equal(sid.value, 'new'); assert.equal(sid.httpOnly, true); assert.equal(sid.sameSite, 'Strict'); assert.equal(sid.expires, -1);
    const persistent = cookies.find(c => c.name === 'persistent'); assert.ok(persistent.expires > Date.now() / 1000); assert.equal(persistent.path, '/scope');
    assert.equal(cookies.find(c => c.name === 'scoped').domain, '.127.0.0.1');
  } finally { await context.dispose(); await new Promise(resolve => server.close(resolve)); }
});
test('real APIRequest Jar with inspected redirects keeps Chrome UA, rejects Partitioned hop and times out', async () => {
  assert.ok(packagePath, 'required Playwright dependency unavailable');
  const http = require('node:http'); let mode = 'normal'; const seen = [];
  const server = http.createServer((req, res) => {
    seen.push({path: req.url, ua: req.headers['user-agent'], cookie: req.headers.cookie});
    if (mode === 'slow') { setTimeout(() => res.end('late'), 200); return; }
    if (req.url === '/admin/index/index.html') res.writeHead(302, {Location: '/finish', 'Set-Cookie': 'sid=rotated; Path=/; HttpOnly; SameSite=Strict' + (mode === 'partition' ? '; Partitioned' : '')});
    else { res.writeHead(200); res.write(BODY); }
    res.end();
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const context = await require(packagePath).request.newContext({userAgent: 'synthetic-chrome-UA'});
  // Test-only address adapter: local HTTP responses retain all real headers/Jar parsing.
  const request = {get: async (url, options) => {
    const u = new globalThis.URL(url);
    const response = await context.get(`http://127.0.0.1:${server.address().port}${u.pathname}${u.search}`, options);
    return {url: () => url, status: () => response.status(), headersArray: () => response.headersArray(), text: () => response.text(), dispose: () => response.dispose()};
  }};
  try {
    assert.equal((await identityResponse(request, 3000, Date.now() + 5000)).status, 200);
    assert.equal(seen.length, 2); assert.ok(seen.every(r => r.ua === 'synthetic-chrome-UA')); assert.match(seen[1].cookie, /sid=rotated/);
    const sid = (await context.storageState()).cookies.find(c => c.name === 'sid'); assert.equal(sid.sameSite, 'Strict'); assert.equal(sid.httpOnly, true);
    mode = 'partition'; const count = seen.length;
    await assert.rejects(identityResponse(request, 3000, Date.now() + 5000), /partition_unsupported/); assert.equal(seen.length, count + 1);
    mode = 'slow'; await assert.rejects(identityResponse(request, 50, Date.now() + 5000), /Timeout/);
  } finally { await context.dispose(); await new Promise(resolve => server.close(resolve)); }
});

test('Partitioned parent-domain responses from Order or sibling redirects fail before submission', async () => {
  for (const origin of ['https://order.p2pah.cn/admin/index/index.html', 'https://auth.p2pah.cn/continue', 'https://p2pah.cn/continue']) {
    let disposed = 0;
    const request = {get: async () => ({url: () => origin, status: () => 302,
      headersArray: () => [{name: 'Set-Cookie', value: 'parent=x; Domain=p2pah.cn; Path=/; Partitioned'}, {name: 'Location', value: URL}],
      dispose: async () => {disposed++;}})};
    await assert.rejects(identityResponse(request, 3000, Date.now()+5000), /partition_unsupported/);
    assert.equal(disposed, 1);
  }
});

test('original real CookieJar sends, rotates and deletes parent-domain cookies without host-only leakage', async () => {
  assert.equal(fs.existsSync(packagePath), true, 'original Playwright CookieJar dependency required');
  const http = require('node:http'); let mode = 'rotate'; const seen = []; const tunnels = new Set();
  const server = http.createServer((req, res) => {
    seen.push({url: req.url, cookie: req.headers.cookie || ''});
    res.writeHead(200, {'Set-Cookie': mode === 'rotate'
      ? 'parent=rotated; Domain=p2pah.cn; Path=/; HttpOnly; SameSite=Strict'
      : 'parent=; Domain=p2pah.cn; Path=/; Max-Age=0'});
    res.end('synthetic');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  server.on('connect', (req, socket, head) => {
    assert.equal(req.url, 'order.p2pah.cn:80');
    const upstream = require('node:net').connect(server.address().port, '127.0.0.1', () => {
      socket.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      if (head.length) upstream.write(head);
      socket.pipe(upstream); upstream.pipe(socket);
    });
    tunnels.add(socket); tunnels.add(upstream);
    socket.on('error', () => upstream.destroy()); upstream.on('error', () => socket.destroy());
  });
  const old = RAW({name: 'parent', domain: '.p2pah.cn', secure: false, sourceScheme: 'NonSecure', sourcePort: 80});
  const exact = RAW({secure: false, sourceScheme: 'NonSecure', sourcePort: 80});
  const context = await require(packagePath).request.newContext({
    proxy: {server: `http://127.0.0.1:${server.address().port}`},
    storageState: {cookies: [toJar(old), toJar(exact), {...toJar(old), name: 'host-only-parent', domain: 'p2pah.cn'}], origins: []}
  });
  try {
    const before = (await context.storageState()).cookies;
    await (await context.get('http://order.p2pah.cn/admin/index/index.html', {timeout: 3000})).dispose();
    assert.match(seen[0].cookie, /parent=synthetic-old/); assert.match(seen[0].cookie, /sid=synthetic-old/);
    assert.doesNotMatch(seen[0].cookie, /host-only-parent=/);
    const after = (await context.storageState()).cookies; const parent = after.find(c => c.name === 'parent');
    assert.equal(parent.domain, '.p2pah.cn'); assert.equal(parent.value, 'rotated');
    assert.equal(parent.httpOnly, true); assert.equal(parent.sameSite, 'Strict');
    const changes = cookieChanges([old, exact], before, after, [old, exact]);
    assert.equal(changes.length, 1); verifyCommit(changes, [{...old, ...parent}, exact]);
    mode = 'delete';
    await (await context.get('http://order.p2pah.cn/admin/index/index.html', {timeout: 3000})).dispose();
    const deleted = (await context.storageState()).cookies;
    assert.equal(deleted.some(c => c.name === 'parent'), false);
    const removal = cookieChanges([{...old, ...parent}, exact], after, deleted, [{...old, ...parent}, exact]);
    assert.equal(removal.length, 1); assert.equal(removal[0].expires, 1); verifyCommit(removal, [exact]);
    assert.deepEqual(rootCookies([old, exact]), [toJar(exact)]);
  } finally { await context.dispose(); for (const socket of tunnels) socket.destroy(); await new Promise(resolve => server.close(resolve)); }
});
