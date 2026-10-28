const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{project,resolveModel}=require('../../app/seasonal/event.js');
const base=()=>({halloween:{schema_version:1,site_id:266,status:'unconfigured',off_percent_tiers:[8,15,10],probabilities:null,tier_product_binding:null,starts_at:null,ends_at:null,games:[{id:'fc',admin_game_id:'1327',fixed_model:null,random_models:[]},{id:'aion',admin_game_id:'891'},{id:'diablo',admin_game_id:'456'},{id:'maplestory',admin_game_id:null}]}});
test('unconfigured public identity always has four games and exactly two mystery slots without invented bindings',()=>{
 const state=project(base());assert.deepEqual(state.games.map(g=>g.id),['fc','aion','diablo','maplestory']);assert(state.games.every(g=>g.random_count===2&&g.fixed_model===null&&g.fixed_off_percent===null));assert.equal(state.probabilities,null);assert.equal(state.binding,null);assert.equal(state.starts_at,null);assert.equal(state.games[2].admin_game_id,'456');
 assert.deepEqual(project({}).games.map(g=>g.id),state.games.map(g=>g.id));
});
test('invalid probability data is not converted to equal odds or normalized by the browser',()=>{
 for(const probabilities of [[],[{off_percent:8,weight:10000}],[{off_percent:8,weight:3333},{off_percent:15,weight:3333},{off_percent:10,weight:3333}],[{off_percent:8,weight:5000},{off_percent:8,weight:2500},{off_percent:10,weight:2500}]]){const c=base();c.halloween.probabilities=probabilities;assert.equal(project(c).probabilities,null);}
 const c=base();c.halloween.probabilities=[{off_percent:8,weight:2000},{off_percent:15,weight:3000},{off_percent:10,weight:5000}];assert.deepEqual(project(c).probabilities,c.halloween.probabilities);
});
test('fixed model resolution keeps site, game, model and product namespaces distinct',()=>{
 const c=base();c.halloween.games[0].fixed_model='fixture-model';c.products=[{key:'correct',product_ref:{site_id:'266',game_id:'1327',model_id:'fixture-model',goods_id:'fixture-goods'}},{key:'wrong-game',product_ref:{site_id:'266',game_id:'891',model_id:'fixture-model'}},{key:'goods-is-not-model',product_ref:{site_id:'266',game_id:'1327',goods_id:'fixture-model'}},{key:'wrong-site',product_ref:{site_id:'other',game_id:'1327',model_id:'fixture-model'}}];assert.deepEqual(resolveModel(c,project(c).games[0]).map(p=>p.key),['correct']);
});
test('current entry loads one Halloween interface and has no old demo reward or Wishing Pool UI',()=>{
 const root=path.resolve(__dirname,'../../app/seasonal'),html=fs.readFileSync(path.join(root,'index.html'),'utf8'),js=fs.readFileSync(path.join(root,'event.js'),'utf8');assert.doesNotMatch(html,/wishing-pool|data-action="(?:pool|invite|refresh)"|vault-core\.js|vault-analytics\.js/);assert.doesNotMatch(js,/Math\.random|localStorage|sessionStorage|priceCents|fetch\(/);assert.match(html,/runtime-bridge\.js/);assert.match(js,/seasonal:model-buy/);assert.doesNotMatch(html,/\p{Script=Han}/u);
});
