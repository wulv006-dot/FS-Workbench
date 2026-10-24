const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'..');
const context={};vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root,'dist/campaign-data.js'),'utf8'),context);
const data=context.SeasonalData;
assert.equal(Object.keys(data.themes).length,4);
assert.equal(data.games.length,6);
assert.equal(data.products.length,18);
assert.equal(new Set(data.products.map(p=>p.id)).size,18);
assert.equal(data.spotlight.length,8);
for(const id of data.spotlight)assert(data.products.some(p=>p.id===id),id);
for(const game of data.games){
  assert.equal(data.products.filter(p=>p.game===game.id).length,3);
  assert.equal(new URL(game.url).origin,'https://www.mmoexp.com');
  assert(fs.existsSync(path.join(root,'dist/assets',`art-${game.id}.webp`)));
  assert.equal(game.frames.length,3);
  for(const [x,y,w,h] of game.frames){assert(x>=0&&y>=0&&w>0&&h>0);assert(x+w<=2172&&y+h<=724);}
}
for(const product of data.products){
  assert(Number.isSafeInteger(product.priceCents)&&product.priceCents>0);
  assert.equal(product.priceCents,product.source.priceCents);
  assert(Number.isSafeInteger(product.source.goodsId)&&product.source.goodsId>0);
  assert.equal(product.source.currency,"USD");
  assert(product.source.quantity>0&&product.source.platform&&product.source.capturedAt);
  assert.equal(new URL(product.source.url).origin,"https://www.mmoexp.com");
  assert(product.artIndex>=0&&product.artIndex<3);
}
for(const theme of Object.keys(data.themes))assert(fs.existsSync(path.join(root,'dist/assets',`hero-${theme}.webp`)));
for(const name of ['index.html','creative-kit.html']){
  const html=fs.readFileSync(path.join(root,'dist',name),'utf8');
  for(const match of html.matchAll(/(?:src|href)="([^"#?]+)"/g)){
    const ref=match[1];if(/^https?:/.test(ref))continue;
    assert(fs.existsSync(path.join(root,'dist',ref)),`${name}: missing ${ref}`);
  }
}
console.log('PASS: four themes; six game families; eighteen unique configured offers; eight valid spotlight slots; mapped integer USD base prices; all sprite frames and local assets valid.');
const html=fs.readFileSync(path.join(root,'dist/index.html'),'utf8');
const graph=JSON.parse(html.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)[1]);
assert.equal(graph['@graph'][1].itemListElement.length,6);
assert(!graph['@graph'].some(x=>x['@type']==='Offer'||x['@type']==='Product'));
assert(html.includes('noindex,nofollow'));
for(const game of data.games){assert(Number.isInteger(game.fixedDiscountPercent)&&game.fixedDiscountPercent>=0&&game.fixedDiscountPercent<10);assert(html.includes(game.url));for(const p of data.products.filter(p=>p.game===game.id))assert(html.includes(p.name.replace(/&/g,'&amp;').replace(/'/g,'&#39;')));}
assert(data.featuredGames.every(id=>data.games.some(g=>g.id===id)));
console.log('PASS: static product text and links; six category graph entries; no fictional Offer schema; per-game fixed discounts lower than mystery tiers.');
