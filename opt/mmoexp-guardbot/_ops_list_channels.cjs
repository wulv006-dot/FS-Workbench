'use strict';
/* 列出服务器的文本/公告频道，挑出像"日志频道"的候选，供配置 logChannelId 用。只读。 */
const mod = require('/opt/mmoexp-guardbot/index.js');
mod.loadConfig();
const cfg = mod.state.config;
const H = { Authorization: 'Bot ' + String(cfg.token).trim() };

(async () => {
  const r = await fetch(`https://discord.com/api/v10/guilds/${cfg.guildId}/channels`, { headers: H });
  if (!r.ok) throw new Error(r.status + ' ' + (await r.text()).slice(0, 200));
  const chs = await r.json();
  const texts = chs.filter((c) => c.type === 0 || c.type === 5);
  console.log('文本/公告频道共 %d 个（全部频道 %d 个）\n', texts.length, chs.length);

  const kw = /log|audit|guard|记录|日志|稽查|安全|moderat|staff|admin/i;
  const cand = texts.filter((c) => kw.test(c.name));
  console.log('--- 名字像日志频道的候选 ---');
  for (const c of cand) console.log(`  ${c.id}   #${c.name}   (type=${c.type === 5 ? '公告' : '文本'})`);
  if (!cand.length) console.log('  （没有名字像日志的频道）');

  console.log('\n--- 全部文本频道（按位置，最多 60 个）---');
  for (const c of texts.sort((a, b) => a.position - b.position).slice(0, 60)) {
    console.log(`  ${c.id}   #${c.name}${c.parent_id ? '   [分类 ' + c.parent_id + ']' : ''}`);
  }
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
