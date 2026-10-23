import {randomBytes} from 'node:crypto';
const csrf=randomBytes(24).toString('hex'),receipts=new Map();
export const allowedTestEvents=new Set(['activity_view','activity_product_view','activity_click','activity_selection','activity_review','activity_scroll','activity_engaged','prediction_match_view','prediction_started']);
const send=(res,status,body)=>{res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(body));};
export async function connection(req,res,url,cfg,clearCache){
 if(!['/analytics/api/connection','/analytics/api/test-event'].includes(url.pathname))return false;
 const expected='http://127.0.0.1:'+(process.env.PORT||8522);
 if(req.headers.host!==new URL(expected).host){send(res,403,{status:'forbidden'});return true;}
 if(req.method==='GET'&&url.pathname.endsWith('/connection')){send(res,200,{csrf,projectId:cfg.projectId,region:'US',configured:!!process.env.POSTHOG_QUERY_KEY,storage:'process-memory-only',receipts:[...receipts.values()].slice(-8)});return true;}
 if(req.method!=='POST'||req.headers.origin!==expected||req.headers['content-type']!=='application/json'){send(res,403,{status:'forbidden'});return true;}
 let data;try{let body='';for await(const chunk of req){body+=chunk;if(Buffer.byteLength(body)>16000)throw Error('oversize');}data=JSON.parse(body);if(data.csrf!==csrf)throw Error('csrf');}catch{send(res,400,{status:'invalid_request'});return true;}
 if(url.pathname.endsWith('/connection')){
  if(typeof data.key!=='string'||!/^phx_[A-Za-z0-9_-]{20,200}$/.test(data.key)){send(res,400,{status:'invalid',message:'请输入有效的 Personal API Key（phx_ 开头）'});return true;}
  process.env.POSTHOG_QUERY_KEY=data.key;process.env.POSTHOG_PROJECT_ID=cfg.projectId;process.env.POSTHOG_QUERY_HOST='https://us.posthog.com';clearCache();send(res,200,{status:'configured',message:'已保存到当前服务进程内存；未写文件，服务重启后需重新录入。'});return true;
 }
 const event=data.event,p=data.properties||{},id=p.event_id;
 if(!allowedTestEvents.has(event)||!cfg.registry.some(a=>a.id===p.activity_id)||!/^[a-f0-9-]{36}$/.test(id||'')||!/^[a-f0-9-]{36}$/.test(p.activity_visit_id||'')){send(res,400,{status:'invalid_event'});return true;}
 if(receipts.has(id)){send(res,200,receipts.get(id));return true;}
 if(receipts.size>=1500){send(res,429,{status:'limit',message:'本次联调已达1500条，请先完成核对。'});return true;}
 const fields=['activity_id','activity_visit_id','activity_session_id','catalog_version','view','platform','language','device','source','campaign','product_id','product_ids','include_sbc','core_id','action','active_seconds','depth','target','event_id','match_id'];
 const properties=Object.fromEntries(fields.filter(k=>p[k]!==undefined).map(k=>[k,p[k]]));
 properties.environment='test';properties.schema_version=1;properties.$process_person_profile=false;
 const distinct='fc-local-test-'+(p.activity_session_id||p.activity_visit_id),timestamp=new Date().toISOString();
 const receipt={eventId:id,event,activityId:p.activity_id,status:'sending',timestamp};receipts.set(id,receipt);
 try{const response=await fetch('https://us.i.posthog.com/i/v0/e/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:cfg.projectToken,event,distinct_id:distinct,uuid:id,timestamp,properties}),signal:AbortSignal.timeout(20000)});
  receipt.status=response.ok?'accepted':'rejected';receipt.httpStatus=response.status;
 }catch(error){receipt.status='unknown';receipt.errorCode=error.cause?.code||error.name;}
 // Preserve the original event id after timeout; never turn an unknown write into an automatic retry.
 clearCache();send(res,receipt.status==='accepted'?200:502,receipt);return true;
}
