/* 只读：读最近的服务端审计日志，找出「谁刚把自己移出角色 / 改了名」 */
import fs from 'node:fs';
const tok = JSON.parse(fs.readFileSync('/opt/mmoexp-guardbot/config.json', 'utf8')).token.trim();
const h = { Authorization: 'Bot ' + tok };
const gid = '1041923524601851914';

const r = await fetch(`https://discord.com/api/v10/guilds/${gid}/audit-logs?limit=60`, { headers: h });
if (!r.ok) {
  console.log('审计日志不可读：HTTP', r.status, (await r.text()).slice(0, 200));
  console.log('（机器人缺少 VIEW_AUDIT_LOG 权限。可让老板在 Discord 里手动看一眼，或把机器人角色加上该权限。）');
  process.exit(0);
}

const j = await r.json();
const TYPE = {
  1: 'GUILD_UPDATE', 10: 'CHANNEL_CREATE', 11: 'CHANNEL_UPDATE', 12: 'CHANNEL_DELETE',
  13: 'CHANNEL_OVERWRITE_CREATE', 20: 'MEMBER_KICK', 21: 'MEMBER_PRUNE', 22: 'MEMBER_BAN_ADD',
  23: 'MEMBER_BAN_REMOVE', 24: 'MEMBER_UPDATE', 25: 'MEMBER_ROLE_UPDATE', 26: 'MEMBER_MOVE',
  27: 'MEMBER_DISCONNECT', 28: 'BOT_ADD', 30: 'ROLE_CREATE', 31: 'ROLE_UPDATE', 32: 'ROLE_DELETE',
  40: 'INVITE_CREATE', 50: 'WEBHOOK_CREATE', 60: 'EMOJI_CREATE', 72: 'MESSAGE_DELETE',
  80: 'MESSAGE_BULK_DELETE', 82: 'MESSAGE_PIN', 110: 'AUTO_MODERATION_BLOCK_MESSAGE',
};
const users = j.users || [];
const uname = (id) => {
  const u = users.find((x) => x.id === id);
  return u ? `${u.username}${u.global_name ? ' (' + u.global_name + ')' : ''}` : id;
};

console.log(`审计日志条数：${(j.audit_log_entries || []).length}`);
for (const e of (j.audit_log_entries || []).slice(0, 40)) {
  const t = TYPE[e.action_type] || ('TYPE_' + e.action_type);
  const chg = (e.changes || []).map((c) => `${c.key}=${JSON.stringify(c.new_value)}`).join(' ');
  console.log(`  [${new Date(Number(BigInt(e.id) >> 22n) + 1420070400000).toISOString().slice(11, 19)}] ${t}  target=${uname(e.target_id)}  by=${uname(e.user_id)}  ${chg.slice(0, 160)}`);
}
