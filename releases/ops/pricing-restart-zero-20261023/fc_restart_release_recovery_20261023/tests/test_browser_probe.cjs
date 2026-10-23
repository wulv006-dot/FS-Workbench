const assert = require('node:assert/strict');
const {inspect, product} = require('../source/browser_probe.js');
async function run(options={}) {
  const calls=[];
  const targets=options.targets || [{type:'page',targetId:'original',url:options.product ? 'https://www.lootbar.com/game-coins/fc27?x=1' : 'about:blank#fc27-idle'}];
  const send=async (method,params={},sessionId) => {
    calls.push({method,params,sessionId});
    if(method==='Target.getBrowserContexts')return {browserContextIds:options.contexts || []};
    if(method==='Target.getTargets')return {targetInfos:targets};
    if(method==='Target.attachToTarget')return {sessionId:'own-session'};
    if(method==='Runtime.evaluate')return {result:{value:options.document !== false}};
    return {};
  };
  try{return {result:await inspect(send),calls};}catch(error){return {error,calls};}
}
(async()=>{
  let value=await run();assert.deepEqual(value.result,{status:'ok'});
  assert.deepEqual(value.calls.map(c=>c.method),['Target.getBrowserContexts','Target.getTargets','Target.attachToTarget','Runtime.evaluate','Target.detachFromTarget']);
  const evaluate=value.calls.find(c=>c.method==='Runtime.evaluate');
  assert.equal(evaluate.sessionId,'own-session');assert.equal(evaluate.params.timeout,2000);
  assert.equal(evaluate.params.contextId,undefined);assert.equal(evaluate.params.uniqueContextId,undefined);
  assert.match(evaluate.params.expression,/querySelectorAll/);
  value=await run({product:true});assert.deepEqual(value.result,{status:'ok'});
  value=await run({contexts:['unexpected']});assert.equal(value.error.message,'browser_context_not_unique');
  value=await run({targets:[]});assert.equal(value.error.message,'product_page_not_unique');
  value=await run({document:false});assert.equal(value.error.message,'browser_document_unavailable');assert.equal(value.calls.at(-1).method,'Target.detachFromTarget');
  value=await run({targets:[{type:'page',targetId:'original',url:'about:blank#fc27-idle'},{type:'worker',url:'blob:https://www.lootbar.com/worker'}]});assert.equal(value.error.message,'owned_idle_not_verified');
  assert.equal(product('https://www.lootbar.com/game-coins/fc27/'),true);
  assert.equal(product('https://attacker.example/game-coins/fc27'),false);
  assert.equal(product('https://www.lootbar.com/game-coins/fc27-extra'),false);
  console.log('browser raw CDP: identity/DOM/Worker and exact session detach pass; no isolated-world commands');
})().catch(error=>{console.error(error);process.exitCode=1;});
