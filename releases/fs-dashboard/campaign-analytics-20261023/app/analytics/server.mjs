// Local preview + read-only PostHog adapter. Mount handler behind FS authentication for production.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import core from './funnel-core.cjs';
import {connection} from './connection.mjs';
const base=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const sandbox={window:{}};vm.runInNewContext(fs.readFileSync(path.join(base,'analytics-config.js'),'utf8'),sandbox);
const registry=core.validateRegistry(sandbox.window.FC_ANALYTICS_CONFIG.registry);
const cache=new Map();let pending=null;
export async function report(params,options={}){
 const token=options.token||process.env.POSTHOG_QUERY_KEY,project=options.project||process.env.POSTHOG_PROJECT_ID,host=options.host||process.env.POSTHOG_QUERY_HOST||'https://us.posthog.com';
 if(!token||!/^\d+$/.test(project||''))return {status:503,body:{status:'not_configured',message:'缺少 PostHog 项目 ID 或只读查询密钥'}};
 if(!['https://us.posthog.com','https://eu.posthog.com'].includes(host))throw Error('Unsupported PostHog host');
 const filter=Object.fromEntries(params),ids=core.validateRegistry(options.registry||registry).map(a=>a.id);
 if(filter.activity!=='all'&&!ids.includes(filter.activity))return {status:400,body:{status:'invalid',message:'活动未部署到服务端白名单'}};
 const validDate=v=>/^\d{4}-\d{2}-\d{2}$/.test(v||'')&&Number.isFinite(Date.parse(v))&&new Date(v).toISOString().slice(0,10)===v;
 if(!validDate(filter.from)||!validDate(filter.to)||filter.from>filter.to||Date.parse(filter.to)-Date.parse(filter.from)>30*86400000)return {status:400,body:{status:'invalid',message:'日期必须有效，且最多查询 31 天'}};
 const environment=filter.mode==='test'?'test':'production';
 const key=JSON.stringify([filter,ids,options.revision||0]),cached=cache.get(key);if(cached&&Date.now()-cached.time<(environment==='test'?3000:300000))return cached.value;
 if(pending)return {status:503,body:{status:'busy',message:'已有查询进行中，请稍后重试'}};
 pending=true;
 try{
  const hours=Number(filter.windowHours)||(filter.template==='reward'?720:24);if(!Number.isInteger(hours)||hours<1||hours>720||filter.template&&!core.templates[filter.template])throw Error('Invalid funnel configuration');
  const end=new Date(Date.parse(filter.to)+(1+Math.ceil(hours/24))*86400000).toISOString().slice(0,10),names=[...new Set(Object.values(core.templates).flatMap(t=>t.steps)),'activity_engaged','activity_click','activity_selection','activity_review'];
  // Bounded raw extraction; refuse capped results rather than display partial counts as complete.
  const fields=['distinct_id','activity_id','activity_visit_id','activity_session_id','source','device','platform','event_id','product_id','product_ids','active_seconds','include_sbc','order_key','currency','activity_paid_minor','match_id','reward_journey_id'];
  const query=`SELECT event, timestamp, ${fields.map(k=>k==='distinct_id'?'distinct_id':'properties.'+k).join(', ')} FROM events WHERE timestamp >= toDateTime('${filter.from} 00:00:00') AND timestamp < toDateTime('${end} 00:00:00') AND properties.environment = '${environment}' AND properties.activity_id IN (${ids.map(x=>"'"+x+"'").join(',')}) AND event IN (${names.map(x=>"'"+x+"'").join(',')}) ORDER BY timestamp LIMIT 50000`;
  const response=await fetch(`${host}/api/projects/${project}/query/`,{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({query:{kind:'HogQLQuery',query},refresh:'force_blocking'}),signal:AbortSignal.timeout(15000)});
  if(!response.ok)throw Error('PostHog query returned '+response.status);
  const data=await response.json();if(!Array.isArray(data.results))throw Error('Unexpected query response');
  if(data.results.length>=50000||data.hasMore||data.has_more||data.error)throw Error('Query incomplete or exceeds 50,000 events; narrow the date range');
  const events=data.results.map(row=>({event:row[0],timestamp:row[1].replace(' ','T')+(/Z$|[+-]\d\d:\d\d$/.test(row[1])?'':'Z'),properties:Object.fromEntries(fields.map((k,i)=>[k,row[i+2]]))}));
  for(const e of events){const p=e.properties;for(const k of ['product_ids','include_sbc','active_seconds','activity_paid_minor'])if(typeof p[k]==='string'){try{p[k]=JSON.parse(p[k]);}catch{p[k]=null;}}if(!Array.isArray(p.product_ids))p.product_ids=[];p.include_sbc=p.include_sbc===true;}
  const value={status:200,body:{status:'available',eventCount:events.length,eventTypes:[...new Set(events.map(e=>e.event))],generatedAt:new Date().toISOString(),coverage:'有界查询完成；浏览器拦截与未授权流量不在覆盖内',report:core.summarize(events,filter)}};
  if(cache.size>30)cache.clear();cache.set(key,{time:Date.now(),value});return value;
 }finally{pending=null;}
}
export const server=http.createServer(async(req,res)=>{
 if(req.headers.host!=='127.0.0.1:'+(process.env.PORT||8522)){res.writeHead(403);res.end();return;}
 const url=new URL(req.url,'http://localhost');
 if(await connection(req,res,url,sandbox.window.FC_ANALYTICS_CONFIG,()=>cache.clear()))return;
 if(req.method!=='GET'){res.writeHead(405);res.end();return;}
 if(url.pathname==='/analytics/api/report'){try{const result=await report(url.searchParams);res.writeHead(result.status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(result.body));}catch(error){res.writeHead(502,{'Content-Type':'application/json'});res.end(JSON.stringify({status:'error',message:error.message}));}return;}
 let requested;try{requested=decodeURIComponent(url.pathname);}catch{res.writeHead(400);res.end();return;}
 const file=path.resolve(base,'.'+requested+(requested.endsWith('/')?'index.html':''));
 const ext=path.extname(file),types={'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript','.cjs':'text/javascript','.json':'application/json','.md':'text/plain; charset=utf-8','.png':'image/png','.webp':'image/webp','.svg':'image/svg+xml'};
 if(!file.startsWith(base+path.sep)||!types[ext]||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
 res.writeHead(200,{'Content-Type':types[ext],'Cache-Control':'no-store'});fs.createReadStream(file).pipe(res);
});
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){server.listen(Number(process.env.PORT||8522),'127.0.0.1',()=>console.log('Preview: http://127.0.0.1:'+(process.env.PORT||8522)+'/analytics/'));}
