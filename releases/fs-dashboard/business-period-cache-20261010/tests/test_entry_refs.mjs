import assert from 'node:assert/strict';import fs from 'node:fs';
const dir=new URL('../deploy/frontend/',import.meta.url),m=JSON.parse(fs.readFileSync(new URL('release-manifest.json',dir)));
for(const entry of ['assets/home.html','assets/index.html',...m.targets.filter(x=>!x.target.endsWith('navigation.js')).map(x=>x.candidate)]){
 const text=fs.readFileSync(new URL(entry,dir),'utf8');const versions=text.match(/workspace-native-20261006-[a-f0-9]{12}/g)||[];
 assert.ok(versions.length,entry);assert.ok(versions.every(x=>x===m.releaseId),entry+' references old asset version');
}
for(const row of m.immutableAssets)assert.equal(row.url,'/dashboard/workspace-assets/'+m.releaseId+'/'+row.candidate.split('/').at(-1));
console.log('Actual home/analytics entry references match the frozen version.');
