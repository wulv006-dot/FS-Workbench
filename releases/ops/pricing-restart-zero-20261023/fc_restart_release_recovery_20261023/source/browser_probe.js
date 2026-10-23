'use strict';
const http = require('node:http');
const IDLE = 'about:blank#fc27-idle';
const BASE = 'https://www.lootbar.com/game-coins/fc27';
function invalid(reason) { const error = new Error(reason); error.invalid = true; throw error; }
function product(url) {
  try { const parsed = new URL(url); return parsed.hostname === 'www.lootbar.com' && parsed.pathname.replace(/\/+$/, '') === '/game-coins/fc27'; }
  catch { return false; }
}
async function inspect(send) {
  const contexts = await send('Target.getBrowserContexts');
  if (!Array.isArray(contexts.browserContextIds) || contexts.browserContextIds.length) invalid('browser_context_not_unique');
  const targets = (await send('Target.getTargets')).targetInfos;
  if (!Array.isArray(targets)) invalid('browser_targets_unavailable');
  const pages = targets.filter(t => t.type === 'page' && (product(t.url) || t.url === IDLE));
  if (pages.length !== 1) invalid('product_page_not_unique');
  const page = pages[0];
  const {sessionId} = await send('Target.attachToTarget', {targetId: page.targetId, flatten: true});
  if (typeof sessionId !== 'string' || !sessionId) invalid('page_session_unavailable');
  try {
    const expression = page.url === IDLE
      ? `Boolean(document.documentElement) && location.href === ${JSON.stringify(IDLE)} && document.readyState !== 'loading' && document.querySelectorAll('a').length === 1 && document.querySelector('a').href === ${JSON.stringify(BASE)}`
      : `Boolean(document.documentElement) && location.hostname === 'www.lootbar.com' && location.pathname.replace(/\\/+$/, '') === '/game-coins/fc27'`;
    // Default-world read only: never install Playwright bindings or isolated worlds.
    const result = await send('Runtime.evaluate', {expression, returnByValue: true, timeout: 2000}, sessionId);
    if (result.exceptionDetails || result.result?.value !== true) invalid('browser_document_unavailable');
    if (page.url === IDLE && targets.some(t => t.type === 'worker' && t.url?.startsWith('blob:https://www.lootbar.com/'))) invalid('owned_idle_not_verified');
    return {status: 'ok'};
  } finally { await send('Target.detachFromTarget', {sessionId}); }
}
async function main() {
  let stage = 'http_discovery', socket;
  const pending = new Map(); let sequence = 0;
  const deadline = setTimeout(() => { console.log(JSON.stringify({status: 'failed', reason: 'browser_connection_timeout:' + stage})); process.exit(2); }, 5500);
  try {
    const version = await new Promise((resolve, reject) => {
      const request = http.get('http://127.0.0.1:9225/json/version', {timeout: 1500}, response => {
        let body = '';
        response.on('data', chunk => { body += chunk; if (body.length > 65536) request.destroy(new Error('discovery_oversize')); });
        response.on('end', () => { try { resolve(JSON.parse(body)); } catch { reject(new Error('discovery_invalid')); } });
      });
      request.on('timeout', () => request.destroy(new Error('discovery_timeout'))); request.on('error', reject);
    });
    const address = new URL(version.webSocketDebuggerUrl);
    if (address.protocol !== 'ws:' || address.hostname !== '127.0.0.1' || address.port !== '9225' || !address.pathname.startsWith('/devtools/browser/')) invalid('browser_endpoint_identity');
    stage = 'connect_over_cdp'; socket = new WebSocket(address.href);
    await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, {once: true}); socket.addEventListener('error', () => reject(new Error('transport_unavailable')), {once: true}); });
    socket.addEventListener('message', event => {
      let message; try { message = JSON.parse(String(event.data)); } catch { return; }
      const item = pending.get(message.id); if (!item) return;
      pending.delete(message.id); clearTimeout(item.timer);
      if (message.error) item.reject(new Error('protocol_error')); else item.resolve(message.result || {});
    });
    const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
      stage = method; const id = ++sequence;
      const timer = setTimeout(() => { pending.delete(id); reject(new Error('protocol_timeout')); }, 2000);
      pending.set(id, {resolve, reject, timer});
      socket.send(JSON.stringify({id, method, params, ...(sessionId ? {sessionId} : {})}));
    });
    const result = await inspect(send);
    console.log(JSON.stringify(result));
  } catch (error) { console.log(JSON.stringify({status: error.invalid ? 'invalid' : 'failed', reason: error.invalid ? error.message : 'browser_probe_failed:' + stage})); }
  finally {
    for (const item of pending.values()) clearTimeout(item.timer);
    if (socket) socket.close(); clearTimeout(deadline);
  }
}
module.exports = {inspect, product};
if (require.main === module || process.argv.includes('--fc-health')) main();
