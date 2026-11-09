import net from 'node:net';
import fs from 'node:fs';
import path from 'node:path';
export const weeklySocket='/run/fs-campaign-weekly/operations.sock';
const safeError=(error,body)=>({status:'failed',...(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(body?.operation_id||'')?{operation_id:body.operation_id}:{}),error:/^[A-Z][A-Z0-9_]{0,99}$/.test(error.code||error.message)?error.code||error.message:'WEEKLY_PIPELINE_FAILED',publication:false});
function validate(body){if(!body||body.contract!=='campaign_weekly_run_v1'||!['prepare','apply_draft','inspect_operation'].includes(body.action)||Object.keys(body).some(k=>!['contract','action','operation_id','owner','plan_ref','recommendation','evidence_sources'].includes(k)))throw Error('WEEKLY_CLI_CONTRACT_INVALID');}
// Local filesystem permissions are the trusted host boundary. No HTTP caller can supply owner.
export async function startWeeklyBridge({pipeline,socketPath=weeklySocket}){
 if(process.platform!=='win32'){
  const parent=path.dirname(socketPath);fs.mkdirSync(parent,{recursive:true,mode:0o700});
  if(fs.lstatSync(parent).isSymbolicLink()||!fs.lstatSync(parent).isDirectory())throw Error('WEEKLY_SOCKET_DIRECTORY_INVALID');fs.chmodSync(parent,0o700);
  if(fs.existsSync(socketPath)){
   if(!fs.lstatSync(socketPath).isSocket())throw Error('WEEKLY_SOCKET_PATH_INVALID');
   const alive=await new Promise((resolve,reject)=>{const probe=net.createConnection(socketPath);probe.setTimeout(1000);probe.once('connect',()=>{probe.destroy();resolve(true);});probe.once('error',e=>{if(e.code==='ECONNREFUSED')resolve(false);else reject(e);});probe.once('timeout',()=>{probe.destroy();reject(Error('WEEKLY_SOCKET_BUSY'));});});
   if(alive)throw Error('WEEKLY_SOCKET_BUSY');fs.unlinkSync(socketPath);
  }
 }
 const server=net.createServer(socket=>{
  let raw='',size=0,handled=false;socket.setEncoding('utf8');socket.setTimeout(180000,()=>socket.destroy());socket.on('error',()=>{});
  socket.on('data',chunk=>{size+=Buffer.byteLength(chunk);if(size>1000000){socket.destroy();return;}raw+=chunk;if(!raw.endsWith('\n')||handled)return;handled=true;
   void (async()=>{let body;try{body=JSON.parse(raw);validate(body);const result=body.action==='prepare'?await pipeline.prepare(body,body.owner):body.action==='inspect_operation'?pipeline.inspect(body,body.owner):pipeline.apply(body,body.owner);const encoded=JSON.stringify(result)+'\n';if(Buffer.byteLength(encoded)>1000000)throw Error('WEEKLY_BRIDGE_RESPONSE_TOO_LARGE');socket.end(encoded);}catch(error){socket.end(JSON.stringify(safeError(error,body))+'\n');}})();
  });
 });
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(socketPath,()=>{server.removeListener('error',reject);resolve();});});
 if(process.platform!=='win32')fs.chmodSync(socketPath,0o600);
 server.on('error',()=>console.error('WEEKLY_LOCAL_BRIDGE_UNAVAILABLE'));
 return server;
}
export function callWeeklyBridge(body,{socketPath=weeklySocket,timeout_ms=180000}={}){
 validate(body);const raw=JSON.stringify(body)+'\n';if(Buffer.byteLength(raw)>1000000)throw Error('REQUEST_TOO_LARGE');
 return new Promise((resolve,reject)=>{const socket=net.createConnection(socketPath);let response='',size=0;socket.setEncoding('utf8');
  socket.setTimeout(timeout_ms,()=>socket.destroy(Error('WEEKLY_BRIDGE_OUTCOME_UNKNOWN')));
  socket.on('connect',()=>socket.write(raw));socket.on('error',()=>reject(Error('WEEKLY_BRIDGE_UNAVAILABLE_OR_OUTCOME_UNKNOWN')));
  socket.on('data',chunk=>{size+=Buffer.byteLength(chunk);if(size>1000000){socket.destroy(Error('WEEKLY_BRIDGE_RESPONSE_INVALID'));return;}response+=chunk;});
  socket.on('end',()=>{try{resolve(JSON.parse(response));}catch{reject(Error('WEEKLY_BRIDGE_RESPONSE_INVALID'));}});
 });
}
