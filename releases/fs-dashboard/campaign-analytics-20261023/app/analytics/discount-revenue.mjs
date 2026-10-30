import {backendRead} from './backend-client.mjs';

// One cache for authoritative orders, independent from browser events and their consent state.
export function makeDiscountRevenue(read=backendRead,clock=Date.now){
 const cache=new Map(),pending=new Map();
 return async function(params){
  const filter=Object.fromEntries(params),allowed=new Set(['activity','mode','from','to','game','refresh']);
  const validDate=v=>/^\d{4}-\d{2}-\d{2}$/.test(v||'')&&Number.isFinite(Date.parse(v))&&new Date(v).toISOString().slice(0,10)===v;
  if(Object.keys(filter).some(k=>!allowed.has(k))||filter.activity!=='mmoexp-seasonal'||filter.mode!=='live'||!validDate(filter.from)||!validDate(filter.to)||filter.from>filter.to||Date.parse(filter.to)-Date.parse(filter.from)>30*86400000||!['all','1327','891','1333','456'].includes(filter.game||'all')||filter.refresh&&!['0','1'].includes(filter.refresh))return {status:400,body:{status:'invalid',message:'活动码收入筛选无效'}};
  const request={action:'discount_revenue',site_id:'266',from:filter.from,to:filter.to,game:filter.game||'all'},key=JSON.stringify(request),cached=cache.get(key);
  if(filter.refresh!=='1'&&cached&&clock()-cached.at<600000)return {status:200,body:cached.body};
  if(pending.has(key))return pending.get(key);
  // Bound all windows together; do not make different filters queue behind an unbounded sweep.
  if(pending.size)return {status:503,body:{status:'busy',message:'活动码收入正在查询，请稍后更新'}};
  const work=(async()=>{try{
   const body=await Promise.resolve().then(()=>read(request));
   if(body?.status!=='available'||body.coverage?.complete!==true)throw Error('INCOMPLETE_ORDER_REVENUE');
   if(cache.size>=32)cache.clear();cache.set(key,{at:clock(),body});return {status:200,body};
  }catch(error){return {status:502,body:{status:'unavailable',message:'活动码付款订单读取未完成，请稍后更新；未完成不记为零。',reason:/^[A-Z_]{3,100}$/.test(error.message)?error.message:'ORDER_SOURCE_UNAVAILABLE'}};}finally{pending.delete(key);}})();
  pending.set(key,work);return work;
 };
}
