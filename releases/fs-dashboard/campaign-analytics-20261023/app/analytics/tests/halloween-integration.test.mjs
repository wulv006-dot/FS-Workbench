import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {randomUUID} from 'node:crypto';import test from 'node:test';import assert from 'node:assert/strict';
import {makeCenterStore,initialCenterDraft} from '../center-store.mjs';
import {emptyHalloween,projectHalloween} from '../../runtime/halloween-contract.mjs';
const product={key:'synthetic-fc',title:'Synthetic model',product_ref:{site_id:'266',game_id:'1327',model_id:'90001',goods_id:'90002'},platform:{code:'ps'},quantity:{min:'1',max:'10',step:'1',unit:'item'},attributes:[],available:false};
function setup(){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'halloween-integration-'));return {dir,store:makeCenterStore({dir:path.join(dir,'private'),publicDir:path.join(dir,'public'),sourceRevision:'synthetic-only',seedProducts:[product],pageProductKeys:{'fc27-weekly':[],'fc27-sbc':[],'fc27-trio':[],'seasonal-vault':[]}})};}
test('Explicit Halloween slots save → publish projection, retaining old page shape and no live permission',()=>{const {dir,store}=setup();try{
 const before=store.read().draft,draft=structuredClone(before);draft.halloween=emptyHalloween();draft.halloween.games[0].fixed_model='90001';draft.halloween.games[0].fixed_off_percent=8;
 store.save({revision:0,operation_id:randomUUID(),draft},'synthetic-admin');store.publish({revision:1,operation_id:randomUUID()},'synthetic-admin');
 const pub=JSON.parse(fs.readFileSync(path.join(dir,'public/current.json'),'utf8'));assert.equal(pub.halloween.games[0].fixed_model,'90001');assert.equal(pub.halloween.probabilities,null);assert.equal(pub.halloween.status,'unconfigured');
 assert.deepEqual(pub.pages.find(p=>p.page_id==='seasonal-vault').product_keys,['synthetic-fc']);assert.deepEqual(store.read().draft.pages,before.pages);assert.equal(pub.products[0].available,false);assert.equal(pub.updated_by,undefined);
}finally{fs.rmSync(dir,{recursive:true,force:true});}});
test('Restore removes newly added Halloween property exactly; stale changes and wrong model rejected',()=>{const {dir,store}=setup();try{
 const before=store.read().draft;store.save({revision:0,operation_id:randomUUID(),draft:before},'synthetic');const next=structuredClone(before);next.halloween=emptyHalloween();store.save({revision:1,operation_id:randomUUID(),draft:next},'synthetic');
 store.restoreDraft({revision:2,operation_id:randomUUID(),restore_revision:1},'synthetic');assert.deepEqual(store.read().draft,before);
 assert.throws(()=>store.save({revision:2,operation_id:randomUUID(),draft:next},'synthetic'),e=>e.code==='REVISION_CONFLICT');next.halloween.games[0].fixed_model='99999';assert.throws(()=>store.save({revision:3,operation_id:randomUUID(),draft:next},'synthetic'),e=>e.code==='HALLOWEEN_MODEL_NOT_IN_CATALOG');
}finally{fs.rmSync(dir,{recursive:true,force:true});}});
test('A release saved before the roster change still projects instead of failing the whole campaign',()=>{
 // server.mjs serves every campaign page through one projectRelease(), so refusing the
 // roster an existing release was written with would take FC down too.
 const h=emptyHalloween();
 h.games[2]={...h.games[2],id:'wow',label:'World of Warcraft',admin_game_id:null};
 const projected=projectHalloween(h);
 assert.deepEqual(projected.games.map(g=>g.id),['fc','aion','wow','maplestory']);
 assert.equal(projected.games[2].label,'World of Warcraft');
 // Real historical WoW releases use three amounts of one gold model.
 h.games[2]={...h.games[2],admin_game_id:'1367',fixed_model:'90003',fixed_off_percent:10,
  fixed_quantity:{value:'100',unit:'K',conversion_verified:false},
  random_source:{mode:'quantity_tiers',category_id:null,snapshot_complete:false},
  random_quantities:[{value:'200',unit:'K'},{value:'400',unit:'K'}]};
 assert.deepEqual(projectHalloween(h).games[2],h.games[2]);
 const invalid=structuredClone(h);invalid.games[2].random_quantities[0].unit='M';
 assert.throws(()=>projectHalloween(invalid),e=>e.code==='INVALID_HALLOWEEN_CONFIG');
 const wrongGame=structuredClone(h);wrongGame.games[0]={...wrongGame.games[0],
  random_source:h.games[2].random_source,random_quantities:h.games[2].random_quantities};
 assert.throws(()=>projectHalloween(wrongGame),e=>e.code==='INVALID_HALLOWEEN_CONFIG');
 // A roster the contract has never shipped is still rejected.
 const foreign=structuredClone(h);foreign.games[2].id='eso';
 assert.throws(()=>projectHalloween(foreign),e=>e.code==='INVALID_HALLOWEEN_CONFIG');
});
test('No implicit odds, wrong scope or accidental activation',()=>{for(const mutate of [h=>h.status='active',h=>h.games[0].admin_game_id='891',h=>h.games[0].fixed_off_percent=20,h=>h.probabilities=[{off_percent:8,weight:1},{off_percent:10,weight:1},{off_percent:15,weight:1}],h=>h.wishing_pool=true]){const h=emptyHalloween();mutate(h);assert.throws(()=>projectHalloween(h));}});
test('FC fixed 1000K is a business amount, category modes stay distinct and pool eligibility never duplicates',async()=>{
 const {eligibleHalloweenPool}=await import('../../runtime/halloween-contract.mjs');const h=emptyHalloween();assert.deepEqual(h.games[0].fixed_quantity,{value:'1000',unit:'K',conversion_verified:false});
 const game=h.games[0];game.fixed_model='90001';game.random_source={mode:'category_dynamic',category_id:'100',snapshot_complete:false};
 const row=id=>({model_id:id,site_id:'266',game_id:'1327',category_id:'100',sellable:true});
 const observations={complete:true,models:[row('90001'),row('90002'),row('90002'),{...row('90003'),sellable:false},{...row('90004'),site_id:'9'}]};
 assert.deepEqual(eligibleHalloweenPool(game,observations),{status:'insufficient_products',models:['90002']});observations.models.push(row('90005'));assert.deepEqual(eligibleHalloweenPool(game,observations),{status:'eligible_not_drawn',models:['90002','90005']});assert.equal(eligibleHalloweenPool(game,{...observations,complete:false}).status,'catalog_incomplete');
 const bad=structuredClone(h);bad.games[0].random_models=['90002'];assert.throws(()=>projectHalloween(bad));
});
test('Trusted model option provider passes sanitized publication projection; draft cannot inject it',async()=>{
 const {projectModelOptions}=await import('../../runtime/model-options.mjs');const dir=fs.mkdtempSync(path.join(os.tmpdir(),'halloween-options-'));
 try{
 const contract={schema_version:1,verified:true,catalog_version:'synthetic',model_ref:{site_id:'266',game_id:'1327',model_id:'90001'},ordering_verified:true,ordering_evidence:'private source path must not leave provider',secret:'PRIVATE_FIXTURE',fields:[{id:'server',label:'服务器',depends_on:[],values:[{id:'east',label:'东区'}]}],combinations:[{product_key:'synthetic-fc',choices:{server:'east'},attributes:[],quantity:{min:'1',max:'1',step:'1',unit:'item'},price:{source:'admin_current',base_minor:10000,minor_unit_scale:2,currency:'USD',quantity_value:'1',expires_at:'2099-01-01T00:00:00Z'}}]};
 const seed={seedProducts:[product],pageProductKeys:{'seasonal-vault':['synthetic-fc']},seasonal_model_contracts:{'90001':contract}},store=makeCenterStore({dir:path.join(dir,'private'),publicDir:path.join(dir,'public'),sourceRevision:'synthetic',seedProvider:()=>seed});
 const forged=store.read().draft;forged.seasonal_model_contracts=seed.seasonal_model_contracts;assert.throws(()=>store.save({revision:0,operation_id:randomUUID(),draft:forged},'synthetic'));
 store.publish({revision:0,operation_id:randomUUID()},'synthetic');const pub=JSON.parse(fs.readFileSync(path.join(dir,'public/current.json'),'utf8'));assert.equal(pub.seasonal_model_contracts['90001'].combinations[0].price.base_minor,10000);assert.doesNotMatch(JSON.stringify(pub),/PRIVATE_FIXTURE|private source path|服务器|东区/);
 const leak=structuredClone(contract);leak.combinations[0].quantity.group={private_response:{token:'SYNTHETIC_SECRET'}};assert.throws(()=>projectModelOptions({'90001':leak},[product]));
 const wrong=structuredClone(contract);wrong.model_ref.game_id='891';assert.throws(()=>projectModelOptions({'90001':wrong},[product]));
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
