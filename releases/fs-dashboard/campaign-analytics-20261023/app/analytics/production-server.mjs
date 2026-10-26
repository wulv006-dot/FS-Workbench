import {emptyHalloween} from '../runtime/halloween-contract.mjs';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import {randomBytes} from 'node:crypto';
import {report} from './server.mjs';
import {atomic,makeStore,previewCatalog,validateLayout} from './store.mjs';
import {makeCenterStore} from './center-store.mjs';
import {centerSeed,effectivePageBindings} from './center-seed.mjs';
import {backendRead,backendMutate} from './backend-client.mjs';
import {effectiveFcCatalog} from '../runtime/model-cards.mjs';
import {mediaLimits,pageMedia} from '../runtime/media-contract.mjs';
import {digest,loadStatic} from '../runtime/snapshot.mjs';
import {presentPage,projectFcCatalog,publicEnglishRelease} from '../runtime/presentation.mjs';
import {makeAdminPriceProvider,readAdminPricePolicy} from './admin-price-provider.mjs';
const base=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),box={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(base,'analytics-config.js'),'utf8'),box);
const cfg=box.window.FC_ANALYTICS_CONFIG,catalog=JSON.parse(fs.readFileSync(path.join(base,'catalog.json'),'utf8'));
const prefix=process.env.CAMPAIGN_PREFIX||'/dashboard/analytics/campaigns/',origin=process.env.CAMPAIGN_ORIGIN||'https://47.85.224.112',dir=process.env.CAMPAIGN_DATA||'/var/lib/fs-campaign-dashboard';
const store=makeStore(dir,catalog,cfg.registry),secretFile=path.join(dir,'posthog-secret.json'),csrf=randomBytes(32).toString('hex');
const seasonalBox={};vm.runInNewContext(fs.readFileSync(path.join(base,'seasonal/campaign-data.js'),'utf8'),seasonalBox);
const publicDir=process.env.CAMPAIGN_PUBLIC_RELEASE_DIR||'/var/lib/fs-campaign-public';
const adminPrices=makeAdminPriceProvider({publicDir,readPolicy:()=>readAdminPricePolicy(process.env.CAMPAIGN_BACKEND_STATE_DIR||path.join(dir,'backend'))});
const validateFcLayout=(layout,models={})=>validateLayout(layout,effectiveFcCatalog(catalog,models));
export function readNativeCheckoutPolicy(stateDir){
 const file=path.join(stateDir,'policy.json');if(!fs.existsSync(file))return {status:'unconfigured'};
 const d=fs.lstatSync(stateDir),s=fs.lstatSync(file);if(d.isSymbolicLink()||!d.isDirectory()||s.isSymbolicLink()||!s.isFile()||s.size>250000||process.platform!=='win32'&&((d.mode&0o077)!==0||(s.mode&0o077)!==0))throw Error('PRIVATE_NATIVE_POLICY_REQUIRED');
 return JSON.parse(fs.readFileSync(file,'utf8')).native_checkout??{status:'unconfigured'};
}
const center=makeCenterStore({dir:path.join(dir,'center'),publicDir,nativeCheckoutProvider:()=>readNativeCheckoutPolicy(process.env.CAMPAIGN_BACKEND_STATE_DIR||path.join(dir,'backend')),sourceRevision:process.env.CAMPAIGN_SOURCE_REVISION||'unreleased',validateFcLayout,
 seedProvider:(layout,models={})=>centerSeed(previewCatalog(effectiveFcCatalog(catalog,models),layout??store.read().layout),seasonalBox.SeasonalData,adminPrices.seedOptions())});
const centerState=s=>{const effective=effectiveFcCatalog(catalog,s.draft.fc_models||{}),layout=validateFcLayout(s.draft.fc_layout??store.read().layout,s.draft.fc_models||{}),seed=centerSeed(previewCatalog(effective,layout),seasonalBox.SeasonalData,adminPrices.seedOptions());return {revision:s.revision,draft:s.draft,effective_halloween:s.draft.halloween??emptyHalloween(),effective_fc_layout:layout,restore_candidate:center.restoreCandidate(s),published:s.published,updated_at:s.updated_at,updated_by:s.updated_by,admin_provider_status:adminPrices.status(),
 fc_catalog:{products:Object.fromEntries(Object.entries(effective.products).map(([key,p])=>[key,{key:p.key,title:p.title,name:p.name,kind:p.kind,version:p.version,...(p.preview_only?{preview_only:true,model_id:p.model_id,image:p.image,platforms:p.platforms}:{})}])),trio:{series:catalog.trio.series},sbc:{fallbackPicks:catalog.sbc.fallbackPicks}},
 catalog_products:seed.seedProducts.map(p=>{const match=/^fc-(.+)-(ps|xbox|pc)$/.exec(p.key);return {...p,display_kind:match?effective.products[match[1]]?.kind:'seasonal'};}),page_product_keys:seed.pageProductKeys,
 page_bindings:Object.fromEntries(s.draft.pages.map(p=>[p.page_id,effectivePageBindings(s.draft,seed,p.page_id)])),media_limits:mediaLimits,
 capabilities:{catalog_source:'accepted_design_snapshot',live_checkout:false,authoritative_quote:false,coupon_mutation:false},
 csrf:undefined};};
const secret=()=>fs.existsSync(secretFile)?JSON.parse(fs.readFileSync(secretFile,'utf8')).key:null;
const json=(res,status,body)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(JSON.stringify(body));};
const publicState=s=>({revision:s.revision,registry:s.registry,layout:s.layout,updatedAt:s.updatedAt,updatedBy:s.updatedBy});
const publicNames=new Set(['index.html','Weekly-Scout.html','Sbc-Companions.html','Player-Trio.html','activity.css','activity.js','activity-core.js','activity-content.js','host-adapter.js','native-code-handoff.js','activity-analytics.js','ANALYTICS-INTEGRATION.md','MATCHDAY-ANALYTICS-PLAN.md','analytics/index.html','analytics/connect.html','analytics/connect.js','analytics/dashboard.js','analytics/dashboard.css','analytics/fs-tokens.css','analytics/fs-ui.css','analytics/funnel-core.cjs','analytics/demo-data.js','analytics/server-client.js','analytics/products.html','analytics/products.js']);
publicNames.add('analytics/operations.html');publicNames.add('analytics/operations.js');
const previews=new Map();let previewFiles=null;
function filesForPreview(){
 if(previewFiles)return previewFiles;
 const names=['index.html','Weekly-Scout.html','Sbc-Companions.html','Player-Trio.html','catalog.js','activity.js','activity-core.js','activity-content.js','activity.css','host-adapter.js','native-code-handoff.js','standalone-adapter.js','analytics-config.js','activity-analytics.js','seasonal/index.html','seasonal/event.js','seasonal/event.css','seasonal/model-selection.js','seasonal/runtime-bridge.js','seasonal/campaign-data.js'];
 for(const folder of ['assets','seasonal/assets'])for(const name of fs.readdirSync(path.join(base,folder)))if(/\.(png|webp|svg|jpg|jpeg|woff2)$/.test(name))names.push(folder+'/'+name);
 previewFiles=loadStatic(base,Object.fromEntries(names.map(name=>[name,digest(fs.readFileSync(path.join(base,name)))])));return previewFiles;
}
async function pendingModelDetails(body){
 const entries=Object.hasOwn(body,'model_imports')?body.model_imports:[];if(!Array.isArray(entries)||entries.length>30)throw Object.assign(Error('INVALID_MODEL_IMPORTS'),{status:400});const details=[],cache=new Map();
 for(const entry of entries){if(!entry||Object.keys(entry).some(k=>!['page_id','model_id','kind'].includes(k))||!['fc27-weekly','fc27-sbc','fc27-trio'].includes(entry.page_id)||!['player','sbc','bundle'].includes(entry.kind)||typeof entry.model_id!=='string'||!/^[1-9]\d{0,19}$/.test(entry.model_id))throw Object.assign(Error('INVALID_MODEL_IMPORTS'),{status:400});
  const key=entry.kind+':'+entry.model_id;if(!cache.has(key))cache.set(key,(await backendRead({action:'model_resolve',site_id:'266',game_id:'1327',kind:entry.kind,model_id:entry.model_id})).model);details.push(cache.get(key));
 }return details;
}
async function pendingProductDetails(body){
 const entries=Object.hasOwn(body,'product_imports')?body.product_imports:[];if(!Array.isArray(entries)||entries.length>30)throw Object.assign(Error('INVALID_PRODUCT_IMPORTS'),{status:400});const details=[],cache=new Map();
 for(const entry of entries){const ref=entry?.product_ref;
  if(!entry||Object.keys(entry).some(k=>!['page_id','product_ref'].includes(k))||!['fc27-weekly','fc27-sbc','fc27-trio','seasonal-vault'].includes(entry.page_id)||!ref||typeof ref!=='object'||Array.isArray(ref)||Object.keys(ref).some(k=>!['site_id','game_id','goods_id','model_id','sku_id'].includes(k))
   ||ref.site_id!=='266'||!['1327','1329','1309','456','552','891'].includes(ref.game_id)||['goods_id',...['model_id','sku_id'].filter(k=>Object.hasOwn(ref,k))].some(k=>typeof ref[k]!=='string'||!(/^[1-9]\d{0,19}$/).test(ref[k])))throw Object.assign(Error('INVALID_PRODUCT_IMPORTS'),{status:400});
  const key=[ref.site_id,ref.game_id,ref.goods_id].join(':');if(!cache.has(key))cache.set(key,(await backendRead({action:'product_read',site_id:ref.site_id,game_id:ref.game_id,goods_id:ref.goods_id})).product);details.push(cache.get(key));
 }return details;
}
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
  if(['GET','HEAD','POST'].includes(req.method)&&['analytics/api/center','analytics/api/center/publish'].includes(relative))await adminPrices.refresh();
  if(req.method!=='GET'&&req.method!=='HEAD'){
   if(req.method!=='POST'||!auth.admin)return json(res,403,{message:'仅现有管理员可保存配置'});
   if(req.headers.origin!==origin||req.headers['x-csrf-token']!==csrf)return json(res,403,{message:'请求来源或会话校验失败，请刷新页面'});
   if(relative==='analytics/api/center/assets/upload'){
    if(!['image/png','image/jpeg','image/webp'].includes(req.headers['content-type']))return json(res,415,{message:'IMAGE_TYPE_INVALID'});
    const chunks=[];let bytes=0;for await(const chunk of req){bytes+=chunk.length;if(bytes>mediaLimits.fileBytes)return json(res,413,{message:'IMAGE_SIZE_INVALID'});chunks.push(chunk);}
    return json(res,200,center.uploadAsset(url.searchParams.get('operation_id'),Buffer.concat(chunks),req.headers['content-type'],auth.user));
   }
   if(req.headers['content-type']!=='application/json')return json(res,403,{message:'请求来源或会话校验失败，请刷新页面'});
   let raw='';for await(const chunk of req){raw+=chunk;if(Buffer.byteLength(raw)>300000)return json(res,413,{message:'配置过大'});}const body=JSON.parse(raw);
   if(relative==='analytics/api/center'){const prior=center.recoverSave(body);return json(res,200,{...centerState(prior||center.save(body,auth.user,await pendingModelDetails(body),await pendingProductDetails(body))),csrf,canEdit:true});}
   if(relative==='analytics/api/center/publish'){const prior=center.recoverPublish(body);return json(res,200,{...centerState(prior||center.publish(body,auth.user,await pendingModelDetails(body),await pendingProductDetails(body))),csrf,canEdit:true});}
   if(relative==='analytics/api/center/preview'){
    const snapshot=center.preview(body,await pendingModelDetails(body),await pendingProductDetails(body)),page=snapshot.pages.find(p=>p.page_id===body.page_id);if(!page)return json(res,400,{message:'INVALID_CAMPAIGN_PAGE'});
    for(const [key,value] of previews)if(value.expires<=Date.now())previews.delete(key);if(previews.size>=20)return json(res,429,{message:'PREVIEW_LIMIT'});
    const token=randomBytes(24).toString('hex'),expires=Date.now()+10*60*1000;previews.set(token,{snapshot,expires,user:auth.user});return json(res,200,{preview_url:prefix+'analytics/preview/'+token+'/'+page.path,expires_at:new Date(expires).toISOString()});
   }
   if(relative==='analytics/api/center/restore')return json(res,200,{...centerState(center.restoreDraft(body,auth.user)),csrf,canEdit:true});
   if(relative==='analytics/api/center/import-model'){
    const prior=center.recoverModel(body);if(prior)return json(res,200,{...centerState(prior),csrf,canEdit:true});
    const data=await backendRead({action:'model_resolve',site_id:'266',game_id:'1327',kind:body.kind,model_id:body.model_id});
    return json(res,200,{...centerState(center.importModel(body,auth.user,data.model)),csrf,canEdit:true});
   }
   if(relative==='analytics/api/center/import-product'){
    const prior=center.recoverImport(body);if(prior)return json(res,200,{...centerState(prior),csrf,canEdit:true});
    const ref=body.product_ref||{};const data=await backendRead({action:'product_read',site_id:ref.site_id,game_id:ref.game_id,goods_id:ref.goods_id});
    return json(res,200,{...centerState(center.importProduct(body,auth.user,data.product)),csrf,canEdit:true});
   }
   if(relative==='analytics/api/center/backend-read')return json(res,200,{status:'ok',data:await backendRead(body)});
   if(relative==='analytics/api/center/backend-mutate')return json(res,200,{status:'ok',data:await backendMutate(body)});
   if(relative==='analytics/api/config'){let saved;try{saved=store.save(body,auth.user);}catch(error){if(!error.code&&!error.status)error.status=400;throw error;}return json(res,200,{status:'saved',...publicState(saved)});}
   if(relative==='analytics/api/connection'){
    if(!/^phx_[A-Za-z0-9_-]{20,200}$/.test(body.key||''))return json(res,400,{message:'密钥格式无效'});
    const date=new Date().toISOString().slice(0,10),r=await report(new URLSearchParams({activity:'all',mode:'test',from:date,to:date}),{token:body.key,project:cfg.projectId,registry:store.read().registry,revision:'verify-'+randomBytes(8).toString('hex')});
    if(r.status!==200)return json(res,r.status,{message:'只读查询验证失败，原连接保留'});
    atomic(secretFile,{key:body.key,updatedAt:new Date().toISOString(),updatedBy:auth.user});return json(res,200,{status:'configured',message:'只读查询通过，密钥已保存在服务器'});
   }
   return json(res,404,{message:'Not found'});
  }
  if(relative.startsWith('analytics/preview/')){
   const match=/^analytics\/preview\/([a-f0-9]{48})\/(.*)$/.exec(relative),preview=match&&previews.get(match[1]);if(!preview||preview.expires<=Date.now()||preview.user!==auth.user)return json(res,404,{message:'PREVIEW_UNAVAILABLE'});
   const name=match[2]==='seasonal/'?'seasonal/index.html':match[2],previewPrefix=prefix+'analytics/preview/'+match[1]+'/',snapshot=publicEnglishRelease(preview.snapshot);
   if(name==='api/campaign/config')return json(res,200,{...snapshot,page_media:pageMedia(snapshot.pages,previewPrefix),integration_mode:'preview',live_checkout:false});
   if(name==='api/campaign/capabilities')return json(res,200,{integration_mode:'preview',live_checkout:false});
   if(name.startsWith('media/')){const id=name.slice(6);if(!Object.hasOwn(snapshot.media_assets||{},id))return json(res,404,{message:'MEDIA_NOT_FOUND'});const {info,bytes}=center.readAsset(id);res.writeHead(200,{'Content-Type':info.mime,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});return res.end(req.method==='HEAD'?undefined:bytes);}
   let body=filesForPreview().get(name),status=200;if(!body)return json(res,404,{message:'Not found'});
   if(name==='catalog.js'){const selected=projectFcCatalog(catalog,snapshot);selected.page_media=pageMedia(snapshot.pages,previewPrefix);body='window.FC_ACTIVITY_CONFIG='+JSON.stringify(selected).replace(/</g,'\\u003c')+';';}
   else if(name.endsWith('.html')){const rendered=presentPage({name,body,snapshot,publicBase:new URL(previewPrefix,origin).href});status=rendered.status;body=rendered.body.replace(/<html\b[^>]*>/i,tag=>tag.replace(/\sdata-campaign-runtime="[^"]*"/g,'').replace(/>$/,' data-campaign-runtime="'+previewPrefix+'">')).replace(/<body([^>]*)>/i,'<body$1><p role="status">Unsaved draft preview. Nothing has been published. Purchasing is disabled.</p>');}
   const type=({'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.webp':'image/webp','.png':'image/png','.svg':'image/svg+xml','.jpg':'image/jpeg','.jpeg':'image/jpeg','.woff2':'font/woff2'})[path.extname(name)];res.writeHead(status,{'Content-Type':type,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'SAMEORIGIN','X-Robots-Tag':'noindex, nofollow'});return res.end(req.method==='HEAD'?undefined:body);
  }
  if(relative==='analytics/api/connection')return json(res,200,{configured:!!secret(),csrf:auth.admin?csrf:null,canEdit:auth.admin,storage:'server-persistent',projectId:cfg.projectId});
  if(relative==='analytics/api/center')return json(res,200,{...centerState(center.read()),csrf:auth.admin?csrf:null,canEdit:auth.admin});
  if(relative.startsWith('analytics/api/center/assets/')){const {info,bytes}=center.readAsset(relative.slice('analytics/api/center/assets/'.length));res.writeHead(200,{'Content-Type':info.mime,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});return res.end(req.method==='HEAD'?undefined:bytes);}
  if(relative==='analytics/api/config')return json(res,200,{...publicState(store.read()),csrf:auth.admin?csrf:null,canEdit:auth.admin});
  if(relative==='analytics/api/report'){const state=store.read();const result=await report(url.searchParams,{token:secret(),project:cfg.projectId,registry:state.registry,revision:state.revision});return json(res,result.status,result.body);}
  if(relative==='analytics/api/catalog')return json(res,200,{catalog, ...publicState(store.read())});
  if(relative==='analytics/api/export')return json(res,200,{...publicState(store.read()),catalog:previewCatalog(catalog,store.read().layout),notice:'仅配置导出，原站仍需构建 SEO 和网站开发发布'});
  // The historical URL is an authenticated alias, never a second editor source.
  if(relative==='analytics/center.html'){res.writeHead(302,{Location:prefix+'analytics/products.html','Cache-Control':'no-store'});return res.end();}
  let body,type;
  if(relative==='catalog.js'){const draft=center.read().draft;body='window.FC_ACTIVITY_CONFIG='+JSON.stringify(previewCatalog(effectiveFcCatalog(catalog,draft.fc_models||{}),draft.fc_layout??store.read().layout)).replace(/</g,'\\u003c')+';';type='text/javascript';}
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
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 void adminPrices.start().catch(()=>{});server.on('close',()=>adminPrices.stop());
 server.listen(Number(process.env.PORT||8948),'127.0.0.1',()=>console.log('FS campaign service listening on loopback'));
}
