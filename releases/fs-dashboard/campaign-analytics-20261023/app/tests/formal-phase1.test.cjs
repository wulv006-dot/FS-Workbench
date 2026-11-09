const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const app=path.resolve(__dirname,'..'),core=require('../activity-core.js');
test('Admin payable percent is never inverted; unverified boundaries fail closed',()=>{
 for(const [paid,off] of [[100,0],[90,10],[80,20],[1,99]]){
  assert.deepEqual(core.discountFromPayPercent(paid),{payPercent:paid,offPercent:off});
  assert.deepEqual(core.discountFromPayPercent(String(paid)),{payPercent:paid,offPercent:off});
 }
 for(const value of [0,-1,101,90.5,'90.5','90%','',null,true,NaN,Infinity])assert.throws(()=>core.discountFromPayPercent(value));
});
test('Unconfigured phase1 has no invented benefit and cannot unlock legacy live adapter',()=>{
 const config=JSON.parse(fs.readFileSync(path.join(app,'catalog.json'),'utf8'));
 assert.equal(config.activityPricing.discountPercent,10);assert.equal(config.activityPricing.enabled,true);
 assert.deepEqual(config.activityPricing.stackWith,[]);
 const window={location:{origin:'https://www.mmoexp.com'}};
 vm.runInNewContext(fs.readFileSync(path.join(app,'host-adapter.js'),'utf8'),{window});
 assert.throws(()=>window.FCActivityHost.create(config),/handoff requires verification/);
  // Filling a commercial rate is not evidence of a verified transport or checkout.
  const configured=structuredClone(config);configured.activityPricing.discountPercent=10;
  configured.activityPricing.status='configured';
  assert.throws(()=>window.FCActivityHost.create(configured),/handoff requires verification/);
});
test('Generated public pages and metadata never advertise legacy stacking or snapshot prices',async()=>{
 const {buildOutputs,loadConfig}=await import('../build-seo.mjs');const outputs=buildOutputs(loadConfig());
 for(const name of ['Weekly-Scout.html','Sbc-Companions.html','Player-Trio.html']){
  const html=outputs[name];assert.match(html,/<[^>]+id="activity-offer"[^>]*hidden[^>]*><\/[^>]+>/);assert.match(html,/10% OFF/);assert.doesNotMatch(html,/Campaign offer not configured/);
  assert.match(html,/cannot be combined with coupons or member points/);
  assert.match(html,/\$\d+\.\d{2}/);assert.doesNotMatch(html,/Stack eligible|stack eligible|Activity price preview|Public price snapshot/);
  assert.match(html,/<button[^>]+id="submit-selection"[^>]+disabled/);
 }
});
