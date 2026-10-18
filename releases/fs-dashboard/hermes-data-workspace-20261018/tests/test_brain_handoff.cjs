'use strict';
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../source/brain.js'),'utf8');
const begin=source.indexOf('  const dataKind=initial.get');
const end=source.indexOf('  refresh().then',begin);
assert(begin>=0&&end>begin,'real handoff block missing');
const handoff=new Function('initial','$','message','let dataRequest=null;'+source.slice(begin,end)+';return dataRequest;');
const cases=JSON.parse(fs.readFileSync(path.join(__dirname,'handoff-cases.json'),'utf8'));
for(const test of cases){
 const fields={};
 const result=handoff(new URLSearchParams(test.input),id=>fields[id]||(fields[id]={}),()=>{});
 assert.deepEqual(result,test.expected,test.name);
}
console.log('PASS: real URL form handoff matches shared typed payloads, including invalid window and unknown kind');
