const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('node:assert/strict');
const root = __dirname;
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const before = fs.readFileSync(path.join(root, 'before.html'), 'utf8');
const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(x => x[1]);
assert.equal(scripts.length, [...before.matchAll(/<script\b/g)].length);
for (const code of scripts) if (code.trim()) new vm.Script(code);
const context = vm.createContext({console});
const canonicalShim=path.join(root, '../game-monitor-autopublish-20261022/tests/shim.json');
const shim=fs.existsSync(canonicalShim)?canonicalShim:path.join(root, '../game_monitor_static_fill_20261022/compat/tests/shim.json');
vm.runInContext(JSON.parse(fs.readFileSync(shim, 'utf8')), context);
for (const code of scripts.slice(0, 3)) vm.runInContext(code, context, {timeout: 10000});
const rows = JSON.parse(fs.readFileSync(path.join(root, 'calendar.json'), 'utf8')).events;
for (const mode of ['current', 'history']) {
  context.calendarMode = mode;
  const rendered = vm.runInContext('window.FS_GAME_DAILY_MODE=calendarMode; gvRender(window.GAME_TIMELINE_DATA.games.find(g=>g.key==="ea-sports-fc"))', context);
  for (const row of rows) assert.ok(rendered.includes(row[1]), mode + ': missing ' + row[1]);
  assert.ok(rendered.includes('社区追踪') && rendered.includes('原表标注'));
  assert.ok(!/\[object Object\]|undefined/.test(rendered));
  for (const pane of ['ov','biz','intel','tool','cls','play','terms','eco','ops','dept']) assert.ok(rendered.includes('data-pane="'+pane+'"'));
}
vm.runInContext('globalThis.CustomEvent=function(){};window.dispatchEvent=function(){};window.fsApplyGameDaily({status:"succeeded",events:[],coverage:{covered_games:["ea-sports-fc"]}},null)', context);
const refreshed = vm.runInContext('gvRender(DATA.find(g=>g.key==="ea-sports-fc"))', context);
for (const row of rows) assert.ok(refreshed.includes(row[1]), 'daily refresh hides ' + row[1]);
console.log('PASS: all inline scripts compile; 18 FC events render in current and history views; source labels and 10 existing columns retained.');
