'use strict';
const ADMINS = Object.freeze(['wulv', 'chenchao', 'DY']);
function resolveIdentity(req, config) {
  if (config.mode === 'proxy') {
    const peer = req.socket && req.socket.remoteAddress;
    if (!['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(peer)) return null;
    const user = String(req.headers['x-auth-user'] || '');
    const role = String(req.headers['x-auth-role'] || '');
    if (!user || !['admin','readonly'].includes(role)) return null;
    return {user, admin: role === 'admin' && ADMINS.includes(user)};
  }
  if (config.mode !== 'token') return null;
  const auth = String(req.headers.authorization || '');
  const token = auth.toLowerCase().startsWith('bearer ') ? auth.slice(7).trim() : String(req.headers['x-access-token'] || '').trim();
  if (!token) return null;
  let user = Object.prototype.hasOwnProperty.call(config.operators, token) ? config.operators[token] : null;
  if (!user && config.token && token === config.token) user = config.operatorName;
  if (typeof user !== 'string' || !user) return null;
  return {user, admin: ADMINS.includes(user)};
}
function checkApply(req, identity, writeReady, origins) {
  if (req.method !== 'POST') return {status:405, code:'POST_REQUIRED'};
  if (!identity) return {status:401, code:'AUTH_REQUIRED'};
  if (!identity.admin) return {status:403, code:'ADMIN_REQUIRED'};
  if (!writeReady) return {status:403, code:'WRITE_DISABLED'};
  if (!/^application\/json(?:\s*;|$)/i.test(String(req.headers['content-type'] || ''))) return {status:415, code:'JSON_REQUIRED'};
  const origin = req.headers.origin;
  if (origin && !origins.includes(origin)) return {status:403, code:'ORIGIN_REFUSED'};
  return null;
}
function validateApply(payload) {
  if (!payload || payload.confirm !== 'NBA_PRICE_APPLY') throw new Error('EXPLICIT_CONFIRMATION_REQUIRED');
  if (payload.requestId !== undefined && (typeof payload.requestId !== 'string' || !/^[0-9a-f]{32}$/.test(payload.requestId))) throw new Error('INVALID_REQUEST_ID');
  if (!Array.isArray(payload.platforms) || !payload.platforms.length || payload.platforms.length > 3) throw new Error('INVALID_PLATFORMS');
  const seen = new Set();
  for (const p of payload.platforms) {
    if (!p || !['PS','Xbox','PC'].includes(p.area) || seen.has(p.area)) throw new Error('INVALID_PLATFORMS');
    seen.add(p.area);
    if (typeof p.price !== 'number' || !Number.isFinite(p.price) || p.price <= 0 || p.price > Number.MAX_SAFE_INTEGER) throw new Error('INVALID_PRICE');
  }
  return payload;
}
module.exports = {ADMINS, resolveIdentity, checkApply, validateApply};
