'use strict';
const assert=require('assert'),fs=require('fs'),path=require('path'),os=require('os'),crypto=require('crypto'),vm=require('vm');
const source=fs.readFileSync(path.join(__dirname,'../../opt/nba-reprice/backend/server.js'),'utf8');
const code=source.slice(source.indexOf('function adminWrite('),source.indexOf('\nfunction appendApplyLog'));
const root=fs.mkdtempSync(path.join(os.tmpdir(),'nba-bound-mock-'));
const pending=[];
const context=vm.createContext({fs,path,crypto,Promise,Error,JSON,Object,String,WRITE_READY:true,WORK_DIR:root,PYTHON:'SYNTHETIC_NOT_EXECUTED',P2PAH_SCRIPT:'SYNTHETIC_NOT_EXECUTED',
 prepareRuntime:()=>{},execFile:(python,args,options,done)=>pending.push({args,done})});
vm.runInContext(code+'; globalThis.run=adminWrite;',context);
function reply(index,override) {
 const call=pending[index],p=JSON.parse(fs.readFileSync(call.args[2],'utf8'));
 const plan=JSON.parse(p.planJson);
 call.done(null,JSON.stringify({ok:true,requestId:p.requestId,planSha256:p.planSha256,operator:plan.operator,observedPrice:plan.prices['PlayStation 5'],...override}));
 return p;
}
(async()=>{
 try {
  const a=context.run({'PlayStation 5':1.1},'wulv','a'.repeat(32));
  const b=context.run({'PlayStation 5':2.2},'DY','b'.repeat(32));
  assert.equal(pending.length,2);assert.notEqual(pending[0].args[2],pending[1].args[2]);
  // Delay A's file read until after B starts; reverse completion to reproduce the old failure ordering.
  const bp=reply(1),ap=reply(0);const [ar,br]=await Promise.all([a,b]);
  assert.equal(ar.observedPrice,1.1);assert.equal(br.observedPrice,2.2);
  assert.equal(ar.planSha256,crypto.createHash('sha256').update(ap.planJson).digest('hex'));
  assert.equal(br.requestId,bp.requestId);
  assert(!fs.existsSync(pending[0].args[2])&&!fs.existsSync(pending[1].args[2]));
  const c=context.run({'PlayStation 5':3.3},'wulv','c'.repeat(32));
  reply(2,{requestId:'a'.repeat(32)});await assert.rejects(c,/BINDING_MISMATCH/);
  const d=context.run({'PlayStation 5':4.4},'wulv','d'.repeat(32));
  pending[3].done(new Error('SYNTHETIC_TIMEOUT'),'');await assert.rejects(d,/OUTCOME_UNKNOWN/);
  assert.equal(pending.length,4);assert.deepEqual(fs.readdirSync(root),[]);
  console.log(JSON.stringify({passed:true,scope:'actual adminWrite isolated temp files and delayed fake execFile; no child process/upstream write'}));
 } finally {
  // Remove only known files and this test-owned empty directory, no recursive deletion.
  for(const name of fs.readdirSync(root))fs.unlinkSync(path.join(root,name));fs.rmdirSync(root);
 }
})().catch(err=>{console.error(err);process.exitCode=1;});
