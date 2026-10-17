'use strict';
/* ============================================================================
 * 只读体检：strict vs loose 两种匹配模式的差异
 *   目的：回答「把 matchMode 从 strict 改成 loose（品牌词开头一律命中）
 *         会多抓出多少人，其中有没有可能误伤的正常玩家」
 *   不改任何线上配置、不发任何 Discord 动作，纯 GET。
 *   跑法：node /opt/mmoexp-guardbot/_ops_preflight_loose.cjs
 * ==========================================================================*/
const path = require('path');

const BOT_DIR = '/opt/mmoexp-guardbot';
const mod = require(path.join(BOT_DIR, 'index.js'));
mod.loadConfig();

const cfg = mod.state.config;
const wl = mod.state.whitelist;
const H = { Authorization: 'Bot ' + String(cfg.token).trim() };
const GID = cfg.guildId;
const ADMIN_PERM = 8n;
const ORIG_MODE = cfg.matchMode;

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
  console.log('线上当前模式 matchMode = %s', ORIG_MODE);
  console.log('对比对象：strict（现状） vs loose（品牌词开头一律命中）\n');

  const roles = await j(`https://discord.com/api/v10/guilds/${GID}/roles`);
  const byId = Object.fromEntries(roles.map((r) => [r.id, r]));
  const adminRoles = new Set();
  for (const r of roles) {
    if ((BigInt(r.permissions) & ADMIN_PERM) === ADMIN_PERM) adminRoles.add(r.id);
  }
  const wlRoleNames = wl.roleIds.map((x) => (byId[x] ? byId[x].name : x));
  console.log('白名单角色：%j  白名单用户：%j\n', wlRoleNames, wl.userIds);

  let after = '0';
  let total = 0, humans = 0, page = 0, bots = 0;
  const onlyLoose = [];   // loose 命中但 strict 不命中
  const strictHit = [];   // strict 也命中

  while (true) {
    const url = `https://discord.com/api/v10/guilds/${GID}/members?limit=1000` +
      (after !== '0' ? `&after=${after}` : '');
    const ms = await j(url);
    if (!ms.length) break;
    page++;
    for (const m of ms) {
      total++;
      const u = m.user;
      if (u.bot) { bots++; continue; }
      humans++;
      const mroles = m.roles || [];
      const memberLike = {
        id: u.id,
        nickname: m.nick || null,
        displayName: m.nick || u.global_name || u.username,
        user: { id: u.id, username: u.username, globalName: u.global_name || null, bot: false },
        roles: { cache: { has: (rid) => mroles.includes(rid) } },
        client: { user: { id: '0' } },
      };

      cfg.matchMode = ORIG_MODE;
      const a = mod.assessMember(memberLike);
      cfg.matchMode = 'loose';
      const b = mod.assessMember(memberLike);
      cfg.matchMode = ORIG_MODE;

      if (!b) continue;
      const highestPos = mroles.reduce((mx, rid) => Math.max(mx, byId[rid] ? byId[rid].position : 0), 0);
      const rec = {
        id: u.id,
        tag: u.username,
        nick: m.nick || null,
        gname: u.global_name || null,
        field: b.field,
        value: b.value,
        via: b.via,
        strictVia: a ? a.via : null,
        pos: highestPos,
        created: Number((BigInt(u.id) >> 22n) + 1420070400000n),
        createdStr: new Date(Number((BigInt(u.id) >> 22n) + 1420070400000n)).toISOString().slice(0, 10),
        isProt: mroles.some((r) => adminRoles.has(r)),
        isWl: mroles.some((r) => wl.roleIds.includes(r)) || wl.userIds.includes(u.id),
      };
      if (a) strictHit.push(rec); else onlyLoose.push(rec);
    }
    after = ms[ms.length - 1].user.id;
    if (page % 10 === 0) console.log(`   … 已扫 ${page} 页 / ${total} 人（其中人类 ${humans}）`);
    await sleep(220);
    if (ms.length < 1000) break;
  }

  const ageDays = (x) => Math.floor((Date.now() - x.created) / 86400000);
  const line = (x) => `   ${String(ageDays(x)).padStart(5)}天  注册${x.createdStr}  位置${String(x.pos).padStart(3)}  ` +
    `${x.tag}  nick=${JSON.stringify(x.nick)}  gname=${JSON.stringify(x.gname)}  → ${x.field}: ${x.value} (loose via=${x.via})` +
    (x.isProt ? '  [管理员硬保护]' : '') + (x.isWl ? '  [白名单]' : '');

  console.log('\n================ 遍历完成 ================');
  console.log(`共 ${page} 页 / ${total} 人（人类 ${humans}，机器人 ${bots}）`);
  console.log(`strict（现状）命中：${strictHit.length} 人`);
  console.log(`loose  命中：${strictHit.length + onlyLoose.length} 人`);
  console.log(`👉 切 loose 会「多抓」：${onlyLoose.length} 人`);

  const risky = onlyLoose.filter((x) => !x.isProt && !x.isWl);
  console.log(`   其中会被真正处置（非管理员、非白名单）：${risky.length} 人`);
  console.log(`   其中被管理员硬保护跳过：${onlyLoose.filter((x) => x.isProt).length} 人`);
  console.log(`   其中被白名单豁免：${onlyLoose.filter((x) => x.isWl).length} 人`);

  if (strictHit.length) {
    console.log('\n--- 两种模式都会抓到的 ---\n' + strictHit.slice(0, 30).map(line).join('\n'));
  }
  if (onlyLoose.length) {
    console.log('\n--- 只有 loose 会多抓的（前 60）---\n' + onlyLoose.slice(0, 60).map(line).join('\n'));
  } else {
    console.log('\n✅ 没有任何人「只有 loose 才会命中」——两种模式在现有成员上结果完全一致。');
  }
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
