import test from 'node:test';import assert from 'node:assert/strict';
import {backendRead,backendMutate} from '../analytics/backend-client.mjs';
test('backend actions cannot cross read/mutation boundary before any subprocess',()=>{
 for(const action of ['benefit_edit','benefit_toggle','operation_reconcile','analysis_reconcile'])assert.throws(()=>backendRead({action,site_id:'266'}),/ACTION_NOT_ALLOWED/);
 for(const action of ['benefit_detail','operation_lookup','analysis_summary','create','grant','capabilities'])assert.throws(()=>backendMutate({action,site_id:'266'}),/ACTION_NOT_ALLOWED/);
 assert.throws(()=>backendMutate({action:'benefit_toggle',site_id:'0'}),/SITE_SCOPE_REQUIRED/);
});
