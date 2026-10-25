const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process');
const root=path.resolve(__dirname,'../../app/seasonal');
test('maintained public copy and regenerated SEO stay English',()=>{
  // Chinese internal registry names and unused labelZh data are intentionally retained.
  for(const file of ['index.html','creative-kit.html','event.js','kit.js','vault-analytics.js','activity-analytics.js','runtime-bridge.js'])assert.doesNotMatch(fs.readFileSync(path.join(root,file),'utf8'),/\p{Script=Han}/u,file);
  assert.doesNotMatch(fs.readFileSync(path.join(root,'../activity-analytics.js'),'utf8'),/\p{Script=Han}/u);
  assert(!fs.readFileSync(path.join(root,'kit.js'),'utf8').includes('theme.labelZh'));
  cp.execFileSync(process.execPath,[path.resolve(__dirname,'../build-seo.cjs'),'--check'],{env:{...process.env,CAMPAIGN_PUBLIC_ORIGIN:'',CAMPAIGN_PUBLIC_PREFIX:''}});
});
