import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {presentPage,projectFcCatalog} from '../presentation.mjs';

const source='<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Original concept</title><meta name="description" content="Original description"><meta content="Duplicate old description" name="description"><meta property="og:title" content="Old title"><meta content="Old description" property="og:description"><meta name="twitter:title" content="Old title"><link rel="canonical" href="https://www.mmoexp.com/original"><link rel="stylesheet" href="activity.css"><script type="application/ld+json">{"@type":"CollectionPage","name":"Old title","description":"Original schema","url":"https://www.mmoexp.com/original"}</script></head><body class="original-design"><main id="offers"><h1>Original design heading</h1><button>Original offer</button><span id="campaign-date" class="caption-date">CONCEPT — OCT 24 – NOV 02</span></main><script src="activity.js"></script></body></html>';
const paths=['Weekly-Scout.html','Sbc-Companions.html','Player-Trio.html','seasonal/index.html'];
const snapshot=()=>({schema_version:1,publication_status:'published',release_id:'published-1',pages:paths.map((path,i)=>({path,page_id:'page-'+i,title:'Published title '+i,description:'Published description '+i,active:true,starts_at:'2026-10-24T09:00:00Z',ends_at:'2026-10-25T10:00:00Z',product_keys:[]}))});
const render=(s=snapshot(),name=paths[0],now='2026-10-24T10:00:00Z')=>presentPage({name,body:source,snapshot:s,now});

test('published config renders exact visible copy and metadata while retaining active design',()=>{
  const s=snapshot(),first=render(s);assert.equal(first.status,200);
  for(const name of paths){const {body}=render(s,name);assert.match(body,/class="original-design"/);assert.match(body,/<main id="offers">/);assert.match(body,/<script src="activity.js"><\/script>/);assert.equal((body.match(/<h1\b/g)||[]).length,1);}
  s.release_id='published-2';s.pages[0].title='Next $& title';s.pages[0].description='Next published description';
  const next=render(s).body;assert.match(next,/<title>Next \$&amp; title<\/title>/);assert.match(next,/<h2 id="campaign-published-title">Next \$&amp; title<\/h2>/);assert.match(next,/<meta property="og:title" content="Next \$&amp; title">/);
  assert.equal((next.match(/name="description"/g)||[]).length,1);assert.match(next,/<meta name="description" content="Next published description">/);assert.ok(!next.includes('Old description'));
  assert.ok(next.includes('"name":"Next $& title"'));assert.ok(next.includes('"description":"Next published description"'));
  assert.match(next,/<link rel="canonical" href="https:\/\/www.mmoexp.com\/original">/);
});
test('UTC time labels replace illustrative dates and aliases resolve the published page',()=>{
  const s=snapshot();s.pages[0].starts_at='2026-10-24T17:00:00+08:00';
  const body=render(s,'index.html').body;assert.match(body,/2026-10-24 09:00:00\.000 UTC/);assert.match(body,/datetime="2026-10-24T09:00:00\.000Z"/);assert.ok(!body.includes('CONCEPT — OCT 24'));
  assert.match(render(s,'seasonal/').body,/Published title 3/);
  const unset=snapshot();delete unset.pages[0].starts_at;delete unset.pages[0].ends_at;assert.match(render(unset).body,/Starts: not specified · Ends: not specified/);
});
test('disabled, missing and draft publication hide original offers and executable clients',()=>{
  for(const mutate of [s=>s.pages[0].active=false,s=>s.pages.shift(),s=>s.publication_status='draft']){
    const s=snapshot();mutate(s);const result=render(s);assert.equal(result.status,404);assert.ok(!result.body.includes('Original offer'));assert.ok(!result.body.includes('<script'));assert.match(result.body,/This activity is not available/);assert.match(result.body,/rel="stylesheet"/);
  }
});
test('upcoming and end boundaries expose truthful status and no original offers',()=>{
  const upcoming=render(snapshot(),paths[0],'2026-10-24T08:59:59Z');assert.equal(upcoming.status,200);assert.match(upcoming.body,/Upcoming activity/);assert.match(upcoming.body,/2026-10-24 09:00:00\.000 UTC/);assert.ok(!upcoming.body.includes('Original offer'));
  assert.match(render(snapshot(),paths[0],'2026-10-24T09:00:00Z').body,/Original offer/);
  const ended=render(snapshot(),paths[0],'2026-10-25T10:00:00Z');assert.equal(ended.status,410);assert.match(ended.body,/has ended/);assert.ok(!ended.body.includes('Original offer'));assert.ok(!ended.body.includes('<script'));
  const malformed=snapshot();malformed.pages[0].starts_at='bad';assert.equal(render(malformed).status,404);
});
test('published text is escaped for HTML, metadata and structured data without adding canonical',()=>{
  const s=snapshot();s.pages[0].title='<img src=x onerror="evil()"> & \'title\'';s.pages[0].description='</script><script>evil()</script> " &';
  const result=presentPage({name:paths[0],body:source.replace(/<link rel="canonical"[^>]*>/,''),snapshot:s,now:'2026-10-24T10:00:00Z'}).body;
  assert.ok(!result.includes('<img src=x'));assert.ok(!result.includes('<script>evil()'));assert.match(result,/&lt;img src=x onerror=&quot;evil\(\)&quot;&gt; &amp; &#39;title&#39;/);assert.ok(result.includes('\\u003c/script>'));assert.ok(!result.includes('rel="canonical"'));
});
test('blank description preserves source description and repeat presentation does not duplicate banner',()=>{
  const s=snapshot();s.pages[0].description='';const result=render(s).body;
  assert.match(result,/<meta name="description" content="Original description">/);assert.match(result,/"description":"Original schema"/);
  const again=presentPage({name:paths[0],body:result,snapshot:s,now:'2026-10-24T10:00:00Z'}).body;assert.equal((again.match(/id="campaign-published-details"/g)||[]).length,1);
  const asset=Buffer.from('asset bytes');assert.deepEqual(presentPage({name:'activity.js',body:asset,snapshot:s}),{status:200,body:asset});
});
test('the actual FC source keeps its main design, stylesheet and one visible main heading',()=>{
  for(const path of paths.slice(0,3)){
    const original=fs.readFileSync(new URL('../../'+path,import.meta.url),'utf8');
    const result=presentPage({name:path,body:original,snapshot:snapshot(),now:'2026-10-24T10:00:00Z'});
    assert.equal(result.status,200);assert.match(result.body,/<main id="fc-activity"/);assert.match(result.body,/href="activity.css/);assert.equal((result.body.match(/<h1\b/g)||[]).length,1);assert.match(result.body,/class="fc-activity fca-container fca-guide"/);
  }
});

const catalog=JSON.parse(fs.readFileSync(new URL('../../catalog.json',import.meta.url),'utf8'));
const keys=ids=>ids.flatMap(id=>['ps','xbox','pc'].map(platform=>'fc-'+id+'-'+platform));
function selection(){const s=snapshot();s.pages.forEach(p=>p.product_keys=[]);return s;}
test('published weekly/trio/bundle selection projects only known original identities and ordering',()=>{
  const before=JSON.stringify(catalog),s=selection(),weekly=[catalog.weekly.ids[2],catalog.weekly.ids[0]],trio=[...catalog.trio.ids].reverse();
  s.pages[0].product_keys=[...keys(weekly),'fc-invented-ps','fc-'+weekly[0]+'-invalid','seasonal-vault','fc-'+catalog.bundles.ids[0]+'-ps'];
  s.pages[2].product_keys=keys([...trio,catalog.bundles.ids[1]]);
  const result=projectFcCatalog(catalog,s);assert.deepEqual(result.weekly.ids,weekly);assert.deepEqual(result.trio.ids,trio);assert.deepEqual(result.bundles.ids,[catalog.bundles.ids[1]]);
  for(const id of [...weekly,...trio])assert.deepEqual(result.products[id],catalog.products[id]);
  assert.equal(result.manageDocumentLanguage,false);assert.equal(result.defaultView,'weekly');assert.equal(result.mode,'preview');assert.equal(JSON.stringify(catalog),before);assert.ok(!('invented' in result.products));
  s.pages[0].active=false;assert.deepEqual(projectFcCatalog(catalog,s).weekly.ids,[]);
});
test('SBC projection distinguishes cores, retains only chosen original routes and safe default',()=>{
  const s=selection(),core=catalog.sbc.ids[1],original=catalog.sbc.routes[core],picks=original.picks;
  s.pages[1].product_keys=keys([core,...picks]);const result=projectFcCatalog(catalog,s);
  assert.deepEqual(result.sbc.ids,[core]);assert.equal(result.sbc.defaultId,core);assert.deepEqual(Object.keys(result.sbc.routes),[core]);assert.deepEqual(result.sbc.routes[core].picks,picks);assert.deepEqual(result.sbc.routes[core].alternatives,[]);assert.deepEqual(result.sbc.routes[core].label,original.label);assert.deepEqual(result.sbc.fallbackPicks,picks);assert.deepEqual(result.sbc.allListedIds,[core]);
  const empty=projectFcCatalog(catalog,selection());assert.deepEqual(empty.weekly.ids,[]);assert.deepEqual(empty.trio.ids,[]);assert.deepEqual(empty.sbc.routes,{});assert.equal(empty.sbc.defaultId,null);
});
