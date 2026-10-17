'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert/strict');
const root=__dirname,helper=fs.readFileSync(path.join(root,'cache-helper.js'),'utf8').replaceAll('\r\n','\n');
let checks=0;
const check=(value,message)=>{assert.ok(value,message);checks++;};
const storage=()=>{const data=new Map();return {getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,String(v)),removeItem:k=>data.delete(k),clear:()=>data.clear()};};
const session=storage(),local=storage(),user={name:'A',role:'admin',groups:['dashboard','deploy']};
function context(code=helper){const events={};const c=vm.createContext({sessionStorage:session,localStorage:local,addEventListener:(k,f)=>events[k]=f,JSON,URL,AbortSignal,location:{origin:'https://fs.test',href:'https://fs.test/'}});vm.runInContext(code,c);c.events=events;return c;}
const run=(c,s)=>vm.runInContext(s,c);
(async()=>{
 for(const name of ['runtime.js','navigation.js','hubnav.js'])check(fs.readFileSync(path.join(root,'source',name),'utf8').replaceAll('\r\n','\n').includes(helper),'identical cache contract: '+name);
 let c=context(),calls=0; c.user=user;c.probe=async()=>{calls++;return true;};
 run(c,'rememberMenuIdentity(user)');await run(c,"menuAccess('/d4/','text/html',probe)");await run(c,"menuAccess('/d4/','text/html',probe)");check(calls===1,'reuse successful probe');
 const second=context();second.user=user;second.probe=c.probe;run(second,'rememberMenuIdentity(user)');await run(second,"menuAccess('/d4/','text/html',probe)");check(calls===1,'reuse across page navigation');
 await run(second,"menuAccess('/d4/','application/json',probe)");check(calls===2,'content type isolated');
 c.user={...user,name:'B'};run(c,'rememberMenuIdentity(user)');await run(c,"menuAccess('/d4/','text/html',probe)");check(calls===3,'account switch invalidates');
 c.user={...c.user,role:'readonly'};run(c,'rememberMenuIdentity(user)');await run(c,"menuAccess('/d4/','text/html',probe)");check(calls===4,'role change invalidates');
 c.user={...c.user,groups:['dashboard']};run(c,'rememberMenuIdentity(user)');await run(c,"menuAccess('/d4/','text/html',probe)");check(calls===5,'group change invalidates');
 local.setItem('fs-menu-access-epoch','new-login');c.events.storage({key:'fs-menu-access-epoch'});check(session.getItem('fs-menu-access-v1')===null,'other tab event clears cache');
 run(c,'rememberMenuIdentity(user)');await run(c,"menuAccess('/d4/','text/html',probe)");check(calls===6,'same user new login reprobes');
 let failures=0;c.bad=async()=>{failures++;return false;};await run(c,"menuAccess('/missing/','text/html',bad)");await run(c,"menuAccess('/missing/','text/html',bad)");check(failures===2,'outage and denied entries are never cached');
 session.setItem('fs-menu-access-v1','broken');run(c,'rememberMenuIdentity(user)');await run(c,"menuAccess('/d4/','text/html',probe)");check(calls===7,'malformed cache recovers');
 let resolve;c.delayed=()=>new Promise(r=>resolve=r);const pending=run(c,"menuAccess('/slow/','text/html',delayed)");run(c,'clearMenuCache()');resolve(true);await pending;check(session.getItem('fs-menu-access-v1')===null,'late response cannot resurrect revoked cache');
 const blocked=context();blocked.user=user;blocked.localStorage={getItem:()=>{throw Error('disabled');}};blocked.probe=c.probe;run(blocked,'rememberMenuIdentity(user)');await run(blocked,"menuAccess('/d4/','text/html',probe)");await run(blocked,"menuAccess('/d4/','text/html',probe)");check(calls===9,'storage unavailable uses original probes');
 // Exercise the real native verifier and probe, not a duplicate implementation.
 session.clear();local.clear();let denied=false,heads=0,verifies=0;
 const runtime=fs.readFileSync(path.join(root,'source/runtime.js'),'utf8').replaceAll('export ','');
 const native=context(runtime);native.window={fetch:async(url,opts={})=>{if(String(url)==='/__auth/verify'){verifies++;return {status:denied?401:200,ok:!denied,headers:{get:n=>({'X-Auth-User':'A','X-Auth-Role':'admin','X-Auth-Groups':'dashboard'}[n]||'')}};}heads++;return {status:200,ok:true,headers:{get:()=> 'text/html'}};}};
 await run(native,'sessionIdentity()');await run(native,"moduleAvailable('/d4/')");await run(native,'sessionIdentity()');await run(native,"moduleAvailable('/d4/')");check(heads===1&&verifies===2,'identity verified each navigation while HEAD scan is cached');
 await assert.rejects(run(native,"moduleAvailable('https://external.test/')"),/same-origin/);check(heads===1,'same-origin boundary checked on every cache call');
 denied=true;await assert.rejects(run(native,'sessionIdentity()'),e=>e.status===401);check(session.getItem('fs-menu-access-v1')===null,'server 401 clears native cache');
 // Run the actual account API hook for logout/login/grant mutations.
 const app=fs.readFileSync(path.join(root,'source/app.js'),'utf8');let ok=true;
 const account=context('');account.crypto={randomUUID:()=> 'epoch-'+checks};account.fetch=async()=>({ok,status:ok?200:403,json:async()=>({})});
 vm.runInContext(app.slice(0,app.indexOf('function message(')),account);
 session.setItem('fs-menu-access-v1','cached');await run(account,"api('bootstrap')");check(session.getItem('fs-menu-access-v1')==='cached','bootstrap read does not invalidate');
 for(const endpoint of ['native-login','login','logout','permissions','account-permissions']){session.setItem('fs-menu-access-v1','cached');await run(account,`api('${endpoint}',{})`);check(session.getItem('fs-menu-access-v1')===null&&local.getItem('fs-menu-access-epoch'),'successful '+endpoint+' invalidates and broadcasts');}
 ok=false;session.setItem('fs-menu-access-v1','cached');await assert.rejects(run(account,"api('permissions',{})"));check(session.getItem('fs-menu-access-v1')==='cached','failed writes do not claim permission change');
 console.log(JSON.stringify({checks,result:'PASS',realAccountWrites:0}));
})().catch(e=>{console.error(e);process.exitCode=1;});
