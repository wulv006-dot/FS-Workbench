window.FSBusinessSnapshots=class {
 constructor(base,onUpdate,onState){this.update=onUpdate;this.state=onState;this.current=null;this.pending=null;}
 check(){if(this.pending)return this.pending;this.pending=(async()=>{try{
  const r=await fetch('/dashboard/fs-home/range.json?mode=catalog',{credentials:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(20000)});
  if(r.status===401||r.status===403){window.dispatchEvent(new CustomEvent('fs-exact-permission-denied',{detail:{status:r.status}}));throw Error('catalog_denied');}
  if(!r.ok)throw Error('catalog_unavailable');const data=await r.json();
  if(data.schemaVersion!==2||!/^catalog-[a-f0-9]{16}$/.test(data.catalogId)||data.snapshotId!==data.catalogId||data.scopeContractId!=='all-websites-order-primary-admin-supplement-v1')throw Error('catalog_contract');
  if(this.current?.catalogId!==data.catalogId){this.current=data;this.update(data);}
  this.state({status:'fresh',catalogId:data.catalogId,generatedAt:data.generatedAt,timezone:data.timezone,snapshotId:data.catalogId});
 }catch{this.state({status:'unavailable',catalogId:this.current?.catalogId});}})().finally(()=>{this.pending=null;});return this.pending;}
 start(){this.check();}stop(){}
};
