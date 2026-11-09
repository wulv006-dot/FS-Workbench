// Fixed local IPC client. Center state is owned exclusively by the existing management service.
import {callWeeklyBridge} from './weekly-bridge.mjs';
let body;
try{
 let raw='';for await(const chunk of process.stdin){raw+=chunk;if(Buffer.byteLength(raw)>1000000)throw Error('REQUEST_TOO_LARGE');}
 body=JSON.parse(raw);const result=await callWeeklyBridge(body);process.stdout.write(JSON.stringify(result));if(result.status==='failed')process.exitCode=1;
}catch(error){process.stdout.write(JSON.stringify({status:'failed',...(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(body?.operation_id||'')?{operation_id:body.operation_id}:{}),error:/^[A-Z][A-Z0-9_]{0,99}$/.test(error.message)?error.message:'WEEKLY_PIPELINE_FAILED',publication:false}));process.exitCode=1;}
