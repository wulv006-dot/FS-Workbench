'use strict';

/* ============================================================================
 * MMOEXP GuardBot  —  Discord 防冒充守卫机器人
 * ----------------------------------------------------------------------------
 * 做什么：
 *   1) 新成员加入瞬间，检查 用户名 / 全局显示名 / 服务器昵称 是否冒充官方前缀
 *      → 不在白名单 → 立即按配置处置（踢出 / 封禁 / 禁言）
 *   2) 成员改名后（昵称、全局显示名、用户名）再次检查，防止"先混进来再改名"
 *   3) 存量成员一键扫描 / 一键清理
 *   4) 白名单双通道：Discord 角色 ID（推荐，给真客服发个角色即可）+ 用户 ID
 *   5) 所有处置写入日志频道，含账号年龄等取证信息
 *   6) 状态自检：私信机器人 / 在服务器里 @机器人 / 用 /guard-status，
 *      都会回报它的「实时运行状态 + 当前配置 + 体检提醒」
 *
 * 依赖：discord.js v14 ；Node.js >= 18
 * 启动：node index.js
 * ==========================================================================*/

const fs = require('fs');
const path = require('path');
const {
  Client,
  GatewayIntentBits,
  Events,
  REST,
  Routes,
  SlashCommandBuilder,
  PermissionFlagsBits,
  EmbedBuilder,
  MessageFlags,
  Partials,
} = require('discord.js');

const ROOT = __dirname;
const CONFIG_PATH = path.join(ROOT, 'config.json');
const WL_PATH = path.join(ROOT, 'whitelist.json');
// 处置台账（append-only JSONL）。审计日志不可编辑、频道消息会翻页，
// 这里留一份结构化留痕：谁、什么时间、因为哪个字段的哪个值被处置。
const LEDGER_PATH = process.env.GUARD_LEDGER || path.join(ROOT, 'action-ledger.jsonl');

/* ---------------------------------- 配置 ---------------------------------- */

const DEFAULTS = {
  token: '',
  guildId: '',
  // kick = 踢出（可再加入）| ban = 封禁（防再入）| timeout = 禁言 | none = 只记录
  action: 'kick',
  timeoutMinutes: 10080,
  // 上线前务必保持 true：只记录不处置，观察 24h 确认真客服/真客户没被误伤
  dryRun: true,
  // loose = 只要名字开头是品牌词就算；strict = 品牌词后面必须是分隔符/数字/常见官方后缀
  matchMode: 'strict',
  // 抓取用正则（作用在"去掉一切非字母数字字符"之后的名字上，全小写）
  brandPattern: '^(?:the)?(?:mm[o0]+)exp([a-z0-9]*)$',
  // 额外"开头即命中"的字面量（压缩比较），留空即可
  extraStartsWith: [],
  // 【片段式匹配】品牌词作为"独立片段"出现在名字任意位置也算命中（如 nick.mmoexp / service_mmoexp）
  brandTokenMatch: true,
  // 片段匹配用的品牌词核心
  brandCore: 'mmoexp',
  // 片段匹配的拼写容错：0=只认全等；1=少一个字母 / 换一个字母也算（如 service_mmoex = mmoexp 少个 p）
  brandTokenFuzzy: 1,
  // 白名单
  whitelistRoleIds: [],
  whitelistUserIds: [],
  // 日志频道 ID（把机器人拉进去、只给管理员可见的频道，强烈建议配置）
  logChannelId: '',
  // 白名单成员改名前也提示（一般不打扰，保持 false 即可）
  alertOnWhitelistedHit: false,
  kickReason: '名称冒充 MMOEXP 官方（防冒充策略）',
  banReason: '名称冒充 MMOEXP 官方（防冒充策略）',
};

// 品牌词后允许出现的"官方类"后缀，命中即视为冒充
const SUFFIX_OK = [
  'support', 'official', 'admin', 'team', 'service', 'help', 'cs', 'staff',
  'store', 'sale', 'sales', 'gift', 'giveaway', 'airdrop', 'claim', 'reward',
  'promo', 'bot', 'mod', 'manager', 'agent', 'online', 'shop', 'market',
  'trade', 'vip', 'global', 'hq', 'inc', 'llc', 'top', 'buy', 'sell',
];

/* ------------------------------- 名称归一化 ------------------------------- */
/* 目的：把 "ＭＭＯＥＸＰ" / "ММОЕХР"(西里尔) / "MM0EXP" / 零宽字符 全部压成 mmoexp */

const ZERO_WIDTH = /[\u200B-\u200D\u2060\uFEFF\u00AD\u180E\u034F]/g;

const HOMOGLYPH = {
  // 视觉近似 m / o / e / x / p 的异体字
  '\u041C': 'm', '\u043C': 'm', '\u217F': 'm', '\uFF4D': 'm', '\uFF2D': 'm',
  '\u039C': 'm', '\u03BC': 'm', '\u041E': 'o', '\u043E': 'o', '\u039F': 'o',
  '\u03BF': 'o', '\u0585': 'o', '\u0586': 'o', '\uFF4F': 'o', '\uFF2F': 'o',
  '\u0415': 'e', '\u0435': 'e', '\u0395': 'e', '\u03B5': 'e', '\uFF45': 'e',
  '\uFF25': 'e', '\u212E': 'e', '\u0425': 'x', '\u0445': 'x', '\u03A7': 'x',
  '\u03C7': 'x', '\u00D7': 'x', '\u2573': 'x', '\uFF58': 'x', '\uFF38': 'x',
  '\u0420': 'p', '\u0440': 'p', '\u03A1': 'p', '\u03C1': 'p', '\uFF50': 'p',
  '\uFF30': 'p',
};

const HOMO_RE = new RegExp(
  '[' + Object.keys(HOMOGLYPH)
    .map((k) => '\\u' + k.charCodeAt(0).toString(16).padStart(4, '0'))
    .join('') + ']',
  'g'
);

function canon(raw) {
  let s = raw == null ? '' : String(raw);
  s = s.normalize('NFKC');                       // 全角 → 半角
  s = s.replace(ZERO_WIDTH, '');                 // 去掉零宽/软连字符
  s = s.replace(HOMO_RE, (ch) => HOMOGLYPH[ch] || ch); // 异体字归一
  return s.toLowerCase();
}

function squash(s) {
  return s.replace(/[^a-z0-9]+/g, '');
}

/* -------------------------------- 判定逻辑 -------------------------------- */

const state = {
  config: null,
  whitelist: null,
  stats: { kicked: 0, banned: 0, timeout: 0, flagged: 0, since: Date.now(), lastHit: null },
};

function loadConfig() {
  let raw = {};
  try {
    raw = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
  } catch (e) {
    console.error('[FATAL] 读不到 config.json：', e.message);
    process.exit(1);
  }
  state.config = Object.assign({}, DEFAULTS, raw);
  if (process.env.DISCORD_TOKEN) state.config.token = process.env.DISCORD_TOKEN;

  let wl = { userIds: [], roleIds: [], note: '' };
  try {
    wl = Object.assign(wl, JSON.parse(fs.readFileSync(WL_PATH, 'utf8')));
  } catch (e) { /* 首次运行没有白名单文件是正常的 */ }
  wl.userIds = Array.from(new Set([...(wl.userIds || []), ...(state.config.whitelistUserIds || [])]));
  wl.roleIds = Array.from(new Set([...(wl.roleIds || []), ...(state.config.whitelistRoleIds || [])]));
  state.whitelist = wl;
  return state.config;
}

function saveWhitelist() {
  fs.writeFileSync(WL_PATH, JSON.stringify(state.whitelist, null, 2), 'utf8');
}

/* --------------- 片段式匹配：品牌词作为"独立片段"出现在名字任意位置 ---------------
 * 背景：旧的前缀正则只认「开头」，所以
 *   nick.mmoexp   （品牌词在中间/结尾）
 *   service_mmoex （品牌词拼错少个字母）
 * 这两类全部放行。下面按「非字母数字切分后的独立片段」比对品牌词核心，
 * 并允许 1 个字符的拼写容错（少一个字母 / 换一个字母），两种冒充形态都能覆盖。
 * 注意：只匹配**独立片段**，所以 mmoexpert / mmoexpo / MMOEXPfan2026 这类
 * 品牌词与其他词粘连在一起的名字**不会**被误伤。
 * ------------------------------------------------------------------------- */

/** a 删掉恰好 1 个字符后是否等于 b */
function dropOneChar(a, b) {
  if (a.length - b.length !== 1) return false;
  for (let i = 0; i < a.length; i++) {
    if (a.slice(0, i) + a.slice(i + 1) === b) return true;
  }
  return false;
}

/** 等长且恰好 1 个位置不同 */
function oneCharDiff(a, b) {
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) d++;
  return d === 1;
}

/** 片段匹配：命中返回 {tail, via, token}，否则 null */
function tokenMatch(rawName) {
  if (!state.config.brandTokenMatch) return null;
  const core = squash(canon(state.config.brandCore || 'mmoexp'));
  if (core.length < 4) return null;
  const fuzzy = Number(state.config.brandTokenFuzzy) || 0;
  const parts = canon(rawName).split(/[^a-z0-9]+/).filter(Boolean);
  for (const p of parts) {
    if (p.length < 4) continue;
    if (p === core) return { tail: '', via: 'token', token: p };
    if (fuzzy >= 1) {
      if (dropOneChar(core, p)) return { tail: '', via: 'token-approx', token: p };
      if (oneCharDiff(core, p)) return { tail: '', via: 'token-approx', token: p };
    }
  }
  return null;
}

/** 判断一个名字是否冒充官方。命中返回 {tail}，否则 null */
function classify(rawName) {
  const sq = squash(canon(rawName));
  if (sq.length < 6) return null;

  for (const token of state.config.extraStartsWith || []) {
    const t = squash(canon(token));
    if (t && sq.startsWith(t)) return { tail: sq.slice(t.length), via: 'extraStartsWith' };
  }

  // 片段式匹配（品牌词在任意位置的独立片段）—— 先于前缀正则，命中信息更准确
  const tk = tokenMatch(rawName);
  if (tk) return tk;

  const m = sq.match(new RegExp(state.config.brandPattern, 'i'));
  if (!m) return null;
  const tail = m[1] || '';

  if (state.config.matchMode === 'loose') return { tail, via: 'loose' };
  if (tail === '') return { tail, via: 'exact' };
  if (/^[0-9]+$/.test(tail)) return { tail, via: 'digits' };
  if (SUFFIX_OK.some((s) => tail.startsWith(s))) return { tail, via: 'suffix' };
  return null; // 例如 mmoexpert / mmoexpo，判为正常
}

/** 检查成员所有名字字段 */
function assessMember(member) {
  const fields = [
    ['用户名 username', member.user && member.user.username],
    ['全局显示名 globalName', member.user && member.user.globalName],
    ['服务器昵称 nickname', member.nickname],
    ['显示名 displayName', member.displayName],
  ];
  for (const [field, value] of fields) {
    if (!value) continue;
    const hit = classify(value);
    if (hit) return { field, value, tail: hit.tail, via: hit.via };
  }
  return null;
}

/** 白名单校验：返回豁免原因或 null */
function whitelisted(member) {
  if (member.id === member.client.user.id) return 'self';
  if (state.whitelist.userIds.includes(member.id)) return 'user-id';
  for (const rid of state.whitelist.roleIds) {
    if (member.roles && member.roles.cache.has(rid)) return 'role';
  }
  return null;
}

/* --------------------------------- 日志 ---------------------------------- */

async function log(client, lines, color) {
  const id = state.config.logChannelId;
  if (!id) return;
  try {
    const ch = await client.channels.fetch(id);
    if (!ch || !ch.isTextBased()) return;
    const embed = new EmbedBuilder()
      .setColor(color == null ? 0xd23f3f : color)
      .setTitle(lines.title)
      .setDescription(lines.body)
      .setTimestamp(new Date());
    if (lines.fields) embed.addFields(lines.fields);
    await ch.send({ embeds: [embed] });
  } catch (e) {
    console.warn('[WARN] 日志推送失败：', e.message);
  }
}

/* ======================= 状态自检报告（私信 / @提及 / 斜杠命令） =======================
 * 需求：给机器人发个消息，它就把「自己当前的状态与配置」回报出来。
 *
 * ⚠️ 为什么不需要开 Message Content Intent：
 *    Discord 官方文档（Message Content Intent Alternatives）明确列了三种**永远可用**的情况：
 *      · 发给机器人的私信（Messages received in DMs）
 *      · 机器人被 @ 提及的消息（Messages where the bot is @mentioned）
 *      · 机器人自己发的消息
 *    所以只要声明非特权的 DirectMessages intent（+ Partials.Channel 以便处理未缓存的私信频道）
 *    就能读到私信内容。**千万不要加特权的 MessageContent** —— 开发者后台没开它，
 *    代码里声明了会让网关直接以 4014「Used disallowed intents」断开，机器人起不来。
 *
 * ⚠️ 安全：报告只读机器人的内存态与 config.json，但**绝不包含 token**，
 *    并且**只回报给白名单内的人**（whitelistUserIds / whitelistRoleIds）。
 *    不在白名单的任何人私信机器人 —— **完全静默，一个字都不回**。
 *    为什么静默而不是回一句"无权限"：冒充者私信时，任何回复都是在给他反馈
 *    （等于告诉他"机器人是活的""我这个号还没被标记"）；静默不给任何信号，
 *    同时把这次探测按用户去重记进服务器日志，便于事后取证。
 * ========================================================================== */

function fmtDur(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const mi = Math.floor((s % 3600) / 60);
  const se = s % 60;
  if (d) return `${d} 天 ${h} 小时 ${mi} 分`;
  if (h) return `${h} 小时 ${mi} 分`;
  if (mi) return `${mi} 分 ${se} 秒`;
  return `${se} 秒`;
}

function isoNow() {
  return new Date().toISOString().replace('T', ' ').slice(0, 19) + 'Z';
}

/** 只把被命令改动的字段写回 config.json；保留 `_说明` 等注释键与 token 原值。 */
function persistConfig(patch) {
  let raw = {};
  try {
    raw = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
  } catch (e) {
    raw = {};
  }
  Object.assign(raw, patch);
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(raw, null, 2) + '\n', 'utf8');
  Object.assign(state.config, patch); // 顺带同步内存态
  return raw;
}

/** 生成状态自检报告（读实时内存态 + config.json 已加载值）。绝不包含 token。 */
async function buildReport(c) {
  const cfg = state.config;
  const wl = state.whitelist;
  const mem = process.memoryUsage();
  const g = (cfg.guildId && c.guilds.cache.get(cfg.guildId)) || c.guilds.cache.first() || null;

  let me = null;
  if (g) {
    me = g.members.me || null;
    if (!me) {
      try { me = await g.members.fetch(c.user.id); } catch (e) { me = null; }
    }
  }

  const roleName = (id) => {
    const r = g && g.roles.cache.get(id);
    return r ? `@${r.name}` : `\`${id}\``;
  };
  const userTag = (id) => {
    const u = c.users.cache.get(id);
    return u ? `${u.tag}` : '（缓存里没有该用户，仅 ID 有效）';
  };
  const cut = (s, n = 1024) => (String(s).length > n ? String(s).slice(0, n - 1) + '…' : String(s));

  const env =
    `Node \`${process.version}\`\n` +
    `discord.js \`${require('discord.js').version}\`\n` +
    `进程 PID \`${process.pid}\`\n` +
    `本次运行已持续 \`${fmtDur(Date.now() - state.stats.since)}\`\n` +
    `内存 RSS \`${(mem.rss / 1048576).toFixed(1)} MB\`\n` +
    `网关心跳 \`${c.ws && c.ws.ping >= 0 ? `${c.ws.ping} ms` : '尚未就绪'}\`\n` +
    `登录账号 \`${c.user.tag}\``;

  const serverTxt = g
    ? `\`${g.name}\`\n服务器 ID \`${g.id}\`\n成员数 \`${g.memberCount}\`\n` +
      `斜杠命令 \`${cfg.guildId === g.id ? '已注册到本服' : 'guildId 与本服不一致，命令可能不在本服'}\``
    : '（机器人当前不在任何服务器里）';

  const hierTxt =
    g && me && me.roles && me.roles.highest
      ? `机器人最高角色 \`${me.roles.highest.name}\`（位置 \`${me.roles.highest.position}\`）\n` +
        `服务器最高角色位置 \`${g.roles.highest.position}\`\n` +
        (me.roles.highest.position >= g.roles.highest.position
          ? '✅ 在最高位，理论上可处置任何成员'
          : `ℹ️ 只能处置最高角色位置 **低于 ${me.roles.highest.position}** 的成员（新加入、未领角色的成员通常在这个范围内）`)
      : '（读不到角色层级）';

  const ruleTxt = [
    `演练模式 dryRun：**${cfg.dryRun ? '🟡 开（只记录，不处置任何人）' : '🟢 关（会真的处置）'}**`,
    `处置动作 action：\`${cfg.action}\``,
    cfg.action === 'timeout' ? `禁言时长：\`${cfg.timeoutMinutes} 分钟\`` : null,
    `匹配模式 matchMode：\`${cfg.matchMode}\``,
    `品牌词正则：\`${cfg.brandPattern}\``,
    `片段匹配 brandTokenMatch：${cfg.brandTokenMatch === false ? '**关**' : `开（品牌词 \`${cfg.brandCore || 'mmoexp'}\` 以独立片段出现在名字任意位置即命中，容错 ${Number(cfg.brandTokenFuzzy) || 0} 个字符）`}`,
    `额外前缀 extraStartsWith：${(cfg.extraStartsWith || []).length ? cfg.extraStartsWith.map((x) => `\`${x}\``).join(' ') : '（空）'}`,
    `处置理由：\`${cfg.action === 'ban' ? cfg.banReason : cfg.kickReason}\``,
    `白名单成员命中时是否也告警：\`${cfg.alertOnWhitelistedHit ? '是' : '否'}\``,
  ]
    .filter(Boolean)
    .join('\n');

  const statTxt =
    `命中（判定为冒充）\`${state.stats.flagged}\`\n` +
    `踢出 \`${state.stats.kicked}\` ／ 封禁 \`${state.stats.banned}\` ／ 禁言 \`${state.stats.timeout}\`\n` +
    `统计起点 \`${new Date(state.stats.since).toISOString().replace('T', ' ').slice(0, 19)}Z\`（进程启动时归零）`;

  const h = state.stats.lastHit;
  const lastHitTxt = h
    ? `时间 \`${h.at}\`\n账号 \`${h.tag}\`（\`${h.id}\`）\n字段 \`${h.field}\` → 命中值 \`${h.value}\`\n判定 \`${h.via}\`　来源 \`${h.src}\`\n结果 **${h.outcome}**`
    : '（本次运行还没有命中记录）';

  const warns = [];
  if (!cfg.logChannelId) warns.push('未配置 **日志频道** —— 命中记录只会写进服务器 journal，你在 Discord 里看不到');
  if (!wl.roleIds.length && !wl.userIds.length) warns.push('**白名单为空** —— 直接上线会误伤真客服');
  if (cfg.dryRun) warns.push('**dryRun 开着** —— 现在只记录、不处置任何人（这是安全状态）');
  if (g && me && me.roles && me.roles.highest && me.roles.highest.position < g.roles.highest.position) {
    warns.push('机器人**角色不在最顶端** —— 层级高于它的成员（如 Admin）处置不了');
  }
  if ((cfg.extraStartsWith || []).length) warns.push('配了 `extraStartsWith` 额外前缀，确认它不是常用词，以免误伤');
  if (cfg.action === 'kick' && !cfg.dryRun) warns.push('action=kick —— 对方改个名就能再进来，对抗专业骗子建议用 ban');

  const embed = new EmbedBuilder()
    .setColor(!warns.length ? 0x3ba55d : cfg.dryRun ? 0x8a8f98 : 0xe0a24a)
    .setTitle('🛡️ MMOEXP GuardBot · 状态自检')
    .setDescription(
      '以下是从机器人**自己的内存与配置**里读出的实时状态（不是看板缓存快照）。\n' +
      `报告生成时间 \`${isoNow()}\``
    )
    .addFields(
      { name: '① 运行环境', value: cut(env), inline: true },
      { name: '② 连接与服务器', value: cut(serverTxt), inline: true },
      { name: '③ 角色层级', value: cut(hierTxt), inline: false },
      { name: '④ 当前处置规则', value: cut(ruleTxt), inline: false },
      { name: '⑤ 日志频道', value: cfg.logChannelId ? `<#${cfg.logChannelId}>` : '**未配置** ⚠️', inline: true },
      { name: '⑥ 本次运行统计', value: cut(statTxt), inline: true },
      { name: '⑦ 最近一次命中', value: cut(lastHitTxt), inline: false },
      { name: '⑧ 白名单角色', value: cut(wl.roleIds.length ? wl.roleIds.map(roleName).join('\n') : '（空）'), inline: true },
      { name: '⑨ 白名单用户', value: cut(wl.userIds.length ? wl.userIds.map(userTag).join('\n') : '（空）'), inline: true }
    )
    .setFooter({ text: warns.length ? `体检：有 ${warns.length} 项待处理 —— 见下方` : '体检：未发现待处理项' })
    .setTimestamp(new Date());

  if (warns.length) {
    embed.addFields({ name: '⑩ 体检提醒', value: cut(warns.map((w) => `• ${w}`).join('\n')), inline: false });
  }
  return embed;
}

/** 是否获准自检：**只认白名单**（用户 ID 或角色）。其余一律拒绝。
 *
 * 设计说明（按要求收紧）：
 *   早先版本还放行「服务器拥有者」与「拥有『管理服务器』权限者」，
 *   现在**两条都取消** —— 只有白名单里的人能拿到报告。
 *   理由：冒充者也在同一个服务器里，用权限位判定对他们可能意外为真；
 *   而"我们自己人"是一份明确的名单，用名单说话最可控。
 */
async function operatorCheck(c, userId) {
  const cfg = state.config;

  // ① 白名单用户 ID：最快路径，不需要查服务器成员
  if (state.whitelist.userIds.includes(userId)) {
    return { ok: true, via: '在白名单用户内' };
  }

  if (!cfg.guildId) return { ok: false, reason: '尚未配置 guildId，无法核验角色' };

  // ② 白名单角色：必须先把用户解析成服务器成员，才能看他的角色
  let g;
  try {
    g = await c.guilds.fetch(cfg.guildId);
  } catch (e) {
    return { ok: false, reason: `读不到服务器 ${cfg.guildId}` };
  }
  const m = await g.members.fetch(userId).catch(() => null);
  if (!m) return { ok: false, reason: `不是 ${g.name} 的成员` };
  if (m.roles && m.roles.cache.some((r) => state.whitelist.roleIds.includes(r.id))) {
    return { ok: true, via: '持有白名单角色' };
  }
  return { ok: false, reason: `不在 ${g.name} 的白名单内` };
}

/* 未获授权者**完全静默**：一个字都不回。
 * 只按用户去重写服务器日志（同一个人 10 分钟内只记一次），避免被刷屏；
 * 日志只落在服务器 journal 里，**不在 Discord 产生任何可见痕迹**。 */
const _probeLog = new Map();
function shouldLogProbe(userId) {
  const now = Date.now();
  const last = _probeLog.get(userId) || 0;
  if (now - last < 10 * 60 * 1000) return false;
  if (_probeLog.size > 500) _probeLog.clear(); // 简单封顶，防内存无限增长
  _probeLog.set(userId, now);
  return true;
}

/** 私信 / @提及 的统一入口 */
async function handleSelfCheck(c, msg, via) {
  const gate = await operatorCheck(c, msg.author.id);
  if (!gate.ok) {
    // 🚫 不在白名单：完全静默（连"无权限"都不回），不给冒充者任何反馈或信息
    if (shouldLogProbe(msg.author.id)) {
      console.log(
        `[SELFCHECK] 静默忽略 via=${via} user=${msg.author.tag} (${msg.author.id}) —— ${gate.reason || '不在白名单内'}`
      );
    }
    return;
  }

  // 只有通过门禁才给"正在处理"的输入指示；未授权者连 typing 这种可见信号都不给
  if (via === 'dm' && msg.channel && typeof msg.channel.sendTyping === 'function') {
    msg.channel.sendTyping().catch(() => {});
  }

  const embed = await buildReport(c);
  try {
    if (via === 'mention') {
      // 群里 @ 机器人：报告走私信，避免把配置细节发到公开频道
      await msg.author.send({ embeds: [embed] });
      await msg
        .reply({ content: `📬 状态报告已私信给你（身份核验：${gate.via}）。`, allowedMentions: { repliedUser: false } })
        .catch(() => {});
    } else {
      await msg.reply({ embeds: [embed] });
    }
    console.log(`[SELFCHECK] 回报 via=${via} user=${msg.author.tag} (${msg.author.id}) 身份=${gate.via}`);
  } catch (e) {
    console.error('[SELFCHECK] 回报失败：', e.message);
    // 能走到这里的一定是白名单成员；提示里不带原始错误串，避免把内部信息带进频道
    await msg
      .reply({
        content:
          '❌ 报告发送失败。群里 @ 机器人时报告是私信发你的 —— 若你关闭了「允许服务器成员私信」，请改成直接私聊机器人。',
        allowedMentions: { repliedUser: false },
      })
      .catch(() => {});
  }
}

/* ------------------------------ 处置执行 --------------------------------- */

/** 官方管理组硬保护：带 Administrator 权限的成员一律不处理（例如 `Admin` 角色）。
 *  这条**与白名单无关** —— 即使有人把 Admin 从白名单里删掉、或把机器人角色
 *  拖到 Admin 之上，这里依然会拦住。老板明确要求：Admin 是我们自己管理的身份组。 */
function isProtectedAdmin(member) {
  return !!(member && member.permissions && member.permissions.has(PermissionFlagsBits.Administrator));
}

async function canActOn(member) {
  const me = member.guild.members.me;
  if (!me) return '机器人自身成员对象不可用';
  if (member.id === member.guild.ownerId) return '目标是服务器拥有者';
  if (member.id === me.id) return '目标是机器人自己';
  if (isProtectedAdmin(member)) return '目标是官方管理组（带 Administrator 权限，硬保护不处理）';
  if (me.roles.highest.comparePositionTo(member.roles.highest) <= 0) {
    return '机器人身份组层级不够高（把机器人角色拖到最上面）';
  }
  return null;
}

/* ---------------------------- 处置留痕 / 取证 ---------------------------- */

/** 把「命中字段 + 命中值」拼进 Discord 审计理由。
 *  为什么要这么做：Discord 的审计日志只保留 `reason` 一栏，且**不可事后编辑**；
 *  实测有人被封后立刻把用户名改回随机串（如 captivating_beagle_38232），
 *  事后翻 Audit Log / 封禁名单只能看到「很正常」的账号名，完全查不出为什么被封。
 *  把命中值写进 reason，封禁那一刻的名字就永久钉在审计日志上。
 *  Discord reason 上限 512 字符 → 这里截到 400 留余量。 */
function reasonWithHit(base, hit) {
  const key = (hit.field || '').split(' ').pop() || 'name';
  return `${base || ''} [${key}=${hit.value}]`.slice(0, 400);
}

/** 处置瞬间的名字快照 —— 对方事后改名也能还原「当时叫什么」。 */
function snapshotNames(member) {
  return {
    username: (member.user && member.user.username) || null,
    global_name: (member.user && member.user.globalName) || null,
    nickname: member.nickname || null,
    display_name: member.displayName || null,
  };
}

/** 本地台账（append-only JSONL）。写失败只告警，绝不影响处置主流程。 */
function appendLedger(rec) {
  try {
    fs.appendFileSync(LEDGER_PATH, JSON.stringify(rec) + '\n', { mode: 0o644 });
  } catch (e) {
    console.warn('[WARN] 台账写入失败（不影响处置）：', e.message);
  }
}

async function act(member, reason) {
  const mode = state.config.action;
  if (mode === 'none') return 'none(仅记录)';
  if (mode === 'ban') {
    await member.ban({ reason, deleteMessageSeconds: 0 });
    state.stats.banned++;
    return 'ban(封禁)';
  }
  if (mode === 'timeout') {
    await member.timeout((state.config.timeoutMinutes || 10080) * 60 * 1000, reason);
    state.stats.timeout++;
    return 'timeout(禁言)';
  }
  await member.kick(reason);
  state.stats.kicked++;
  return 'kick(踢出)';
}

/** 主流程：评估 + 处置 */
async function handle(member, source) {
  const at = new Date().toISOString();
  if (!member || !member.guild) return;
  if (member.user && member.user.bot) return;
  // 🛡️ 官方管理组（带 Administrator 权限）硬保护：不看名字、不计命中、不处置
  if (isProtectedAdmin(member)) return;

  const hit = assessMember(member);
  if (!hit) return;

  const wl = whitelisted(member);
  const who = `${member.user.tag}  (\`${member.id}\`)`;
  const ageDays = Math.floor((Date.now() - member.user.createdTimestamp) / 86400000);

  if (wl) {
    if (state.config.alertOnWhitelistedHit) {
      await log(member.client, {
        title: '白名单成员命中前缀（已豁免）',
        body: `${who}\n字段：\`${hit.field}\`  命中值：\`${hit.value}\`\n豁免依据：\`${wl}\`  来源：\`${source}\``,
      }, 0xe0a24a);
    }
    return;
  }

  state.stats.flagged++;
  const block = await canActOn(member);
  const planned = state.config.action;

  /** 记一笔「最近一次命中」，供状态自检报告展示 */
  const noteHit = (outcome) => {
    state.stats.lastHit = {
      at: at.replace('T', ' ').slice(0, 19) + 'Z',
      id: member.id,
      tag: member.user.tag,
      field: hit.field,
      value: hit.value,
      via: hit.via,
      src: source,
      outcome,
    };
  };

  if (state.config.dryRun || block) {
    noteHit(state.config.dryRun ? 'DRY-RUN 未处置' : `被阻塞（${block}）`);
    await log(member.client, {
      title: state.config.dryRun ? '【DRY-RUN】命中冒充前缀（未处置）' : '命中冒充前缀但无法处置',
      body: `${who}\n字段：\`${hit.field}\`  命中值：\`${hit.value}\`\n判定：\`${hit.via}\`  计划动作：\`${planned}\`  来源：\`${source}\`` +
        (block ? `\n⚠️ 阻塞原因：**${block}**` : '') +
        (state.config.dryRun ? '\n\n（当前 dryRun=true，只记录不动作。确认无误后改为 false 上线）' : ''),
      fields: [{ name: '账号创建于', value: `${ageDays} 天前`, inline: true }],
    }, state.config.dryRun ? 0x8a8f98 : 0xd23f3f);
    console.log(`[${at}] ${state.config.dryRun ? 'DRY-RUN ' : 'BLOCKED '}${hit.field}="${hit.value}" user=${member.user.tag} (${member.id}) ${block || ''}`);
    return;
  }

  try {
    const reason = reasonWithHit(planned === 'ban' ? state.config.banReason : state.config.kickReason, hit);
    const done = await act(member, reason);
    noteHit(done);
    const snap = snapshotNames(member);
    console.log(
      `[${at}] ACTION ${done} user=${member.user.tag} (${member.id}) field=${hit.field} value="${hit.value}" ` +
      `via=${hit.via} src=${source} names=${JSON.stringify(snap)} reason="${reason}"`
    );
    appendLedger({
      ts: at,
      action: done,
      user_id: member.id,
      tag: member.user.tag,
      ...snap,
      field: hit.field,
      value: hit.value,
      via: hit.via,
      src: source,
      reason,
    });
    await log(member.client, {
      title: '已处置：冒充官方前缀',
      body: `${who}\n字段：\`${hit.field}\`  命中值：\`${hit.value}\`\n判定：\`${hit.via}\`  动作：**${done}**  来源：\`${source}\`` +
        `\n\n**处置时的名字**\n用户名：\`${snap.username}\`　全局显示名：\`${snap.global_name || '（无）'}\`　服务器昵称：\`${snap.nickname || '（无）'}\`` +
        `\n写入审计日志的理由：\`${reason}\``,
      fields: [{ name: '账号创建于', value: `${ageDays} 天前`, inline: true }],
    }, 0x3ba55d);
  } catch (e) {
    console.error(`[ERROR] 处置失败 user=${member.user.tag}：`, e.message);
    await log(member.client, {
      title: '处置失败（需人工处理）',
      body: `${who}\n字段：\`${hit.field}\`  命中值：\`${hit.value}\`\n错误：\`${e.message}\``,
    }, 0xd23f3f);
  }
}

/* ------------------------------ 客户端启动 ------------------------------- */

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMembers, // 特权 intent：需要在开发者后台打开 SERVER MEMBERS INTENT
    // 非特权 intent：为了能收到「私信机器人」的消息（状态自检用）。
    // 私信内容不受 Message Content 特权 intent 限制（Discord 官方明确豁免），
    // 所以这里**不需要**、也**不应该**加 GatewayIntentBits.MessageContent。
    GatewayIntentBits.DirectMessages,
  ],
  // 私信频道默认不在缓存里，不声明 Channel partial 的话 messageCreate 可能收不到 DM。
  partials: [Partials.Channel],
});

client.once(Events.ClientReady, async (c) => {
  console.log(`\n✅ 已登录：${c.user.tag}  (id=${c.user.id})`);
  console.log(`已加入服务器：${c.guilds.cache.map((g) => `${g.name}(${g.id})`).join(', ') || '（尚未被邀请进任何服务器）'}`);
  if (!state.config.guildId) {
    console.log('ℹ️  未配置 guildId，本次跳过斜杠命令注册（核心防护不依赖命令）。填入 guildId 后重启即可注册。');
  } else {
    try {
      const cmds = buildCommands();
      const rest = new REST({ version: '10' }).setToken(state.config.token);
      await rest.put(Routes.applicationGuildCommands(c.user.id, state.config.guildId), { body: cmds });
      console.log(`✅ 已注册 ${cmds.length} 条斜杠命令到服务器 ${state.config.guildId}`);
    } catch (e) {
      console.warn('[WARN] 斜杠命令注册失败（不影响核心防护）：', e.message);
    }
  }
  console.log(`模式：${state.config.dryRun ? 'DRY-RUN（只记录）' : '正式处置'}  动作：${state.config.action}  匹配：${state.config.matchMode}`);
  console.log(`白名单：角色 ${state.whitelist.roleIds.length} 个 / 用户 ${state.whitelist.userIds.length} 个`);

  // intent 自检：直接反映「私信到底收不收得到」。MessageContent 应当恒为 false ——
  // 它是特权 intent，开发者后台没开时声明了会让网关以 4014 断连。
  const I = client.options.intents;
  console.log(
    '网关注册的 intent：' +
    `Guilds=${I.has(GatewayIntentBits.Guilds)} ` +
    `GuildMembers=${I.has(GatewayIntentBits.GuildMembers)}(特权) ` +
    `DirectMessages=${I.has(GatewayIntentBits.DirectMessages)} ` +
    `MessageContent=${I.has(GatewayIntentBits.MessageContent)}(特权，须为 false) ` +
    `| partials=${(client.options.partials || []).join(',') || '无'}`
  );
  console.log('状态自检已开启：私信机器人 / 在服务器里 @机器人 / 用 /guard-status，均可回报状态与配置\n');
});

client.on(Events.GuildMemberAdd, (m) => handle(m, 'join'));
client.on(Events.GuildMemberUpdate, async (oldM, newM) => {
  const changed =
    oldM.nickname !== newM.nickname ||
    (oldM.user && newM.user && oldM.user.globalName !== newM.user.globalName) ||
    (oldM.user && newM.user && oldM.user.username !== newM.user.username);
  if (changed) await handle(newM, 'rename');
});
client.on(Events.UserUpdate, async (oldU, newU) => {
  if (oldU.username === newU.username && oldU.globalName === newU.globalName) return;
  if (!state.config.guildId) return;
  try {
    const guild = await client.guilds.fetch(state.config.guildId);
    const member = await guild.members.fetch(newU.id);
    await handle(member, 'global-rename');
  } catch (e) { /* 不在本服务器，忽略 */ }
});

/* --------------------- 状态自检：私信 / @提及 触发 ----------------------- */

client.on(Events.MessageCreate, async (msg) => {
  try {
    if (!msg || !msg.author || msg.author.bot) return;
    if (!client.user || msg.author.id === client.user.id) return;

    const isDM = !msg.guildId;
    const mentioned = !isDM && !!(msg.mentions && msg.mentions.users.has(client.user.id));

    // 群里必须真的 @ 到机器人；私信则任何一条消息都算（方便随手测试）
    if (!isDM && !mentioned) return;

    // 注意：typing 指示不在这一层发 —— 未通过白名单门禁的人不该收到任何可见信号，
    // 所以 sendTyping 挪到了 handleSelfCheck() 门禁通过之后。
    await handleSelfCheck(client, msg, isDM ? 'dm' : 'mention');
  } catch (e) {
    console.error('[SELFCHECK] 处理异常：', e);
  }
});

/* ----------------------------- 斜杠命令 ---------------------------------- */

function buildCommands() {
  const perm = PermissionFlagsBits.ManageGuild;

  const scan = new SlashCommandBuilder()
    .setName('guard-scan')
    .setDescription('扫描当前服务器所有成员，列出命中冒充前缀的账号（不处置）')
    .setDefaultMemberPermissions(perm);

  const purge = new SlashCommandBuilder()
    .setName('guard-purge')
    .setDescription('对当前存量成员执行处置（白名单自动跳过）')
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator)
    .addBooleanOption((o) => o.setName('confirm').setDescription('必须填 true 才会真的执行').setRequired(true))
    .addBooleanOption((o) => o.setName('force').setDescription('忽略 dryRun 开关，强制真踢'));

  const check = new SlashCommandBuilder()
    .setName('guard-check')
    .setDescription('检查某个用户是否会被判定为冒充')
    .setDefaultMemberPermissions(perm)
    .addUserOption((o) => o.setName('user').setDescription('要检查的用户').setRequired(true));

  const wl = new SlashCommandBuilder()
    .setName('guard-whitelist')
    .setDescription('管理白名单')
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator)
    .addStringOption((o) =>
      o.setName('action').setDescription('操作').setRequired(true)
        .addChoices(
          { name: 'list 查看', value: 'list' },
          { name: 'add 添加', value: 'add' },
          { name: 'remove 移除', value: 'remove' },
        ))
    .addStringOption((o) =>
      o.setName('type').setDescription('类型：user 用户 / role 角色').setRequired(false)
        .addChoices({ name: 'user 用户', value: 'user' }, { name: 'role 角色', value: 'role' }))
    .addStringOption((o) => o.setName('id').setDescription('用户ID 或 角色ID').setRequired(false));

  const dry = new SlashCommandBuilder()
    .setName('guard-dryrun')
    .setDescription('切换 DRY-RUN（只记录不处置）开关')
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator)
    .addBooleanOption((o) => o.setName('enabled').setDescription('true=只记录，false=正式处置').setRequired(true));

  const status = new SlashCommandBuilder()
    .setName('guard-status')
    .setDescription('状态自检：回报实时运行状态与当前配置（也可私信机器人或 @ 机器人）')
    .setDefaultMemberPermissions(perm);

  return [scan, purge, check, wl, dry, status].map((c) => c.toJSON());
}

client.on(Events.InteractionCreate, async (i) => {
  if (!i.isChatInputCommand()) return;
  const cfg = state.config;

  try {
    if (i.commandName === 'guard-status') {
      const embed = await buildReport(client);
      return i.reply({ embeds: [embed], flags: MessageFlags.Ephemeral });
    }

    if (i.commandName === 'guard-check') {
      const u = i.options.getUser('user', true);
      const m = await i.guild.members.fetch(u.id).catch(() => null);
      if (!m) return i.reply({ content: '该用户不在本服务器。仅按名字判断：', flags: MessageFlags.Ephemeral });
      const hit = assessMember(m);
      const wl = whitelisted(m);
      const txt = hit
        ? `⚠️ 会命中：字段 \`${hit.field}\`，值 \`${hit.value}\`（判定 ${hit.via}）${wl ? `\n✅ 但已在白名单（${wl}），不会处置` : '\n🔴 不在白名单，会被处置'}`
        : '✅ 不会命中冒充前缀规则';
      return i.reply({ content: `<@${u.id}>  ${txt}`, flags: MessageFlags.Ephemeral });
    }

    if (i.commandName === 'guard-whitelist') {
      const action = i.options.getString('action', true);
      const type = i.options.getString('type');
      const rawId = i.options.getString('id');

      if (action === 'list') {
        const r = state.whitelist.roleIds.length ? state.whitelist.roleIds.map((x) => `<@&${x}>`).join('\n') : '（无）';
        const u = state.whitelist.userIds.length ? state.whitelist.userIds.map((x) => `<@${x}> (\`${x}\`)`).join('\n') : '（无）';
        return i.reply({ content: `**白名单角色**\n${r}\n\n**白名单用户**\n${u}`, flags: MessageFlags.Ephemeral });
      }

      if (!type || !rawId) return i.reply({ content: '❌ 需要同时提供 type 和 id', flags: MessageFlags.Ephemeral });
      const id = rawId.replace(/[<@&>!]/g, '').trim();
      if (!/^\d{15,25}$/.test(id)) return i.reply({ content: '❌ ID 格式不对（应为纯数字）', flags: MessageFlags.Ephemeral });

      const bucket = type === 'role' ? state.whitelist.roleIds : state.whitelist.userIds;
      const idx = bucket.indexOf(id);
      if (action === 'add') {
        if (idx >= 0) return i.reply({ content: '已在白名单中。', flags: MessageFlags.Ephemeral });
        bucket.push(id); saveWhitelist();
        return i.reply({ content: `✅ 已加入白名单：${type === 'role' ? `<@&${id}>` : `<@${id}>`}`, flags: MessageFlags.Ephemeral });
      }
      if (idx < 0) return i.reply({ content: '不在白名单中。', flags: MessageFlags.Ephemeral });
      bucket.splice(idx, 1); saveWhitelist();
      return i.reply({ content: `✅ 已移出白名单：\`${id}\``, flags: MessageFlags.Ephemeral });
    }

    if (i.commandName === 'guard-dryrun') {
      const enabled = i.options.getBoolean('enabled', true);
      // ⚠️ 必须落盘！早期版本只改内存，重启后会静默回退 ——
      // 若有人用它开 dryRun「刹车」，重启就变回正式处置，方向是危险的。
      try {
        persistConfig({ dryRun: enabled });
      } catch (e) {
        return i.reply({ content: `❌ 写入 config.json 失败，为避免重启后状态不一致，本次未生效：\`${e.message}\`` });
      }
      return i.reply({
        content:
          `模式已切换为：${enabled ? '🟡 DRY-RUN（只记录）' : '🟢 正式处置（会真的踢人！）'}\n` +
          `✅ 已写入 \`config.json\`（重启后保持），当前处置动作 \`${state.config.action}\`。`,
        flags: MessageFlags.Ephemeral,
      });
    }

    if (i.commandName === 'guard-scan' || i.commandName === 'guard-purge') {
      const isPurge = i.commandName === 'guard-purge';
      if (isPurge && i.options.getBoolean('confirm', true) !== true) {
        return i.reply({ content: '❌ 需要 confirm=true', flags: MessageFlags.Ephemeral });
      }
      const force = isPurge ? !!i.options.getBoolean('force') : false;
      await i.deferReply({ flags: MessageFlags.Ephemeral });

      const members = await i.guild.members.fetch();
      const hits = [];
      const skipped = [];
      for (const m of members.values()) {
        if (m.user.bot) continue;
        if (isProtectedAdmin(m)) continue; // 🛡️ 官方管理组硬保护：连扫都不扫
        const hit = assessMember(m);
        if (!hit) continue;
        const wl = whitelisted(m);
        if (wl) { skipped.push({ m, hit, wl }); continue; }
        hits.push({ m, hit });
      }

      const listTxt = hits.slice(0, 40).map((h) => `<@${h.m.id}> \`${h.m.user.tag}\` — ${h.hit.field}: \`${h.hit.value}\``).join('\n') || '（无）';
      let result = `**扫描完成**（共 ${members.size} 名成员）\n命中 ${hits.length} 个 / 白名单豁免 ${skipped.length} 个\n\n${listTxt}`;

      if (isPurge && hits.length) {
        const reallyRun = force || !state.config.dryRun;
        if (!reallyRun) {
          result += `\n\n🟡 当前 dryRun=true，未执行处置。加 \`force:true\` 可强制执行。`;
        } else {
          let ok = 0, fail = 0;
          for (const h of hits) {
            try {
              const blocked = await canActOn(h.m);
              if (blocked) { fail++; continue; }
              await act(h.m, '存量清理：名称冒充 MMOEXP 官方');
              ok++;
              await new Promise((r) => setTimeout(r, 350)); // 轻微限速，避免触发风控
            } catch (e) { fail++; }
          }
          result += `\n\n🟢 已处置 ${ok} 个（失败 ${fail}）`;
        }
      }
      return i.editReply({ content: result.slice(0, 1900) });
    }
  } catch (e) {
    console.error('[ERROR] 命令处理失败：', e);
    if (i.deferred) i.editReply({ content: '❌ 执行出错：' + e.message }).catch(() => {});
    else i.reply({ content: '❌ 执行出错：' + e.message, flags: MessageFlags.Ephemeral }).catch(() => {});
  }
});

/* --------------------------------- 入口 ---------------------------------- */

function main() {
  const cfg = loadConfig();
  if (!cfg.token || cfg.token.includes('在这里')) {
    console.error('[FATAL] 请先把 config.json 里的 token 填上（Discord 开发者后台 → Bot → Reset Token）。');
    process.exit(1);
  }
  client.login(cfg.token).catch((e) => {
    console.error('[FATAL] 登录失败：', e.message);
    console.error('常见原因：token 填错 / 没在开发者后台开启 SERVER MEMBERS INTENT。');
    process.exit(1);
  });
}

if (require.main === module) main();

process.on('unhandledRejection', (e) => console.error('[unhandledRejection]', e));

module.exports = {
  canon, squash, classify, assessMember, loadConfig, state, DEFAULTS,
  client, // 真实 discord.js 客户端实例（供单测投递合成事件）
  handle, canActOn, isProtectedAdmin, // 处置主流程（供单测验证 dryRun 硬闸与 Admin 硬保护）
  // 状态自检（供单测直接调用，不触发登录）
  buildReport, handleSelfCheck, operatorCheck, fmtDur, persistConfig,
};
