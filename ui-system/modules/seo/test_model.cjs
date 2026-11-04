const assert=require('node:assert/strict');
(async()=>{
 const {SnapshotClient,value}=await import('./model.mjs');
 const calls=[];
 const meta={snapshot_id:'seo-2026-11-05',facts_hash:'fixture',games:['FC27']};
 const client=new SnapshotClient(async(path)=>{calls.push(path);return {ok:true,json:async()=>path.endsWith('current')?meta:{snapshot_id:meta.snapshot_id,facts_hash:'fixture',rows:[]}};});
 await client.init();await client.load('history','FC27');await client.load('history','FC27',100);
 assert(calls.slice(1).every(p=>p.includes('/seo-2026-11-05/')));
 assert(calls.every(p=>!p.includes('refresh')));
 await assert.rejects(()=>client.load('history','D4'));
 assert.equal(value(null),'—');assert.equal(value('0'),'0');assert.equal(value('.5',true),'50.0%');
 client.fetch=async()=>({ok:true,json:async()=>({snapshot_id:meta.snapshot_id,facts_hash:'different'})});
 await assert.rejects(()=>client.load('history','FC27'),/版本/);
 console.log('PASS: frozen snapshot pagination, scoped game, missing versus zero and hash mismatch');
})().catch(e=>{console.error(e);process.exitCode=1;});
