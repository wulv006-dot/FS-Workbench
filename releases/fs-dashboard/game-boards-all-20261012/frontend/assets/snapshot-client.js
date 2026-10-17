/* Preparation contract: shared transaction version check; no upstream collection. */
window.FSBusinessSnapshots=class {
 constructor(base,onUpdate,onState){this.base=base.endsWith('/')?base:base+'/';this.update=onUpdate;this.state=onState;this.current=null;this.pending=null;this.timer=null;}
 async read(path){const r=await fetch(path,{credentials:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(20000)});if(!r.ok||!r.headers.get('content-type')?.includes('application/json'))throw Error('snapshot_unavailable');return r;}
 check(){if(this.pending)return this.pending;this.pending=(async()=>{try{
  const [m,attempt]=await Promise.all([(async()=>await (await this.read(this.base+'current.json')).json())(),(async()=>{try{return await (await this.read(this.base+'attempt.json')).json();}catch{return null;}})()]);
  if(m.schemaVersion!==2||!/^\d{8}T\d{6}Z-[a-f0-9]{16}$/.test(m.snapshotId)||m.path!=='snapshots/'+m.snapshotId+'/snapshot.json')throw Error('invalid_manifest');
  if(this.current?.snapshotId!==m.snapshotId){const bytes=await (await this.read(this.base+m.path)).arrayBuffer();const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(b=>b.toString(16).padStart(2,'0')).join('');if(hash!==m.sha256)throw Error('snapshot_hash_mismatch');const data=JSON.parse(new TextDecoder().decode(bytes));if(data.snapshotId!==m.snapshotId||data.scopeContractId!==m.scopeContractId)throw Error('snapshot_version_mismatch');this.current=data;this.update(data);}
  const age=(Date.now()-Date.parse(this.current.generatedAt))/1000;this.state({status:Number.isFinite(age)&&age<=7200&&attempt?.status==='success'&&attempt.snapshotId===m.snapshotId?'fresh':'stale',generatedAt:this.current.generatedAt,timezone:this.current.timezone,snapshotId:this.current.snapshotId});
 }catch{this.state({status:this.current?'stale':'unavailable',generatedAt:this.current?.generatedAt,snapshotId:this.current?.snapshotId});}})().finally(()=>{this.pending=null;});return this.pending;}
 start(){if(this.timer)return;this.check();this.timer=setInterval(()=>this.check(),60000);}
 stop(){clearInterval(this.timer);this.timer=null;}
};
