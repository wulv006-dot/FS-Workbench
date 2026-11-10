// Trusted catalog-provider projection; never accepted from an editor draft.
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),selection=require('../seasonal/model-selection.js');
const bad=()=>{throw Object.assign(Error('INVALID_MODEL_OPTIONS'),{code:'INVALID_MODEL_OPTIONS',status:400});};
const numeric=v=>typeof v==='string'&&/^[1-9]\d{0,19}$/.test(v);
const safe=(v,max=160)=>typeof v==='string'&&v.length>0&&v.length<=max&&!/[<>\u0000-\u001f]/u.test(v);
const english=(v,fallback)=>safe(v)&&!/[\u3400-\u9fff]/u.test(v)?v:fallback;
export function projectModelOptions(input,products){
 if(!input||typeof input!=='object'||Array.isArray(input)||Object.keys(input).length>300)bad();const out={};
 for(const [id,source] of Object.entries(input)){
  if(!numeric(id)||!source||source.model_ref?.model_id!==id||source.model_ref?.site_id!=='266'||!numeric(source.model_ref?.game_id)||source.verified!==true||!safe(source.catalog_version,100)||!Array.isArray(source.fields)||source.fields.length>12||!Array.isArray(source.combinations)||source.combinations.length>1000)bad();
  const model_ref={site_id:'266',game_id:source.model_ref.game_id,model_id:id};
  const fields=source.fields.map((f,i)=>{if(!safe(f.id,64)||!Array.isArray(f.depends_on)||!Array.isArray(f.values)||f.values.length>200)bad();return {id:f.id,label:english(f.label,'Option '+(i+1)),depends_on:[...f.depends_on],values:f.values.map((v,n)=>{if(!safe(v.id,100))bad();return {id:v.id,label:english(v.label,'Option '+(n+1))};})};});
  const combinations=source.combinations.map(c=>{
   const product=products.find(p=>p.key===c.product_key);if(!product||Object.entries(model_ref).some(([k,v])=>product.product_ref?.[k]!==v)||!c.quantity||!safe(c.quantity.unit,64)||!Array.isArray(c.attributes)||c.attributes.length>30)bad();
   const q=c.quantity;if(q.group!==undefined&&!numeric(q.group))bad();const row={product_key:c.product_key,choices:Object.fromEntries(fields.map(f=>[f.id,c.choices?.[f.id]])),attributes:c.attributes.map(a=>{if(!numeric(a.attribute_id)||!numeric(a.value_id))bad();return {attribute_id:a.attribute_id,value_id:a.value_id};}),quantity:{min:q.min,max:q.max,step:q.step,unit:q.unit,...(q.group?{group:q.group}:{})}};
   const p=c.price;if(p){if(p.source!=='admin_current'||!Number.isSafeInteger(p.base_minor)||p.base_minor<0||!Number.isInteger(p.minor_unit_scale)||p.minor_unit_scale<0||p.minor_unit_scale>4||!(/^[A-Z]{3}$/).test(p.currency)||!safe(p.quantity_value,32)||!Number.isFinite(Date.parse(p.expires_at)))bad();row.price={source:'admin_current',base_minor:p.base_minor,minor_unit_scale:p.minor_unit_scale,currency:p.currency,quantity_value:p.quantity_value,expires_at:p.expires_at};}
   return row;
  });
  const row={schema_version:1,verified:true,catalog_version:source.catalog_version,model_ref,fields,combinations,ordering_verified:source.ordering_verified===true,...(source.ordering_verified===true&&safe(source.ordering_evidence,200)?{ordering_evidence:'verified_catalog_source_order'}:{})};
  try{selection.create(row);}catch{bad();}out[id]=row;
 }return out;
}
