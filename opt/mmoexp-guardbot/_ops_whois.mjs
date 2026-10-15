/* 只读：查某个成员的当前名字 / 角色 / 是否带 Administrator 权限 / 是否命中守卫规则 */
import fs from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const uid = process.argv[2];
if (!uid) { console.log('用法: node _ops_whois.mjs <userId>'); process.exit(1); }

const BOTDIR = '/opt/mmoexp-guardbot';
const tok = JSON.parse(fs.readFileSync(`${BOTDIR}/config.json`, 'utf8')).token.trim();
const h = { Authorization: 'Bot ' + tok };
const gid = '1041923524601851914';

const m = await (await fetch(`https://discord.com/api/v10/guilds/${gid}/members/${uid}`, { headers: h })).json();
if (m.message) { console.log('读成员失败：', JSON.stringify(m)); process.exit(0); }

const roles = await (await fetch(`https://discord.com/api/v10/guilds/${gid}/roles`, { headers: h })).json();
const byId = Object.fromEntries(roles.map((r) => [r.id, r]));

const cfg = JSON.parse(fs.readFileSync(`${BOTDIR}/config.json`, 'utf8'));
let wlRoleIds = cfg.whitelistRoleIds || [];
let wlUserIds = cfg.whitelistUserIds || [];
try {
  const wf = JSON.parse(fs.readFileSync(`${BOTDIR}/whitelist.json`, 'utf8'));
  wlRoleIds = [...new Set([...wlRoleIds, ...(wf.roleIds || [])])];
  wlUserIds = [...new Set([...wlUserIds, ...(wf.userIds || [])])];
} catch { /* whitelist.json 不存在 */ }

console.log('=== 成员 ===');
console.log('  id        :', m.user.id);
console.log('  username  :', m.user.username);
console.log('  globalName:', JSON.stringify(m.user.global_name));
console.log('  nickname  :', JSON.stringify(m.nick));
console.log('  displayName:', JSON.stringify(m.nick || m.user.global_name || m.user.username));
console.log('  joined    :', m.joined_at, `(${Math.round((Date.now() - new Date(m.joined_at)) / 86400000)} 天前加入)`);

console.log('\n=== 角色 ===');
const adminRoles = [], wlRoles = [];
for (const rid of m.roles) {
  const r = byId[rid];
  if (!r) { console.log('  ', rid, '(角色已被删除)'); continue; }
  const isAdmin = (BigInt(r.permissions) & 8n) === 8n;
  if (isAdmin) adminRoles.push(r.name);
  if (wlRoleIds.includes(rid)) wlRoles.push(r.name);
  console.log(`   ${r.name.padEnd(26)} pos=${String(r.position).padStart(3)}  Administrator=${isAdmin ? 'YES' : 'no '}  白名单角色=${wlRoleIds.includes(rid) ? 'YES' : 'no'}`);
}

console.log('\n=== 名字判定（直接调用线上 index.js 的 classify）===');
const userMod = require(`${BOTDIR}/index.js`);
for (const [f, v] of [
  ['用户名 username', m.user.username],
  ['全局显示名 globalName', m.user.global_name],
  ['服务器昵称 nickname', m.nick],
  ['显示名 displayName', m.nick || m.user.global_name || m.user.username],
]) {
  if (!v) { console.log(`  ${f}: (空)`); continue; }
  const hit = userMod.classify(v);
  console.log(`  ${f}: ${JSON.stringify(v)}  →  ${hit ? `🔴 命中 (tail=${JSON.stringify(hit.tail)}, via=${hit.via})` : '🟢 不命中'}`);
}

console.log('\n=== 结论 ===');
console.log('  Administrator 角色 :', adminRoles.length ? adminRoles.map((x) => '「' + x + '」').join(' ') : '（无）');
console.log('  白名单角色         :', wlRoles.length ? wlRoles.map((x) => '「' + x + '」').join(' ') : '（无）');
console.log('  白名单用户ID       :', wlUserIds.includes(uid) ? 'YES' : 'no');
if (adminRoles.length) console.log('  → 🛡️ 受 Admin 硬保护：无论改什么名字都不会被处置，且**不写任何日志**（静默跳过）');
else if (wlRoles.length || wlUserIds.includes(uid)) console.log('  → ✅ 受白名单豁免：不处置；alertOnWhitelistedHit=false 时也不写日志');
else console.log('  → ⚠️ 无任何保护：名字一旦命中就会被 ban');
