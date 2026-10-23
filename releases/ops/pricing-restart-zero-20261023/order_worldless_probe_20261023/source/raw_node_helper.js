'use strict';

// The HTTP CookieJar is Playwright's existing parser; CDP never attaches to a page.
const http = require('node:http');
const DOMAIN = 'order.p2pah.cn';
const IDENTITY = 'https://order.p2pah.cn/admin/index/index.html';
const PACKAGE = '/usr/local/lib/python3.10/dist-packages/playwright/driver/package';
const COOKIE_FIELDS = ['name', 'value', 'domain', 'path', 'expires', 'httpOnly', 'secure', 'sameSite'];
const PARAM_EXTRA = ['priority', 'sourceScheme', 'sourcePort'];
const RAW_FIELDS = new Set([...COOKIE_FIELDS, ...PARAM_EXTRA, 'size', 'session', 'partitionKey', 'partitionKeyOpaque']);

function fail(code) { throw new Error(code); }
function isOrder(c) { return typeof c?.domain === 'string' && c.domain.replace(/^\./, '') === DOMAIN; }
function forOrderRequest(c) { return isOrder(c) || c?.domain === '.p2pah.cn'; }
function key(c) { return JSON.stringify([c.name, c.domain, c.path]); }
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k => [k, canonical(value[k])]));
  return value;
}
function same(a, b) { return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b)); }
function validateCookie(c, raw = false) {
  if (!c || !forOrderRequest(c) || typeof c.name !== 'string' || !c.name || typeof c.value !== 'string'
      || typeof c.path !== 'string' || !c.path.startsWith('/') || typeof c.secure !== 'boolean'
      || typeof c.httpOnly !== 'boolean' || !Number.isFinite(c.expires) || c.expires < -1
      || (c.sameSite !== undefined && !['Strict', 'Lax', 'None'].includes(c.sameSite))) fail('order_cookie_invalid');
  if (c.partitionKey !== undefined || c.partitionKeyOpaque === true) fail('order_cookie_partition_unsupported');
  if (raw && Object.keys(c).some(k => !RAW_FIELDS.has(k))) fail('order_cookie_attributes_unsupported');
  if (c.priority !== undefined && !['Low', 'Medium', 'High'].includes(c.priority)) fail('order_cookie_invalid');
  if (c.sourceScheme !== undefined && !['Unset', 'NonSecure', 'Secure'].includes(c.sourceScheme)) fail('order_cookie_invalid');
  if (c.sourcePort !== undefined && (!Number.isInteger(c.sourcePort) || c.sourcePort < -1 || c.sourcePort > 65535)) fail('order_cookie_invalid');
  return c;
}
function orderCookies(rows, raw = false) {
  if (!Array.isArray(rows) || rows.length > 1000) fail('order_cookie_invalid');
  const result = rows.filter(forOrderRequest).map(c => validateCookie(c, raw));
  if (new Set(result.map(key)).size !== result.length) fail('order_cookie_duplicate_key');
  return result;
}
function toJar(c) {
  validateCookie(c, true);
  return Object.fromEntries(COOKIE_FIELDS.map(k => [k, k === 'sameSite' ? (c[k] ?? 'Lax') : c[k]]));
}
function identityOk(status, url, body) {
  let u;
  try { u = new URL(url); } catch { return false; }
  return status === 200 && u.protocol === 'https:' && u.hostname === DOMAIN
    && u.pathname === '/admin/index/index.html'
    && /href=["']\/admin\/public\/logout\.html["']/i.test(body)
    && !/<input[^>]+type\s*=\s*["']?password/i.test(body);
}
function cookieChanges(initialRaw, beforeJar, afterJar, currentRaw) {
  const initial = new Map(orderCookies(initialRaw, true).map(c => [key(c), c]));
  const before = new Map(orderCookies(beforeJar).map(c => [key(c), c]));
  const after = new Map(orderCookies(afterJar).map(c => [key(c), c]));
  const current = new Map(orderCookies(currentRaw, true).map(c => [key(c), c]));
  const changed = [...new Set([...before.keys(), ...after.keys()])].filter(k => !same(before.get(k), after.get(k)));
  // Validate every changed key before the single write. Other concurrent cookies are untouched.
  if (changed.some(k => !same(initial.get(k), current.get(k)))) fail('order_cookie_conflict');
  return changed.map(k => {
    const old = initial.get(k);
    const next = after.get(k);
    const c = next ? validateCookie(next) : old;
    if (!c) fail('order_cookie_invalid');
    const param = Object.fromEntries(['name', 'value', 'domain', 'path', 'httpOnly', 'secure', 'sameSite'].filter(f => c[f] !== undefined).map(f => [f, c[f]]));
    for (const f of PARAM_EXTRA) if (old?.[f] !== undefined) param[f] = old[f];
    if (!next) { param.value = ''; param.expires = 1; }
    else if (next.expires !== -1) param.expires = next.expires;
    return param;
  });
}
function rootCookies(rows) {
  return orderCookies(rows, true).filter(c => isOrder(c) && c.path === '/').map(toJar);
}
function verifyCommit(changes, rows) {
  const current = new Map(orderCookies(rows, true).map(c => [key(c), c]));
  for (const change of changes) {
    const actual = current.get(key(change));
    if (change.expires === 1) { if (actual) fail('order_cookie_commit_unverified'); continue; }
    if (!actual) fail('order_cookie_commit_unverified');
    for (const field of ['name', 'value', 'domain', 'path', 'httpOnly', 'secure', 'sameSite', ...PARAM_EXTRA]) {
      if (change[field] !== undefined && !same(change[field], actual[field])) fail('order_cookie_commit_unverified');
    }
    if (change.expires === undefined ? !actual.session : Math.abs(change.expires - actual.expires) > 0.001) fail('order_cookie_commit_unverified');
  }
}

async function discover(deadline) {
  return new Promise((resolve, reject) => {
    const request = http.get('http://127.0.0.1:9225/json/version', res => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', chunk => { body += chunk; if (body.length > 65536) request.destroy(new Error('order_cdp_invalid')); });
      res.on('end', () => {
        try {
          const u = new URL(JSON.parse(body).webSocketDebuggerUrl);
          if (res.statusCode !== 200 || u.protocol !== 'ws:' || u.hostname !== '127.0.0.1' || u.port !== '9225'
              || !/^\/devtools\/browser\/[A-Za-z0-9-]+$/.test(u.pathname) || u.search || u.hash || u.username || u.password) fail('order_cdp_invalid');
          resolve(u.href);
        } catch { reject(new Error('order_cdp_invalid')); }
      });
    });
    request.setTimeout(Math.max(1, deadline - Date.now()), () => request.destroy(new Error('order_cdp_timeout')));
    request.on('error', () => reject(new Error('order_cdp_unavailable')));
  });
}
async function connect(deadline) {
  const socket = new WebSocket(await discover(deadline));
  let seq = 0;
  const pending = new Map();
  const stop = () => { for (const {reject, timer} of pending.values()) { clearTimeout(timer); reject(new Error('order_cdp_unavailable')); } pending.clear(); };
  socket.addEventListener('message', event => {
    let response;
    try { response = JSON.parse(event.data); } catch { stop(); socket.close(); return; }
    const p = pending.get(response.id);
    if (!p) return;
    pending.delete(response.id); clearTimeout(p.timer);
    response.error ? p.reject(new Error('order_cdp_command_failed')) : p.resolve(response.result);
  });
  socket.addEventListener('close', stop);
  socket.addEventListener('error', stop);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { socket.close(); reject(new Error('order_cdp_timeout')); }, Math.max(1, deadline - Date.now()));
    socket.addEventListener('open', () => { clearTimeout(timer); resolve(); }, {once: true});
    socket.addEventListener('error', () => { clearTimeout(timer); reject(new Error('order_cdp_unavailable')); }, {once: true});
  });
  return {
    async call(method, params = {}, end = deadline) {
      if (!['Browser.getVersion', 'Target.getBrowserContexts', 'Storage.getCookies', 'Storage.setCookies'].includes(method)) fail('order_cdp_command_forbidden');
      if (end <= Date.now()) fail('order_cdp_timeout');
      const id = ++seq;
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => { pending.delete(id); reject(new Error('order_cdp_timeout')); }, Math.min(3000, end - Date.now()));
        pending.set(id, {resolve, reject, timer});
        socket.send(JSON.stringify({id, method, params}));
      });
    },
    close() { stop(); socket.close(); }
  };
}
async function validateBrowser(connection, end) {
  const version = await connection.call('Browser.getVersion', {}, end);
  const contexts = await connection.call('Target.getBrowserContexts', {}, end);
  if (!Array.isArray(contexts.browserContextIds) || contexts.browserContextIds.length !== 0) fail('order_context_ambiguous');
  if (typeof version.userAgent !== 'string' || !version.userAgent || version.userAgent.length > 1024 || /[\r\n]/.test(version.userAgent)) fail('order_browser_identity_invalid');
  return version.userAgent;
}
async function identityResponse(request, budget, end) {
  let url = IDENTITY;
  const deadline = Math.min(end, Date.now() + budget);
  // Same original 20 redirects and one request budget; inspect each hop before a
  // CookieJar-unsupported Partitioned attribute could be committed as ordinary.
  for (let hops = 0; hops <= 20; hops++) {
    if (deadline <= Date.now()) fail('order_probe_transport_unavailable');
    const response = await request.get(url, {timeout: deadline - Date.now(), failOnStatusCode: false, maxRedirects: 0});
    try {
      const headers = await response.headersArray();
      const address = new URL(response.url());
      if (headers.some(h => h.name.toLowerCase() === 'set-cookie'
          && /;\s*partitioned(?:\s*=[^;]*)?\s*(?:;|$)/i.test(h.value)
          && (address.hostname === DOMAIN || ((address.hostname === 'p2pah.cn' || address.hostname.endsWith('.p2pah.cn'))
              && /;\s*domain\s*=\s*\.?p2pah\.cn\s*(?:;|$)/i.test(h.value))))) fail('order_cookie_partition_unsupported');
      const location = headers.find(h => h.name.toLowerCase() === 'location')?.value;
      if ([301, 302, 303, 307, 308].includes(response.status()) && location !== undefined) {
        if (hops === 20) fail('order_probe_transport_unavailable');
        url = new URL(location, response.url()).href;
        continue;
      }
      return {status: response.status(), url: response.url(), body: await response.text()};
    } finally { await response.dispose(); }
  }
}
async function probe(deps = {}) {
  const end = Date.now() + 32000;
  const attachEnd = Date.now() + 8000;
  const open = deps.connect || connect;
  let connection, request;
  try {
    connection = await open(attachEnd);
    const userAgent = await validateBrowser(connection, attachEnd);
    const initialRaw = (await connection.call('Storage.getCookies', {}, attachEnd)).cookies;
    const initial = orderCookies(initialRaw, true);
    connection.close(); connection = null;
    const api = deps.request || require(PACKAGE).request;
    request = await api.newContext({userAgent, storageState: {cookies: initial.map(toJar), origins: []}});
    const before = (await request.storageState()).cookies;
    let valid = false;
    let error = 'order_probe_transport_unavailable';
    for (const budget of [12000, 8000]) {
      try {
        const response = await identityResponse(request, budget, end);
        if (response.status === 429 || response.status >= 500) continue;
        valid = identityOk(response.status, response.url, response.body);
        error = valid ? null : 'order_identity_unverified';
        break;
      } catch (error) {
        if (error.message === 'order_cookie_partition_unsupported') throw error;
        // Original transport retry only; no new identity/login attempt.
      }
    }
    const after = (await request.storageState()).cookies;
    // Re-read and CAS on this same submission connection, including original attributes.
    connection = await open(end);
    await validateBrowser(connection, end);
    const current = (await connection.call('Storage.getCookies', {}, end)).cookies;
    const changes = cookieChanges(initialRaw, before, after, current);
    if (changes.length) await connection.call('Storage.setCookies', {cookies: changes}, end);
    const verified = changes.length ? (await connection.call('Storage.getCookies', {}, end)).cookies : current;
    verifyCommit(changes, verified);
    const rows = valid ? rootCookies(verified) : [];
    return {ready: rows.length > 0, cookies: rows, error: rows.length ? null : error || 'order_identity_unverified'};
  } finally {
    connection?.close();
    if (request) await request.dispose();
  }
}

module.exports = {identityOk, identityResponse, cookieChanges, toJar, rootCookies, orderCookies, verifyCommit, probe};
if (process.argv.includes('--order-probe')) {
  probe().then(result => process.stdout.write(JSON.stringify(result) + '\n')).catch(error => {
    const safe = new Set(['order_cookie_invalid', 'order_cookie_partition_unsupported', 'order_cookie_attributes_unsupported',
      'order_cookie_duplicate_key', 'order_cookie_conflict', 'order_cookie_commit_unverified', 'order_context_ambiguous']);
    process.stdout.write(JSON.stringify({ready: false, cookies: [], error: safe.has(error.message) ? error.message : 'order_probe_unavailable'}) + '\n');
  });
}
