import fs from 'node:fs';
import path from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {isDeepStrictEqual} from 'node:util';
import core from './funnel-core.cjs';
export function atomic(file,value){
 fs.mkdirSync(path.dirname(file),{recursive:true,mode:0o700});
 const temp=file+'.'+randomUUID()+'.tmp',fd=fs.openSync(temp,'wx',0o600);
 try{fs.writeFileSync(fd,JSON.stringify(value));fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
 try{fs.renameSync(temp,file);}finally{if(fs.existsSync(temp))fs.unlinkSync(temp);}
 if(process.platform!=='win32'){const dir=fs.openSync(path.dirname(file),'r');try{fs.fsyncSync(dir);}finally{fs.closeSync(dir);}}
}
export function initialLayout(c){return {weekly:c.weekly.ids,trio:c.trio.ids,bundles:c.bundles.ids,sbc:c.sbc.ids,defaultCore:c.sbc.defaultId,routes:c.sbc.routes};}
export function validateLayout(d,c){
 if(!d||typeof d!=='object')throw Error('商品配置缺失');
 const ids=(a,min,max,kind)=>{if(!Array.isArray(a)||a.length<min||a.length>max||new Set(a).size!==a.length||a.some(id=>typeof id!=='string'||!c.products[id]||kind&&c.products[id].kind!==kind))throw Error('商品数量、身份或类型无效');return [...a];};
 const weekly=ids(d.weekly,1,6,'player'),trio=ids(d.trio,3,3,'player'),bundles=ids(d.bundles,0,8,'bundle'),sbc=ids(d.sbc,1,9,'sbc');
 if(trio.some(id=>c.products[id].version!==c.trio.series))throw Error('三人组必须使用当前系列的真实卡版本');
 if(!sbc.includes(d.defaultCore))throw Error('默认 SBC 必须在已选核心内');
 const routes={};for(const id of sbc){const row=d.routes?.[id];if(!row)throw Error('每个 SBC 核心都需设置搭档');const picks=ids(row.picks,2,2,'player'),alternatives=ids(row.alternatives||[],0,8,'player');if(alternatives.some(x=>picks.includes(x)))throw Error('搭档与备选不可重复');routes[id]={picks,alternatives,label:c.sbc.routes[id]?.label||{zh:'自选搭配方向',en:'Companion ideas'}};}
 return {weekly,trio,bundles,sbc,defaultCore:d.defaultCore,routes};
}
export function previewCatalog(c,d){const copy=structuredClone(c);copy.mode='preview';copy.weekly.ids=d.weekly;copy.weekly.edition=d.weekly.every(id=>c.products[id].version==='Team of the Week')?c.weekly.edition:{zh:'本周好卡精选',en:'WEEKLY PLAYER PICKS'};copy.trio.ids=d.trio;copy.bundles.ids=d.bundles;copy.sbc.ids=d.sbc;copy.sbc.defaultId=d.defaultCore;copy.sbc.routes=d.routes;return copy;}
export function makeStore(dir,catalog,registry){
 const file=path.join(dir,'state.json');
 const read=()=>fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):{revision:0,registry:core.validateRegistry(registry),layout:initialLayout(catalog),operations:[],updatedAt:null,updatedBy:null};
 return {read,save({revision,operationId,registry:next,layout},user){
  if(!/^[a-f0-9-]{36}$/.test(operationId||''))throw Error('操作 ID 无效');
  const current=read();
  // A registry-only save must preserve the server's accepted layout across catalog version changes.
  const retained=current.revision>0&&isDeepStrictEqual(layout,current.layout);
  const payload={registry:core.validateRegistry(next),layout:retained?structuredClone(current.layout):validateLayout(layout,catalog)};
  const hash=createHash('sha256').update(JSON.stringify(payload)).digest('hex'),prior=current.operations.find(o=>o.id===operationId);
  if(prior){if(prior.hash!==hash)throw Error('操作 ID 已用于另一份配置');return current;}
  if(revision!==current.revision){const e=Error('配置已被其他人更新，请重新加载后再保存');e.status=409;throw e;}
  const missing=current.registry.filter(a=>!payload.registry.some(b=>b.id===a.id));if(missing.length)throw Error('历史活动不可删除，请使用归档状态');
  const value={...payload,revision:current.revision+1,updatedAt:new Date().toISOString(),updatedBy:user,operations:[...current.operations,{id:operationId,hash}].slice(-100)};
  if(current.revision)atomic(path.join(dir,'history',String(current.revision)+'.json'),current);
  atomic(file,value);return value;
 }};
}
