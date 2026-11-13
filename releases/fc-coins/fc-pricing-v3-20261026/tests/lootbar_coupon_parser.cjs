const fs=require('fs'), vm=require('vm'), assert=require('assert/strict');
const base=fs.readFileSync('releases/fc-coins/lootbar-spec-repair-20261009/fc27_chrome_collector/test_lootbar_collection.cjs','utf8');
const classes=base.slice(base.indexOf('class Element {'),base.indexOf('function buildCard(')).replace('for (const child of children) child.parent = this;', 'for (const child of children) { child.parent = this; child.parentElement = this; }');
const source=fs.readFileSync(process.argv[2] || 'releases/ops/pricing-recovery-20261023/fc_residency/source/background.js','utf8').replaceAll('\r\n','\n');
const parser=source.slice(source.indexOf('function readVisibleOffer() {'),source.indexOf('\n\nasync function collectOne(target)'));
function read({paid='$8.00',discount='-$2.00',strike=null,advert=false,tiers=[]}={}){
 const setup=`${classes}
 const price=new Element('span',{classes:['discount-price'],text:${JSON.stringify(paid)}});
 const nodes=[new Element('span',{classes:['con-name'],text:'100K Safe Coins'}),price,new Element('span',{classes:['gift-num'],text:'+5K'})];
 ${discount===null?'':`const amount=new Element('span',{text:${JSON.stringify(discount)}}); nodes.push(${advert?"new Element('div',{children:[new Element('span',{text:'Save up to'}),amount]})":"amount"});`}
 ${strike===null?'':`nodes.push(new Element('del',{text:${JSON.stringify(strike)}}));`}
 const card=new Element('div',{classes:['coin-listitem'],children:nodes});
 const more=${JSON.stringify(tiers)}.map(([title,usd,gift])=>new Element('div',{classes:['coin-listitem'],children:[
   new Element('span',{classes:['con-name'],text:title}),new Element('span',{classes:['discount-price'],text:usd}),
   new Element('span',{classes:['gift-num'],text:gift})]}));
 const selected=new Element('a',{classes:['on'],text:'PS4/5'});
 const currency=new Element('button',{classes:['c-nav-prefer'],text:'EN / USD'});
 const document={querySelectorAll(s){return s==='.coin-listitem'?[card,...more]:s==='a.on'?[selected]:[]},querySelector(s){return s==='button.c-nav-prefer'?currency:null}};
 const getComputedStyle=n=>({display:'block',visibility:'visible',textDecorationLine:n.decoration});
 (${parser})(${tiers.length ? '[1000,2000,5000]' : ''});`;
 return vm.runInNewContext(setup,{});
}
const normal=read({paid:'$8.00',discount:null});assert.equal(normal.couponState,'none');
const actual=read();assert.equal(actual.couponState,'excluded');assert.equal(actual.usdPrice,'10.00');assert.equal(actual.reconstruction.method,'derived_actual_discount');
const strike=read({strike:'$10.00'});assert.equal(strike.couponState,'excluded');assert.equal(strike.reconstruction.method,'direct_strike');
const conflict=read({discount:'-$1.00',strike:'$10.00'});assert.equal(conflict.couponState,'relation_mismatch');
const ad=read({discount:'-$50.00',advert:true});assert.notEqual(ad.couponState,'excluded');
const native=read({tiers:[['1M Safe Coins','$69.86','+50K'],['5M Safe Coins','$386.88','+250K'],
 ['5M Safe Coins','$390.00','+250K'],['2M Safe Coins Special Sale','$99.00','+100K']]});
assert.equal(native.baseK,100);
assert.equal(native.quantityOffers['1000'].usdPrice,'69.86');
assert.equal(native.quantityOffers['1000'].bonusK,'50');
assert.equal(native.quantityOffers['2000'].tierState,'missing');
assert.equal(native.quantityOffers['5000'].tierState,'multiple');
console.log('6 shared real-parser cases passed');
