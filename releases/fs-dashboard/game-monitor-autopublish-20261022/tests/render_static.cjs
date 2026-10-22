// Reuse the deployed page's own renderer and the existing DOM shim.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('node:assert/strict');
const moduleRoot=path.resolve(__dirname,'..');
const folder=fs.existsSync(path.join(moduleRoot,'static-fill-20261022'))?path.join(moduleRoot,'static-fill-20261022'):path.resolve(moduleRoot,'../static-fill');
const html=fs.readFileSync(path.join(folder,'index.html'),'utf8');
const requests=JSON.parse(fs.readFileSync(path.join(folder,'requests.json'),'utf8'));
const request={updates:Object.assign({},...requests.map(x=>x.updates))};
const scripts=[...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(x=>x[1]);
const before=fs.readFileSync(path.join(folder,'before.html'),'utf8');
assert.equal(scripts.length,[...before.matchAll(/<script\b/g)].length);
for(const code of scripts)if(code.trim())new vm.Script(code);
const context=vm.createContext({console});
vm.runInContext(JSON.parse(fs.readFileSync(path.join(__dirname,'shim.json'),'utf8')),context);
for(const code of scripts.slice(0,3))vm.runInContext(code,context,{timeout:10000});
for(const key of Object.keys(request.updates)){
 let input='window.GAME_TIMELINE_DATA.games.find(x=>x.key==='+JSON.stringify(key)+')';
 if(key==='college-football-26'){
  context.archivedInput=request.updates[key].game;
  const normalizer=html.match(/DATA\.forEach\(g=>\{[\s\S]*?\n\}\);\r?\nfunction evStatus/)[0].replace(/\r?\nfunction evStatus$/,'').replace('DATA.forEach','[archivedInput].forEach');
  vm.runInContext(normalizer,context);input='archivedInput'; // Exercise the archived entry with the page's own event normalization.
 }
 const rendered=vm.runInContext('gvRender('+input+')',context);
 for(const pane of ['ov','biz','intel','tool','cls','play','terms','eco','ops','dept'])assert.ok(rendered.includes('data-pane="'+pane+'"'),key+':'+pane);
 assert.ok(!/undefined|\[object Object\]/.test(rendered),key+': render');
 assert.equal((rendered.match(/class="gv-gi"/g)||[]).length,4);
 console.log(JSON.stringify({key,columns:10,images:4,render:'passed'}));
}
