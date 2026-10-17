'use strict';
/* ============================================================================
 * 只读体检：扩展规则「片段式匹配 + 拼写容错」的影响面
 *
 * 背景：老板发现两类漏网
 *   ① nick.mmoexp    —— 品牌词不是开头，是中间/结尾的独立片段
 *   ② service_mmoex  —— 品牌词拼错了（少一个字母 p）
 * 现有规则 brandPattern=^(?:the)?(?:mm[o0]+)exp([a-z0-9]*)$ 只认「开头」，
 * 且要求后缀是官方类词，所以这两类全部放行。
 *
 * 本脚本模拟「新规则」：把名字按非字母数字切成片段，任一独立片段与品牌词
 *   - 全等            → 命中
 *   - 少一个字母      → 命中（service_mmoex）
 *   - 换一个字母      → 命中
 * 然后与「线上当前判定」逐人对比，列出新增命中的人，并标注是否管理员硬保护/白名单。
 *
 * 不改任何线上配置、不发任何 Discord 动作，纯 GET。
 * 跑法：node /opt/mmoexp-guardbot/_ops_preflight_anywhere.cjs
 * ==========================================================================*/
const fs = require('fs');

const CFG = '/opt/mmoexp-guardbot/config.json';
const cfg = JSON.parse(fs.readFileSync(CFG, 'utf8'));
const H = { Authorization: 'Bot ' + String(cfg.token).trim() };
const GID = cfg.guildId;
const ADMIN_PERM = 8n;

const BRAND_ANY = 'mmoexp';                 // 拟新增配置 brandCore
const FUZZY = 1;                            // 拟新增配置 brandTokenFuzzy
const SUFFIX_OK = ['support','official','admin','team','service','help','cs','staff',
  'store','sale','sales','gift','giveaway','airdrop','claim','reward','promo','bot','mod',
  'manager','agent','online','shop','market','trade','vip','global','hq','inc','llc','top','buy','sell'];

const ZW = /[\u200B-\u200D\u2060\uFEFF\u00AD\u180E\u034F]/g;
const HOMO = {
  '\u041C':'m','\u043C':'m','\u217F':'m','\uFF4D':'m','\uFF2D':'m','\u039C':'m','\u03BC':'m',
  '\u041E':'o','\u043E':'o','\u039F':'o','\u03BF':'o','\u0585':'o','\u0586':'o','\uFF4F':'o','\uFF2F':'o',
  '\u0415':'e','\u0435':'e','\u0395':'e','\u03B5':'e','\uFF45':'e','\uFF25':'e','\u212E':'e',
  '\u0425':'x','\u0445':'x','\u03A7':'x','\u03C7':'x','\u00D7':'x','\u2573':'x','\uFF58':'x','\uFF38':'x',
  '\u0420':'p','\u0440':'p','\u03A1':'p','\u03C1':'p','\uFF50':'p','\uFF30':'p',
};
const HOMO_RE = new RegExp('[' + Object.keys(HOMO).map((k) => '\\u' + k.charCodeAt(0).toString(16).padStart(4, '0')).join('') + ']', 'g');

function canon(raw) {
  let s = raw == null ? '' : String(raw);
  s = s.normalize('NFKC').replace(ZW, '').replace(HOMO_RE, (ch) => HOMO[ch] || ch);
  return s.toLowerCase();
}
const squash = (s) => s.replace(/[^a-z0-9]+/g, '');

/* ---------- 线上当前判定（复刻 index.js classify） ---------- */
function classifyOld(raw) {
  const sq = squash(canon(raw));
  if (sq.length < 6) return null;
  for (const t of cfg.extraStartsWith || []) {
    const tt = squash(canon(t));
    if (tt && sq.startsWith(tt)) return { via: 'extra' };
  }
  const m = sq.match(new RegExp(cfg.brandPattern, 'i'));
  if (!m) return null;
  const tail = m[1] || '';
  if (cfg.matchMode === 'loose') return { via: 'loose' };
  if (tail === '') return { via: 'exact' };
  if (/^[0-9]+$/.test(tail)) return { via: 'digits' };
  if (SUFFIX_OK.some((s) => tail.startsWith(s))) return { via: 'suffix' };
  return null;
}

/* ---------- 拟新增：片段式匹配 + 容错 ---------- */
function dropOne(a, b) {              // 从 a 删 1 个字符 == b
  if (a.length - b.length !== 1) return false;
  for (let i = 0; i < a.length; i++) if (a.slice(0, i) + a.slice(i + 1) === b) return true;
  return false;
}
function oneCharDiff(a, b) {          // 等长且恰好 1 位不同
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) d++;
  return d === 1;
}
const CORE_RE = /^(?:the)?mm[o0]+exp$/;
function tokenMatch(raw) {
  const parts = canon(raw).split(/[^a-z0-9]+/).filter(Boolean);
  for (const p of parts) {
    if (p.length < 4) continue;
    if (p === BRAND_ANY || CORE_RE.test(p)) return { via: 'token', tok: p };
    if (FUZZY >= 1) {
      if (BRAND_ANY.length - p.length === 1 && dropOne(BRAND_ANY, p)) return { via: 'token-approx', tok: p };
      if (p.length === BRAND_ANY.length && oneCharDiff(BRAND_ANY, p)) return { via: 'token-approx', tok: p };
    }
  }
  return null;
}
function classifyNew(raw) {
  const old = classifyOld(raw);
  if (old) return old;
  const sq = squash(canon(raw));
  if (sq.length < 6) return null;
  const tk = tokenMatch(raw);
  if (tk) return tk;
  return null;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function j(url, tries = 10) {
  for (let i = 0; i < tries; i++) {
    const r = await fetch(url, { headers: H });
    if (r.status === 429) {
      const b = await r.json().catch(() => ({}));
      const wait = Math.ceil((Number(b.retry_after) || 1) * 1000 + 400);
      console.log(`   … 429 限流，等 ${wait}ms 重试 (${i + 1}/${tries})`);
      await sleep(wait); continue;
    }
    if (!r.ok) throw new Error(`${r.status} ${url} :: ${(await r.text()).slice(0, 200)}`);
    return r.json();
  }
  throw new Error('重试次数用尽：' + url);
}

(async () => {
  console.log('线上当前 matchMode = %s', cfg.matchMode);
  console.log('拟新增规则：片段式匹配 brandCore=%s 容错 brandTokenFuzzy=%d（少一个/换一个字母）\n', BRAND_ANY, FUZZY);

  const roles = await j(`https://discord.com/api/v10/guilds/${GID}/roles`);
  const byId = Object.fromEntries(roles.map((r) => [r.id, r]));
  const adminRoles = new Set();
  for (const r of roles) if ((BigInt(r.permissions) & ADMIN_PERM) === ADMIN_PERM) adminRoles.add(r.id);
  const wlRoleIds = [...(cfg.whitelistRoleIds || [])];
  const wlUserIds = [...(cfg.whitelistUserIds || [])];
  console.log('白名单角色：%j  白名单用户：%j\n', wlRoleIds.map((x) => (byId[x] ? byId[x].name : x)), wlUserIds);

  let after = '0', total = 0, humans = 0, bots = 0, page = 0;
  const onlyNew = [];   // 新规则命中、当前不命中
  const both = [];      // 两边都命中

  while (true) {
    const url = `https://discord.com/api/v10/guilds/${GID}/members?limit=1000` + (after !== '0' ? `&after=${after}` : '');
    const ms = await j(url);
    if (!ms.length) break;
    page++;
    for (const m of ms) {
      total++;
      const u = m.user;
      if (u.bot) { bots++; continue; }
      humans++;
      const fields = [
        ['username', u.username],
        ['globalName', u.global_name || null],
        ['nickname', m.nick || null],
        ['displayName', m.nick || u.global_name || u.username],
      ];
      let oldHit = null, newHit = null;
      for (const [f, v] of fields) {
        if (!v) continue;
        if (!oldHit) { const h = classifyOld(v); if (h) oldHit = { f, v, h }; }
        if (!newHit) { const h = classifyNew(v); if (h) newHit = { f, v, h }; }
      }
      if (!newHit) continue;
      const mroles = m.roles || [];
      const pos = mroles.reduce((mx, rid) => Math.max(mx, byId[rid] ? byId[rid].position : 0), 0);
      const created = Number((BigInt(u.id) >> 22n) + 1420070400000n);
      const rec = {
        id: u.id, tag: u.username, nick: m.nick || null, gname: u.global_name || null,
        field: newHit.f, value: newHit.v, via: newHit.h.via, tok: newHit.h.tok || null,
        oldVia: oldHit ? oldHit.h.via : null,
        pos, created, createdStr: new Date(created).toISOString().slice(0, 10),
        isProt: mroles.some((r) => adminRoles.has(r)),
        isWl: mroles.some((r) => wlRoleIds.includes(r)) || wlUserIds.includes(u.id),
        roleNames: mroles.map((rid) => (byId[rid] ? byId[rid].name : rid)).slice(0, 6).join('/'),
      };
      if (oldHit) both.push(rec); else onlyNew.push(rec);
    }
    after = ms[ms.length - 1].user.id;
    if (page % 10 === 0) console.log(`   … 已扫 ${page} 页 / ${total} 人`);
    await sleep(220);
    if (ms.length < 1000) break;
  }

  const ageDays = (x) => Math.floor((Date.now() - x.created) / 86400000);
  const line = (x) => `   ${String(ageDays(x)).padStart(5)}天  注册${x.createdStr}  位置${String(x.pos).padStart(3)}  ` +
    `${x.tag}  nick=${JSON.stringify(x.nick)}  gname=${JSON.stringify(x.gname)}  ` +
    `→ ${x.field}:${JSON.stringify(x.value)} via=${x.via}${x.tok ? '(' + x.tok + ')' : ''}` +
    (x.roleNames ? `  roles=[${x.roleNames}]` : '') +
    (x.isProt ? '  [管理员硬保护]' : '') + (x.isWl ? '  [白名单]' : '');

  console.log('\n================ 遍历完成 ================');
  console.log(`共 ${page} 页 / ${total} 人（人类 ${humans}，机器人 ${bots}）`);
  console.log(`当前规则命中：${both.length} 人`);
  console.log(`新规则命中：${both.length + onlyNew.length} 人`);
  console.log(`👉 扩规则会「多抓」：${onlyNew.length} 人`);
  const risky = onlyNew.filter((x) => !x.isProt && !x.isWl);
  console.log(`   其中会被真正处置（非管理员、非白名单）：${risky.length} 人`);
  console.log(`   其中被管理员硬保护跳过：${onlyNew.filter((x) => x.isProt).length} 人`);
  console.log(`   其中被白名单豁免：${onlyNew.filter((x) => x.isWl).length} 人`);

  if (both.length) console.log('\n--- 两种规则都会抓到的（前 40）---\n' + both.slice(0, 40).map(line).join('\n'));
  if (onlyNew.length) console.log('\n--- 只有新规则会多抓的（全部）---\n' + onlyNew.map(line).join('\n'));
  else console.log('\n✅ 没有「只有新规则才命中」的人。');
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
