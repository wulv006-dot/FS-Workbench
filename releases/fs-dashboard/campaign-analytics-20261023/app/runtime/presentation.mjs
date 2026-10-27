import {presentationFields,fail,projectPreviewProduct,pageDisplayFields} from './snapshot.mjs';
import {effectiveFcCatalog} from './model-cards.mjs';
// Public copy policy only: preserve the management draft and immutable release.
// Unsupported demo text gets a neutral English identity, never an invented offer.
const hasHan=value=>typeof value==='string'&&/\p{Script=Han}/u.test(value);
const pageTitles={'Weekly-Scout.html':'Weekly Player Picks','Sbc-Companions.html':'SBC Companions','Player-Trio.html':'Star Performer Trio','seasonal/index.html':'MMOEXP Seasonal Vault'};
export function publicEnglishRelease(snapshot){
 if(!snapshot)return snapshot;
 const result=structuredClone(snapshot);
 result.pages=(result.pages||[]).map(page=>({...page,title:hasHan(page.title)?pageTitles[page.path]||'MMOEXP Activity':page.title,
  ...(hasHan(page.description)?{description:''}:{}),default_language:'en'}));
 result.products=(result.products||[]).map(product=>({...product,...(hasHan(product.title)?{title:'Product ID '+product.product_ref.goods_id,...(product.preview_only?{title_source:'identity_fallback'}:{})}:{}),
  ...(product.observed_quantity&&hasHan(product.observed_quantity.unit)?{observed_quantity:{...product.observed_quantity,unit:null}}:{})}));
 if(result.fc_layout?.routes)for(const row of Object.values(result.fc_layout.routes))if(row.label)row.label={en:hasHan(row.label.en)||!row.label.en?'Companion ideas':row.label.en};
 return result;
}
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const routes=new Set(['Weekly-Scout.html','Sbc-Companions.html','Player-Trio.html','seasonal/index.html']);
const aliases={'':'Weekly-Scout.html','index.html':'Weekly-Scout.html','seasonal/':'seasonal/index.html'};
const route=name=>Object.hasOwn(aliases,name)?aliases[name]:name;
const attr=(tag,key)=>new RegExp('\\b'+key+'\\s*=\\s*(?:"([^"]*)"|\'([^\']*)\'|([^\\s>]+))','i').exec(tag)?.slice(1).find(v=>v!==undefined);
const date=value=>value?Date.parse(value):null;
const utc=value=>new Date(value).toISOString().replace('T',' ').replace(/Z$/,' UTC');
const time=value=>`<time datetime="${escape(new Date(value).toISOString())}">${escape(utc(value))}</time>`;
const windowText=p=>`Starts: ${p.starts_at?utc(p.starts_at):'not specified'} · Ends: ${p.ends_at?utc(p.ends_at):'not specified'}`;
const windowHtml=p=>`Starts: ${p.starts_at?time(p.starts_at):'not specified'} · Ends: ${p.ends_at?time(p.ends_at):'not specified'}`;
const importedFor=(snapshot,page)=>{
  const products=new Map((snapshot?.products||[]).filter(p=>p.preview_only===true&&!p.model_card_key).map(p=>[p.key,p]));
  return (page?.product_keys||[]).filter(key=>products.has(key)).map(key=>projectPreviewProduct(products.get(key)));
};
function displayGroups(snapshot,page,source){
  const fields=pageDisplayFields(page),products=new Map((snapshot.products||[]).map(p=>[p.key,p])),groups={};
  for(const key of page.product_keys||[]){
    const raw=products.get(key);if(!raw||raw.model_card_key)continue;
    const role=fields.product_roles?.[key]??(raw.preview_only?'preview':null);if(!role)continue;
    const product=raw.preview_only?projectPreviewProduct(raw):raw;
    (groups[role]||=[]).push(product);
  }
  const titles={preview:'Unassigned product previews',player:'Published player previews',bundle:'Published bundle previews',core:'Published SBC core previews',companion:'Published SBC companion previews'};
  let first=true;
  return Object.entries(groups).map(([role,rows])=>{
    const marker=first?'campaign-imported-products':'campaign-imported-products-'+role;first=false;
    const cards=rows.map(product=>{
      const related=(fields.sbc_companions?.[product.key]||[]).map(key=>products.get(key)).filter(Boolean);
      const pairing=role==='core'?(related.length?`<p>Configured companion previews:</p><ul>${related.map(p=>`<li>${escape(p.title)}</li>`).join('')}</ul>`:'<p>No companions configured. This is not a complete SBC lineup.</p>'):'';
      return `<article class="fca-card"><h3>${escape(product.title)}</h3>${product.title_source==='identity_fallback'?'<p>English product title is unavailable; identity label only.</p>':''}<p>Product ${escape(product.product_ref.goods_id)} · Model ${escape(product.product_ref.model_id||'not verified')}</p><p>Platform reference: ${escape(product.platform.attribute_id||'not verified')}</p>${pairing}<p>Display role only; no SKU, price or purchase eligibility is implied.</p><p>Price unavailable · Purchase mapping unverified</p></article>`;
    }).join('');
    const html=`<section id="${marker}" class="${sectionClass(source)}" data-display-role="${role}"><h2>${titles[role]}</h2><p>Product information only. Specifications, quantities and prices still require verification. Purchasing is not enabled.</p><div class="fca-grid">${cards}</div></section>`;
    const anchor=role==='bundle'?'bundle-grid':role==='core'?'sbc-lineup':role==='companion'?'sbc-options':'product-grid';
    return {html,anchor};
  });
}
const sectionClass=source=>/href=["'][^"']*event\.css(?:[?"'])/i.test(source)?'seo-content page-width':'fc-activity fca-container fca-guide';
function metadata(html,p,publicBase) {
  const fieldsConfig=presentationFields(p);
  if(fieldsConfig.default_language!=='original'){
    const language=fieldsConfig.default_language==='zh'?'zh-CN':'en';
    html=html.replace(/<html\b[^>]*>/i,tag=>tag.replace(/\s+lang=["'][^"']*["']/i,'').replace(/>$/,' lang="'+language+'">'));
    if(p.path!=='seasonal/index.html')html=html.replace(/\bdata-default-language=["'][^"']*["']/,'data-default-language="'+fieldsConfig.default_language+'"');
  }
  let shareImage;
  if(p.media?.share){let base;try{base=new URL(publicBase);}catch{fail('INVALID_PUBLIC_BASE',503);}if(base.protocol!=='https:'&&!(base.protocol==='http:'&&['localhost','127.0.0.1'].includes(base.hostname))||base.username||base.password)fail('INVALID_PUBLIC_BASE',503);shareImage=new URL('media/'+p.media.share.asset_id,base).href;}
  if(!shareImage&&fieldsConfig.social_image!=='original'){
    let base;try{base=new URL(publicBase);}catch{fail('INVALID_PUBLIC_BASE',503);}
    if(base.username||base.password||base.search||base.hash||!base.pathname.endsWith('/')||!/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(base.pathname)||(base.protocol!=='https:'&&!(base.protocol==='http:'&&['127.0.0.1','localhost'].includes(base.hostname))))fail('INVALID_PUBLIC_BASE',503);
    shareImage=new URL(fieldsConfig.social_image,base).href;
  }
  const title=escape(p.title),description=typeof p.description==='string'&&p.description.trim()?p.description:null;
  let found=false;
  html=html.replace(/<title\b[^>]*>[\s\S]*?<\/title\s*>/gi,()=>{if(found)return '';found=true;return `<title>${title}</title>`;});
  if(!found)html=html.replace(/<\/head\s*>/i,()=>`<title>${title}</title></head>`);
  const fields=[['property','og:title',p.title],['name','twitter:title',p.title],...(fieldsConfig.default_language!=='original'?[['property','og:locale',fieldsConfig.default_language==='zh'?'zh_CN':'en_US']]:[]),...(shareImage?[['property','og:image',shareImage],['name','twitter:image',shareImage]]:[]),...(description?[['name','description',description],['property','og:description',description],['name','twitter:description',description]]:[])];
  for(const [kind,key,value] of fields){
    html=html.replace(/<meta\b[^>]*>/gi,tag=>attr(tag,kind)?.toLowerCase()===key?'':tag);
    html=html.replace(/<\/head\s*>/i,()=>`<meta ${kind}="${key}" content="${escape(value)}"></head>`);
  }
  // Keep collection metadata consistent without rebuilding product identity, URLs or canonical origin.
  return html.replace(/(<script\b[^>]*type\s*=\s*["']application\/ld\+json["'][^>]*>)([\s\S]*?)(<\/script\s*>)/gi,(all,open,raw,close)=>{
    try{
      const data=JSON.parse(raw),update=node=>{if(!node||typeof node!=='object')return;if(node['@type']==='CollectionPage'){node.name=p.title;if(description)node.description=description;if(fieldsConfig.default_language!=='original')node.inLanguage=fieldsConfig.default_language==='zh'?'zh-CN':'en';}for(const value of Object.values(node))if(value&&typeof value==='object')Array.isArray(value)?value.forEach(update):update(value);};
      update(data);return open+JSON.stringify(data).replace(/</g,'\\u003c').replace(/\u2028/g,'\\u2028').replace(/\u2029/g,'\\u2029')+close;
    }catch{return all;}
  });
}
function neutral(source,p,status,label) {
  const styles=(source.match(/<link\b[^>]*>/gi)||[]).filter(tag=>attr(tag,'rel')?.toLowerCase()==='stylesheet').join('');
  const title=p?.title||'Activity unavailable';
  return {status,body:`<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>${escape(title)}</title><meta property="og:title" content="${escape(title)}">${p?.description?`<meta name="description" content="${escape(p.description)}"><meta property="og:description" content="${escape(p.description)}">`:''}${styles}</head><body><main class="${sectionClass(source)}"><h1>${escape(title)}</h1><p>${escape(label)}</p>${p?.description?`<p>${escape(p.description)}</p>`:''}${p?`<p>Published schedule (UTC): ${windowHtml(p)}</p>`:''}</main></body></html>`};
}

function versionAssets(html,target,assetVersion){
 if(typeof assetVersion!=='function')return html;
 const base=new URL('https://campaign-assets.invalid/'+target);
 return html.replace(/<(?:script|link)\b[^>]*>/gi,tag=>{
  const script=/^<script/i.test(tag);if(!script&&attr(tag,'rel')?.toLowerCase()!=='stylesheet')return tag;
  const ref=attr(tag,script?'src':'href');if(!ref)return tag;
  let url;try{url=new URL(ref,base);}catch{return tag;}
  if(url.origin!==base.origin)return tag;
  const version=assetVersion(url.pathname.slice(1));
  if(typeof version!=='string'||!/^[A-Za-z0-9_-]{1,128}$/.test(version))return tag;
  url.searchParams.set('v',version);
  return tag.replace(ref,ref.split(/[?#]/)[0]+url.search+url.hash);
 });
}

// Call with the current validated published projection; immutable source HTML stays unchanged.
export function presentPage({name,body,snapshot,now=Date.now(),publicBase,assetVersion}={}) {
  snapshot=publicEnglishRelease(snapshot);
  const target=route(name);
  if(!routes.has(target))return {status:200,body};
  const source=Buffer.isBuffer(body)?body.toString('utf8'):String(body??'');
  const p=snapshot?.schema_version===1&&snapshot.release_id&&(!snapshot.publication_status||snapshot.publication_status==='published')?snapshot.pages?.find(p=>route(p.path)===target):null;
  if(!p||p.active!==true)return neutral(source,null,404,'This activity is not available.');
  const start=date(p.starts_at),end=date(p.ends_at),clock=Number(new Date(typeof now==='function'?now():now));
  if(!Number.isFinite(clock)||(start!==null&&!Number.isFinite(start))||(end!==null&&!Number.isFinite(end))||(start!==null&&end!==null&&start>=end))return neutral(source,null,404,'This activity is not available.');
  if(end!==null&&end<clock)return neutral(source,p,410,'This activity has ended.');
  if(start!==null&&start>clock)return neutral(source,p,200,'Upcoming activity — the published start time has not arrived.');
  let html=source.replace(/<section\b[^>]*\bid=["']campaign-published-details["'][^>]*>[\s\S]*?<\/section\s*>/gi,'');
  html=html.replace(/<section\b[^>]*\bid=["']campaign-imported-products(?:-[a-z]+)?["'][^>]*>[\s\S]*?<\/section\s*>/gi,'');
  html=metadata(html,p,publicBase);
  html=versionAssets(html,target,assetVersion);
  if(p.media?.hero_desktop||p.media?.hero_mobile){
    const url=ref=>{let base;try{base=new URL(publicBase);}catch{fail('INVALID_PUBLIC_BASE',503);}if(base.username||base.password||base.protocol!=='https:'&&!(base.protocol==='http:'&&['localhost','127.0.0.1'].includes(base.hostname)))fail('INVALID_PUBLIC_BASE',503);return new URL('media/'+ref.asset_id,base).href;};
    if(p.media.hero_desktop)html=html.replace(/<img\b[^>]*\bid=["']hero-image["'][^>]*>/i,tag=>tag.replace(/\s+(?:src|alt)=["'][^"']*["']/gi,'').replace(/>$/,` src="${escape(url(p.media.hero_desktop))}" alt="${escape(p.media.hero_desktop.alt)}" data-published-media="true">`));
    if(p.media.hero_mobile)html=html.replace(/<source\b[^>]*\bid=["']hero-mobile-source["'][^>]*>/i,tag=>tag.replace(/\s+srcset=["'][^"']*["']/gi,'').replace(/>$/,` srcset="${escape(url(p.media.hero_mobile))}" data-published-media="true">`));
  }
  let fallback='';
  if(!target.startsWith('seasonal/'))for(const group of displayGroups(snapshot,p,source)){
    // Use stable siblings of the actual original layout containers. The original
    // activity client replaces container contents, so inserting inside would vanish.
    const anchor=new RegExp('<div\\b[^>]*\\bid=["\']'+group.anchor+'["\'][^>]*>','i');
    if(anchor.test(html))html=html.replace(anchor,tag=>group.html+tag);else fallback+=group.html;
  }
  if(fallback)html=html.replace(/<body\b[^>]*>/i,tag=>tag+fallback);
  // Replace the Seasonal source's illustrative caption; its client must retain this published value too.
  html=html.replace(/(<([a-z][a-z0-9]*)\b[^>]*\bid=["']campaign-date["'][^>]*>)[\s\S]*?(<\/\2\s*>)/gi,(all,open,tag,close)=>open.replace(/>$/,' data-published-schedule="true">')+escape(windowText(p))+close);
  return {status:200,body:html};
}

export function projectFcCatalog(originalCatalog,snapshot) {
  snapshot=publicEnglishRelease(snapshot);
  const source=effectiveFcCatalog(originalCatalog,snapshot?.fc_models||{}),catalog=structuredClone(source),products=source.products||{};
  const keys=path=>{
    const page=snapshot?.pages?.find(p=>p.active===true&&route(p.path)===path);
    return [...new Set((page?.product_keys||[]).flatMap(key=>{
      const match=/^fc-(.+)-(ps|xbox|pc)$/.exec(key),product=match&&products[match[1]];
      const role=page.product_roles?.[key];
      return product?.platforms?.[match[2]]&&(!role||({player:'player',bundle:'bundle',core:'sbc',companion:'player'})[role]===product.kind)?[match[1]]:[];
    }))];
  };
  const weekly=keys('Weekly-Scout.html').filter(key=>products[key].kind==='player');
  const trioKeys=keys('Player-Trio.html'),sbcKeys=keys('Sbc-Companions.html'),sbcSet=new Set(sbcKeys);
  catalog.weekly.ids=weekly;
  if(weekly.some(key=>products[key].version!=='Team of the Week'))catalog.weekly.edition={zh:'已发布球员精选',en:'Published player picks'};
  catalog.trio.ids=trioKeys.filter(key=>products[key].kind==='player'&&products[key].version===catalog.trio.series);
  catalog.bundles.ids=trioKeys.filter(key=>products[key].kind==='bundle');
  catalog.weekly.bundleIds=keys('Weekly-Scout.html').filter(key=>products[key].kind==='bundle');
  catalog.sbc.ids=sbcKeys.filter(key=>products[key].kind==='sbc');
  const publishedRoutes=snapshot?.fc_layout?.routes??originalCatalog.sbc.routes;
  catalog.sbc.routes=Object.fromEntries(catalog.sbc.ids.filter(key=>publishedRoutes[key]).map(key=>{
    const original=publishedRoutes[key],selected=ids=>(ids||[]).filter(id=>sbcSet.has(id)&&products[id]?.kind==='player');
    return [key,{...structuredClone(original),picks:selected(original.picks),alternatives:selected(original.alternatives)}];
  }));
  const defaultCore=snapshot?.fc_layout?.defaultCore??originalCatalog.sbc.defaultId;
  catalog.sbc.defaultId=catalog.sbc.ids.includes(defaultCore)?defaultCore:catalog.sbc.ids[0]??null;
  catalog.sbc.fallbackPicks=[...(catalog.sbc.routes[catalog.sbc.defaultId]?.picks||[])];
  catalog.sbc.allListedIds=[...catalog.sbc.ids];
  const selected=new Set([...weekly,...catalog.weekly.bundleIds,...catalog.trio.ids,...catalog.bundles.ids,...catalog.sbc.ids,...Object.values(catalog.sbc.routes).flatMap(r=>[...r.picks,...r.alternatives])]);
  catalog.products=Object.fromEntries(Object.entries(catalog.products).filter(([key])=>selected.has(key)));
  // Imported items stay outside the original priced/SBC/trio algorithms until their
  // page-specific structure is actually verified. They are visible metadata previews.
  catalog.imported_products=Object.fromEntries((snapshot?.pages||[]).filter(p=>p.active===true&&routes.has(route(p.path))&&!route(p.path).startsWith('seasonal/')).map(p=>[p.page_id,importedFor(snapshot,p)]));
  catalog.mode='preview';catalog.manageDocumentLanguage=false;catalog.defaultView='weekly';
  return catalog;
}
