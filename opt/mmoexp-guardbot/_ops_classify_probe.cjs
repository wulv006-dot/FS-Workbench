/* 只读：用线上真实配置跑分类判定 */
const mod = require('/opt/mmoexp-guardbot/index.js');
mod.loadConfig();
const cfg = mod.state.config;
console.log('生效配置：brandPattern=' + JSON.stringify(cfg.brandPattern) +
  '  matchMode=' + cfg.matchMode + '  action=' + cfg.action +
  '  extraStartsWith=' + JSON.stringify(cfg.extraStartsWith || []));
console.log('SUFFIX_OK =', JSON.stringify(mod.SUFFIX_OK || '(未导出)'));
console.log('');
const names = [
  'mmoexp_offical', 'mmoexp_offical'.replace(/_/g, ''), 'mmoexp_official',
  'MMOEXP_OFFICAL', 'mmoexp_offical2', 'mmoexp', 'mmoexp_support',
  'mmoexp_vip', 'mmoexpert', 'mmoexpo', 'John', 'mm0exp_test',
];
for (const n of names) {
  const hit = mod.classify(n);
  console.log(`${JSON.stringify(n).padEnd(24)} -> ${hit ? `🔴 HIT tail=${JSON.stringify(hit.tail)} via=${hit.via}` : '🟢 miss'}`);
}
