const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const model=require('../activity-content.js');
const original=JSON.parse(fs.readFileSync(require.resolve('../catalog.json'),'utf8'));
const han=/[\u3400-\u9fff\uf900-\ufaff]/u;
test('public content stays English for old zh inputs and contaminated display fields without changing product identities or rules',()=>{
 const input=structuredClone(original);input.defaultLanguage='zh';input.weekly.edition.en='中文标签';input.platforms.ps.label='中文平台';input.trio.roles.forEach(role=>role.en='中文位置');Object.values(input.sbc.routes).forEach(route=>route.label.en='中文搭配');
 for(const p of Object.values(input.products)){p.name='中文姓名';p.title='中文名称';p.league='中文联赛';p.club='中文球队';if(p.included)p.included.forEach(row=>{row.name='中文队员';});}
 const safe=model.publicConfig(input);assert.equal(safe.defaultLanguage,'en');assert.deepEqual(Object.keys(safe.products),Object.keys(input.products));for(const key of Object.keys(input.products)){assert.deepEqual(safe.products[key].platforms,input.products[key].platforms);assert.equal(safe.products[key].key,input.products[key].key);}
 assert.deepEqual(safe.activityPricing,input.activityPricing);const content=model.create(input);for(const view of ['weekly','sbc','trio']){const p=content.page(view,'zh');assert.equal(p.lang,'en');assert(!han.test(JSON.stringify(p)));}
 for(const p of Object.values(input.products)){const rendered=p.kind==='bundle'?content.bundle(p,{lang:'zh'}):content.card(p,{lang:'zh',label:'中文标签'});assert(!han.test(rendered));}assert(!han.test(content.promotionText('zh')));
});
test('every generated FC page, fragment, SEO/JSON-LD and template is English with no locale switch',async()=>{
 const {buildOutputs}=await import('../build-seo.mjs');const out=buildOutputs(original);for(const [name,body] of Object.entries(out)){if(/^(?:index.html|Weekly-Scout.html|Sbc-Companions.html|Player-Trio.html|activity-fragment-|seo-head-|structured-data-|validation\/)/.test(name)){assert(!han.test(body),name);assert(!body.includes('id="lang-zh"'),name);}}
 for(const name of ['index.html','Weekly-Scout.html','Sbc-Companions.html','Player-Trio.html']){
  assert.equal((out[name].match(/src="seasonal\/activity-analytics\.js"/g)||[]).length,1,name+' shares published tracking');
  assert(!out[name].includes('src="activity-analytics.js"'),name+' does not restore legacy preview tracker');
 }
 for(const name of ['page-template.html','locale-controls.html'])assert(!han.test(fs.readFileSync(require.resolve('../'+name),'utf8')),name);
});
