import {test} from 'node:test';
import assert from 'node:assert/strict';
import {buildOutputs,loadConfig} from '../build-seo.mjs';
const config=loadConfig();
function extract(html){return JSON.parse(html.match(/<script id="fc-seo-jsonld" type="application\/ld\+json">([\s\S]*?)<\/script>/)[1]);}
test('three independent static pages have absolute self-canonicals, one H1, crawlable links and matching visible cards',()=>{
 const out=buildOutputs(config),titles=new Set(),descriptions=new Set();
 for(const [view,{path}] of Object.entries(config.seo.pages)){
  const file=path.split('/').at(-1),html=out[file],canonical=config.seo.origin+path;
  assert.equal((html.match(/<h1\b/g)||[]).length,1);assert(html.includes('<link rel="canonical" href="'+canonical+'">'));
  assert(html.includes('content="noindex,follow"'));assert(out['seo-head-'+view+'.html'].includes('index,follow,max-image-preview:large'));
  titles.add(html.match(/<title>(.*?)<\/title>/)[1]);descriptions.add(html.match(/name="description" content="([^"]+)"/)[1]);
  const graph=extract(html)['@graph'];assert.deepEqual(graph.map(x=>x['@type']),['CollectionPage','BreadcrumbList','ItemList']);
  assert.equal(graph[0].url,canonical);assert.equal(graph[1].itemListElement.at(-1).item,canonical);
  assert.deepEqual(graph[1].itemListElement.map(x=>x.position),[1,2,3]);
  assert.equal(graph[2].numberOfItems,3);assert.deepEqual(graph[2].itemListElement.map(x=>x.position),[1,2,3]);
  for(const row of graph[2].itemListElement){const id=row.item.url.split('#')[1];assert(html.includes('id="'+id+'"'));assert(html.includes(row.item.name.replaceAll('&','&amp;')));}
  assert(!JSON.stringify(graph).match(/"(?:offers|aggregateRating|review|price)"/));assert(!html.includes('hreflang='));
  for(const p of Object.values(config.seo.pages))assert(html.includes('href="'+p.path.split('/').at(-1)+'"'));
 }
 assert.equal(titles.size,3);assert.equal(descriptions.size,3);
 assert.equal((out['sitemap.xml'].match(/<loc>/g)||[]).length,3);
});
test('a future configured series and player change updates SSR, metadata, ItemList and guide together',()=>{
 const next=structuredClone(config),oldSeries=next.trio.series;next.trio.series=oldSeries==='Scream'?'Future Test Series':'Scream';
 for(const id of next.trio.ids){next.products[id].version=next.trio.series;next.products[id].title=next.products[id].title.replace(oldSeries,next.trio.series);}
 const first=next.trio.ids[0];next.products[first].name='Configuration Update Test';next.products[first].title='Configuration Update Test/86/LW/'+next.trio.series;
 const out=buildOutputs(next),html=out[next.seo.pages.trio.path.split('/').at(-1)],schema=extract(html);
 assert(html.includes('FC 27 '+next.trio.series+' Players'));assert(html.includes('Configuration Update Test'));assert(!html.includes(oldSeries));
 assert.equal(schema['@graph'][2].itemListElement[0].item.name,next.products[first].title);
 assert(out['structured-data-trio.json'].includes(next.products[first].title));assert(out['activity-fragment-trio.html'].includes('Meet the '+next.trio.series));
});
test('configuration errors fail generation instead of shipping mismatched card versions or duplicate routes',()=>{
 for(const alter of [c=>c.trio.series='Different Invalid Series',c=>c.trio.ids[1]=c.trio.ids[0],c=>c.seo.pages.trio.path=c.seo.pages.weekly.path,c=>c.seo.pages.trio.path='/../Cart.html']){
  const bad=structuredClone(config);alter(bad);assert.throws(()=>buildOutputs(bad));
 }
});
test('script serialization cannot close the JSON-LD tag when a configured name contains HTML',()=>{
 const next=structuredClone(config);next.products[next.trio.ids[0]].title='</script><img src=x onerror=alert(1)>';
 const html=buildOutputs(next)[next.seo.pages.trio.path.split('/').at(-1)];const schema=extract(html);
 assert.equal(schema['@graph'][2].itemListElement[0].item.name,next.products[next.trio.ids[0]].title);
 assert(!html.includes('<img src=x onerror='));assert(html.includes('\\u003c/script>'));
});
test('SBC selection and activity-source eligibility follow the configuration, with SBC second in the navigation',()=>{
 const next=structuredClone(config);next.sbc.defaultId=next.sbc.ids[1];
 const out=buildOutputs(next),html=out[next.seo.pages.sbc.path.split('/').at(-1)],schema=extract(html);
 assert.equal(schema['@graph'][2].itemListElement[0].item.name,next.products[next.sbc.defaultId].title);
 assert.deepEqual([...html.matchAll(/<a data-view="([^"]+)"/g)].map(x=>x[1]),['weekly','sbc','trio']);
 const policy=JSON.parse(out['promotion-policy.json']);assert.equal(policy.discountPercent,10);assert.equal(policy.strategy,'native_discount_code');assert.equal(policy.enabled,false);assert.deepEqual(policy.stackWith,[]);assert.deepEqual(policy.mutuallyExclusiveWith,['coupon','points']);
 assert(policy.eligible.some(x=>x.id===next.products[next.sbc.defaultId].platforms.ps.id));assert(policy.eligible.every(x=>x.aid!==undefined));
});
