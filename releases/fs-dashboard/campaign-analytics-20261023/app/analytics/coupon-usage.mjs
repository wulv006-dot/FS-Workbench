import {backendRead} from './backend-client.mjs';
import {carnivalContext} from './report-context.mjs';
import {transientFailure} from './statistics-retry.mjs';

// Use and conversion of the unified FC27 activity coupon, read from the Admin coupon record and
// its use log. It sits next to the dedicated-code revenue and never replaces or adds into it.
const PAGES=['fc27-weekly','fc27-trio','fc27-sbc','fc27-season2'];
const CARNIVAL=carnivalContext.activityId,MODULES=['home','mystery','blackFriday','capsule'];
const ORDER_COUNTS=['used_orders','paid_orders','refunded_orders','unpaid_orders','paid_usd_minor','discount_usd_minor'];
const COUNTS=[...ORDER_COUNTS,'repurchase_orders','repurchase_usd_minor','unique_buyers'];
const safe=v=>Number.isSafeInteger(v)&&v>=0;
function valid(body,activity){
 if(activity===CARNIVAL)return body?.status==='available'&&body.activity_id===activity&&body.coverage?.complete===true
  &&safe(body.coverage.orders_unmatched)&&Array.isArray(body.modules)&&body.modules.length===MODULES.length
  &&MODULES.every(id=>body.modules.some(m=>m?.module===id&&['issued_total','used_total',...COUNTS].every(k=>safe(m[k]))))
  &&(body.games===undefined||Array.isArray(body.games)&&body.games.every(g=>g&&(g.game_id===null||typeof g.game_id==='string'&&/^[1-9][0-9]{0,19}$/.test(g.game_id))
   &&(g.game_name===null||typeof g.game_name==='string'&&g.game_name.length<=120)&&ORDER_COUNTS.every(k=>safe(g[k]))));

 return body?.status==='available'&&body.activity_id==='fc27-season2'&&body.coverage?.complete===true&&body.coupon?.coupon_id==='1395'
  &&safe(body.coupon.issued_total)&&safe(body.coupon.used_total)&&COUNTS.every(k=>safe(body.totals?.[k]))&&Array.isArray(body.daily);
}
export function makeCouponUsage(read=backendRead,clock=Date.now){
 const cache=new Map(),pending=new Map();
 return async function(params){
  const filter=Object.fromEntries(params),allowed=new Set(['activity','mode','from','to','refresh']);
  const validDate=v=>/^\d{4}-\d{2}-\d{2}$/.test(v||'')&&Number.isFinite(Date.parse(v))&&new Date(v).toISOString().slice(0,10)===v;
  if(Object.keys(filter).some(k=>!allowed.has(k))||(filter.activity!==CARNIVAL&&!PAGES.includes(filter.activity))||filter.mode!=='live'||!validDate(filter.from)||!validDate(filter.to)||filter.from>filter.to||Date.parse(filter.to)-Date.parse(filter.from)>30*86400000||filter.refresh&&!['0','1'].includes(filter.refresh))return {status:400,body:{status:'invalid',message:'活动券筛选无效'}};
  const start=Date.parse(carnivalContext.startsAt);
  if(filter.activity===CARNIVAL&&(clock()<start||Date.parse(filter.to)+86400000<=start))
   return {status:200,body:{status:'not_started',message:'所选区间尚未开始统计。'}};
  const request={action:'coupon_usage',site_id:'266',from:filter.from,to:filter.to,activity:filter.activity===CARNIVAL?CARNIVAL:'fc27-season2'},key=JSON.stringify(request),cached=cache.get(key);
  if(filter.refresh!=='1'&&cached&&clock()-cached.at<600000)return {status:200,body:cached.body};
  if(pending.has(key))return pending.get(key);
  if(pending.size)return {status:503,body:{status:'busy',message:'活动券使用正在查询，请稍后更新'}};
  const work=(async()=>{try{
   const body=await Promise.resolve().then(()=>read(request));
   if(!valid(body,request.activity))throw Error('INCOMPLETE_COUPON_USAGE');
   if(cache.size>=32)cache.clear();cache.set(key,{at:clock(),body});return {status:200,body};
  }catch(error){return {status:502,body:{status:'unavailable',message:'活动券使用记录读取未完成，请稍后更新；未完成不记为零。',...(transientFailure(error)||{reason:/^[A-Z_]{3,100}$/.test(error.message)?error.message:'COUPON_SOURCE_UNAVAILABLE'})}};}finally{pending.delete(key);}})();
  pending.set(key,work);return work;
 };
}
