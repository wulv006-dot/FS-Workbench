'use strict';
/* ============================================================================
 * 状态自检功能单测（不联网、不登录）
 *   1) buildReport() 生成的 Embed 结构与内容
 *   2) **报告里绝不能出现 token**
 *   3) operatorCheck() 身份核验的四种情形
 *   4) persistConfig() 落盘（dryRun 修复的回归测试）—— 会临时改写本地 config.json 后还原
 * 跑法：node _test_selfcheck.js
 * ==========================================================================*/

const fs = require('fs');
const path = require('path');
const { PermissionFlagsBits } = require('discord.js');

const mod = require('./index.js');
const { state, DEFAULTS, buildReport, operatorCheck, fmtDur, persistConfig } = mod;

const CONFIG_PATH = path.join(__dirname, 'config.json');

let pass = 0, fail = 0;
const results = [];
function check(name, ok, detail) {
  results.push([name, !!ok, detail]);
  if (ok) { pass++; console.log('PASS  ' + name + (detail ? '  | ' + detail : '')); }
  else { fail++; console.log('FAIL  ' + name + '  | ' + detail); }
}

/* ----------------------------- 假的 discord.js 集合 ----------------------------- */
class FakeCol extends Map {
  first() { return this.values().next().value; }
  some(fn) { for (const v of this.values()) if (fn(v)) return true; return false; }
}

const TOKEN_SENTINEL = 'MTU1OTgxOTA3MjE2ODc5NjI0MA.SENTINEL.DO_NOT_LEAK_ME';

const ROLE_WHITELIST_A = '1049504460768038932';
const ROLE_WHITELIST_B = '1360438635631214692';

const fakeRoles = new FakeCol();
fakeRoles.set('1', { id: '1', name: '@everyone', position: 0 });
fakeRoles.set('34', { id: '34', name: 'Bot', position: 34 });
fakeRoles.set('35', { id: '35', name: 'MMOEXP_Official_Player', position: 35 });
fakeRoles.set('36', { id: '36', name: 'Admin', position: 36 });
fakeRoles.set(ROLE_WHITELIST_A, { id: ROLE_WHITELIST_A, name: 'MMOEXP Support', position: 20 });
fakeRoles.set(ROLE_WHITELIST_B, { id: ROLE_WHITELIST_B, name: 'Customer Service', position: 21 });
const highestRole = { id: '36', name: 'Admin', position: 36 };

const fakeGuild = {
  id: '1041923524601851914',
  name: 'MMOEXP Official Club',
  ownerId: '999999999999999999',
  memberCount: 53195,
  roles: { cache: fakeRoles, highest: highestRole },
  members: { me: { id: '1559819072168796240', roles: { highest: fakeRoles.get('34') } } },
};

const fakeUsers = new FakeCol();
fakeUsers.set('424242424242424242', { id: '424242424242424242', tag: 'chenchao#0001' });

const fakeClient = {
  user: { id: '1559819072168796240', tag: 'MMOEXP_Bot#2297' },
  ws: { ping: 43 },
  guilds: {
    cache: (() => { const m = new FakeCol(); m.set(fakeGuild.id, fakeGuild); return m; })(),
    async fetch(id) { if (id === fakeGuild.id) return fakeGuild; throw new Error('Unknown Guild'); },
  },
  users: { cache: fakeUsers },
};

/* ----------------------------- 应用一份「服务器上真实」配置 ----------------------------- */
mod.loadConfig();
Object.assign(state.config, {
  token: TOKEN_SENTINEL,
  guildId: fakeGuild.id,
  action: 'ban',
  dryRun: true,
  matchMode: 'strict',
  brandPattern: '^(?:the)?(?:mm[o0]+)exp([a-z0-9]*)$',
  extraStartsWith: [],
  timeoutMinutes: 10080,
  logChannelId: '',
  alertOnWhitelistedHit: false,
  kickReason: 'Impersonation of the Official MMOEXP Name',
  banReason: 'Impersonation of the Official MMOEXP Name',
});
state.whitelist = { userIds: [], roleIds: [ROLE_WHITELIST_A, ROLE_WHITELIST_B], note: '' };
state.stats.flagged = 3;
state.stats.lastHit = {
  at: '2026-10-14 08:01:23Z', id: '888888888888888888', tag: 'MM0EXP Support#1234',
  field: '用户名 username', value: 'MM0EXP Support', via: 'suffix', src: 'join',
  outcome: 'DRY-RUN 未处置',
};

/* ================================ 1. buildReport ================================ */
(async () => {
  const embed = await buildReport(fakeClient, {});
  const j = embed.toJSON();
  const raw = JSON.stringify(j);

  check('标题正确', j.title === '🛡️ MMOEXP GuardBot · 状态自检', j.title);
  check('字段数在 1~25 之间', j.fields.length >= 9 && j.fields.length <= 25, 'fields=' + j.fields.length);

  const names = j.fields.map((f) => f.name);
  for (const want of ['① 运行环境', '② 连接与服务器', '③ 角色层级', '④ 当前处置规则',
    '⑤ 日志频道', '⑥ 本次运行统计', '⑦ 最近一次命中', '⑧ 白名单角色', '⑨ 白名单用户']) {
    check('含字段 ' + want, names.includes(want), '');
  }

  // 🔴 最关键：绝不能泄露 token
  check('报告不含 token 明文', !raw.includes(TOKEN_SENTINEL), '');
  check('报告不含 token 变量值', !raw.includes('DO_NOT_LEAK'), '');
  check('报告不含 Bearer', !/Bearer/i.test(raw), '');
  check('报告不含 token 字段名', !/"token"/.test(raw), '');

  // 内容断言
  check('显示登录账号', raw.includes('MMOEXP_Bot#2297'), '');
  check('显示服务器名与 ID', raw.includes('MMOEXP Official Club') && raw.includes(fakeGuild.id), '');
  check('显示成员数', raw.includes('53195'), '');
  check('显示 dryRun 开着（安全态）', /dryRun：\*\*🟡 开/.test(raw), '');
  check('显示 action=ban', raw.includes('\\`ban\\`') || raw.includes('| `ban`') || raw.includes('`ban`'), '');
  check('白名单角色解析成了名字', raw.includes('@MMOEXP Support') && raw.includes('@Customer Service'), '');
  check('显示最近一次命中', raw.includes('MM0EXP Support') && raw.includes('DRY-RUN 未处置'), '');
  check('显示网关心跳', raw.includes('43 ms'), '');
  check('显示角色层级位置', raw.includes('位置') && raw.includes('34'), '');

  // 体检提醒（本配置没有 logChannelId、白名单角色有但用户没有 -> 只应报日志频道等）
  check('有体检提醒字段', names.includes('⑩ 体检提醒'), '');
  const remind = (j.fields.find((f) => f.name === '⑩ 体检提醒') || {}).value || '';
  check('提醒里指出未配日志频道', remind.includes('日志频道'), remind.slice(0, 80));
  check('提醒里指出 dryRun 开着', remind.includes('dryRun'), '');
  check('提醒里指出 ban 之后不会再提 kick', !remind.includes('action=kick'), '');

  // Discord 硬限制
  const badVal = j.fields.filter((f) => !f.value || String(f.value).length > 1024);
  check('所有字段 value 非空且 <=1024', badVal.length === 0,
    badVal.map((f) => f.name + ':' + String(f.value).length).join(','));
  const badName = j.fields.filter((f) => !f.name || String(f.name).length > 256);
  check('所有字段 name 非空且 <=256', badName.length === 0, '');
  check('整体 JSON < 6000 字符', raw.length < 6000, 'len=' + raw.length);
  check('有 footer 体检结论', !!(j.footer && j.footer.text), JSON.stringify(j.footer));

  /* ===== 2. dryRun=false 时文案应改变，且出现 kick 建议只在 action=kick 时 ===== */
  state.config.dryRun = false;
  state.config.action = 'kick';
  const e2 = (await buildReport(fakeClient, {})).toJSON();
  const raw2 = JSON.stringify(e2);
  const remind2 = (e2.fields.find((f) => f.name === '⑩ 体检提醒') || {}).value || '';
  check('dryRun=false 时标题仍正常', e2.title.includes('状态自检'), e2.title);
  check('dryRun=false 时不再出现「dryRun 开着」提醒', !remind2.includes('dryRun 开着'), remind2.slice(0, 80));
  check('action=kick 且非 dryRun 时提示改用 ban', remind2.includes('kick'), remind2.slice(0, 120));
  check('dryRun=false 时也不泄露 token', !raw2.includes(TOKEN_SENTINEL), '');
  state.config.dryRun = true;
  state.config.action = 'ban';

  /* ================================ 3. operatorCheck（只认白名单） ================================ */
  const Client2 = {
    guilds: {
      async fetch(id) {
        if (id !== fakeGuild.id) throw new Error('Unknown Guild');
        return {
          ...fakeGuild,
          members: {
            async fetch(uid) {
              if (uid === '2000') {
                // 有 ManageGuild 权限 —— 新策略下**不再**放行
                return { id: uid, roles: { cache: new FakeCol() }, permissions: { has: (p) => p === PermissionFlagsBits.ManageGuild } };
              }
              if (uid === '2001') {
                // 无权限、无白名单角色
                return { id: uid, roles: { cache: new FakeCol() }, permissions: { has: () => false } };
              }
              if (uid === '2002') {
                // 持有白名单角色
                const c = new FakeCol(); c.set(ROLE_WHITELIST_A, { id: ROLE_WHITELIST_A });
                return { id: uid, roles: { cache: c }, permissions: { has: () => false } };
              }
              if (uid === fakeGuild.ownerId) {
                // 服务器拥有者 —— 新策略下**不再**放行（除非确实在名单里）
                return { id: uid, roles: { cache: new FakeCol() }, permissions: { has: () => true } };
              }
              return null; // 不在服务器
            },
          },
        };
      },
    },
  };

  state.whitelist = { userIds: ['2004'], roleIds: [ROLE_WHITELIST_A], note: '' };

  const gOwner = await operatorCheck(Client2, fakeGuild.ownerId);
  check('服务器拥有者（不在名单）-> 拒绝', !gOwner.ok, JSON.stringify(gOwner));

  const gPerm = await operatorCheck(Client2, '2000');
  check('有管理服务器权限（不在名单）-> 拒绝', !gPerm.ok && /不在.*白名单/.test(gPerm.reason || ''), JSON.stringify(gPerm));

  const gRole = await operatorCheck(Client2, '2002');
  check('持白名单角色 -> 通过', gRole.ok && /白名单角色/.test(gRole.via), JSON.stringify(gRole));

  const gUser = await operatorCheck(Client2, '2004');
  check('白名单用户 ID -> 通过（无需查成员）', gUser.ok && /白名单用户/.test(gUser.via), JSON.stringify(gUser));

  const gNo = await operatorCheck(Client2, '2001');
  check('成员但不在名单 -> 拒绝', !gNo.ok && /不在.*白名单/.test(gNo.reason || ''), JSON.stringify(gNo));

  const gOut = await operatorCheck(Client2, '3000');
  check('非成员 -> 拒绝', !gOut.ok && /不是.*成员/.test(gOut.reason || ''), JSON.stringify(gOut));

  /* ================================ 4. fmtDur ================================ */
  check('fmtDur 0 秒', fmtDur(0) === '0 秒', fmtDur(0));
  check('fmtDur 45 秒', fmtDur(45000) === '45 秒', fmtDur(45000));
  check('fmtDur 90 秒', fmtDur(90000) === '1 分 30 秒', fmtDur(90000));
  check('fmtDur 2 小时', fmtDur(2 * 3600 * 1000) === '2 小时 0 分', fmtDur(2 * 3600 * 1000));
  check('fmtDur 1 天', fmtDur(86400000 + 3600000) === '1 天 1 小时 0 分', fmtDur(86400000 + 3600000));

  /* ================================ 5. persistConfig 落盘（回归测试） ================================ */
  const original = fs.readFileSync(CONFIG_PATH);
  try {
    const before = JSON.parse(original.toString('utf8'));
    const hadNoteKey = Object.keys(before).some((k) => k.startsWith('_'));
    const tokenBefore = before.token;

    persistConfig({ dryRun: true });

    const after = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    check('persistConfig 写入了 dryRun', after.dryRun === true, 'dryRun=' + after.dryRun);
    check('persistConfig 保留 token 原值', after.token === tokenBefore, '');
    check('persistConfig 保留 _说明 等注释键', !hadNoteKey || Object.keys(after).some((k) => k.startsWith('_')),
      'keys=' + Object.keys(after).join(','));
    check('persistConfig 保留了其它配置键', after.action !== undefined || after.guildId !== undefined || after.matchMode !== undefined,
      'keys=' + Object.keys(after).join(','));
    check('persistConfig 同步了内存态', state.config.dryRun === true, 'mem=' + state.config.dryRun);

    // 再切回 false，验证能双向写
    persistConfig({ dryRun: false });
    const after2 = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    check('persistConfig 可写 false（双向）', after2.dryRun === false, 'dryRun=' + after2.dryRun);
  } finally {
    fs.writeFileSync(CONFIG_PATH, original); // 精确还原
    check('已还原 config.json', fs.readFileSync(CONFIG_PATH).equals(original), '');
  }

  /* ================================ 6. 导出完整性 ================================ */
  check('导出了 handleSelfCheck', typeof mod.handleSelfCheck === 'function', '');
  check('导出了 buildReport', typeof mod.buildReport === 'function', '');
  check('导出了 operatorCheck', typeof mod.operatorCheck === 'function', '');
  check('导出了 persistConfig', typeof mod.persistConfig === 'function', '');
  check('导出了 handle', typeof mod.handle === 'function', '');
  check('DEFAULTS.dryRun 默认 true', DEFAULTS.dryRun === true, '');

  /* =============== 7. handle() 的 dryRun 硬闸（安全关键路径回归） ===============
   * 断言：dryRun=true 时绝不调用 kick/ban/timeout，但必须记录 flagged 与 lastHit。 */
  const calls = { kick: 0, ban: 0, timeout: 0 };
  function fakeMember(name) {
    return {
      id: '777777777777777777',
      nickname: null,
      displayName: name,
      user: { id: '777777777777777777', tag: name + '#0001', username: name, globalName: null,
        bot: false, createdTimestamp: Date.now() - 3 * 86400000 },
      roles: { cache: new FakeCol(), highest: { position: 1 } },
      guild: {
        ownerId: '999999999999999999',
        members: {
          me: { id: '1559819072168796240', roles: { highest: { position: 34, comparePositionTo: (o) => 34 - (o && o.position ? o.position : 0) } } },
        },
      },
      client: fakeClient,
      async kick() { calls.kick++; },
      async ban() { calls.ban++; },
      async timeout() { calls.timeout++; },
    };
  }

  state.stats.flagged = 0;
  state.stats.lastHit = null;
  state.stats.kicked = 0; state.stats.banned = 0; state.stats.timeout = 0;
  state.config.dryRun = true;
  state.config.action = 'ban';
  state.whitelist = { userIds: [], roleIds: [], note: '' };

  await mod.handle(fakeMember('MMOEXP Support'), 'join');
  check('dryRun=true 时统计命中 +1', state.stats.flagged === 1, 'flagged=' + state.stats.flagged);
  check('dryRun=true 时没有真的 ban', calls.ban === 0, 'ban=' + calls.ban);
  check('dryRun=true 时没有真的 kick', calls.kick === 0, 'kick=' + calls.kick);
  check('dryRun=true 时没有真的 timeout', calls.timeout === 0, 'timeout=' + calls.timeout);
  check('dryRun=true 时记录了 lastHit', !!state.stats.lastHit, JSON.stringify(state.stats.lastHit));
  check('lastHit 结论标为 DRY-RUN 未处置', !!(state.stats.lastHit && /DRY-RUN/.test(state.stats.lastHit.outcome)),
    state.stats.lastHit && state.stats.lastHit.outcome);

  // 正常名字不应命中，也不应记 lastHit
  state.stats.flagged = 0; state.stats.lastHit = null;
  await mod.handle(fakeMember('mmoexpert'), 'join');
  check('正常名字 mmoexpert 不命中', state.stats.flagged === 0, 'flagged=' + state.stats.flagged);
  check('正常名字不写 lastHit', state.stats.lastHit === null, '');

  // dryRun=false 且层级够 -> 应真的调用 ban（用假的 ban 计数验证，不打真实 API）
  state.stats.flagged = 0; state.stats.lastHit = null;
  state.config.dryRun = false;
  await mod.handle(fakeMember('MMOEXP Support'), 'join');
  check('dryRun=false 时会真的执行 ban', calls.ban === 1, 'ban=' + calls.ban);
  check('dryRun=false 时 lastHit 记为 ban(封禁)', !!(state.stats.lastHit && /ban/.test(state.stats.lastHit.outcome)),
    state.stats.lastHit && state.stats.lastHit.outcome);
  state.config.dryRun = true; // 还原
  state.config.action = 'ban';

  /* ===== 8. Admin 硬保护：带 Administrator 权限者一律不处理 =====
   * 断言：即使 dryRun=false（正式处置模式）、即使不在白名单，也绝不动作、不计数。 */
  const calls8 = { ban: 0 };
  function fakeAdminMember(name) {
    const m = fakeMember(name);
    m.permissions = { has: (p) => p === PermissionFlagsBits.Administrator };
    m.ban = async () => { calls8.ban++; };
    return m;
  }
  state.stats.flagged = 0; state.stats.lastHit = null;
  state.config.dryRun = false; // 正式处置模式下也必须拦住
  state.whitelist = { userIds: [], roleIds: [], note: '' };

  const adminM = fakeAdminMember('MMOEXP Support');
  check('isProtectedAdmin 识别 Administrator 成员', mod.isProtectedAdmin(adminM) === true, '');
  check('isProtectedAdmin 对普通成员为 false', mod.isProtectedAdmin(fakeMember('x')) === false, '');
  const blockedAdmin = await mod.canActOn(adminM);
  check('canActOn 对 Administrator 返回阻塞', !!blockedAdmin && /管理组|Administrator/.test(blockedAdmin), String(blockedAdmin));

  await mod.handle(adminM, 'join');
  check('Administrator 成员：dryRun=false 也不 ban', calls8.ban === 0, 'ban=' + calls8.ban);
  check('Administrator 成员：不计入 flagged', state.stats.flagged === 0, 'flagged=' + state.stats.flagged);
  check('Administrator 成员：不写 lastHit', state.stats.lastHit === null, '');

  state.config.dryRun = true;

  console.log(`\n===== 汇总：${pass + fail} 项，失败 ${fail} 项 =====`);
  for (const [n, ok, d] of results) if (!ok) console.log('  FAIL', n, d || '');
  process.exit(fail ? 1 : 0);
})().catch((e) => {
  console.error('测试脚本自身异常：', e);
  process.exit(2);
});
