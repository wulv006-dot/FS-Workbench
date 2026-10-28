// Isolated candidate data from public read-only product pages. Never install as a live policy.
import {halloweenFixture} from './halloween-fixture.mjs';

const selected=[
 {model:'5264',goods:'1365865',title:'Diablo IV Gold',category:'new_gold',quantity:'500000',unit:'M',group:'500000',price:276,fixed:true},
 {model:'43191217',goods:'170070065',title:'Resplendent Spark x100 (Manual salvage required)',category:'new_items',quantity:'1',unit:'item',group:'1',price:749},
 {model:'43039181',goods:'170042137',title:'Flawless Horadric Ruby(Lv.30)',category:'new_items',quantity:'1',unit:'item',group:'1',price:281},
 {model:'43039069',goods:'170042461',title:'Flawless Horadric Skull(Lv.30)',category:'new_items',quantity:'1',unit:'item',group:'1',price:112},
 {model:'43038035',goods:'169752893',title:'Kullean Tuning Prism (DLC Required)*100',category:'new_items',quantity:'1',unit:'item',group:'1',price:105},
 {model:'43038033',goods:'169752973',title:'Entropic Tuning Prism (DLC Required)*100',category:'new_items',quantity:'1',unit:'item',group:'1',price:18}
];

export function d4SeasonalFixture(){
 const snapshot=halloweenFixture(),h=snapshot.halloween,game=h.games.find(g=>g.id==='diablo');
 Object.assign(h,{probabilities:[{off_percent:8,weight:4000},{off_percent:15,weight:3000},{off_percent:10,weight:3000}]});
 Object.assign(game,{fixed_model:'5264',fixed_off_percent:10,fixed_quantity:{value:'500000',unit:'M',conversion_verified:false},random_source:{mode:'models',category_id:null,snapshot_complete:false},random_models:selected.filter(x=>!x.fixed).map(x=>x.model),random_count:2});
 snapshot.products=snapshot.products.filter(p=>p.product_ref.game_id!=='456');
 for(const model of Object.keys(snapshot.seasonal_model_contracts))if(snapshot.seasonal_model_contracts[model].model_ref.game_id==='456')delete snapshot.seasonal_model_contracts[model];
 const retained=new Set(snapshot.products.map(p=>p.key));snapshot.native_checkout.bindings=snapshot.native_checkout.bindings.filter(b=>retained.has(b.product_key));
 const expires_at=new Date(Date.now()+3600000).toISOString();
 for(const row of selected){
  const key='admin-266-456-'+row.goods+'-15943',quantity={min:row.quantity,max:row.quantity,step:'1',unit:row.unit};
  snapshot.products.push({key,title:row.title,product_ref:{site_id:'266',game_id:'456',model_id:row.model,goods_id:row.goods},platform:{code:'season_15_softcore',attribute_id:'15943'},quantity,attributes:[],available:false});
  snapshot.seasonal_model_contracts[row.model]={schema_version:1,verified:true,catalog_version:'d4-public-readonly-20261028-v1',ordering_verified:true,ordering_evidence:'Public goods list source order; Season 15 Softcore only',model_ref:{site_id:'266',game_id:'456',model_id:row.model},fields:[{id:'server',label:'Server',depends_on:[],values:[{id:'15943',label:'Season 15 Softcore'}]}],combinations:[{product_key:key,choices:{server:'15943'},attributes:[],quantity:{...quantity},price:{source:'admin_current',base_minor:row.price,currency:'USD',minor_unit_scale:2,quantity_value:row.quantity,expires_at}}]};
  for(const off_percent of row.fixed?[10]:[8,15,10])snapshot.native_checkout.bindings.push({activity_id:'mmoexp-seasonal',page_id:'seasonal-vault',product_key:key,quantity:{value:row.quantity,unit:row.unit},attributes:[],off_percent,code:'D4-CANDIDATE-'+off_percent,native:{category:row.category,id:row.goods,group:row.group,num:'1',attr:'',aid:''},observed_serialization:{verification_ref:'d4-public-readonly-20261028',game_id:'456',model_id:row.model,region:'us',currency:'USD'}});
 }
 snapshot.release_id='d4-seasonal-candidate-20261028';snapshot.source_revision='d4-seasonal-candidate-20261028';snapshot.pages[0].product_keys=snapshot.products.map(p=>p.key);
 return snapshot;
}

export const d4Selected=selected.map(x=>({...x}));
