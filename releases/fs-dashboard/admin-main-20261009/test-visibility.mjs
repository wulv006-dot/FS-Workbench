import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('./assets/shell.js',import.meta.url),'utf8');
const handler=source.slice(source.indexOf('// Keep the mounted view'),source.indexOf("addEventListener('pagehide'"));
assert(handler.includes('visibilitychange'));
function fixture(){
 const calls=[];let listener;
 const c={document:{hidden:false,addEventListener:(type,fn)=>{assert.equal(type,'visibilitychange');listener=fn;}},identity:{name:'A'},epoch:1,home:false,
 active:{api:{state:()=>({selection:'FC27'}),update:async()=>calls.push('update')},scope:{destroy:()=>calls.push('destroy')}},
 verify:async()=>{calls.push('verify');return {name:'A'};},capture:q=>calls.push(q.selection),halt:s=>calls.push(s),boot:async()=>calls.push('boot'),
 nativeLoad:async()=>calls.push('mount'),homeData:()=>calls.push('home'),watcher:{check:async()=>calls.push('snapshot')},$:()=>({dataset:{}})};
 vm.runInNewContext(handler,c);return {c,calls,run:()=>listener()};
}
let f=fixture();f.c.document.hidden=true;await f.run();assert.deepEqual(f.calls,[]);
f.c.document.hidden=false;const mounted=f.c.active;await f.run();assert.equal(f.c.active,mounted);assert.deepEqual(f.calls,['verify','FC27','update']);
f=fixture();f.c.verify=async()=>{throw Object.assign(Error(),{status:401});};await f.run();assert.deepEqual(f.calls,[401]);
f=fixture();f.c.verify=async()=>({name:'B'});await f.run();assert.deepEqual(f.calls,[403,'boot']);
f=fixture();f.c.verify=async()=>{throw Error('offline');};await f.run();assert.deepEqual(f.calls,[]);assert(f.c.active);
f=fixture();f.c.active=null;await f.run();assert.deepEqual(f.calls,['verify','mount']);
f=fixture();f.c.active.api=null;await f.run();assert.deepEqual(f.calls,['verify']);
f=fixture();f.c.home=true;await f.run();assert.deepEqual(f.calls,['verify','snapshot']);
f=fixture();let resolve;f.c.verify=()=>new Promise(r=>resolve=r);const pending=f.run();await f.run();f.c.document.hidden=true;resolve({name:'A'});await pending;assert.deepEqual(f.calls,[]);
f=fixture();f.c.verify=async()=>{f.c.epoch++;return {name:'A'};};await f.run();assert.deepEqual(f.calls,[]);
assert(source.includes("addEventListener('pagehide',()=>{epoch++;active?.scope.destroy()"));
console.log('11 visibility lifecycle checks passed: retention, auth failure/change, outage, races, initial load, home and real navigation teardown.');
