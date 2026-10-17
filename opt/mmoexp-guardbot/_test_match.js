/* 自检脚本：验证"冒充前缀"判定是否会误伤 / 会不会漏杀。
   运行：node _test_match.js     （不需要 Discord Token，不会联网） */
'use strict';
const g = require('./index.js');
g.loadConfig();

const cfg = g.state.config;
console.log(`配置：matchMode=${cfg.matchMode}  action=${cfg.action}  dryRun=${cfg.dryRun}\n`);

// ---- 应该被抓的（冒充官方） ----
const POSITIVE = [
  'MMOEXP', 'mmoexp', 'MmoExp',
  'MMOEXP Support', 'MMOEXP_Official', 'MMOEXP-CS', 'MMOEXP | Store',
  'MMOEXP01', 'mmoexp_88', 'mmoEXP.team',
  'MM0EXP', 'MMOOEXP', 'mmo0exp',
  'ＭＭＯＥＸＰ',                 // 全角
  'ММОЕХР',                       // 西里尔字母同形
  'MMO E X P', 'm.m.o.e.x.p',     // 分隔符
  'The MMOEXP', 'mmoexpbot', 'MMOEXP-gift', 'mmoexp official',
  'MMO\u200BEXP',                 // 中间塞零宽字符
];

// ---- 不应该被抓的（正常名字） ----
const NEGATIVE = [
  'mmoexpert', 'mmoexpo', 'mmoex', 'moexp',
  'John', 'Support', 'Mike', 'Nicholas',
  'MMO Player', 'WoW Gold Seller', 'Cheap Diablo 4 Gold',
  'official support', 'mmo exp lover',
  'MMOEXPfan2026_play',
];

let pass = 0, fail = 0;
console.log('===== 应该命中（冒充） =====');
for (const n of POSITIVE) {
  const r = g.classify(n);
  const ok = !!r;
  ok ? pass++ : fail++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${JSON.stringify(n).padEnd(28)} -> ${r ? `命中 tail="${r.tail}" via=${r.via}` : '未命中 ❌'}`);
}

console.log('\n===== 不应命中（正常） =====');
for (const n of NEGATIVE) {
  const r = g.classify(n);
  const ok = !r;
  ok ? pass++ : fail++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${JSON.stringify(n).padEnd(28)} -> ${r ? `误伤 ❌ tail="${r.tail}"` : '放行'}`);
}

// ---- 字段优先级：昵称冒充、用户名正常 ----
console.log('\n===== 字段检查（用户名正常但昵称冒充） =====');
const fakeMember = {
  id: '123456789012345678',
  nickname: 'MMOEXP Support',
  displayName: 'MMOEXP Support',
  roles: { cache: { has: () => false } },
  user: { bot: false, username: 'randomdude42', globalName: 'Random Dude' },
};
const hit = g.assessMember(fakeMember);
const okField = hit && hit.field.includes('nickname');
okField ? pass++ : fail++;
console.log(`${okField ? 'PASS' : 'FAIL'}  命中字段 = ${hit ? hit.field + ' / ' + hit.value : '无 ❌'}`);

console.log(`\n===== 汇总：通过 ${pass} / 失败 ${fail} =====`);
process.exit(fail === 0 ? 0 : 1);
