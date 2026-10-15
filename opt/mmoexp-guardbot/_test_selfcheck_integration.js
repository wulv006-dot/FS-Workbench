'use strict';
/* ============================================================================
 * 状态自检 · 事件接线集成测试（不联网、不登录）
 *
 * 做法：require 到模块内部那个**真实的 discord.js Client 实例**，
 *       然后 client.emit(Events.MessageCreate, 合成消息)，
 *       断言监听器真的被触发、分支走向正确、门禁生效、回复内容正确。
 *
 * 这比「直接调 buildReport()」更强：它验证的是事件注册与路由，
 * 而不是单个函数 —— 私信收不到事件这类问题正是这一层才能发现。
 *
 * 跑法：node _test_selfcheck_integration.js
 * ==========================================================================*/

const path = require('path');
const { Events, GatewayIntentBits, Partials, PermissionFlagsBits } = require('discord.js');

const mod = require('./index.js');
const { state, client } = mod;

const BOT_ID = '1559819072168796240';
const GUILD_ID = '1041923524601851914';
const OPERATOR_ID = '424242424242424242';
const STRANGER_ID = '555555555555555555';
const TOKEN_SENTINEL = 'MT0.SENTINEL.MUST_NOT_LEAK';

let pass = 0, fail = 0;
const results = [];
function check(name, ok, detail) {
  results.push([name, !!ok, detail]);
  if (ok) { pass++; console.log('PASS  ' + name + (detail ? '  | ' + detail : '')); }
  else { fail++; console.log('FAIL  ' + name + '  | ' + detail); }
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
class FakeCol extends Map {
  first() { return this.values().next().value; }
  some(fn) { for (const v of this.values()) if (fn(v)) return true; return false; }
}

/* ============================ 0. intent 与 partials 声明 ============================ */
const I = client.options.intents;
check('声明了 DirectMessages intent（非特权，收私信用）', I.has(GatewayIntentBits.DirectMessages), 'bit=' + GatewayIntentBits.DirectMessages);
check('声明了 Guilds intent', I.has(GatewayIntentBits.Guilds), '');
check('声明了 GuildMembers intent（特权）', I.has(GatewayIntentBits.GuildMembers), '');
check('❌ 没有声明特权的 MessageContent intent（声明了会导致 4014 登录失败）',
  !I.has(GatewayIntentBits.MessageContent), 'bit=' + GatewayIntentBits.MessageContent);
const partials = (client.options.partials || []).map(Number);
check('声明了 Channel partial（否则可能收不到 DM）', partials.includes(Number(Partials.Channel)),
  'partials=' + JSON.stringify(partials));

/* ============================ 1. 装配合成环境 ============================ */
const roles = new FakeCol();
roles.set('34', { id: '34', name: 'Bot', position: 34 });

const WL_ROLE = 'WLROLE000000000000';
const ROLE_OPERATOR_ID = '666666666666666666';

const fakeGuild = {
  id: GUILD_ID,
  name: 'MMOEXP Official Club',
  ownerId: '999999999999999999',
  memberCount: 53195,
  roles: { cache: roles, highest: { id: '36', name: 'Admin', position: 36 } },
  members: {
    me: { id: BOT_ID, roles: { highest: roles.get('34') } },
    async fetch(uid) {
      if (uid === ROLE_OPERATOR_ID) {
        // 通过「白名单角色」放行
        const c = new FakeCol();
        c.set(WL_ROLE, { id: WL_ROLE, name: 'MMOEXP Support' });
        return { id: uid, roles: { cache: c }, permissions: { has: () => false } };
      }
      if (uid === STRANGER_ID) {
        // 🔴 关键：即使拥有「管理服务器」权限，**也不再**能自检（旧版本会放行）
        return { id: uid, roles: { cache: new FakeCol() }, permissions: { has: (p) => p === PermissionFlagsBits.ManageGuild } };
      }
      return null;
    },
  },
};

// 给真实客户端装上假的登录态与服务器
Object.defineProperty(client, 'user', {
  value: { id: BOT_ID, tag: 'MMOEXP_Bot#2297' }, configurable: true,
});
client.guilds.cache.set(fakeGuild.id, fakeGuild);
const realFetch = client.guilds.fetch.bind(client.guilds);
client.guilds.fetch = async (id) => {
  if (String(id) === GUILD_ID) return fakeGuild;
  throw new Error('Unknown Guild (测试环境)');
};

mod.loadConfig();
Object.assign(state.config, {
  token: TOKEN_SENTINEL,
  guildId: GUILD_ID,
  action: 'ban',
  dryRun: false,
  matchMode: 'strict',
  logChannelId: '',
});
// 门禁只认白名单：白名单用户 ID + 白名单角色
state.whitelist = { userIds: [OPERATOR_ID], roleIds: [WL_ROLE], note: '' };

/* ============================ 2. 合成一条消息的工具 ============================ */
function makeMsg({ isDM, authorId, mentionBot }) {
  const log = { reply: [], send: [], typing: 0 };
  const author = {
    id: authorId,
    bot: false,
    tag: authorId + '#0001',
    async send(payload) { log.send.push(payload); return {}; },
  };
  const msg = {
    author,
    guildId: isDM ? null : GUILD_ID,
    content: 'status',
    channel: { sendTyping: () => { log.typing++; return Promise.resolve(); } },
    mentions: { users: { has: () => !!mentionBot } },
    async reply(payload) { log.reply.push(payload); return {}; },
  };
  return { msg, log };
}

(async () => {
  /* ---------- 场景 A：私信 + 非白名单（但有管理服务器权限）-> 完全静默 ---------- */
  {
    const { msg, log } = makeMsg({ isDM: true, authorId: STRANGER_ID });
    client.emit(Events.MessageCreate, msg);
    await wait(500);
    check('A 非白名单私信 -> 一个回复都没有', log.reply.length === 0, 'replies=' + log.reply.length);
    check('A 非白名单私信 -> 不发私信', log.send.length === 0, 'sends=' + log.send.length);
    check('A 非白名单私信 -> 连 typing 都不发（不给任何可见信号）', log.typing === 0, 'typing=' + log.typing);
  }

  /* ---------- 场景 B：私信 + 白名单用户 -> 回报报告 ---------- */
  {
    const { msg, log } = makeMsg({ isDM: true, authorId: OPERATOR_ID });
    client.emit(Events.MessageCreate, msg);
    await wait(700);
    check('B 白名单用户私信有回复', log.reply.length === 1, 'replies=' + log.reply.length);
    check('B 通过门禁后才发 typing 指示', log.typing >= 1, 'typing=' + log.typing);
    const p = log.reply[0] || {};
    check('B 回复带 embeds', Array.isArray(p.embeds) && p.embeds.length === 1, JSON.stringify(Object.keys(p)));
    const j = p.embeds && p.embeds[0] && p.embeds[0].toJSON ? p.embeds[0].toJSON() : null;
    check('B 报告标题正确', !!(j && j.title && j.title.includes('状态自检')), j && j.title);
    check('B 报告含 dryRun 说明', !!(j && JSON.stringify(j).includes('dryRun')), '');
    check('B 报告含 action=ban', !!(j && JSON.stringify(j).includes('ban')), '');
    check('B 🔴 报告不含 token', !(j && JSON.stringify(j).includes(TOKEN_SENTINEL)), '');
  }

  /* ---------- 场景 B2：私信 + 持「白名单角色」-> 也回报（角色路径） ---------- */
  {
    const { msg, log } = makeMsg({ isDM: true, authorId: ROLE_OPERATOR_ID });
    client.emit(Events.MessageCreate, msg);
    await wait(700);
    check('B2 白名单角色私信也有回复', log.reply.length === 1, 'replies=' + log.reply.length);
    const j = log.reply[0] && log.reply[0].embeds && log.reply[0].embeds[0];
    check('B2 报告可正常生成', !!(j && j.toJSON && j.toJSON().title.includes('状态自检')), '');
  }

  /* ---------- 场景 C：服务器频道里没 @ 机器人 -> 完全不理 ---------- */
  {
    const { msg, log } = makeMsg({ isDM: false, authorId: OPERATOR_ID, mentionBot: false });
    client.emit(Events.MessageCreate, msg);
    await wait(300);
    check('C 未 @ 机器人时不回复', log.reply.length === 0, 'replies=' + log.reply.length);
    check('C 未 @ 机器人时不私信', log.send.length === 0, 'sends=' + log.send.length);
  }

  /* ---------- 场景 D：服务器频道里 @ 机器人 + 白名单 -> 报告走私信 ---------- */
  {
    const { msg, log } = makeMsg({ isDM: false, authorId: OPERATOR_ID, mentionBot: true });
    client.emit(Events.MessageCreate, msg);
    await wait(700);
    check('D @ 机器人时报告走私信', log.send.length === 1, 'sends=' + log.send.length);
    const sj = log.send[0] && log.send[0].embeds && log.send[0].embeds[0];
    check('D 私信内容为状态报告', !!(sj && sj.toJSON && sj.toJSON().title.includes('状态自检')),
      sj && sj.toJSON && sj.toJSON().title);
    check('D 频道里只回一句短提示（不公开配置）', log.reply.length === 1 && !log.reply[0].embeds,
      JSON.stringify(log.reply[0]).slice(0, 80));
    check('D 短提示说明已私信', !!((log.reply[0] || {}).content || '').includes('私信'), (log.reply[0] || {}).content);
  }

  /* ---------- 场景 E：@ 机器人但不是白名单 -> 完全静默 ---------- */
  {
    const { msg, log } = makeMsg({ isDM: false, authorId: STRANGER_ID, mentionBot: true });
    client.emit(Events.MessageCreate, msg);
    await wait(600);
    check('E 非白名单 @ 机器人 -> 频道里一句话都不回', log.reply.length === 0, 'replies=' + log.reply.length);
    check('E 非白名单 -> 不会收到私信报告', log.send.length === 0, 'sends=' + log.send.length);
  }

  /* ---------- 场景 F：机器人自己的消息 / 其他机器人 -> 不理 ---------- */
  {
    const a = makeMsg({ isDM: true, authorId: OPERATOR_ID });
    a.msg.author.bot = true;
    client.emit(Events.MessageCreate, a.msg);
    await wait(250);
    check('F 忽略机器人/自己发的消息', a.log.reply.length === 0, 'replies=' + a.log.reply.length);
  }

  /* ---------- 场景 G：空消息对象不应抛异常 ---------- */
  {
    let threw = false;
    try {
      client.emit(Events.MessageCreate, null);
      client.emit(Events.MessageCreate, { author: null });
      await wait(200);
    } catch (e) { threw = true; }
    check('G 异常输入被吞掉、不崩溃', !threw, '');
  }

  client.guilds.fetch = realFetch; // 还原

  console.log(`\n===== 汇总：${pass + fail} 项，失败 ${fail} 项 =====`);
  for (const [n, ok, d] of results) if (!ok) console.log('  FAIL', n, d || '');
  process.exit(fail ? 1 : 0);
})().catch((e) => {
  console.error('测试脚本自身异常：', e);
  process.exit(2);
});
