// Publishes the Carnival Mystery Shop paid-use list for the public runtime.
// The dashboard reads Admin (read only) through the backend bridge; the runtime runs as
// another user and only reads this file, so it is written world-readable (no secrets:
// member uid, coupon set and use time only, kept on this server).
import fs from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';

export const CARNIVAL_UNLOCKS_FILE='carnival-unlocks.json';
const FROM=Date.parse('2026-11-19T00:00:00-05:00'),UNTIL=Date.parse('2026-12-03T00:00:00-05:00');

export function writePublic(file,value){
 const temp=file+'.'+randomUUID()+'.tmp';
 fs.writeFileSync(temp,JSON.stringify(value),{mode:0o644,flag:'wx'});
 try{fs.chmodSync(temp,0o644);fs.renameSync(temp,file);}finally{if(fs.existsSync(temp))fs.unlinkSync(temp);}
}

// Every 2 minutes: a paid order unlocks the next Mystery round within a few minutes.
// (Dashboard statistics are a separate, hourly path.)
export function createCarnivalUnlocks({publicDir,read,now=Date.now,intervalMs=120000,log=()=>{}}={}){
 let timer=null,running=false;
 async function refresh(){
  const clock=now();if(clock<FROM||clock>=UNTIL||running)return {status:'idle'};
  running=true;
  try{
   const data=await read({action:'carnival_unlocks'});
   if(data?.status!=='available'||!Array.isArray(data.uses))throw Error('CARNIVAL_UNLOCKS_INVALID');
   writePublic(path.join(publicDir,CARNIVAL_UNLOCKS_FILE),{generated_at:data.generated_at,uses:data.uses});
   return {status:'written',uses:data.uses.length};
  }catch(error){log('CARNIVAL_UNLOCKS_UNAVAILABLE',error?.message);return {status:'failed'};}  // keep the last good file
  finally{running=false;}
 }
 return {refresh,start(){if(!timer){void refresh();timer=setInterval(()=>void refresh(),intervalMs);timer.unref?.();}},stop(){clearInterval(timer);timer=null;}};
}
