const fs=require('fs'),crypto=require('crypto'),child=require('child_process'),assert=require('assert');
const config=JSON.parse(fs.readFileSync('source/targets.json','utf8'));
function canonical(v){return Array.isArray(v)?v.map(canonical):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])])):v;}
const browser=crypto.createHash('sha256').update(JSON.stringify(canonical(config))).digest('hex');
const python=child.execFileSync(process.argv[2]||'python',['-B','-c',"import sys,json;sys.path.insert(0,'source');from management_facts import fingerprint;print(fingerprint(json.load(open('source/targets.json',encoding='utf8'))))"],{encoding:'utf8'}).trim();
assert.equal(browser,python,'browser and published Python target fingerprints must match');
console.log('Python/browser target fingerprint match:',browser);
