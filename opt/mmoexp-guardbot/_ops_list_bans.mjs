/* 只读：列出本服当前封禁名单，用于确认是否有误封（尤其老板自己的号） */
import fs from 'node:fs';
const tok = JSON.parse(fs.readFileSync('/opt/mmoexp-guardbot/config.json', 'utf8')).token.trim();
const h = { Authorization: 'Bot ' + tok };
const gid = '1041923524601851914';

let after = null, all = [];
while (true) {
  const url = `https://discord.com/api/v10/guilds/${gid}/bans?limit=1000${after ? `&after=${after}` : ''}`;
  let r = await fetch(url, { headers: h });
  if (r.status === 429) {
    const j = await r.json().catch(() => ({}));
    await new Promise((s) => setTimeout(s, Math.ceil((j.retry_after || 1) * 1000) + 300));
    continue;
  }
  if (!r.ok) { console.log('ERR', r.status, (await r.text()).slice(0, 200)); break; }
  const bans = await r.json();
  if (!bans.length) break;
  all.push(...bans);
  after = bans[bans.length - 1].user.id;
  if (bans.length < 1000) break;
  await new Promise((s) => setTimeout(s, 250));
}

console.log(`当前封禁总数：${all.length}`);
const now = Date.now();
for (const b of all) {
  const u = b.user;
  console.log(`  ${u.id}  @${u.username}  global=${JSON.stringify(u.global_name)}  bot=${u.bot}  reason=${JSON.stringify(b.reason)}`);
}

// 判断有没有"刚刚"被封的（无法从 API 拿到时间，只提示数量）
console.log('\n提示：Discord 封禁列表不含封禁时间，需结合 journal 的 ACTION 行判断先后。');
