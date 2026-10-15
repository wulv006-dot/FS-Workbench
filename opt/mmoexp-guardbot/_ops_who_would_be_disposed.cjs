'use strict';
/* ============================================================================
 * 终检：用【线上正在跑的 index.js】全量扫一遍，回答一个唯一的问题 ——
 *   「按当前规则（loose + 片段式匹配 + 拼写容错 + 白名单身份组 + Admin 硬保护），
 *     现在服务器里到底有谁会被真正处置？」
 *
 * 判定顺序完全复刻 handle()：Admin 硬保护 -> assessMember 命中 -> 白名单 -> 处置。
 * 不改任何配置、不发任何 Discord 动作，纯 GET。
 * 跑法：node /opt/mmoexp-guardbot/_ops_who_would_be_disposed.cjs
 * ==========================================================================*/
const g = require('/opt/mmoexp-guardbot/index.js');
g.loadConfig();

const cfg = g.state.config;
const wl = g.state.whitelist;
const H = { Authorization: 'Bot ' + String(cfg.token).trim() };
const GID = cfg.guildId;
const ADMIN_PERM = 8n;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function j(url, tries = 10) {
  for (let i = 0; i < tries; i++) {
    const r = await fetch(url, { headers: H });
    if (r.status === 429) {
      const b = await r.json().catch(() => ({}));
      await sleep(Math.ceil((Number(b.retry_after) || 1) * 1000 + 400));
      continue;
    }
    if (!r.ok) throw new Error(r.status + ' ' + url);
    return r.json();
  }
  throw new Error('retry exhausted');
}

(async () => {
  console.log('index.js 导出：%j', Object.keys(g));
  console.log('线上规则：matchMode=%s action=%s dryRun=%s', cfg.matchMode, cfg.action, cfg.dryRun);
  console.log('片段匹配：brandTokenMatch=%s brandCore=%s brandTokenFuzzy=%s',
    cfg.brandTokenMatch, cfg.brandCore, cfg.brandTokenFuzzy);
  console.log('白名单角色 %d 个：%j', (wl.roleIds || []).length, wl.roleIds);
  console.log('白名单用户 %d 个：%j\n', (wl.userIds || []).length, wl.userIds);

  const roles = await j(`https://discord.com/api/v10/guilds/${GID}/roles`);
  const byId = Object.fromEntries(roles.map((r) => [r.id, r]));
  const adminRoles = new Set();
  for (const r of roles) if ((BigInt(r.permissions) & ADMIN_PERM) === ADMIN_PERM) adminRoles.add(r.id);
  console.log('Admin 硬保护角色（带 Administrator 权限）：%j\n',
    [...adminRoles].map((x) => (byId[x] ? byId[x].name : x)));

  let after = '0', total = 0, bots = 0, page = 0;
  const hitList = [];

  while (true) {
    const url = `https://discord.com/api/v10/guilds/${GID}/members?limit=1000` + (after !== '0' ? `&after=${after}` : '');
    const ms = await j(url);
    if (!ms.length) break;
    page++;
    for (const m of ms) {
      total++;
      const u = m.user;
      if (u.bot) { bots++; continue; }
      const memberLike = {
        id: u.id,
        nickname: m.nick || null,
        displayName: m.nick || u.global_name || u.username,
        user: { id: u.id, username: u.username, globalName: u.global_name || null, bot: false },
      };
      const hit = g.assessMember(memberLike);
      if (!hit) continue;
      const mroles = m.roles || [];
      const isProt = mroles.some((rid) => adminRoles.has(rid));
      const isWl = mroles.some((rid) => (wl.roleIds || []).includes(rid)) || (wl.userIds || []).includes(u.id);
      hitList.push({
        id: u.id, tag: u.username, gname: u.global_name || null, nick: m.nick || null,
        field: hit.field, value: hit.value, via: hit.via,
        isProt, isWl,
        roles: mroles.map((rid) => (byId[rid] ? byId[rid].name : rid)),
        created: new Date(Number((BigInt(u.id) >> 22n) + 1420070400000n)).toISOString().slice(0, 10),
      });
    }
    after = ms[ms.length - 1].user.id;
    if (page % 10 === 0) console.log(`   … 已扫 ${page} 页 / ${total} 人`);
    await sleep(200);
    if (ms.length < 1000) break;
  }

  const wouldDispose = hitList.filter((x) => !x.isProt && !x.isWl);
  const line = (x) => `   ${x.tag}  gname=${JSON.stringify(x.gname)}  nick=${JSON.stringify(x.nick)}  id=${x.id}\n` +
    `      命中：${x.field} = ${JSON.stringify(x.value)}  via=${x.via}   角色=[${x.roles.join('/')}]  注册 ${x.created}`;

  console.log('\n================ 终检结果 ================');
  console.log(`共 ${page} 页 / ${total} 人（机器人 ${bots} 已跳过）`);
  console.log(`名字命中规则的真人：${hitList.length} 人`);
  console.log(`  ├─ 被 Admin 硬保护跳过：${hitList.filter((x) => x.isProt).length} 人`);
  console.log(`  └─ 被白名单身份组豁免：${hitList.filter((x) => !x.isProt && x.isWl).length} 人`);
  console.log(`👉 会真正被处置（${cfg.action}）：${wouldDispose.length} 人`);

  if (hitList.length) {
    console.log('\n--- 全部命中者明细 ---');
    for (const x of hitList) {
      const tag = x.isProt ? '[Admin硬保护]' : x.isWl ? '[白名单]' : '⚡会被处置';
      console.log(line(x) + '   ' + tag);
    }
  }
  if (wouldDispose.length) {
    console.log('\n⚠️ 以下账号会被处置：');
    for (const x of wouldDispose) console.log(line(x));
  } else {
    console.log('\n✅ 没有任何「非保护组」的成员会被处置 —— 当前无误封风险。');
  }
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
