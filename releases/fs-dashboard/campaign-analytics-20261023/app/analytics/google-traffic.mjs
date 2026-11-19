import {execFile} from 'node:child_process';
import path from 'node:path';
import fs from 'node:fs';
import {fileURLToPath} from 'node:url';
import {originRange} from './origin-traffic.mjs';

function read(request){
 const base=path.dirname(fileURLToPath(import.meta.url)),deployed=path.resolve(base,'../backend/google_traffic.py'),bridge=fs.existsSync(deployed)?deployed:path.resolve(base,'../../backend/google_traffic.py');
 return new Promise((resolve,reject)=>{
  const child=execFile('/opt/mmoexp-marketing/venv-ssl/bin/python',['-B',bridge],{timeout:90000,maxBuffer:250000,windowsHide:true},(error,stdout)=>{
   if(error)return reject(Error('GOOGLE_READ_FAILED'));
   try{const value=JSON.parse(stdout);if(!['available','no_rows','partial','unavailable'].includes(value.status))throw Error();resolve(value);}catch{reject(Error('GOOGLE_READ_FAILED'));}
  });child.stdin.on('error',()=>{});child.stdin.end(JSON.stringify(request));
 });
}
export function makeGoogleTraffic(reader=read,now=Date.now){
 const cache=new Map();let pending=null;
 return async params=>{
  if([...params.keys()].some(k=>!['activity','source','from','to','refresh'].includes(k))||[...params.keys()].some(k=>params.getAll(k).length!==1)||!['ga4','gsc','ads'].includes(params.get('source'))||params.has('refresh')&&params.get('refresh')!=='1')throw Object.assign(Error('INVALID_GOOGLE_FILTER'),{status:400});
  const {activity,fromDay,toDay}=originRange(params,now(),['mmoexp-seasonal','fc27-season2','mmoexp-carnival']);
  const request={source:params.get('source'),from:fromDay,to:toDay};
  if(activity==='mmoexp-carnival')request.activity=activity;
  const key=JSON.stringify(request),old=cache.get(key);
  if(params.get('refresh')!=='1'&&old&&old.expires>now())return structuredClone(old.value);
  if(pending){if(pending.key===key)return structuredClone(await pending.work);return {status:'unavailable',reason:'GOOGLE_READER_BUSY'};}
  const work=(async()=>{let value;try{value=await reader(request);}catch{value={status:'unavailable',reason:'GOOGLE_READ_FAILED'};}
   if(cache.size>=12)cache.clear();cache.set(key,{value,expires:now()+(['available','no_rows'].includes(value.status)?600000:5000)});return value;})();
  pending={key,work};try{return structuredClone(await work);}finally{pending=null;}
 };
}
