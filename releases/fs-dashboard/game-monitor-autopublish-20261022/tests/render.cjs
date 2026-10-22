const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),folder=path.join(root,'candidate');
const fixtures=[path.resolve(root,'../game-monitor-sop-20261022/source/index.html'),path.resolve(root,'../docs/planning/game-monitor-sop-20261022/evidence/repo/releases/fs-dashboard/game-monitor-sop-20261022/source/index.html')];
const pending=fs.existsSync(folder),fixture=fixtures.find(x=>fs.existsSync(x));
assert.ok(pending||fixture,'required rendering fixture missing');
const html=fs.readFileSync(pending?path.join(folder,'index.html'):fixture,'utf8');
const before=pending?fs.readFileSync(path.join(folder,'before.html'),'utf8'):html;
const request=pending?JSON.parse(fs.readFileSync(path.join(folder,'request.json'),'utf8')):{updates:{maplestory:{}}};
const scripts=[...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(x=>x[1]);
assert.equal(scripts.length,[...before.matchAll(/<script\b/g)].length);
for(const code of scripts)if(code.trim())new vm.Script(code);
const context=vm.createContext({console});
vm.runInContext(JSON.parse(fs.readFileSync(path.join(root,'tests/shim.json'),'utf8')),context,{timeout:2000});
for(const code of scripts.slice(0,3))vm.runInContext(code,context,{timeout:10000});
for(const game of Object.keys(request.updates)){
  const rendered=vm.runInContext('gvRender(window.GAME_TIMELINE_DATA.games.find(x=>x.key==='+JSON.stringify(game)+'))',context,{timeout:10000});
  for(const pane of ['ov','biz','intel','tool','cls','play','terms','eco','ops','dept'])assert.ok(rendered.includes('data-pane="'+pane+'"'),game+':'+pane);
  assert.ok(!/\[object Object\]|undefined/.test(rendered),'invalid rendered data');
  assert.equal((rendered.match(/class="gv-gi"/g)||[]).length,4);
  assert.ok((rendered.match(/class="gv-cls-tab/g)||[]).length>=4);
  assert.ok((rendered.match(/Hermes经营草稿·待运营确认/g)||[]).length>=19);
  console.log(JSON.stringify({game,rendered_columns:10,script_compilation:'pass',draft_markers:'visible'}));
}

require('./render_static.cjs');
