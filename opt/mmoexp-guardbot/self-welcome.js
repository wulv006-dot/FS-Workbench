'use strict';
/* 欢迎（参考 AION2 shugo-bot 逻辑）
 * - 新人进服 → **私信**一张欢迎卡（只有本人能看到，频道里一条都不发）
 * - 私信被挡（关了服务器成员私信）→ 记 not_delivered，不公开、不刷屏
 * - #👋・welcome 只留一张置顶引导卡，点「Choose Roles」→ ephemeral 选游戏身份组
 * - 数据读写走 secure-storage（与 privacy 模块同一把密钥），读不到就安全降级，绝不让进程崩
 */
const rawfs = require('fs');
const path = require('path');
const { Events, MessageFlags } = require('discord.js');
const { entries, installNavigation } = require('./welcome-navigation.js');

const CFG_FILE = path.join(__dirname, 'welcome-config.json');

/* 与 privacy 模块共用加密存储；密钥缺失时退回普通 fs */
let io = rawfs;
try {
  const lib = require('./secure-storage.js');
  const keyFile = process.env.GUARD_PRIVACY_KEY_FILE || '/etc/mmoexp-guardbot/data.key';
  io = lib.createStorage({ root: __dirname, keyFile, enforce: false });
} catch (e) {
  console.error('[WELCOME] secure-storage 不可用，退回普通 fs:', e.message);
}

function loadCfg() {
  try {
    return JSON.parse(io.readFileSync(CFG_FILE, 'utf8'));
  } catch (e) {
    return JSON.parse(rawfs.readFileSync(CFG_FILE, 'utf8'));
  }
}

const link = (cfg, id) => `https://discord.com/channels/${cfg.guildId}/${id}`;

function ordinal(n) {
  if (10 <= n % 100 && n % 100 <= 20) return n + 'th';
  return n + ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
}

/* 私信卡：与 shugo-bot 的 DM welcome 同构（缩略图、序号、直达链接） */
function dmPayload(cfg, member) {
  const name = member.displayName || member.user?.globalName || member.user?.username || 'there';
  const n = member.guild?.memberCount || 0;
  const e = {
    title: '🎮 Welcome to MMOEXP Official Club!',
    description: `Hey **${name}**, welcome aboard! 👋\n\n` +
      '**Your game. Your squad. Your next adventure.** ✨\n\n' +
      (n ? `You're our **${ordinal(n)}** member. ` : '') +
      'Grab your game badges, meet fellow players, and make yourself at home — your next stop is one click away! 🚀',
    color: 0xF28C28,
    fields: [
      { name: '🎭 Pick your games', value: 'Open **#👋・welcome** and press **Choose Roles**, tick every game you play, then **Save Games**. You can change this anytime.', inline: false },
      { name: '🎧 Need a hand?', value: 'Order questions or need help? Our support team answers in tickets.', inline: false },
      { name: '📜 Before you jump in', value: `Take a moment to read <#${cfg.rulesChannelId}>. Keep it friendly and enjoy the community!`, inline: false }
    ],
    footer: { text: '🛡️ Stay safe • Our team will never ask for your password in DMs • Use /privacy for data deletion' }
  };
  const icon = member.guild?.iconURL?.({ size: 128 });
  if (icon) e.thumbnail = { url: icon };
  return {
    embeds: [e],
    components: [
      { type: 1, components: [
        { type: 2, style: 5, label: 'Choose game roles', emoji: { name: '🎭' }, url: link(cfg, cfg.channelId) },
        { type: 2, style: 5, label: 'Read rules', emoji: { name: '📜' }, url: link(cfg, cfg.rulesChannelId) },
        { type: 2, style: 5, label: 'Contact support', emoji: { name: '🎧' }, url: link(cfg, cfg.supportChannelId) }
      ] }
    ],
    allowedMentions: { parse: [] }
  };
}

/* 频道里那张常驻引导卡（无个人信息） */
function panelPayload(cfg) {
  return {
    content: '**👋 Welcome to MMOEXP Official Club**\n\n' +
      'Your welcome card was sent to your **DMs**. Press **Choose Roles** below to pick the games you play.\n' +
      '> 🔒 Keep DMs from server members open so our welcome can reach you.',
    components: entries(cfg),
    embeds: [],
    allowedMentions: { parse: [] }
  };
}

function createWelcome({ cfg, directory, canWelcome = () => true, now = () => Date.now() }) {
  try { io.mkdirSync(directory, { recursive: true }); } catch (e) { rawfs.mkdirSync(directory, { recursive: true }); }
  const ledger = path.join(directory, 'welcome-delivery.jsonl');
  const seen = new Set();
  try {
    if (rawfs.existsSync(ledger)) {
      for (const line of io.readFileSync(ledger, 'utf8').split('\n').filter(Boolean)) {
        try { const row = JSON.parse(line); if (row.key) seen.add(row.key); } catch (e) { /* 跳过坏行 */ }
      }
    }
  } catch (e) {
    console.warn('[WELCOME] 读台账失败（继续运行）:', e.message);
  }
  const record = (row) => {
    try { io.appendFileSync(ledger, JSON.stringify({ ...row, at: now() }) + '\n', { mode: 0o600 }); }
    catch (e) { console.warn('[WELCOME] 台账写入失败:', e.message); }
  };

  async function joined(member) {
    if (!cfg.enabled || member?.guild?.id !== cfg.guildId || !member.user || member.user.bot || !canWelcome(member)) return false;
    const stamp = member.joinedTimestamp;
    if (!Number.isSafeInteger(stamp) || stamp <= 0) return false;
    const key = `${member.id}:${stamp}`;
    if (seen.has(key)) return false;
    record({ key, status: 'reserved' }); seen.add(key);   // 先占位，未知结果绝不自动重发
    try {
      const sent = await member.send(dmPayload(cfg, member));
      record({ key, status: 'sent', messageId: sent.id });
      console.log('[WELCOME] DM OK -> %s (%s)', member.user.username, member.id);
      return true;
    } catch (error) {
      record({ key, status: 'not_delivered', code: String(error.code || 'unknown') });
      console.warn('[WELCOME] DM 未送达（对方关了成员私信）；不公开兜底。code=%s user=%s', error.code || 'unknown', member.id);
      return false;
    }
  }

  /* 频道面板已改用 navigation 的 Choose Roles 按钮；这里只留旧按钮的兜底提示 */
  async function interact(i) {
    if (!cfg.enabled || !i.isButton?.() || i.customId !== 'mmoexp:selfwelcome:v1') return false;
    if (i.guildId !== cfg.guildId || i.user?.bot) return false;
    await i.reply({ content: 'Your welcome card is in your DMs. Press **Choose Roles** to pick your games.', flags: MessageFlags.Ephemeral, allowedMentions: { parse: [] } });
    return true;
  }

  function forget(userId) {
    if (userId) for (const key of seen) if (key.startsWith(String(userId) + ':')) seen.delete(key);
    try {
      if (!userId || !rawfs.existsSync(ledger)) return;
      const rows = io.readFileSync(ledger, 'utf8').split('\n').filter(Boolean)
        .filter((line) => { try { const r = JSON.parse(line); return String(r.key || '').split(':')[0] !== String(userId) && r.userId !== String(userId); } catch (e) { return false; } });
      io.writeFileSync(ledger, rows.length ? rows.join('\n') + '\n' : '', { mode: 0o600 });
    } catch (e) {
      console.warn('[WELCOME] forget 失败:', e.message);
    }
  }

  async function ensurePanel(client) {
    if (!cfg.enabled) return;
    const marker = path.join(directory, 'welcome-panel.json');
    const channel = await client.channels.fetch(cfg.channelId);
    if (channel?.guild?.id !== cfg.guildId) throw new Error('Welcome channel guild mismatch');
    const payload = panelPayload(cfg);
    if (rawfs.existsSync(marker)) {
      const saved = JSON.parse(io.readFileSync(marker, 'utf8'));
      if (saved.channelId !== cfg.channelId || saved.status !== 'published') throw new Error('Reconcile welcome panel marker');
      const message = await channel.messages.fetch(saved.messageId);
      if (message.author.id !== client.user.id) throw new Error('Welcome panel author mismatch');
      await message.edit(payload);
      return;
    }
    io.writeFileSync(marker, JSON.stringify({ status: 'sending', channelId: cfg.channelId }), { mode: 0o600 });
    const message = await channel.send(payload);
    io.writeFileSync(marker, JSON.stringify({ status: 'published', channelId: cfg.channelId, messageId: message.id }), { mode: 0o600 });
  }

  return { joined, interact, forget, ensurePanel };
}

function install(client, { canWelcome } = {}) {
  let cfg;
  try {
    cfg = loadCfg();
  } catch (e) {
    console.error('[WELCOME] 读取 welcome-config.json 失败，欢迎模块停用（进程不退出）:', e.message);
    return { joined: async () => false, interact: async () => false, forget() {}, ensurePanel: async () => {} };
  }
  try {
    if (cfg.guildId !== '1041923524601851914' || cfg.channelId !== '1569198390107971795') throw new Error('Unapproved welcome route');
    installNavigation(client, cfg);
    const welcome = createWelcome({ cfg, directory: path.join(__dirname, 'welcome-state'), canWelcome });
    client.on(Events.GuildMemberAdd, (m) => welcome.joined(m).catch((e) => console.error('[WELCOME] join', e.message)));
    client.on(Events.InteractionCreate, (i) => welcome.interact(i).catch((e) => console.error('[WELCOME] interaction', e.message)));
    client.once(Events.ClientReady, () => welcome.ensurePanel(client).catch((e) => console.error('[WELCOME] panel', e.message)));
    return welcome;
  } catch (e) {
    console.error('[WELCOME] 初始化失败，欢迎模块停用（进程不退出）:', e.message);
    return { joined: async () => false, interact: async () => false, forget() {}, ensurePanel: async () => {} };
  }
}

module.exports = { dmPayload, panelPayload, createWelcome, install };
