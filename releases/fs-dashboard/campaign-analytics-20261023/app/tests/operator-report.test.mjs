import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import core from '../analytics/funnel-core.cjs';import {eventDiagnostics,reportContext} from '../analytics/report-context.mjs';
const row=(id,event,game,extra={},visit='v')=>({event,timestamp:'2026-10-29T07:00:00Z',properties:{activity_id:'mmoexp-seasonal',activity_visit_id:visit,activity_session_id:'s',distinct_id:'anon',event_id:id,game_id:game,device:'desktop',platform:'unknown',source:'direct',...extra}});
test('seasonal journey separates games and deduplicates cross-game visit totals',()=>{
 const rows=[row('view','activity_view'),row('v1','activity_product_view','456'),row('r1','activity_selection','456',{action:'offer_reveal'}),row('r2','activity_selection','1327',{action:'offer_reveal'}),row('s1','activity_selection','456',{action:'product_select'}),row('cart','activity_add_to_cart','456',{complete:true}),row('cart','activity_add_to_cart','456',{complete:true})];
 const result=core.summarize(rows,{activity:'mmoexp-seasonal'});assert.equal(result.visits,1);assert.equal(result.seasonalTotals.revealed,1);assert.equal(result.seasonalGames.length,2);assert.equal(result.seasonalTotals.cart,1);
 const fc=core.summarize(rows,{activity:'mmoexp-seasonal',game:'1327'});assert.equal(fc.visits,1);assert.equal(fc.seasonalTotals.cart,0);assert.deepEqual(fc.seasonalGames.map(g=>g.gameId),['1327']);
 assert.equal(core.summarize(rows,{activity:'mmoexp-seasonal',game:'891'}).visits,0);
});
test('diagnostics reports scoped ingestion separately from visits, without exposing event payloads',()=>{
 const rows=[row('orphan','activity_selection','456',{activity_visit_id:null,action:'game_select'}),row('other','activity_view','456',{activity_id:'fc27-weekly'}),row('old','activity_view','456')];rows[2].timestamp='2026-10-28T07:00:00Z';
 const d=eventDiagnostics(rows,{activity:'mmoexp-seasonal',mode:'live',from:'2026-10-29',to:'2026-10-29'});assert.equal(d.environment,'production');assert.equal(d.eventCount,1);assert.equal(d.lastEventAt,'2026-10-29T07:00:00Z');assert.equal(d.eventCounts.activity_selection,1);assert.equal('events' in d,false);
});
test('public report context exposes names but no checkout policy, prices or private coupon fields',()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'report-context-'));try{
  fs.writeFileSync(path.join(dir,'current.json'),JSON.stringify({release_id:'campaign-preview-16',config_hash:'a'.repeat(64),pages:[{page_id:'seasonal-vault',activity_id:'mmoexp-seasonal',active:true}],halloween:{status:'configured',games:[{admin_game_id:'456',label:'Diablo IV',random_models:['1']}],ends_at:'2026-11-02T23:59:59-05:00'},products:[{title:'Resplendent Spark',price:99,product_ref:{game_id:'456',model_id:'111',goods_id:'333'}}],native_checkout:{secret:'not-exposed'}}));
  const c=reportContext(dir);assert.equal(c.models['456:111'],'Resplendent Spark');assert.equal(c.products['333'],'Resplendent Spark');assert.equal(c.games[0].name,'Diablo IV');assert.equal(c.payment,'not_integrated');assert(!JSON.stringify(c).includes('not-exposed'));assert(!JSON.stringify(c).includes('random_models'));assert(!JSON.stringify(c).includes('price'));
  fs.writeFileSync(path.join(dir,'current.json'),'bad');assert.equal(reportContext(dir),null);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
