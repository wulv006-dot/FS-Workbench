import {halloweenFixture} from './halloween-fixture.mjs';
export function quantityFixture(){
 const s=halloweenFixture();
 for(const id of ['aion','diablo']){
  const g=s.halloween.games.find(g=>g.id===id),p=s.products.find(p=>p.product_ref.model_id===g.fixed_model),c=s.seasonal_model_contracts[g.fixed_model],unit=id==='aion'?'M':'G';
  g.random_source={mode:'quantity_tiers',category_id:null,snapshot_complete:false};g.random_models=[];g.fixed_quantity={value:'10',unit,conversion_verified:false};g.random_quantities=[{value:'30',unit},{value:'100',unit}];
  p.quantity={min:'10',max:'100',step:'1',unit};c.fields.push({id:'quantity_tier',label:'Amount',depends_on:[],values:['10','30','100'].map(v=>({id:v,label:v+unit}))});
  const combo=c.combinations[0];c.combinations=['10','30','100'].map(value=>({...structuredClone(combo),choices:{...combo.choices,quantity_tier:value},quantity:{min:value,max:value,step:'1',unit},price:{...combo.price,quantity_value:value}}));
  const old=s.native_checkout.bindings.filter(b=>b.product_key===p.key);s.native_checkout.bindings=s.native_checkout.bindings.filter(b=>b.product_key!==p.key);
  for(const value of ['10','30','100'])for(const b of old)s.native_checkout.bindings.push({...structuredClone(b),quantity:{value,unit},native:{...b.native,category:'new_gold',group:value,num:'1'}});
 }
 return s;
}
