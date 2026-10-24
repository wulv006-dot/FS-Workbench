import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFile} from 'node:child_process';
import fs from 'node:fs';
import {fail} from '../runtime/snapshot.mjs';

const deployedBridge=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../backend/bridge.py');
export function backendRead(request,{python=process.env.CAMPAIGN_PYTHON||'/opt/python39/bin/python3',bridge=process.env.CAMPAIGN_BACKEND_BRIDGE||(fs.existsSync(deployedBridge)?deployedBridge:path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../backend/bridge.py')),timeout=120000}={}){
 if(!['capabilities','benefits_read','catalog_read'].includes(request?.action))fail('ACTION_NOT_ALLOWED');
 if(request.action!=='capabilities'&&String(request.site_id)!=='266')fail('SITE_SCOPE_REQUIRED');
 const raw=JSON.stringify(request);if(Buffer.byteLength(raw)>250000)fail('REQUEST_TOO_LARGE',413);
 return new Promise((resolve,reject)=>{
  const child=execFile(python,[bridge],{timeout,maxBuffer:2000000,windowsHide:true},(error,stdout)=>{
   if(error)return reject(Object.assign(new Error('BACKEND_UNAVAILABLE'),{code:'BACKEND_UNAVAILABLE',status:502}));
   try{const result=JSON.parse(stdout);if(result.status!=='ok')return reject(Object.assign(new Error(result.error&&/^[A-Z_]+$/.test(result.error)?result.error:'BACKEND_UNAVAILABLE'),{status:502}));resolve(result.data);}catch{reject(Object.assign(new Error('BACKEND_UNAVAILABLE'),{status:502}));}
  });
  child.stdin.on('error',()=>{});child.stdin.end(raw);
 });
}
