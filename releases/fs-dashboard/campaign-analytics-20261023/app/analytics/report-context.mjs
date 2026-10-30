import fs from 'node:fs';
import path from 'node:path';

// Only public names and publication identifiers cross the report boundary.
export function reportContext(publicDir){
 try{
  const p=JSON.parse(fs.readFileSync(path.join(publicDir,'current.json'),'utf8'));
  const page=p.pages?.find(x=>x.page_id==='seasonal-vault'&&x.activity_id==='mmoexp-seasonal');
  if(!page)return null;
  const games=(p.halloween?.games||[]).map(g=>({id:String(g.admin_game_id),name:g.label}));
  const models={},products={};
  for(const item of p.products||[]){
   const r=item.product_ref||{},name=item.title||item.name;
   if(typeof name!=='string'||!name.trim())continue;
   if(r.game_id&&r.model_id)models[r.game_id+':'+r.model_id]=name;
   if(r.goods_id)products[r.goods_id]=name;
  }
  return {activityId:'mmoexp-seasonal',name:'万圣节神秘商店',url:'https://www.mmoexp.com/events/seasonal/',releaseId:p.release_id,configHash:p.config_hash,active:page.active===true&&p.halloween?.status==='configured',startsAt:p.halloween?.starts_at,endsAt:p.halloween?.ends_at,games,models,products,checkout:'not_integrated',payment:'not_integrated',traffic:{status:'not_connected',pageRequests:null,estimatedVisitors:null,reason:'TRUSTED_EDGE_AGGREGATE_REQUIRED',visitorBasis:'distinct_ip_not_people',periodDistinct:'separate_from_daily_sum'}};
 }catch{return null;}
}

export function eventDiagnostics(events,filter){
 const rows=events.filter(e=>{const p=e.properties||{},date=e.timestamp.slice(0,10);return (!filter.activity||filter.activity==='all'||p.activity_id===filter.activity)&&date>=filter.from&&date<=filter.to&&['device','platform','source','game'].every(k=>!filter[k]||filter[k]==='all'||String(p[k==='game'?'game_id':k])===filter[k]);});
 const counts={},ids=new Set();let latest=null;
 for(const e of rows){const id=e.properties?.event_id;if(id&&ids.has(id))continue;if(id)ids.add(id);counts[e.event]=(counts[e.event]||0)+1;if(!latest||Date.parse(e.timestamp)>Date.parse(latest))latest=e.timestamp;}
 return {environment:filter.mode==='test'?'test':'production',eventCount:Object.values(counts).reduce((a,b)=>a+b,0),lastEventAt:latest,eventCounts:counts};
}
