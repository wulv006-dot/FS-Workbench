'use strict';
const {need,grantResult}=require('./core.cjs');
const BASE='http://127.0.0.1:8911'; // Existing chenchaoapi HMAC proxy; credentials never leave its process.
async function request(path,body){
 const r=await fetch(BASE+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(95000),redirect:'error'});
 if(!r.ok)throw Error('优惠券后台 HTTP '+r.status);const raw=await r.text();need(raw.length<2000000,'后台响应过大');const d=JSON.parse(raw);
 need(d.code===1,'优惠券后台未确认本次操作');return d.data;
}
const FIELDS=['id','title','type','fetch_scene','status','mode_type','attain','reduce','max_reduce','limit_qty','repeat_qty','time_effect','start_time','end_time','days','site_id','game_id','product_type','goods_id','scope_bindings','is_open'];
async function detail(id){const d=await request('/admin/market.Coupon/edit?id='+id);need(d.row&&Number(d.row.id)===Number(id),'优惠券详情不匹配');return Object.fromEntries(FIELDS.filter(k=>k in d.row).map(k=>[k,d.row[k]]));}
function validate(row){need(row.fetch_scene===4&&row.status===1,'请选择已启用的后台定向券');need([0,266].includes(Number(row.site_id)),'此券不属于 MMOEXP 站点');
 if(row.time_effect===1&&row.end_time&&Date.parse(row.end_time.replace(' ','T')+'+08:00')<Date.now())throw Error('该券已过期');return row;}
async function grant(couponId,address,batch){const d=await request('/admin/market.CouponGrant/import',{site_id:266,coupon_id:couponId,grant_batch_no:batch,emails:address});return grantResult(d,address,batch);}
async function reconcile(w){need(w.job_id,'没有后台任务编号，需人工核对原批次，禁止重发');const d=await request('/admin/market.CouponGrant/jobStatus?job_id='+encodeURIComponent(w.job_id));return grantResult(d,w.email,w.batch,w.job_id);}
module.exports={detail,validate,grant,reconcile};
