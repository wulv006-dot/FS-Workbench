import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import {randomBytes} from 'node:crypto';
import {report} from './server.mjs';
import {atomic,makeStore,previewCatalog} from './store.mjs';
const base=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),box={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(base,'analytics-config.js'),'utf8'),box);
const cfg=box.window.FC_ANALYTICS_CONFIG,catalog=JSON.parse(fs.readFileSync(path.join(base,'catalog.json'),'utf8'));
const prefix=process.env.CAMPAIGN_PREFIX||'/dashboard/analytics/campaigns/',origin=process.env.CAMPAIGN_ORIGIN||'https://47.85.224.112',dir=process.env.CAMPAIGN_DATA||'/var/lib/fs-campaign-dashboard';
const store=makeStore(dir,catalog,cfg.registry),secretFile=path.join(dir,'posthog-secret.json'),csrf=randomBytes(32).toString('hex');
const secret=()=>fs.existsSync(secretFile)?JSON.parse(fs.readFileSync(secretFile,'utf8')).key:null;
const json=(res,status,body)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(JSON.stringify(body));};
const publicState=s=>({revision:s.revision,registry:s.registry,layout:s.layout,updatedAt:s.updatedAt,updatedBy:s.updatedBy});
const publicNames=new Set(['index.html','Weekly-Scout.html','Sbc-Companions.html','Player-Trio.html','activity.css','activity.js','activity-core.js','activity-content.js','host-adapter.js','activity-analytics.js','ANALYTICS-INTEGRATION.md','MATCHDAY-ANALYTICS-PLAN.md','analytics/index.html','analytics/connect.html','analytics/connect.js','analytics/dashboard.js','analytics/dashboard.css','analytics/fs-tokens.css','analytics/fs-ui.css','analytics/funnel-core.cjs','analytics/demo-data.js','analytics/server-client.js','analytics/products.html','analytics/products.js']);
export async function authorize(req){
 const r=await fetch('http://127.0.0.1:8895/verify?group=dashboard',{headers:{Cookie:req.headers.cookie||'','X-Original-Method':req.method,'X-Original-URI':req.url},signal:AbortSignal.timeout(5000),redirect:'manual'});
 return {status:r.status,user:r.headers.get('x-auth-user'),admin:r.headers.get('x-auth-role')==='admin'};
}
export const server=http.createServer(async(req,res)=>{
 try{
  if(!['127.0.0.1','::ffff:127.0.0.1','::1'].includes(req.socket.remoteAddress))return json(res,403,{message:'仅允许反向代理入口'});
  const auth=await authorize(req);if(auth.status!==200||!auth.user)return json(res,auth.status===401?401:403,{message:'请使用 FS 原有登录及权限'});
  const url=new URL(req.url,'http://localhost');if(!url.pathname.startsWith(prefix))return json(res,404,{message:'Not found'});
  const relative=decodeURIComponent(url.pathname.slice(prefix.length));
  if(req.method!=='GET'&&req.method!=='HEAD'){
   if(req.method!=='POST'||!auth.admin)return json(res,403,{message:'仅现有管理员可保存配置'});
   if(req.headers.origin!==origin||req.headers['content-type']!=='application/json'||req.headers['x-csrf-token']!==csrf)return json(res,403,{message:'请求来源或会话校验失败，请刷新页面'});
   let raw='';for await(const chunk of req){raw+=chunk;if(Buffer.byteLength(raw)>300000)return json(res,413,{message:'配置过大'});}const body=JSON.parse(raw);
   if(relative==='analytics/api/config'){let saved;try{saved=store.save(body,auth.user);}catch(error){if(!error.code&&!error.status)error.status=400;throw error;}return json(res,200,{status:'saved',...publicState(saved)});}
   if(relative==='analytics/api/connection'){
    if(!/^phx_[A-Za-z0-9_-]{20,200}$/.test(body.key||''))return json(res,400,{message:'密钥格式无效'});
    const date=new Date().toISOString().slice(0,10),r=await report(new URLSearchParams({activity:'all',mode:'test',from:date,to:date}),{token:body.key,project:cfg.projectId,registry:store.read().registry,revision:'verify-'+randomBytes(8).toString('hex')});
    if(r.status!==200)return json(res,r.status,{message:'只读查询验证失败，原连接保留'});
    atomic(secretFile,{key:body.key,updatedAt:new Date().toISOString(),updatedBy:auth.user});return json(res,200,{status:'configured',message:'只读查询通过，密钥已保存在服务器'});
   }
   return json(res,404,{message:'Not found'});
  }
  if(relative==='analytics/api/connection')return json(res,200,{configured:!!secret(),csrf:auth.admin?csrf:null,canEdit:auth.admin,storage:'server-persistent',projectId:cfg.projectId});
  if(relative==='analytics/api/config')return json(res,200,{...publicState(store.read()),csrf:auth.admin?csrf:null,canEdit:auth.admin});
  if(relative==='analytics/api/report'){const state=store.read();const result=await report(url.searchParams,{token:secret(),project:cfg.projectId,registry:state.registry,revision:state.revision});return json(res,result.status,result.body);}
  if(relative==='analytics/api/catalog')return json(res,200,{catalog, ...publicState(store.read())});
  if(relative==='analytics/api/export')return json(res,200,{...publicState(store.read()),catalog:previewCatalog(catalog,store.read().layout),notice:'仅配置导出，原站仍需构建 SEO 和网站开发发布'});
  let body,type;
  if(relative==='catalog.js'){body='window.FC_ACTIVITY_CONFIG='+JSON.stringify(previewCatalog(catalog,store.read().layout)).replace(/</g,'\\u003c')+';';type='text/javascript';}
  else if(relative==='analytics-config.js'){body='window.FC_ANALYTICS_CONFIG='+JSON.stringify({...cfg,enabled:false,localPreviewJournal:false,serverManaged:true,registry:store.read().registry}).replace(/</g,'\\u003c')+';';type='text/javascript';}
  else {
   const name=relative==='analytics/'?'analytics/index.html':relative||'index.html';if(!publicNames.has(name)&&!/^assets\/[A-Za-z0-9_.-]+\.(webp|png|svg)$/.test(name))return json(res,404,{message:'Not found'});
   const file=path.join(base,name);if(!fs.existsSync(file))return json(res,404,{message:'Not found'});
   type=({'.html':'text/html; charset=utf-8','.js':'text/javascript','.cjs':'text/javascript','.css':'text/css','.md':'text/plain; charset=utf-8','.webp':'image/webp','.png':'image/png','.svg':'image/svg+xml'})[path.extname(file)];body=fs.readFileSync(file);
   if(name.startsWith('analytics/')&&name.endsWith('.html'))body=body.toString().replace(/href="(fs-tokens|fs-ui)\.css"/g,'href="/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/ui/$1.css"');
   if(name==='analytics/index.html')body=body.replace(/<option value="(?:demo|local)">[^<]*<\/option>/g,'').replace('<script src="demo-data.js"></script>','');
  }
  res.writeHead(200,{'Content-Type':type,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin','X-Frame-Options':'SAMEORIGIN'});res.end(req.method==='HEAD'?undefined:body);
 }catch(error){json(res,error.status||502,{status:'error',message:error.name==='SyntaxError'?'配置格式无效':error.message});}
});
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))server.listen(Number(process.env.PORT||8948),'127.0.0.1',()=>console.log('FS campaign service listening on loopback'));
