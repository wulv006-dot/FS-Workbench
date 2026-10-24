import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';

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
const ref = value => Object.fromEntries(['site_id','game_id','model_id','goods_id','sku_id'].filter(k => value?.[k] != null).map(k => [k,id(value[k])]));
const localPath = value => {
  text(value, 300);
  if (!/^[A-Za-z0-9][A-Za-z0-9_./-]*$/.test(value) || value.split('/').some(p => !p || p === '.' || p === '..')) fail('INVALID_PUBLIC_PATH');
  return value;
};
const hash = value => { if (!/^[a-f0-9]{64}$/.test(value || '')) fail('INVALID_RELEASE'); return value; };
function product(p) {
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
  const result={schema_version:1, release_id:id(input.release_id), source_revision:id(input.source_revision), config_hash:hash(input.config_hash), rule_hash:hash(input.rule_hash),
    pages:input.pages.map(p => ({activity_id:id(p.activity_id), page_id:id(p.page_id), rule_version:id(p.rule_version), benefit_binding_version:id(p.benefit_binding_version),
      path:localPath(p.path), title:text(p.title), product_keys:p.product_keys.map(id),
      ...(p.ends_at ? {ends_at:new Date(p.ends_at).toISOString()} : {}), active:p.active === true})),
    products:input.products.map(product)};
  if (new Set(result.products.map(p=>p.key)).size !== result.products.length || new Set(result.pages.map(p=>p.page_id)).size !== result.pages.length || result.pages.some(p=>p.product_keys.some(k=>!result.products.some(r=>r.key===k)))) fail('INVALID_RELEASE');
  return JSON.parse(JSON.stringify(result));
}

export const validateSnapshot=projectRelease;
export function createSnapshot(publishedRelease) {
  return {publication_status:'published',...projectRelease(publishedRelease)};
}

const allowedNames = new Set(['index.html','Weekly-Scout.html','Sbc-Companions.html','Player-Trio.html','activity.css','activity.js','activity-core.js','activity-content.js','host-adapter.js','standalone-adapter.js','activity-analytics.js','analytics-config.js','catalog.js','sitemap.xml','robots.txt',
  'seasonal/index.html','seasonal/creative-kit.html','seasonal/event.js','seasonal/event.css','seasonal/vault-core.js','seasonal/campaign-data.js','seasonal/kit.js','seasonal/kit.css','seasonal/vault-analytics.js','seasonal/activity-analytics.js','seasonal/analytics-config.js']);
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
