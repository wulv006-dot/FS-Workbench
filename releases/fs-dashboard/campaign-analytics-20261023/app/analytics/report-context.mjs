import fs from 'node:fs';
import path from 'node:path';
import core from './funnel-core.cjs';
import {CARNIVAL} from '../runtime/carnival.mjs';

export const carnivalContext={
 activityId:'mmoexp-carnival',name:'狂欢盛典 2026',url:'https://www.mmoexp.com/events/Carnival.html',
 releaseId:'carnival-2026',configHash:'carnival-2026-v1',active:true,startsAt:CARNIVAL.starts_at,endsAt:CARNIVAL.ends_at,
 games:[],checkout:'existing_main_cart',payment:'coupon_use_log',traffic:{status:'not_integrated'}
};

// Only public names and publication identifiers cross the report boundary.
export function reportContext(publicDir,activity='mmoexp-seasonal'){
 if(activity===carnivalContext.activityId)return carnivalContext;
 try{
  const p=JSON.parse(fs.readFileSync(path.join(publicDir,'current.json'),'utf8'));
  const fc=core.canonicalActivity(activity)==='fc27-season2';
  const page=p.pages?.find(x=>fc?['fc27-weekly','fc27-sbc','fc27-trio'].includes(x.page_id):x.page_id==='seasonal-vault'&&x.activity_id==='mmoexp-seasonal');
  if(!page)return null;
  const games=(p.halloween?.games||[]).map(g=>({id:String(g.admin_game_id),name:g.label}));
  const models={},products={};
  for(const item of p.products||[]){
   const r=item.product_ref||{},name=item.title||item.name;
   if(fc&&String(r.game_id)!=='1327')continue;
   if(typeof name!=='string'||!name.trim())continue;
   if(r.game_id&&r.model_id)models[r.game_id+':'+r.model_id]=name;
   if(r.goods_id)products[r.goods_id]=name;
  }
  return {activityId:fc?'fc27-season2':'mmoexp-seasonal',name:fc?'FC27 周更活动（三页合计）':'万圣节神秘商店',url:fc?'https://www.mmoexp.com/events/Weekly-Scout.html':'https://www.mmoexp.com/events/seasonal/index.html',releaseId:p.release_id,configHash:p.config_hash,active:fc?p.pages.some(x=>['fc27-weekly','fc27-sbc','fc27-trio'].includes(x.page_id)&&x.active===true):page.active===true&&p.halloween?.status==='configured',startsAt:fc?null:p.halloween?.starts_at,endsAt:fc?null:p.halloween?.ends_at,games:fc?[{id:'1327',name:'FC 27'}]:games,models,products,checkout:fc?'existing_main_cart':'not_integrated',payment:fc?'dedicated_discount_code_paid_order':'not_integrated',traffic:{status:'separate_query',source:'existing_origin_access_log',pageRequests:null,estimatedVisitors:null,reason:'ORIGIN_LOG_QUERY_REQUIRED',visitorBasis:'unverified_proxy_chain',periodDistinct:'separate_from_daily_sum'}};
 }catch{return null;}
}

export function eventDiagnostics(events,filter){
 const rows=events.filter(e=>{const p=e.properties||{},date=e.timestamp.slice(0,10);return core.activityMatches(filter.activity,p.activity_id)&&date>=filter.from&&date<=filter.to&&['device','platform','source','game'].every(k=>!filter[k]||filter[k]==='all'||String(p[k==='game'?'game_id':k])===filter[k]);});
 const counts={},ids=new Set();let latest=null;
 for(const e of rows){const id=e.properties?.event_id;if(id&&ids.has(id))continue;if(id)ids.add(id);counts[e.event]=(counts[e.event]||0)+1;if(!latest||Date.parse(e.timestamp)>Date.parse(latest))latest=e.timestamp;}
 return {environment:filter.mode==='test'?'test':'production',eventCount:Object.values(counts).reduce((a,b)=>a+b,0),lastEventAt:latest,eventCounts:counts};
}
