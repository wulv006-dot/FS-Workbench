import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createCarnivalUnlocks,CARNIVAL_UNLOCKS_FILE} from '../analytics/carnival-unlocks.mjs';

test('publishes paid Mystery uses for the runtime and keeps the last good file on failure',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'unlocks-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 let reply={status:'available',generated_at:'2026-11-20T00:00:00Z',uses:[{uid:'1',set:'fc27',used_at:'2026-11-20T00:00:00Z'}]},calls=[];
 const now=Date.parse('2026-11-20T00:00:00Z');
 const u=createCarnivalUnlocks({publicDir:dir,now:()=>now,read:async r=>{calls.push(r);if(reply instanceof Error)throw reply;return reply;}});
 assert.deepEqual(await u.refresh(),{status:'written',uses:1});
 assert.deepEqual(calls,[{action:'carnival_unlocks'}]);
 const file=path.join(dir,CARNIVAL_UNLOCKS_FILE);
 assert.deepEqual(JSON.parse(fs.readFileSync(file,'utf8')).uses,reply.uses);
 if(process.platform!=='win32')assert.equal(fs.statSync(file).mode&0o777,0o644);
 reply=Error('down');assert.equal((await u.refresh()).status,'failed');
 assert.equal(JSON.parse(fs.readFileSync(file,'utf8')).uses.length,1,'last good list stays');
 reply={status:'available',uses:'bad'};assert.equal((await u.refresh()).status,'failed');
});

test('idle outside the carnival window',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'unlocks-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 let calls=0;const read=async()=>{calls++;return {status:'available',uses:[]};};
 assert.equal((await createCarnivalUnlocks({publicDir:dir,now:()=>Date.parse('2026-11-18T12:00:00Z'),read}).refresh()).status,'idle');
 assert.equal((await createCarnivalUnlocks({publicDir:dir,now:()=>Date.parse('2026-12-03T06:00:00Z'),read}).refresh()).status,'idle');
 assert.equal(calls,0);
});
