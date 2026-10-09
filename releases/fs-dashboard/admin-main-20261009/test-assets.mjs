import assert from 'node:assert/strict';
import fs from 'node:fs';
import crypto from 'node:crypto';
const read=p=>fs.readFileSync(new URL(p,import.meta.url),'utf8');
const manifest=JSON.parse(read('./asset-manifest.json'));
assert.equal(manifest.files.length,14);
for(const row of manifest.files){
 const bytes=fs.readFileSync(new URL(row.path,import.meta.url));
 assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),row.sha256,row.path);
}
const policy=read('./source-policy.mjs').replaceAll('export function','function').trim();
for(const file of ['business.js','shell.js'])assert(read('./assets/'+file).includes(policy),file+' policy differs from tested source');
const version=read('./assets/home.html').match(/workspace-native-[a-z0-9-]+/)[0];
assert(read('./assets/index.html').includes(version),'entry versions differ');
assert(read('./assets/business.js').includes('const DATA = {profiles:{},groups:[]}'));
assert(read('./assets/business.css').includes('#supplement-insights > label select'));
console.log('14 exact assets, embedded policy, version references and empty runtime data verified.');
