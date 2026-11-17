import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createCarnivalVerifier,CARNIVAL_UNLOCKS_FILE} from '../analytics/carnival-unlocks.mjs';
import {createCarnival} from '../runtime/carnival.mjs';
import {backendRead} from '../analytics/backend-client.mjs';

function setup(t,clock){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'verify-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const runtimeDir=path.join(dir,'runtime'),publicDir=path.join(dir,'public');fs.mkdirSync(publicDir);
 const state={now:Date.parse(clock),reply:{status:'available',generated_at:'x',uses:[]}},calls=[];
 const carnival=createCarnival({dir:runtimeDir,publishedDir:publicDir,now:()=>state.now});
 const verifier=createCarnivalVerifier({publicDir,requestDir:path.join(runtimeDir,'carnival-verify'),now:()=>state.now,
  read:async r=>{calls.push(r);if(state.reply instanceof Error)throw state.reply;return state.reply;}});
 return {carnival,verifier,state,calls,publicDir,runtimeDir};
}
const status=(c,uid,game)=>c.state(new URLSearchParams({uid})).games[game];

test('Admin is read only when a member presses verify, and the result reaches the page state',async t=>{
 const {carnival,verifier,state,calls,publicDir,runtimeDir}=setup(t,'2026-11-20T10:00:00-05:00');
 assert.equal((await verifier.refresh()).status,'idle');assert.equal(calls.length,0,'no request, no Admin read');
 const round=carnival.draw({uid:'42',game:'fc27',items:[0,1,2]});
 assert.equal(round.verify,null);
 // Not paid yet.
 assert.equal(carnival.verify({uid:'42',game:'fc27'}).verify.status,'checking');
 assert.equal(fs.readdirSync(path.join(runtimeDir,'carnival-verify')).filter(n=>n.endsWith('.json')).length,1);
 assert.match(fs.readdirSync(path.join(runtimeDir,'carnival-verify'))[0],/^[0-9a-f]{32}-fc27\.json$/,'hashed member id only');
 assert.deepEqual(await verifier.refresh(),{status:'checked',requests:1});
 assert.deepEqual(calls,[{action:'carnival_unlocks',site_id:'266'}]);
 assert.equal(fs.readdirSync(path.join(runtimeDir,'carnival-verify')).filter(n=>n.endsWith('.json')).length,0,'request answered');
 assert.deepEqual(status(carnival,'42','fc27').verify,{status:'not_found'});
 if(process.platform!=='win32')assert.equal(fs.statSync(path.join(publicDir,CARNIVAL_UNLOCKS_FILE)).mode&0o777,0o644);
 // Pressing again within 30 seconds does not queue another Admin read.
 state.now+=10000;carnival.verify({uid:'42',game:'fc27'});
 assert.equal((await verifier.refresh()).status,'idle');assert.equal(calls.length,1);
 // Paid after the draw: the next press unlocks a new round.
 state.now+=30000;state.reply={status:'available',generated_at:'y',uses:[{uid:'42',set:'fc27',used_at:new Date(state.now-5000).toISOString()}]};
 carnival.verify({uid:'42',game:'fc27'});await verifier.refresh();
 const after=status(carnival,'42','fc27');assert.equal(after.can_draw,true);assert.equal(after.current,null);
 assert.equal(round.current.round,1);assert.equal(carnival.draw({uid:'42',game:'fc27',items:[3,4,5]}).current.round,2);
});

test('an Admin failure is reported as "try again" and keeps the last paid-use list',async t=>{
 const {carnival,verifier,state,publicDir}=setup(t,'2026-11-20T10:00:00-05:00');
 carnival.draw({uid:'7',game:'wow',items:[0,1,2]});
 fs.writeFileSync(path.join(publicDir,CARNIVAL_UNLOCKS_FILE),JSON.stringify({uses:[{uid:'1',set:'fc27',used_at:'2026-11-20T00:00:00Z'}],checked:{}}));
 state.reply=Error('down');carnival.verify({uid:'7',game:'wow'});
 assert.equal((await verifier.refresh()).status,'failed');
 assert.deepEqual(status(carnival,'7','wow').verify,{status:'error'});
 assert.equal(JSON.parse(fs.readFileSync(path.join(publicDir,CARNIVAL_UNLOCKS_FILE),'utf8')).uses.length,1,'last good list stays');
});

test('during an internal test only the test coupon is read before the event',async t=>{
 const {carnival,verifier,state,calls,publicDir}=setup(t,'2026-11-17T10:00:00-05:00');
 fs.writeFileSync(path.join(publicDir,'carnival-test.json'),JSON.stringify({open_until:'2026-11-18T23:00:00-05:00',coupon_id:1601,slot:'carnival_test'}));
 carnival.draw({uid:'42',game:'wow',items:[0,1,2]});
 state.now+=60000;state.reply={status:'available',generated_at:'t',uses:[{uid:'42',set:'wow',used_at:new Date(state.now-1000).toISOString()}]};
 carnival.verify({uid:'42',game:'wow'});
 assert.deepEqual(await verifier.refresh(),{status:'checked',requests:1});
 assert.deepEqual(calls,[{action:'carnival_unlocks',site_id:'266',test_coupon_id:1601}]);
 assert.equal(status(carnival,'42','wow').can_draw,true);
});

test('the verifier request passes the real backend client scope check',async t=>{
 // Regression: live 2026-11-17 every press answered "couldn't check" because the request
 // had no site_id and backendRead refused it (SITE_SCOPE_REQUIRED) before reaching Admin.
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'verify-bridge-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const bridge=path.join(dir,'echo.cjs');
 fs.writeFileSync(bridge,"let raw='';process.stdin.on('data',x=>raw+=x).on('end',()=>{const r=JSON.parse(raw);process.stdout.write(JSON.stringify({status:'ok',data:{status:'available',generated_at:'e',uses:[],echo:r}}));});");
 const runtimeDir=path.join(dir,'runtime'),publicDir=path.join(dir,'public');fs.mkdirSync(publicDir);
 const clock=Date.parse('2026-11-20T10:00:00-05:00'),seen=[];
 const c=createCarnival({dir:runtimeDir,publishedDir:publicDir,now:()=>clock});
 const verifier=createCarnivalVerifier({publicDir,requestDir:path.join(runtimeDir,'carnival-verify'),now:()=>clock,
  read:async r=>{const d=await backendRead(r,{python:process.execPath,bridge});seen.push(d.echo);return d;}});
 c.draw({uid:'42',game:'fc27',items:[0,1,2]});c.verify({uid:'42',game:'fc27'});
 assert.deepEqual(await verifier.refresh(),{status:'checked',requests:1});
 assert.equal(seen[0].site_id,'266');
 assert.deepEqual(status(c,'42','fc27').verify,{status:'not_found'},'answered, not "couldn\'t check"');
});

// Mystery Shop rules (user, 2026-11-17): each game has its own lock. After a draw the game
// stays locked until a paid order used one of that game's Mystery coupons; then a new draw
// opens. Other games are unaffected, and coupon claims are unlimited.
test('each game unlocks on its own, even where games share a coupon set',async t=>{
 const {carnival,verifier,state}=setup(t,'2026-11-20T10:00:00-05:00');
 const pay=(set,ago=1000)=>{state.reply={status:'available',generated_at:'p',uses:[...(state.reply.uses||[]),{uid:'42',set,used_at:new Date(state.now-ago).toISOString()}]};};
 for(const g of ['poe1','poe2','fc27'])carnival.draw({uid:'42',game:g,items:[0,1,2]});
 // A second draw on a locked game returns the same round, never a new roll.
 const again=carnival.draw({uid:'42',game:'poe1',items:[6,7,8]});assert.equal(again.repeated,true);assert.equal(again.current.round,1);
 // One purchase with a POE coupon: the member verifies POE 2 → only POE 2 reopens.
 state.now+=60000;pay('poe');
 carnival.verify({uid:'42',game:'poe2'});await verifier.refresh();
 assert.equal(status(carnival,'42','poe2').can_draw,true);
 assert.equal(status(carnival,'42','poe1').can_draw,false,'POE 1 stays locked: the use went to POE 2');
 assert.equal(status(carnival,'42','fc27').can_draw,false,'other games are unaffected');
 // Verifying POE 1 with no further purchase finds nothing new.
 state.now+=31000;carnival.verify({uid:'42',game:'poe1'});await verifier.refresh();
 assert.deepEqual(status(carnival,'42','poe1').verify,{status:'not_found'});
 // A second POE purchase reopens POE 1 too.
 state.now+=31000;pay('poe');carnival.verify({uid:'42',game:'poe1'});await verifier.refresh();
 assert.equal(status(carnival,'42','poe1').can_draw,true);
 // Purchases before a round was drawn never reopen it.
 state.now+=1000;assert.equal(carnival.draw({uid:'42',game:'poe2',items:[3,4,5]}).current.round,2);
 state.now+=31000;carnival.verify({uid:'42',game:'poe2'});await verifier.refresh();
 assert.equal(status(carnival,'42','poe2').can_draw,false);
 // Unlimited: keep paying, keep drawing.
 for(let n=3;n<=6;n++){
  state.now+=31000;pay('poe');carnival.verify({uid:'42',game:'poe2'});await verifier.refresh();
  assert.equal(status(carnival,'42','poe2').can_draw,true);
  state.now+=1000;assert.equal(carnival.draw({uid:'42',game:'poe2',items:[0,4,8]}).current.round,n);
 }
 // Another member's purchase never unlocks this member.
 carnival.draw({uid:'43',game:'wow',items:[0,1,2]});state.now+=31000;
 state.reply={status:'available',generated_at:'q',uses:[{uid:'42',set:'wow',used_at:new Date(state.now-1000).toISOString()}]};
 carnival.verify({uid:'43',game:'wow'});await verifier.refresh();
 assert.equal(status(carnival,'43','wow').can_draw,false);
});

test('idle outside the carnival window',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'verify-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 fs.writeFileSync(path.join(dir,'0'.repeat(32)+'-fc27.json'),'{}');
 let calls=0;const read=async()=>{calls++;return {status:'available',uses:[]};};
 for(const at of ['2026-11-18T12:00:00Z','2026-12-03T06:00:00Z'])
  assert.equal((await createCarnivalVerifier({publicDir:dir,requestDir:dir,now:()=>Date.parse(at),read}).refresh()).status,'idle');
 assert.equal(calls,0);
});
