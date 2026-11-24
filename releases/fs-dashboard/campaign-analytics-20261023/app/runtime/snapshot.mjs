import {projectModelOptions} from './model-options.mjs';
import nativeHandoff from '../native-code-handoff.js';
import {projectHalloween,halloweenProductKeys} from './halloween-contract.mjs';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {publicModels,modelVariants,projectModels} from './model-cards.mjs';
import {projectMedia,projectMediaManifest,mediaReferences} from './media-contract.mjs';

export const digest = value => createHash('sha256').update(value).digest('hex');
export const canonical = value => JSON.stringify(value, function(key, item) {
  return item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.keys(item).sort().map(k => [k, item[k]])) : item;
});
export function fail(code, status = 400) { throw Object.assign(new Error(code), {code, status}); }
export function text(value, max = 200) {
  if (typeof value !== 'string' || !value.length || value.length > max || /[\u0000-\u001f]/.test(value)) fail('INVALID_REQUEST');
  return value;
}
export function id(value) {
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value || '')) fail('INVALID_REQUEST');
  return value;
}
export const presentationOptions=Object.freeze({
 'Weekly-Scout.html':{languages:['original','en','zh'],images:['original','assets/weekly-hero.webp','assets/weekly-hero-mobile.webp']},
 'Sbc-Companions.html':{languages:['original','en','zh'],images:['original','assets/reward-hero.webp','assets/reward-hero-mobile.webp']},
 'Player-Trio.html':{languages:['original','en','zh'],images:['original','assets/scream-hero.webp','assets/scream-hero-mobile.webp']},
 'seasonal/index.html':{languages:['original','en'],images:['original',...['halloween','thanksgiving','christmas','black-friday'].map(theme=>'seasonal/assets/hero-'+theme+'.webp')]}
});
export function presentationFields(page){
 const options=presentationOptions[page.path],language=page.default_language??'original',image=page.social_image??'original';
 if((language!=='original'||image!=='original')&&(!options||!options.languages.includes(language)||!options.images.includes(image)))fail('INVALID_PRESENTATION_CONFIG');
 return {default_language:language,social_image:image};
}
const ref = value => Object.fromEntries(['site_id','game_id','model_id','goods_id','sku_id'].filter(k => value?.[k] != null).map(k => [k,id(value[k])]));
const localPath = value => {
  text(value, 300);
  if (!/^[A-Za-z0-9][A-Za-z0-9_./-]*$/.test(value) || value.split('/').some(p => !p || p === '.' || p === '..')) fail('INVALID_PUBLIC_PATH');
  return value;
};
const hash = value => { if (!/^[a-f0-9]{64}$/.test(value || '')) fail('INVALID_RELEASE'); return value; };
export const pageRoleOptions=Object.freeze({'fc27-weekly':['preview','player','bundle'],'fc27-trio':['preview','player','bundle'],
  'fc27-sbc':['preview','core','companion','bundle'],'seasonal-vault':['preview','pool','fixed','both']});
const rolePageByPath={'Weekly-Scout.html':'fc27-weekly','Player-Trio.html':'fc27-trio','Sbc-Companions.html':'fc27-sbc','seasonal/index.html':'seasonal-vault'};
// Visible hero copy (heading / intro / body) is operator-editable so a weekly
// refresh no longer needs a code change. Public pages are English-only, so the
// contract rejects markup, control characters and Han text instead of silently
// publishing something the runtime would then have to strip.
export const COPY_FIELDS=Object.freeze({heading:120,intro:320,body:400});
export const COPY_PAGES=Object.freeze(['fc27-weekly','fc27-sbc','fc27-trio']);
export function pageCopyFields(page){
  if(!Object.hasOwn(page,'copy'))return {};
  const copy=page.copy;
  const pageId=rolePageByPath[page.path]||page.page_id;
  if(!copy||typeof copy!=='object'||Array.isArray(copy)||!COPY_PAGES.includes(pageId))fail('INVALID_PAGE_COPY');
  const result={};
  for(const [key,value] of Object.entries(copy)){
    if(!Object.hasOwn(COPY_FIELDS,key))fail('INVALID_PAGE_COPY');
    if(typeof value!=='string'||!value.trim()||value.length>COPY_FIELDS[key]||/[\u0000-\u001f<>]/.test(value)||/\p{Script=Han}/u.test(value))fail('INVALID_PAGE_COPY');
    result[key]=value.trim();
  }
  return Object.keys(result).length?{copy:result}:{};
}
export function pageDisplayFields(page){
  const own=(key)=>Object.hasOwn(page,key),result={},selected=new Set(page.product_keys||[]),pageId=rolePageByPath[page.path]||page.page_id;
  const record=value=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length<=500;
  if(own('product_roles')){
    if(!record(page.product_roles)||Object.entries(page.product_roles).some(([key,role])=>!selected.has(key)||!pageRoleOptions[pageId]?.includes(role)))fail('INVALID_PRODUCT_ROLES');
    result.product_roles=Object.fromEntries(Object.entries(page.product_roles).map(([key,role])=>[id(key),role]));
  }
  if(own('sbc_companions')){
    if(pageId!=='fc27-sbc'||!record(page.sbc_companions))fail('INVALID_SBC_COMPANIONS');
    result.sbc_companions={};
    for(const [key,companions] of Object.entries(page.sbc_companions)){
      if(!selected.has(key)||page.product_roles?.[key]!=='core'||!Array.isArray(companions)||companions.length>20
        ||new Set(companions).size!==companions.length||companions.some(k=>!selected.has(k)||page.product_roles?.[k]!=='companion'))fail('INVALID_SBC_COMPANIONS');
      result.sbc_companions[id(key)]=companions.map(id);
    }
  }
  return result;
}
export function projectFcLayout(layout,products){
  if(!layout||typeof layout!=='object'||Array.isArray(layout)||Object.keys(layout).some(k=>!['weekly','trio','bundles','sbc','defaultCore','routes'].includes(k)))fail('INVALID_FC_LAYOUT');
  const known=new Set(products.flatMap(p=>{const match=/^fc-(.+)-(ps|xbox|pc)$/.exec(p.key);return match&&p.product_ref.game_id==='1327'?[match[1]]:[];}));
  const ids=values=>{if(!Array.isArray(values)||values.length>500||new Set(values).size!==values.length||values.some(k=>typeof k!=='string'||!known.has(k)))fail('INVALID_FC_LAYOUT');return values.map(id);};
  const result=Object.fromEntries(['weekly','trio','bundles','sbc'].map(k=>[k,ids(layout[k])]));
  if(layout.defaultCore!==null&&!result.sbc.includes(layout.defaultCore))fail('INVALID_FC_LAYOUT');result.defaultCore=layout.defaultCore;
  if(!layout.routes||typeof layout.routes!=='object'||Array.isArray(layout.routes)||Object.keys(layout.routes).some(k=>!result.sbc.includes(k)))fail('INVALID_FC_LAYOUT');
  result.routes=Object.fromEntries(Object.entries(layout.routes).map(([key,row])=>{
    if(!row||typeof row!=='object'||Object.keys(row).some(k=>!['picks','alternatives','label'].includes(k)))fail('INVALID_FC_LAYOUT');
    const route={picks:ids(row.picks),alternatives:ids(row.alternatives)};
    if(row.label!=null){if(typeof row.label!=='object'||Array.isArray(row.label)||Object.keys(row.label).some(k=>!['zh','en'].includes(k)))fail('INVALID_FC_LAYOUT');route.label=Object.fromEntries(Object.entries(row.label).map(([k,v])=>[k,text(v,160)]));}
    return [id(key),route];
  }));return result;
}
// Imported Admin metadata is display-only. Unknown purchase quantities stay null.
export function projectPreviewProduct(p) {
  const exact=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).every(k=>keys.includes(k));
  const number=value=>{if(typeof value!=='string'||!/^[1-9]\d{0,19}$/.test(value))fail('INVALID_IMPORTED_PRODUCT');return value;};
  if(!exact(p,['key','title','title_source','product_ref','platform','preview_only','available','quantity','attributes','observed_quantity','preview_reason'])||p.preview_only!==true||p.available!==false||p.quantity!==null||!Array.isArray(p.attributes)||p.attributes.length)fail('INVALID_IMPORTED_PRODUCT');
  if(!exact(p.product_ref,['site_id','game_id','goods_id','model_id','sku_id']))fail('INVALID_IMPORTED_PRODUCT');
  const product_ref=Object.fromEntries(['site_id','game_id','goods_id','model_id'].map(k=>[k,number(p.product_ref[k])]));
  if(product_ref.site_id!=='266')fail('INVALID_IMPORTED_PRODUCT');
  if(p.product_ref.sku_id!=null)product_ref.sku_id=number(p.product_ref.sku_id);
  if(!exact(p.platform,['code','attribute_id']))fail('INVALID_IMPORTED_PRODUCT');
  const aid=p.platform.attribute_id==null?'unknown':number(p.platform.attribute_id),known={'21587':'ps','21585':'xbox','21589':'pc'};
  const code=aid==='unknown'?'unknown':product_ref.game_id==='1327'&&known[aid]||'area-'+aid;
  const key='admin-'+[product_ref.site_id,product_ref.game_id,product_ref.goods_id,aid].join('-')+(product_ref.sku_id?'-sku-'+product_ref.sku_id:'');
  if(p.key!==key||p.platform.code!==code||typeof p.title!=='string'||/[<>\u0000-\u001f]/.test(p.title))fail('INVALID_IMPORTED_PRODUCT');
  const observation=p.observed_quantity;
  if(!exact(observation,['minimum','unit','group']))fail('INVALID_IMPORTED_PRODUCT');
  const observed=value=>{if(value==null)return null;if(typeof value!=='string'||!/^\d{1,20}(?:\.\d{1,6})?$/.test(value))fail('INVALID_IMPORTED_PRODUCT');return value;};
  if(observation.unit!=null&&(typeof observation.unit!=='string'||observation.unit.length>64||/[<>\u0000-\u001f]/.test(observation.unit)))fail('INVALID_IMPORTED_PRODUCT');
  const title_source=p.title_source??'admin';if(!['admin','identity_fallback'].includes(title_source))fail('INVALID_IMPORTED_PRODUCT');
  if(title_source==='identity_fallback'&&!['商品ID '+product_ref.goods_id,'Product ID '+product_ref.goods_id].includes(p.title))fail('INVALID_IMPORTED_PRODUCT');
  return {key:id(key),title:text(p.title,200),title_source,product_ref,platform:{code,...(aid==='unknown'?{}:{attribute_id:aid})},
    preview_only:true,available:false,quantity:null,attributes:[],observed_quantity:{minimum:observed(observation.minimum),unit:observation.unit??null,group:observed(observation.group)},preview_reason:'PURCHASE_MAPPING_UNVERIFIED'};
}
function product(p,variants,publicVariants) {
  if(p?.model_card_key){
    const expected=variants.get(p.key);
    if(!expected||p.model_card_key!==expected.model_card_key||p.binding_state!==expected.binding_state||p.available!==false||p.preview_only!==true||p.quantity!==null||!Array.isArray(p.attributes)||p.attributes.length
      ||canonical(p.product_ref)!==canonical(expected.product_ref)||canonical(p.platform)!==canonical(expected.platform)||canonical(p.observed_quantity)!==canonical(expected.observed_quantity))fail('INVALID_MODEL_VARIANT');
    return publicVariants.get(p.key);
  }
  if(p?.preview_only===true)return projectPreviewProduct(p);
  const product_ref = ref(p.product_ref);
  if (!product_ref.site_id || !product_ref.game_id || !product_ref.goods_id) fail('INVALID_RELEASE');
  const quantity = {unit:id(p.quantity?.unit), min:text(p.quantity?.min,32), max:text(p.quantity?.max,32), step:text(p.quantity?.step,32)};
  if ([quantity.min,quantity.max,quantity.step].some(v => !/^\d{1,12}(\.\d{1,6})?$/.test(v)) || Number(quantity.min) <= 0 || Number(quantity.max) < Number(quantity.min) || Number(quantity.step) <= 0) fail('INVALID_RELEASE');
  if (p.quantity.group != null) quantity.group=id(p.quantity.group);
  return {key:id(p.key), title:text(p.title), product_ref,
    platform:{code:id(p.platform?.code), ...(p.platform?.attribute_id ? {attribute_id:id(p.platform.attribute_id)} : {})},
    quantity, available:p.available === true,
    attributes:(p.attributes || []).map(a => ({attribute_id:id(a.attribute_id), required:a.required === true, values:a.values.map(id)})),
    ...(p.image ? {image:localPath(p.image)} : {})};
}

// Only this field projection crosses into the customer service; never spread management state.
export function projectRelease(input) {
  if (input?.schema_version !== 1 || input.publication_status !== 'published' || !Array.isArray(input.pages) || !Array.isArray(input.products)) fail('UNPUBLISHED_RELEASE',503);
  const originalModels=projectModels(input.fc_models||{}),models=publicModels(originalModels),variants=new Map(modelVariants(originalModels).map(p=>[p.key,p])),publicVariants=new Map(modelVariants(models).map(p=>[p.key,p]));
  const result={schema_version:1, release_id:id(input.release_id), source_revision:id(input.source_revision), config_hash:hash(input.config_hash), rule_hash:hash(input.rule_hash),
    pages:input.pages.map(p => ({activity_id:id(p.activity_id), page_id:id(p.page_id), rule_version:id(p.rule_version), benefit_binding_version:id(p.benefit_binding_version),
      path:localPath(p.path), title:text(p.title), product_keys:p.product_keys.map(id),...pageDisplayFields(p),...pageCopyFields(p),...(Object.hasOwn(p,'media')?{media:projectMedia(p.media)}:{}),
      ...(p.description ? {description:text(p.description,320)} : {}),
      ...((p.default_language!=null||p.social_image!=null)?presentationFields(p):{}),
      ...(p.starts_at ? {starts_at:new Date(p.starts_at).toISOString()} : {}),
      ...(p.ends_at ? {ends_at:new Date(p.ends_at).toISOString()} : {}), active:p.active === true})),
    products:input.products.map(p=>product(p,variants,publicVariants))};
  if(Object.keys(models).length)result.fc_models=models;
  if(input.media_assets!=null)result.media_assets=projectMediaManifest(input.media_assets);
  const media=mediaReferences(result),manifest=result.media_assets||{};
  if(media.some(key=>!Object.hasOwn(manifest,key))||Object.keys(manifest).some(key=>!media.includes(key)))fail('INVALID_MEDIA_MANIFEST');
  if (new Set(result.products.map(p=>p.key)).size !== result.products.length || new Set(result.pages.map(p=>p.page_id)).size !== result.pages.length || result.pages.some(p=>p.product_keys.some(k=>!result.products.some(r=>r.key===k)))) fail('INVALID_RELEASE');
  if(input.seasonal_theme!=null){if(!['halloween','thanksgiving','christmas','black-friday'].includes(input.seasonal_theme))fail('INVALID_RELEASE');result.seasonal_theme=input.seasonal_theme;}
  if(input.halloween!=null){result.halloween=projectHalloween(input.halloween);const keys=halloweenProductKeys(result.halloween,result.products);const page=result.pages.find(p=>p.page_id==='seasonal-vault');if(!page||keys.some(k=>!page.product_keys.includes(k)))fail('INVALID_HALLOWEEN_CONFIG');}
  if(input.seasonal_model_contracts!=null){result.seasonal_model_contracts=projectModelOptions(input.seasonal_model_contracts,result.products);const allowed=new Set(result.pages.filter(p=>['seasonal-vault','fc27-trio','fc27-weekly','fc27-sbc'].includes(p.page_id)).flatMap(p=>p.product_keys||[]));if(Object.values(result.seasonal_model_contracts).some(c=>c.combinations.some(x=>!allowed.has(x.product_key))))fail('INVALID_MODEL_OPTIONS');}
  if(input.native_checkout!=null){try{result.native_checkout=nativeHandoff.projectConfiguration(input.native_checkout,result.pages,result.products);}catch{fail('NATIVE_CONFIGURATION_INVALID');}}
  if(input.fc_layout!=null)result.fc_layout=projectFcLayout(input.fc_layout,result.products);
  if(result.pages.some(p=>p.starts_at&&p.ends_at&&p.starts_at>=p.ends_at))fail('INVALID_RELEASE');
  return JSON.parse(JSON.stringify(result));
}

export const validateSnapshot=projectRelease;
export function createSnapshot(publishedRelease) {
  return {publication_status:'published',...projectRelease(publishedRelease)};
}

const allowedNames = new Set(['D4-Build-Shop.html','d4-build-shop.js','d4-build-shop.css','d4-armory-store.js','D4-Armory.html','d4-armory-cart.js','Carnival.html','carnival.css','carnival-proto.js','carnival-live.js','index.html','Weekly-Scout.html','Sbc-Companions.html','Player-Trio.html','activity.css','activity.js','activity-core.js','activity-content.js','host-adapter.js','native-code-handoff.js','standalone-adapter.js','activity-analytics.js','analytics-config.js','catalog.js','sitemap.xml','robots.txt',
  'seasonal/index.html','seasonal/creative-kit.html','seasonal/event.js','seasonal/event.css','seasonal/vault-core.js','seasonal/campaign-data.js','seasonal/kit.js','seasonal/kit.css','seasonal/vault-analytics.js','seasonal/activity-analytics.js','seasonal/analytics-config.js','seasonal/runtime-bridge.js','seasonal/model-selection.js']);
export function loadStatic(root, manifest) {
  const realRoot=fs.realpathSync(root), files=new Map();
  if (fs.lstatSync(root).isSymbolicLink()) fail('INVALID_PUBLIC_PATH');
  for (const [name,sha] of Object.entries(manifest)) {
    localPath(name); hash(sha);
    if (!allowedNames.has(name) && !/^(?:seasonal\/)?assets\/[A-Za-z0-9_.-]+\.(webp|png|svg|jpg|jpeg|gif|woff2)$/.test(name)) fail('INVALID_PUBLIC_PATH');
    let current=realRoot;
    for (const part of name.split('/')) { current=path.join(current,part); if (fs.lstatSync(current).isSymbolicLink()) fail('INVALID_PUBLIC_PATH'); }
    if (!fs.statSync(current).isFile() || !fs.realpathSync(current).startsWith(realRoot+path.sep)) fail('INVALID_PUBLIC_PATH');
    const body=fs.readFileSync(current);
    if (digest(body)!==sha) fail('STATIC_HASH_MISMATCH');
    files.set(name,body);
  }
  return files;
}
