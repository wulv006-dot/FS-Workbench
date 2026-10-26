const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process');
const root=path.resolve(__dirname,'../../app/seasonal');
test('current four-game entry and regenerated collection metadata stay English',()=>{
  // Chinese internal registry names and unused labelZh data are intentionally retained.
  for(const file of ['index.html','creative-kit.html','event.js','kit.js','vault-analytics.js','activity-analytics.js','runtime-bridge.js'])assert.doesNotMatch(fs.readFileSync(path.join(root,file),'utf8'),/\p{Script=Han}/u,file);
  assert.doesNotMatch(fs.readFileSync(path.join(root,'../activity-analytics.js'),'utf8'),/\p{Script=Han}/u);
  assert(!fs.readFileSync(path.join(root,'kit.js'),'utf8').includes('theme.labelZh'));
  const html=fs.readFileSync(path.join(root,'index.html'),'utf8'),graph=JSON.parse(html.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)[1]);
  assert.match(html,/<html lang="en"/);assert.match(html,/noindex,nofollow/);
  assert.deepEqual(graph['@graph'][1].itemListElement.map(item=>item.name),['FC27','Aion2','World of Warcraft','MapleStory']);
  assert(!graph['@graph'].some(item=>['Product','Offer'].includes(item['@type'])));assert(graph['@graph'][1].itemListElement.every(item=>!item.url));
  cp.execFileSync(process.execPath,[path.resolve(__dirname,'../build-seo.cjs'),'--check'],{env:{...process.env,CAMPAIGN_PUBLIC_ORIGIN:'',CAMPAIGN_PUBLIC_PREFIX:''}});
});
