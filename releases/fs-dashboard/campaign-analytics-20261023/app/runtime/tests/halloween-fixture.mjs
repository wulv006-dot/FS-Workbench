// Synthetic isolated commerce only. Never install this snapshot/policy anywhere.
import {emptyHalloween} from '../halloween-contract.mjs';
export function halloweenFixture(){
 const h=emptyHalloween(),products=[],contracts={},bindings=[];
 Object.assign(h,{status:'configured',probabilities:[{off_percent:8,weight:10000},{off_percent:15,weight:0},{off_percent:10,weight:0}],tier_product_binding:'independent',starts_at:'2020-01-01T00:00:00Z',ends_at:'2099-01-01T00:00:00Z'});
 for(const [index,game] of h.games.entries()){
  game.admin_game_id||=String(910000+index);game.fixed_model=index===0?'41217957':String(920000+index*10);game.fixed_off_percent=10;
  game.random_models=[String(920001+index*10),String(920002+index*10)];
  for(const [slot,model] of [game.fixed_model,...game.random_models].entries()){
   const coin=index===0&&slot===0,key='synthetic61-'+model,goods=coin?'163329311':String(930000+index*10+slot),quantity={min:coin?'1000':'1',max:coin?'1000':'1',step:'1',unit:coin?'K':'item'},attrs=index===2&&slot===1?[{attribute_id:'31',value_id:'41'}]:[];
   const product={key,title:'Synthetic '+game.label+' selection '+slot,product_ref:{site_id:'266',game_id:game.admin_game_id,model_id:model,goods_id:goods},platform:{code:coin?'ps':'synthetic',attribute_id:coin?'21587':'1'},quantity,available:false,attributes:attrs.map(a=>({attribute_id:a.attribute_id,required:true,values:[a.value_id]}))};products.push(product);
   contracts[model]={schema_version:1,verified:true,catalog_version:'synthetic61-only',model_ref:{site_id:'266',game_id:game.admin_game_id,model_id:model},ordering_verified:true,ordering_evidence:'synthetic61-only',fields:[{id:'server',label:'Server',depends_on:[],values:[{id:'1',label:'Synthetic default server'}]}],combinations:[{product_key:key,choices:{server:'1'},attributes:attrs,quantity:{...quantity},price:{source:'admin_current',base_minor:1000,currency:'USD',minor_unit_scale:2,quantity_value:quantity.min,expires_at:new Date(Date.now()+600000).toISOString()}}]};
   for(const off_percent of [8,10,15])bindings.push({activity_id:'mmoexp-seasonal',page_id:'seasonal-vault',product_key:key,quantity:{value:quantity.min,unit:quantity.unit},attributes:attrs,off_percent,code:'SYNTHETIC61-'+off_percent,native:coin?{category:'new_gold',id:goods,group:'1000',num:'1',attr:'',aid:''}:{category:slot%2?'new_items':'new_gold',id:goods,group:'9',num:'2',attr:attrs.length?'31:41':'',aid:'1'},...(coin?{}:{observed_serialization:{verification_ref:'synthetic61-only',game_id:game.admin_game_id,model_id:model,region:'us',currency:'USD'}})});
  }
 }
 return {schema_version:1,publication_status:'published',release_id:'synthetic61',source_revision:'synthetic61',config_hash:'a'.repeat(64),rule_hash:'b'.repeat(64),halloween:h,seasonal_model_contracts:contracts,products,pages:[{activity_id:'mmoexp-seasonal',page_id:'seasonal-vault',rule_version:'synthetic61',benefit_binding_version:'synthetic61',path:'seasonal/index.html',title:'Synthetic Halloween',active:true,product_keys:products.map(p=>p.key)}],native_checkout:{status:'configured',verification_ref:'synthetic61-only',valid_from:h.starts_at,valid_until:h.ends_at,origin:'https://www.mmoexp.com',cart_path:'/Cart.html',consumer_behavior_confirmed:true,bindings}};
}
