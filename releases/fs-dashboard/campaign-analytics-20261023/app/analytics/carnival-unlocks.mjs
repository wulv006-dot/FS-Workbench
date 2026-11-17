// Answers Carnival Mystery Shop "verify my purchase" requests for the public runtime.
// The runtime drops one small request file per press in its verify queue; only then is
// Admin read (once per batch, read only, through the backend bridge). The paid-use list
// and a per-request check stamp are written world-readable to the shared public
// directory, because the runtime runs as another user (no secrets: member uid, coupon
// set and use time only, kept on this server). With no requests, nothing is read.
import fs from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {carnivalTest} from '../runtime/carnival.mjs';

export const CARNIVAL_UNLOCKS_FILE='carnival-unlocks.json';
const FROM=Date.parse('2026-11-19T00:00:00-05:00'),UNTIL=Date.parse('2026-12-03T00:00:00-05:00');
const REQUEST=/^[0-9a-f]{32}-[a-z0-9]{1,16}\.json$/;

export function writePublic(file,value){
 const temp=file+'.'+randomUUID()+'.tmp';
 fs.writeFileSync(temp,JSON.stringify(value),{mode:0o644,flag:'wx'});
 try{fs.chmodSync(temp,0o644);fs.renameSync(temp,file);}finally{if(fs.existsSync(temp))fs.unlinkSync(temp);}
}
function previous(file){
 try{const p=JSON.parse(fs.readFileSync(file,'utf8'));return {generated_at:p.generated_at,uses:Array.isArray(p.uses)?p.uses:[],checked:p.checked&&typeof p.checked==='object'&&!Array.isArray(p.checked)?p.checked:{}};}
 catch{return {uses:[],checked:{}};}
}

export function createCarnivalVerifier({publicDir,requestDir,read,now=Date.now,intervalMs=3000,log=()=>{}}={}){
 let timer=null,running=false;
 async function refresh(){
  // Before the event only the internal test (carnival-test.json) asks for checks, and then
  // only that test coupon's uses are read.
  const clock=now(),test=clock<FROM?carnivalTest(publicDir,clock):null;
  if(clock<FROM&&!test||clock>=UNTIL||running)return {status:'idle'};
  let names;try{names=fs.readdirSync(requestDir).filter(n=>REQUEST.test(n));}catch{return {status:'idle'};}
  if(!names.length)return {status:'idle'};
  running=true;
  try{
   let data=null;
   // site_id: the backend bridge only serves site 266 (MMOEXP) reads.
   try{data=await read(test?{action:'carnival_unlocks',site_id:'266',test_coupon_id:test.coupon_id}:{action:'carnival_unlocks',site_id:'266'});if(data?.status!=='available'||!Array.isArray(data.uses))throw Error('CARNIVAL_UNLOCKS_INVALID');}
   catch(error){log('CARNIVAL_UNLOCKS_UNAVAILABLE',error?.message);data=null;}
   const file=path.join(publicDir,CARNIVAL_UNLOCKS_FILE),last=previous(file),at=new Date(now()).toISOString(),checked={...last.checked};
   // ok:false = Admin could not be read; the page says "try again" instead of "not paid".
   for(const name of names)checked[name.slice(0,-5)]={at,ok:!!data};
   writePublic(file,{generated_at:data?data.generated_at:last.generated_at,uses:data?data.uses:last.uses,checked});
   for(const name of names)try{fs.unlinkSync(path.join(requestDir,name));}catch{}
   return {status:data?'checked':'failed',requests:names.length};
  }finally{running=false;}
 }
 return {refresh,start(){if(!timer){timer=setInterval(()=>void refresh(),intervalMs);timer.unref?.();}},stop(){clearInterval(timer);timer=null;}};
}
