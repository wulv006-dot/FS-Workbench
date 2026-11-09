import test from 'node:test';
import assert from 'node:assert/strict';
import * as history from '../weekly-hermes.mjs';
const request={model:'gpt-6.1-sol',dedupe_key:'historical',input:{source_revision:'1',sbc_update:{id:'old',observed_at:'2026-11-09T09:00:00Z',expires_at:null,sources:[]},pages:[],catalog:[]}};
test('historical response validation remains but generation exports are removed',()=>{
 assert.equal(history.prepareWeeklyRequest,undefined);assert.equal(history.recommendWeekly,undefined);
 const result=history.projectWeeklyResponse({model:request.model,source_revision:'1',sbc_update_id:'old',recommendations:[]},request);assert.equal(result.status,'completed');assert.equal(result.publication,false);
});
test('historical response still binds exact model, source and update identity',()=>{
 for(const changes of [{model:'other'},{source_revision:'2'},{sbc_update_id:'other'},{recommendations:[{page_id:'fc27-trio',product_key:'unknown',reason:'invented',evidence_indices:[]}]}])assert.throws(()=>history.projectWeeklyResponse({model:request.model,source_revision:'1',sbc_update_id:'old',recommendations:[],...changes},request));
});
