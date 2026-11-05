const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const dir=__dirname,html=fs.readFileSync(path.join(dir,'index.html'),'utf8');
let count=0;for(const m of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)){if(m[1].trim()){new vm.Script(m[1]);count++;}}
assert(count>0);assert(!html.includes('const INLINE_DATA = {'));
for(const n of ['hubnav.js','nav.js']){
 const text=fs.readFileSync(path.join(dir,'navigation',n),'utf8');new vm.Script(text);
 const r=JSON.parse(text.match(/const registry=(.*);\r?\n/)[1]);
 const ids=r.sections.map(s=>s.id),i=ids.indexOf('sales');assert.equal(ids[i-1],'arpg');assert.equal(ids[i+1],'marketing');
 assert(!r.sections.find(s=>s.id==='arpg').ids.includes('sales'));assert.equal(r.tools.find(t=>t.id==='sales').section,'sales');
}
console.log('Sales scripts compile; registry keeps sales between RPG and marketing.');
