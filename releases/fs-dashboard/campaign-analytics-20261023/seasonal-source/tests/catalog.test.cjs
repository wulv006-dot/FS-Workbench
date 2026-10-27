const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../../app/seasonal'),context={};vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(root,'campaign-data.js'),'utf8'),context);
const products=context.SeasonalData.products;
test('real catalog preserves goods identity, exact package price and included bonuses',()=>{
  const expected=[['fc-1',163329311,100,5,1054],['fc-2',163329311,500,25,5270],['fc-3',163329311,1000,50,10540],['nba-1',165466529,50,1,683],['nba-2',165466529,150,8,2048],['nba-3',165466529,300,20,4095],['madden-1',159812737,100,0,309],['madden-2',159812737,300,0,926],['madden-3',159812737,600,0,1833],['diablo-1',1365865,100000,0,58],['diablo-2',1365865,300000,0,171],['diablo-3',1365865,600000,0,324],['poe-1',169644111,1,0,165],['poe-2',169682813,1,0,412],['poe-3',117074411,1,0,4508],['aion-1',178594601,10,0,774],['aion-2',178594601,30,0,2322],['aion-3',178594601,100,0,7740]];
  assert.equal(products.length,expected.length);
  for(const [id,goodsId,quantity,bonus,cents] of expected){const p=products.find(x=>x.id===id);assert(p,id);assert.equal(p.source.goodsId,goodsId,id);assert.equal(p.source.quantity,quantity,id);assert.equal(p.source.bonus,bonus,id);assert.equal(p.priceCents,cents,id);assert.equal(p.source.priceCents,cents,id);assert.equal(p.source.currency,'USD');assert(p.source.aid>0&&p.source.cid>0);}
  assert.equal(context.SeasonalData.games.find(x=>x.id==='nba').unit,'VC');
  assert(products.filter(x=>x.game==='diablo').every(x=>x.amount.includes('M Gold')));
  assert.equal(products.find(x=>x.id==='poe-1').amount,'200 + 10 free Divine Orbs');
});
test('current four-game fixed cards retain safe flip semantics while random slots require the server',()=>{
  const css=fs.readFileSync(path.join(root,'event.css'),'utf8'),js=fs.readFileSync(path.join(root,'event.js'),'utf8');
  assert(css.includes('backface-visibility:hidden'));assert(css.includes('.flip-card.is-revealed{transform:rotateY(180deg)}'));
  assert(css.includes('.card-front{transform:rotateY(180deg)'));assert(css.includes('@media(prefers-reduced-motion:reduce)'));
  assert(js.includes('This card did not open. Tap it to try again.'));assert(js.includes('data-fixed-reveal'));assert(!js.includes('Math.random'));
  assert.deepEqual(Array.from(context.SeasonalHalloweenData.games,g=>g.id),['fc','aion','wow','maplestory']);
});
