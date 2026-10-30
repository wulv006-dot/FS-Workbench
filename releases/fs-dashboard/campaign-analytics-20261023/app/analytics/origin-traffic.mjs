// Existing origin access logs only. No client identifiers or raw log rows leave this reader.
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import {createGunzip} from 'node:zlib';
import {createHash} from 'node:crypto';

const paths=new Set(['/events/seasonal/index.html','/events/seasonal/']);
const bots=/bot|crawler|spider|headless|uptimerobot|pingdom|healthcheck/i;
const months=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const linePattern=/^\S+ \S+ \S+ \[([^\]]+)\] "(\S+) ([^ ]+) HTTP\/[^\"]+" (\d{3}) \S+ "(?:\\.|[^"\\])*" "((?:\\.|[^"\\])*)"(?: |$)/;
const nonSuccessPrefix=/^\S+ \S+ \S+ \[([^\]]+)\] "(?:\\.|[^"\\])*" (\d{3}) \S+(?: |$)/;
function timestamp(value){
 const m=/^(\d{2})\/(\w{3})\/(\d{4}):(\d{2}):(\d{2}):(\d{2}) ([+-])(\d{2})(\d{2})$/.exec(value);
 if(!m||!months.includes(m[2])||+m[4]>23||+m[5]>59||+m[6]>59||+m[8]>23||+m[9]>59)return NaN;
 const utc=Date.UTC(+m[3],months.indexOf(m[2]),+m[1],+m[4],+m[5],+m[6]);
 if(new Date(utc).getUTCDate()!==+m[1])return NaN;
 return utc-(m[7]==='+'?1:-1)*(+m[8]*60 + +m[9])*60000;
}
export function originRange(params,now=Date.now()){
 const day=k=>{const s=params.get(k);if(!/^\d{4}-\d{2}-\d{2}$/.test(s||''))throw Object.assign(Error('INVALID_TRAFFIC_RANGE'),{status:400});const t=Date.parse(s+'T00:00:00Z');if(!Number.isFinite(t)||new Date(t).toISOString().slice(0,10)!==s)throw Object.assign(Error('INVALID_TRAFFIC_RANGE'),{status:400});return t;};
 const from=day('from'),end=day('to')+86400000;
 if(params.get('activity')!=='mmoexp-seasonal'||from>=end||end-from>31*86400000||from>now)throw Object.assign(Error('INVALID_TRAFFIC_RANGE'),{status:400});
 return {from,to:Math.min(end,now),fromDay:new Date(from).toISOString().slice(0,10),toDay:new Date(end-1).toISOString().slice(0,10)};
}
const missing=reason=>({status:'unavailable',reason,pageRequests:null,observedPageRequests:null,estimatedVisitors:null,visitorReason:'UNVERIFIED_PROXY_CHAIN',source:'existing_origin_access_log'});
const stamp=s=>s.dev+':'+s.ino;
const snapshotKey=Symbol('internal-source-snapshot');
async function inventory(logPath,maxEntries){
 const dir=path.dirname(logPath),base=path.basename(logPath),escaped=base.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),pattern=new RegExp('^'+escaped+'(?:\\.(\\d+)(\\.gz)?)?$');
 const names=(await fsp.readdir(dir)).flatMap(name=>{const m=pattern.exec(name);return m?[{name,index:m[1]?Number(m[1]):0}]:[];}).sort((a,b)=>a.index-b.index||a.name.localeCompare(b.name));
 return Promise.all(names.slice(0,maxEntries).map(async row=>{const file=path.join(dir,row.name),stat=await fsp.lstat(file);if(stat.isSymbolicLink()||!stat.isFile())throw Error('UNSAFE_LOG_FILE');return {...row,file,stat};}));
}
async function readLog(row,budget,maxFileBytes){
 if(row.stat.size>maxFileBytes)throw Error('LOG_READ_LIMIT');
 const fd=await fsp.open(row.file,fs.constants.O_RDONLY|(fs.constants.O_NOFOLLOW||0));
 const before=await fd.stat();if(stamp(before)!==stamp(row.stat)||before.size<row.stat.size){await fd.close();throw Error('LOG_ROTATED_DURING_READ');}
 const input=fd.createReadStream({start:0,end:Math.max(0,row.stat.size-1),autoClose:true,signal:budget.signal});
 const stream=row.name.endsWith('.gz')?input.pipe(createGunzip()):input;
 if(stream!==input)input.on('error',error=>stream.destroy(error));
 let pending='',first=Infinity,last=-Infinity,malformed=0,bytes=0;
 const days=new Map(),hash=createHash('sha256');
 function consume(line){
  if(!line.trim())return;
  const m=linePattern.exec(line),time=m&&timestamp(m[1]);
  if(!m){
   // Nginx also logs invalid/TLS requests as400 without an HTTP request line.
   // A verified non200 status cannot contribute to our GET200 metric.
   const rejected=nonSuccessPrefix.exec(line),at=rejected&&timestamp(rejected[1]);
   if(rejected&&rejected[2]!=='200'&&Number.isFinite(at)){first=Math.min(first,at);last=Math.max(last,at);return;}
   malformed++;return;
  }
  if(!Number.isFinite(time)){malformed++;return;}
  first=Math.min(first,time);last=Math.max(last,time);
  if(m[2]!=='GET'||m[4]!=='200'||!m[3].startsWith('/')||m[3].startsWith('//'))return;
  let url;try{url=new URL(m[3],'http://origin.invalid');}catch{malformed++;return;}
  if(!paths.has(url.pathname))return;
  const day=new Date(time).toISOString().slice(0,10),r=days.get(day)||{successful:0,excluded:0,requests:0};
  r.successful++;if(bots.test(m[5])||url.searchParams.get('analytics_test')==='1')r.excluded++;else r.requests++;
  days.set(day,r);
 }
 try{
  for await(const chunk of stream){
   bytes+=chunk.length;budget.used+=chunk.length;if(bytes>maxFileBytes||budget.used>budget.max)throw Error('LOG_READ_LIMIT');hash.update(chunk);
   pending+=chunk.toString('utf8');let at;
   while((at=pending.indexOf('\n'))>=0){const line=pending.slice(0,at);pending=pending.slice(at+1);if(line.length>16384)throw Error('LOG_LINE_LIMIT');consume(line);}
   if(pending.length>16384)throw Error('LOG_LINE_LIMIT');
  }
  // A writer may currently be appending this last line. Never treat it as a complete record.
  const truncatedLine=Boolean(pending);
  const after=await fsp.lstat(row.file);
  if(stamp(after)!==stamp(row.stat)||after.size<row.stat.size)throw Error('LOG_ROTATED_DURING_READ');
  return {first,last,days,malformed,truncatedLine,bytes,hash:hash.digest('hex')};
 }finally{stream.destroy();if(stream!==input)input.destroy();await fd.close().catch(()=>{});}
}

export function makeOriginTraffic({logPath='/var/log/nginx/access.log',ttlMs=600000,maxBytes=64*1024*1024,maxFileBytes=32*1024*1024,maxFiles=8,now=Date.now}={}){
 const cache=new Map();let flight=null;
 async function scan(range){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);timer.unref?.();
  const generatedAt=new Date(now()).toISOString(),budget={used:0,max:maxBytes,signal:controller.signal},days=new Map(),identities=new Set(),hashes=new Set();
  let first=Infinity,last=-Infinity,malformed=0,files=0,previousFirst=Infinity,reason=null,initial;
  try{
   initial=await inventory(logPath,maxFiles+1);if(!initial.some(r=>r.index===0))return missing('LOG_NOT_AVAILABLE');
   let expected=0;
   for(const row of initial){
    if(files>=maxFiles){reason='LOG_FILE_LIMIT';break;}
    if(row.index!==expected){reason='LOG_ROTATION_GAP';break;}expected++;
    if(identities.has(stamp(row.stat)))continue; // rename/hard-link aliases are one physical log
    const r=await readLog(row,budget,maxFileBytes);identities.add(stamp(row.stat));files++;
    if(hashes.has(r.hash))continue; // exact copied log, not a second request stream
    hashes.add(r.hash);
    if(r.last>=previousFirst){reason='OVERLAPPING_LOG_SNAPSHOTS';break;}
    previousFirst=r.first;first=Math.min(first,r.first);last=Math.max(last,r.last);malformed+=r.malformed;
    if(r.truncatedLine)reason='INCOMPLETE_LOG_LINE';
    for(const [day,row] of r.days){const d=days.get(day)||{successful:0,excluded:0,requests:0};for(const k of Object.keys(d))d[k]+=row[k];days.set(day,d);}
    if(first<=range.from)break;
   }
   // Recheck physical identities after the whole scan, including rename/copytruncate races.
   for(const row of initial.filter(r=>identities.has(stamp(r.stat)))){const s=await fsp.lstat(row.file);if(stamp(s)!==stamp(row.stat)||s.size<row.stat.size)throw Error('LOG_ROTATED_DURING_READ');}
   if(!Number.isFinite(first))return missing('LOG_EMPTY');
   if(malformed)reason='UNPARSED_LOG_ROWS';
   const daily=[...days].filter(([day])=>day>=range.fromDay&&day<=range.toDay).sort(([a],[b])=>a.localeCompare(b)).map(([date,r])=>({date,...r}));
   const observed=daily.reduce((n,r)=>n+r.requests,0),complete=!reason&&first<=range.from;
   return {[snapshotKey]:{identity:stamp(initial[0].stat),size:initial[0].stat.size},status:complete?'available':'partial',reason:reason||(complete?null:'LOG_HISTORY_GAP'),source:'existing_origin_access_log',generatedAt,from:range.fromDay,to:range.toDay,pageRequests:complete?observed:null,observedPageRequests:observed,estimatedVisitors:null,visitorReason:'UNVERIFIED_PROXY_CHAIN',daily,coverage:{complete,from:new Date(first).toISOString(),through:generatedAt,lastRecordAt:new Date(last).toISOString(),files,bytesRead:budget.used},successfulRequests:daily.reduce((n,r)=>n+r.successful,0),excludedRequests:daily.reduce((n,r)=>n+r.excluded,0),repeatedRefreshCounted:true,cacheMissCoverageOnly:true,scope:'all_games_devices_channels',deduplication:'physical_or_identical_log_files_only',cacheTtlSeconds:ttlMs/1000};
  }catch(error){return {...missing(controller.signal.aborted?'LOG_READ_TIMEOUT':['LOG_READ_LIMIT','LOG_LINE_LIMIT','LOG_ROTATED_DURING_READ','UNSAFE_LOG_FILE'].includes(error.message)?error.message:'LOG_READ_FAILED'),generatedAt};}
  finally{clearTimeout(timer);}
 }
 return async function query(params){
  const range=originRange(params,now()),key=range.fromDay+':'+range.toDay;
  const force=params.get('refresh')==='1';
  while(flight)await flight;
  const old=cache.get(key);
  if(!force&&old&&old.expires>now()){
   if(old.data.status==='unavailable')return structuredClone(old.data);
   try{const s=await fsp.lstat(logPath);if(stamp(s)===old.identity&&s.size>=old.size)return structuredClone(old.data);}catch{}
  }
  flight=(async()=>{const data=await scan(range),meta=data[snapshotKey];
   cache.set(key,{data,identity:meta?.identity,size:meta?.size,expires:now()+(data.status==='unavailable'?5000:ttlMs)});if(cache.size>8)cache.delete(cache.keys().next().value);return data;})();
  try{return structuredClone(await flight);}finally{flight=null;}
 };
}
