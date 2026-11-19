import test from 'node:test';
import assert from 'node:assert/strict';
import {makeGoogleTraffic} from '../analytics/google-traffic.mjs';
const params=(source='gsc')=>new URLSearchParams({activity:'mmoexp-seasonal',source,from:'2026-10-26',to:'2026-10-30'});
test('Google page reports validate before reading; concurrent identical reads coalesce and cache clones',async()=>{
 let calls=0;const query=makeGoogleTraffic(async request=>{calls++;await new Promise(r=>setTimeout(r,5));return {status:'no_rows',source:request.source,reports:{}};});
 const values=await Promise.all([query(params()),query(params())]);assert.equal(calls,1);values[0].reports.changed=true;assert.deepEqual((await query(params())).reports,{});
 for(const [key,value]of [['source','other'],['activity','other'],['from','2026-02-30'],['path','/etc/passwd'],['refresh','yes']]){const p=params();p.set(key,value);await assert.rejects(query(p));}const duplicate=params();duplicate.append('source','ga4');await assert.rejects(query(duplicate));assert.equal(calls,1);
});
test('same dates and source for two activities use distinct page scopes',async()=>{
 const requests=[],query=makeGoogleTraffic(async request=>{requests.push(request);return {status:'no_rows'};});
 const carnival=params();carnival.set('activity','mmoexp-carnival');
 await query(params());await query(carnival);await query(carnival);
 assert.equal(requests.length,2);
 assert.equal(requests[1].activity,'mmoexp-carnival');
});
test('failures remain missing with short backoff; different source does not start a second child',async()=>{
 let now=Date.parse('2026-10-31T08:00:00Z'),calls=0,release;const query=makeGoogleTraffic(async()=>{calls++;if(calls===1)await new Promise(r=>release=r);throw Error('private error');},()=>now);
 const first=query(params());assert.equal((await query(params('ga4'))).reason,'GOOGLE_READER_BUSY');release();assert.equal((await first).reason,'GOOGLE_READ_FAILED');await query(params());assert.equal(calls,1);now+=5001;await query(params());assert.equal(calls,2);
});
