const {test}=require('node:test'),assert=require('node:assert/strict');
const {nativeModelOffer}=require('../activity-core.js'),content=require('../activity-content.js');
function fixture(){
 const ref={site_id:'266',game_id:'1327',model_id:'99',goods_id:'101'},quantity={min:'1',max:'1',step:'1',unit:'item',group:'1'};
 const model={key:'model-266-1327-99',model_id:'99',title:'Fixture / 88 / CM / Gold',kind:'player',preview_only:true,platforms:{ps:{state:'verified',product_ref:ref}}};
 const product={key:'admin-101',product_ref:ref,platform:{code:'ps',attribute_id:'21587'},quantity,attributes:[],available:false};
 const price={source:'admin_current',base_minor:1234,currency:'USD',minor_unit_scale:2,quantity_value:'1',expires_at:'2099-01-01T00:00:00Z'};
 const trade={products:[{...product,key:'fc-model-266-1327-99-ps',preview_only:true},product],seasonal_model_contracts:{99:{verified:true,model_ref:{site_id:'266',game_id:'1327',model_id:'99'},combinations:[{product_key:product.key,quantity,attributes:[],price}]}},native_checkout:{status:'configured',origin:'https://www.mmoexp.com',consumer_behavior_confirmed:true,valid_from:'2020-01-01T00:00:00Z',valid_until:'2099-01-01T00:00:00Z',bindings:[{activity_id:'fc27-season2',page_id:'fc27-weekly',product_key:product.key,off_percent:10,quantity:{value:'1',unit:'item'},attributes:[],native:{id:'101',aid:'21587',group:'1',num:'1'}}]}};
 return {model,trade};
}
test('exact native model price joins preserve identity-only flags and original product key',()=>{
 const {model,trade}=fixture(),before=JSON.stringify({model,trade}),offer=nativeModelOffer(model,'ps',trade,'fc27-weekly');
 assert.equal(offer.product_key,'admin-101');assert.equal(offer.price.base_minor,1234);assert.equal(offer.checkout_ready,true);
 assert.equal(JSON.stringify({model,trade}),before);assert.equal(model.preview_only,true);assert.equal(trade.products[1].available,false);
 assert.match(content.previewCard(model,{nativeOffer:offer,price:'$11.11'}),/data-toggle-product="model-266-1327-99"/);
 assert.match(content.previewCard(model,{nativeOffer:offer,price:'$11.11'}),/\$11.11/);
});
test('reference prices are visible without a page checkout binding but purchase stays disabled',()=>{
 const {model,trade}=fixture(),offer=nativeModelOffer(model,'ps',trade,'fc27-sbc');assert.equal(offer.checkout_ready,false);
 const html=content.previewCard(model,{nativeOffer:offer});assert.match(html,/\$12.34/);assert.match(html,/Current reference price/);assert.match(html,/disabled>Purchasing unavailable/);
 assert(!html.includes('data-toggle-product'));
});
test('wrong goods, platform, SKU, model, duplicate match, expired price or ambiguous options cannot supply a quote',()=>{
 for(const change of [f=>f.trade.products[1].product_ref={...f.trade.products[1].product_ref,goods_id:'102'},f=>f.trade.products[1].platform.code='pc',f=>f.trade.products[1].product_ref={...f.trade.products[1].product_ref,sku_id:'5'},f=>f.trade.seasonal_model_contracts[99].model_ref.model_id='98',f=>f.trade.products.push({...f.trade.products[1],key:'duplicate'}),f=>f.trade.seasonal_model_contracts[99].combinations[0].price.expires_at='2020-01-01T00:00:00Z',f=>f.trade.seasonal_model_contracts[99].combinations.push({...f.trade.seasonal_model_contracts[99].combinations[0]})]){
  const f=fixture();change(f);assert.equal(nativeModelOffer(f.model,'ps',f.trade,'fc27-weekly'),null);
 }
});
test('mismatched quantity/attributes, expired policy and other origin cannot enable purchase',()=>{
 for(const change of [f=>f.trade.native_checkout.bindings[0].quantity.value='2',f=>f.trade.native_checkout.bindings[0].attributes=[{attribute_id:'1',value_id:'2'}],f=>f.trade.native_checkout.valid_until='2020-01-01T00:00:00Z',f=>f.trade.native_checkout.origin='https://preview.example']){
  const f=fixture();change(f);assert.equal(nativeModelOffer(f.model,'ps',f.trade,'fc27-weekly').checkout_ready,false);
 }
 const f=fixture();f.model.native_offers={ps:nativeModelOffer(f.model,'ps',f.trade,'fc27-weekly')};
 assert.match(content.previewCard(f.model,{nativeOffer:null}),/Price unavailable/,'fresh missing quote must not fall back to stale catalog projection');
});
