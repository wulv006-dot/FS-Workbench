// Server-side aggregate snapshots. No browser identity, raw event or order rows are persisted.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {randomUUID,randomBytes} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {retrySource,transientFailure} from './statistics-retry.mjs';

const day=ms=>new Date(ms).toISOString().slice(0,10),DAY=86400000;
const sources=['traffic','behavior','revenue'],games=new Set(['1327','891','456','1333']);
const count=v=>{if(!Number.isSafeInteger(v)||v<0)throw Error('INVALID_AGGREGATE');return v;};
const iso=v=>{if(typeof v!=='string'||!Number.isFinite(Date.parse(v)))throw Error('INVALID_AGGREGATE');return new Date(v).toISOString();};
function windowFor(from,to,kind,at){return {kind,timezone:'UTC',from,to,start:from+'T00:00:00.000Z',endExclusive:new Date(Date.parse(to)+DAY).toISOString(),dateIntervalClosed:Date.parse(to)+DAY<=at};}
export function refreshPlan(published,status={},at=Date.now()){
 const start=Date.parse(published?.halloween?.starts_at);
 if(!Number.isFinite(start)||start>at||!published?.pages?.some(p=>p.page_id==='seasonal-vault'&&p.activity_id==='mmoexp-seasonal'))throw Error('CAMPAIGN_CONTEXT_REQUIRED');
 const bjt=new Date(at+8*3600000),hour=Math.floor(bjt.getUTCHours()/8)*8,today=day(at),yesterday=day(Date.parse(today)-DAY);
 const slot=day(at+8*3600000)+'T'+String(hour).padStart(2,'0')+':00:00+08:00';
 const windows=[windowFor(today,today,'today',at),windowFor(day(start),today,'campaign',at)];
 // 08:00 is the daily close. A later slot can catch up a missed/incomplete close, never a history sweep.
 if(hour===8||status.lastCompleteDailyDate!==yesterday)windows.push(windowFor(yesterday,yesterday,'yesterday',at));
 return {slot,scheduleTimezone:'Asia/Shanghai',scheduleHours:[0,8,16],metricTimezone:'UTC',campaignStartsAt:new Date(start).toISOString(),windows};
}
function sourceFailure(error){
 const text=String(error?.message||'');
 const blocked=text==='SOURCE_NOT_CONFIGURED'||/^PostHog query returned (401|403)$/.test(text)||/^[A-Z_]*(?:AUTH|PERMISSION|ACCESS_DENIED)[A-Z_]*$/.test(text);
 const transient=!blocked&&transientFailure(error);if(transient)return {status:'unavailable',...transient,blocked:false};
 return {status:'unavailable',reason:text==='SOURCE_NOT_CONFIGURED'?text:blocked?'SOURCE_ACCESS_DENIED':/^[A-Z_]{3,80}$/.test(text)?text:'SOURCE_READ_FAILED',blocked};
}
export function compactSource(name,value){
 if(name==='traffic'){
  const v=value;if(!['available','partial','unavailable'].includes(v?.status))throw Error('INVALID_AGGREGATE');
  const data={pageRequests:v.status==='available'?count(v.pageRequests):null,observedPageRequests:v.observedPageRequests==null?null:count(v.observedPageRequests),estimatedVisitors:null,visitorReason:'UNVERIFIED_PROXY_CHAIN',source:'existing_origin_access_log'};
  if(v.coverage)data.coverage={complete:v.coverage.complete===true,from:iso(v.coverage.from),through:iso(v.coverage.through)};
  if(v.status==='available'&&data.coverage?.complete!==true)throw Error('INCOMPLETE_AGGREGATE');
  return {status:v.status,reason:/^[A-Z_]{3,80}$/.test(v.reason||'')?v.reason:null,data};
 }
 const v=value?.body;
 if(value?.status!==200||v?.status!=='available'){
  if([401,403].includes(value?.status))return {status:'unavailable',reason:'SOURCE_ACCESS_DENIED',blocked:true};
  if(value?.status===400)return {status:'unavailable',reason:v?.message==='活动未部署到服务端白名单'?'SOURCE_CONFIGURATION_INVALID':'WINDOW_FILTER_INVALID',blocked:v?.message==='活动未部署到服务端白名单'};
  return sourceFailure(Object.assign(Error(v?.status==='not_configured'?'SOURCE_NOT_CONFIGURED':v?.reason||'SOURCE_READ_FAILED'),{retryAfterMs:v?.retryAfterMs}));
 }
 if(name==='behavior'){
  const r=v.report,t=r?.seasonalTotals;
  const keys=['gameViews','revealed','selected','reviewed','cart','unconfirmed'];
  const totals=Object.fromEntries(keys.map(k=>[k,count(t?.[k])]));
  if(!Array.isArray(r?.seasonalGames)||r.seasonalGames.length>4)throw Error('INVALID_AGGREGATE');
  const byGame=r.seasonalGames.map(g=>{if(!games.has(g.gameId))throw Error('INVALID_AGGREGATE');return {gameId:g.gameId,...Object.fromEntries(['visits','revealed','selected','reviewed','cart','unconfirmed'].map(k=>[k,count(g[k])]))};});
  return {status:'available',data:{source:'opt_in_production_events',generatedAt:iso(v.generatedAt),visits:count(r.visits),sessionVisitors:count(r.visitors),totals,byGame,notAllVisitors:true,lateEventsMayRevise:true}};
 }
 if(name!=='revenue'||v.coverage?.complete!==true||!Array.isArray(v.codes)||v.codes.length!==12||!Array.isArray(v.paid_currencies)||v.paid_currencies.length>20)throw Error('INVALID_AGGREGATE');
 const codes=v.codes.map(c=>{if(!games.has(c.game_id)||!/^HW[A-Z0-9]{3,17}$/.test(c.code)||![8,10,15].includes(c.off_percent))throw Error('INVALID_AGGREGATE');return {code:c.code,gameId:c.game_id,offPercent:c.off_percent,paidOrders:count(c.paid_orders),paidUsdMinor:count(c.paid_usd_minor)};});
 if(new Set(codes.map(c=>c.code)).size!==12)throw Error('INVALID_AGGREGATE');
 const currencies=v.paid_currencies.map(c=>{if(!/^[A-Z]{3}$/.test(c.currency)||!/^\d{1,15}(?:\.\d{1,6})?$/.test(c.amount))throw Error('INVALID_AGGREGATE');return {currency:c.currency,amount:c.amount};});
 return {status:'available',data:{source:'paid_dedicated_code_orders',generatedAt:iso(v.generated_at),paidOrders:count(v.totals?.paid_orders),paidUsdMinor:count(v.totals?.paid_usd_minor),paidCurrencies:currencies,codes,refundsNotDeducted:true,notVisitorAttribution:true}};
}
const slots=new Set(['status','today','campaign','yesterday']);
function readSlot(dir,name){
 if(!slots.has(name))throw Error('INVALID_SNAPSHOT_SLOT');const file=path.join(dir,name+'.json');
 try{const s=fs.lstatSync(file);if(!s.isFile()||s.isSymbolicLink()||s.size>65536)throw Error('INVALID_SNAPSHOT_FILE');const data=JSON.parse(fs.readFileSync(file,'utf8'));if(data.schemaVersion!==1)throw Error('INVALID_SNAPSHOT_FILE');return data;}catch(e){if(e.code==='ENOENT')return null;throw e;}
}
function prepareDir(dir){
 fs.mkdirSync(dir,{recursive:true,mode:0o700});const s=fs.lstatSync(dir);
 if(s.isSymbolicLink()||!s.isDirectory()||(process.platform!=='win32'&&(s.mode&0o077)!==0))throw Error('INSECURE_SNAPSHOT_DIRECTORY');
}
function writeSlot(dir,name,data){
 if(!slots.has(name))throw Error('INVALID_SNAPSHOT_SLOT');const target=path.join(dir,name+'.json');
 if(fs.existsSync(target)&&fs.lstatSync(target).isSymbolicLink())throw Error('INVALID_SNAPSHOT_FILE');
 const bytes=Buffer.from(JSON.stringify(data)+'\n');if(bytes.length>65536)throw Error('SNAPSHOT_SIZE_LIMIT');
 const temp=target+'.tmp-'+randomBytes(8).toString('hex');let fd;
 try{fd=fs.openSync(temp,'wx',0o600);fs.writeFileSync(fd,bytes);fs.fsyncSync(fd);fs.closeSync(fd);fd=undefined;fs.renameSync(temp,target);if(process.platform!=='win32'){const d=fs.openSync(dir,'r');try{fs.fsyncSync(d);}finally{fs.closeSync(d);}}}
 finally{if(fd!==undefined)fs.closeSync(fd);try{fs.unlinkSync(temp);}catch(e){if(e.code!=='ENOENT')throw e;}}
}
export async function runStatisticsRefresh({directory,published,readers,now=Date.now,runId=randomUUID(),retryBlocked=false,isCurrent=()=>true}={}){
 const deadline=Date.now()+360000;
 prepareDir(directory);const old=readSlot(directory,'status')||{schemaVersion:1,blockedSources:{}},startedAt=new Date(now()).toISOString(),plan=refreshPlan(published,old,now());
 if(old.lastAttempt?.slot===plan.slot&&old.lastAttempt?.status==='success'&&!retryBlocked)return {status:'already_completed',runId:old.lastAttempt.runId};
 const state={schemaVersion:1,scheduleTimezone:plan.scheduleTimezone,scheduleHours:plan.scheduleHours,metricTimezone:'UTC',lastSuccessfulRunAt:old.lastSuccessfulRunAt||null,lastCompleteDailyDate:old.lastCompleteDailyDate||null,blockedSources:retryBlocked?{}:{...old.blockedSources},lastAttempt:{runId,slot:plan.slot,startedAt,status:'running',windows:[]}};
 writeSlot(directory,'status',state);let anyGood=false,allGood=true;
 for(const window of plan.windows){
  const prior=readSlot(directory,window.kind),priorCompatible=prior?.activityId==='mmoexp-seasonal'&&prior.releaseId===published.release_id&&prior.configHash===published.config_hash&&prior.campaignStartsAt===plan.campaignStartsAt,output={schemaVersion:1,activityId:'mmoexp-seasonal',releaseId:published.release_id,configHash:published.config_hash,runId,window,campaignStartsAt:plan.campaignStartsAt,updatedAt:new Date(now()).toISOString(),sources:{}};
  const results=await Promise.all(sources.map(async name=>{
   if(Date.parse(window.to)-Date.parse(window.from)>30*DAY)return {status:'unavailable',reason:'WINDOW_RANGE_TOO_LARGE'};
   if(state.blockedSources[name])return {status:'blocked',reason:state.blockedSources[name].reason};
   return retrySource(async()=>{try{return compactSource(name,await readers[name](window));}catch(error){return sourceFailure(error);}},{deadline,attemptTimeoutMs:({traffic:10000,behavior:15000,revenue:120000})[name],isCurrent});
  }));
  for(let i=0;i<sources.length;i++){
   const name=sources[i],result=results[i],at=new Date(now()).toISOString(),lastSuccess=priorCompatible?prior?.sources?.[name]?.lastSuccess||null:null;
   output.sources[name]={lastAttempt:{runId,at,status:result.status,reason:result.reason||null,...(result.retry?{retry:result.retry}:{}),...(result.data?{summary:result.data}:{})},lastSuccess:result.status==='available'?{runId,at,window,summary:result.data}:lastSuccess};
   if(result.blocked)state.blockedSources[name]={at,reason:result.reason};
   anyGood ||= result.status==='available';allGood &&= result.status==='available';
  }
  writeSlot(directory,window.kind,output);
  const complete=results.every(r=>r.status==='available');if(window.kind==='yesterday'&&complete)state.lastCompleteDailyDate=window.from;
  state.lastAttempt.windows.push({kind:window.kind,from:window.from,to:window.to,status:complete?'success':'incomplete',sources:Object.fromEntries(sources.map((name,i)=>[name,results[i].status]))});writeSlot(directory,'status',state);
 }
 state.lastAttempt.status=allGood?'success':anyGood?'partial':'failed';state.lastAttempt.finishedAt=new Date(now()).toISOString();if(allGood)state.lastSuccessfulRunAt=state.lastAttempt.finishedAt;writeSlot(directory,'status',state);
 return {status:state.lastAttempt.status,runId,slot:plan.slot,finishedAt:state.lastAttempt.finishedAt,lastSuccessfulRunAt:state.lastSuccessfulRunAt,windows:state.lastAttempt.windows};
}
// Authenticated dashboard consumer: only exact, unfiltered slots; never invoke source readers.
export function readStatisticsSnapshot({directory,published,kind,at=Date.now()}){
 if(!['today','campaign','yesterday'].includes(kind))throw Error('INVALID_SNAPSHOT_SLOT');
 const plan=refreshPlan(published,{},at),window=plan.windows.find(w=>w.kind===kind),state=readSlot(directory,'status'),snapshot=readSlot(directory,kind);
 const matching=snapshot?.activityId==='mmoexp-seasonal'&&snapshot.releaseId===published.release_id&&snapshot.configHash===published.config_hash&&snapshot.campaignStartsAt===plan.campaignStartsAt;
 const sameWindow=w=>w?.from===window.from&&w?.to===window.to&&w?.timezone==='UTC';
 const selected=Object.fromEntries(sources.map(name=>{const value=matching?snapshot.sources?.[name]:null,success=value?.lastSuccess;return [name,{lastAttempt:sameWindow(snapshot?.window)?value?.lastAttempt||null:null,lastSuccess:success&&sameWindow(success.window)?success:null,previousSuccessAt:success?.at||null,previousWindow:success?.window||null}];}));
 return {status:matching&&sameWindow(snapshot?.window)?'available':'not_ready',activityId:'mmoexp-seasonal',kind,window,releaseId:published.release_id,scheduleTimezone:'Asia/Shanghai',metricTimezone:'UTC',scheduleHours:[0,8,16],nextScheduledAt:new Date((Math.floor(at/(8*3600000))+1)*8*3600000).toISOString(),lastSuccessfulRunAt:state?.lastSuccessfulRunAt||null,lastAttempt:state?.lastAttempt||null,sources:selected};
}
async function production(){
 const args=process.argv.slice(2),get=name=>{const i=args.indexOf(name);return i<0?null:args[i+1];},directory=get('--directory'),runId=get('--run-id');
 if(!directory||!runId||!/^[a-f0-9-]{36}$/i.test(runId))throw Error('WRAPPER_ARGUMENTS_REQUIRED');
 const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),dataDir='/var/lib/fs-campaign-dashboard',publicDir='/var/lib/fs-campaign-public';
 const [{makeOriginTraffic},{report},{reportContext},{makeDiscountRevenue}]=await Promise.all([import('./origin-traffic.mjs'),import('./server.mjs'),import('./report-context.mjs'),import('./discount-revenue.mjs')]);
 const context=JSON.parse(fs.readFileSync(path.join(publicDir,'current.json'),'utf8')),box={window:{}};vm.runInNewContext(fs.readFileSync(path.join(root,'analytics-config.js'),'utf8'),box);
 const traffic=makeOriginTraffic(),revenue=makeDiscountRevenue();
 const readers={traffic:w=>traffic(new URLSearchParams({activity:'mmoexp-seasonal',from:w.from,to:w.to,refresh:'1'})),
  behavior:w=>{const state=JSON.parse(fs.readFileSync(path.join(dataDir,'state.json'),'utf8'));let secret;try{secret=JSON.parse(fs.readFileSync(path.join(dataDir,'posthog-secret.json'),'utf8')).key;}catch{throw Error('SOURCE_NOT_CONFIGURED');}return report(new URLSearchParams({activity:'mmoexp-seasonal',mode:'live',from:w.from,to:w.to,template:'commerce',windowHours:'24',game:'all',device:'all',platform:'all',source:'all'}),{token:secret,project:box.window.FC_ANALYTICS_CONFIG.projectId,registry:state.registry,revision:state.revision,context:reportContext(publicDir)});},
  revenue:w=>revenue(new URLSearchParams({activity:'mmoexp-seasonal',mode:'live',from:w.from,to:w.to,game:'all',refresh:'1'}))};
 const initialDay=day(Date.now()),isCurrent=()=>{try{const p=JSON.parse(fs.readFileSync(path.join(publicDir,'current.json'),'utf8'));return day(Date.now())===initialDay&&p.release_id===context.release_id&&p.config_hash===context.config_hash&&p.halloween?.starts_at===context.halloween?.starts_at;}catch{return false;}};
 const result=await runStatisticsRefresh({directory,published:context,readers,runId,isCurrent,retryBlocked:args.includes('--retry-blocked')});console.log(JSON.stringify(result));process.exitCode=result.status==='success'||result.status==='already_completed'?0:result.status==='partial'?2:1;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))production().catch(()=>{console.error(JSON.stringify({status:'failed',reason:'STATISTICS_REFRESH_FAILED'}));process.exitCode=1;});
