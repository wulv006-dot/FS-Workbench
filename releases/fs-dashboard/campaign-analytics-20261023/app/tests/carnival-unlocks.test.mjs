import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createCarnivalVerifier,CARNIVAL_UNLOCKS_FILE} from '../analytics/carnival-unlocks.mjs';
import {createCarnival} from '../runtime/carnival.mjs';

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
 assert.deepEqual(calls,[{action:'carnival_unlocks'}]);
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

test('idle outside the carnival window',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'verify-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 fs.writeFileSync(path.join(dir,'0'.repeat(32)+'-fc27.json'),'{}');
 let calls=0;const read=async()=>{calls++;return {status:'available',uses:[]};};
 for(const at of ['2026-11-18T12:00:00Z','2026-12-03T06:00:00Z'])
  assert.equal((await createCarnivalVerifier({publicDir:dir,requestDir:dir,now:()=>Date.parse(at),read}).refresh()).status,'idle');
 assert.equal(calls,0);
});
