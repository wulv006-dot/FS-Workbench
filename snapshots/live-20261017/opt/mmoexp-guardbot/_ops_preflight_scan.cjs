'use strict';
/* ============================================================================
 * 上线前体检（只读 v2）
 *   ① 统计「带 Administrator 权限的角色」各被多少人持有
 *      —— 用来判断把"管理员权限"当硬保护是否安全（例如邀请追踪角色若人手一个，
 *         那它就不能算保护，否则守卫会被整体架空）
 *   ② 把所有成员过一遍判定规则，分桶输出：
 *        🔴 会被处置 / 🟡 白名单豁免 / 🟢 管理员硬保护跳过
 *   判定直接复用 index.js 的 classify/assessMember，与线上同源。
 *
 * 跑法：node /opt/mmoexp-guardbot/_ops_preflight_scan.cjs
 * ==========================================================================*/
const path = require('path');

const BOT_DIR = '/opt/mmoexp-guardbot';
const mod = require(path.join(BOT_DIR, 'index.js'));
mod.loadConfig();

const cfg = mod.state.config;
const wl = mod.state.whitelist;
const H = { Authorization: 'Bot ' + String(cfg.token).trim() };
const GID = cfg.guildId;
const ADMIN_PERM = 8n; // PermissionFlagsBits.Administrator
const BOT_ROLE_POS = 34; // 线上读到的机器人最高角色位置

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function j(url, tries = 10) {
  for (let i = 0; i < tries; i++) {
    const r = await fetch(url, { headers: H });
    if (r.status === 429) {
      const body = await r.json().catch(() => ({}));
      const wait = Math.ceil((Number(body.retry_after) || 1) * 1000 + 400);
      console.log(`   … 429 限流，等待 ${wait}ms 重试 (${i + 1}/${tries})`);
      await sleep(wait);
      continue;
    }
    if (!r.ok) throw new Error(`${r.status} ${url} :: ${(await r.text()).slice(0, 200)}`);
    return r.json();
  }
  throw new Error('重试次数用尽：' + url);
}

(async () => {
  console.log('判定规则：matchMode=%s\nbrandPattern=%s\nextraStartsWith=%j\n',
    cfg.matchMode, cfg.brandPattern, cfg.extraStartsWith || []);
  console.log('白名单：角色=%j 用户=%j\n', wl.roleIds, wl.userIds);

  const roles = await j(`https://discord.com/api/v10/guilds/${GID}/roles`);
  const byId = Object.fromEntries(roles.map((r) => [r.id, r]));
  const adminRoles = new Set();
  for (const r of roles) {
    if ((BigInt(r.permissions) & ADMIN_PERM) === ADMIN_PERM) adminRoles.add(r.id);
  }

  let after = '0';
  let total = 0, humans = 0, page = 0;
  const roleHolders = {}; // roleId -> count of humans
  const hits = [], wlHits = [], protHits = [];

  while (true) {
    const url = `https://discord.com/api/v10/guilds/${GID}/members?limit=1000` +
      (after !== '0' ? `&after=${after}` : '');
    const ms = await j(url);
    if (!ms.length) break;
    page++;
    for (const m of ms) {
      total++;
      const u = m.user;
      if (u.bot) continue;
      humans++;
      const mroles = m.roles || [];
      for (const rid of mroles) {
        if (adminRoles.has(rid)) roleHolders[rid] = (roleHolders[rid] || 0) + 1;
      }
      const memberLike = {
        id: u.id,
        nickname: m.nick || null,
        displayName: m.nick || u.global_name || u.username,
        user: { id: u.id, username: u.username, globalName: u.global_name || null, bot: false },
        roles: { cache: { has: (rid) => mroles.includes(rid) } },
        client: { user: { id: '0' } },
      };
      const hit = mod.assessMember(memberLike);
      if (!hit) continue;

      const highestPos = mroles.reduce((mx, rid) => Math.max(mx, byId[rid] ? byId[rid].position : 0), 0);
      const rec = {
        id: u.id,
        tag: u.username,
        nick: m.nick || null,
        gname: u.global_name || null,
        field: hit.field,
        value: hit.value,
        via: hit.via,
        pos: highestPos,
        created: Number((BigInt(u.id) >> 22n) + 1420070400000n),
      };
      const isProt = mroles.some((r) => adminRoles.has(r));
      const isWl = mroles.some((r) => wl.roleIds.includes(r)) || wl.userIds.includes(u.id);
      if (isProt) protHits.push(rec);
      else if (isWl) wlHits.push(rec);
      else hits.push(rec);
    }
    after = ms[ms.length - 1].user.id;
    if (page % 10 === 0) console.log(`   … 已扫 ${page} 页 / ${total} 人`);
    await sleep(220); // 主动限速，避免再触发 429
    if (ms.length < 1000) break;
  }

  console.log('\n================ ① 带 Administrator 权限的角色被多少人持有 ================');
  for (const rid of adminRoles) {
    const r = byId[rid];
    console.log(`  ${String(r.position).padStart(3)}  ${r.name.padEnd(24)}  人类成员持有 ${roleHolders[rid] || 0} 人`);
  }
  console.log(`  （白名单里的两个角色：${wl.roleIds.map((x) => (byId[x] ? byId[x].name : x)).join(' / ')}）`);

  const ageDays = (x) => Math.floor((Date.now() - x.created) / 86400000);
  const line = (x) => `   ${String(ageDays(x)).padStart(5)}天  位置${String(x.pos).padStart(3)}  ${x.tag}` +
    `  nick=${JSON.stringify(x.nick)}  gname=${JSON.stringify(x.gname)}  →  ${x.field}: ${x.value} (${x.via})`;

  console.log('\n================ ② 判定分桶 ================');
  console.log(`遍历完成：${page} 页 / 共 ${total} 人（其中真实人类 ${humans} 人）`);
  console.log(`🔴 会被处置（不在白名单、非管理员）：${hits.length}`);
  console.log(`🟡 被白名单豁免：${wlHits.length}`);
  console.log(`🟢 被 Administrator 硬保护跳过：${protHits.length}`);
  if (hits.length) console.log('\n--- 🔴 会被处置的（前 40）---\n' + hits.slice(0, 40).map(line).join('\n'));
  if (protHits.length) console.log('\n--- 🟢 被硬保护跳过的（前 20）---\n' + protHits.slice(0, 20).map(line).join('\n'));
  if (wlHits.length) console.log('\n--- 🟡 白名单豁免的（前 20）---\n' + wlHits.slice(0, 20).map(line).join('\n'));
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
