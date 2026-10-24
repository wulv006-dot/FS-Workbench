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
const sectionClass=source=>/href=["'][^"']*event\.css(?:[?"'])/i.test(source)?'seo-content page-width':'fc-activity fca-container fca-guide';
function metadata(html,p) {
  const title=escape(p.title),description=typeof p.description==='string'&&p.description.trim()?p.description:null;
  let found=false;
  html=html.replace(/<title\b[^>]*>[\s\S]*?<\/title\s*>/gi,()=>{if(found)return '';found=true;return `<title>${title}</title>`;});
  if(!found)html=html.replace(/<\/head\s*>/i,()=>`<title>${title}</title></head>`);
  const fields=[['property','og:title',p.title],['name','twitter:title',p.title],...(description?[['name','description',description],['property','og:description',description],['name','twitter:description',description]]:[])];
  for(const [kind,key,value] of fields){
    html=html.replace(/<meta\b[^>]*>/gi,tag=>attr(tag,kind)?.toLowerCase()===key?'':tag);
    html=html.replace(/<\/head\s*>/i,()=>`<meta ${kind}="${key}" content="${escape(value)}"></head>`);
  }
  // Keep collection metadata consistent without rebuilding product identity, URLs or canonical origin.
  return html.replace(/(<script\b[^>]*type\s*=\s*["']application\/ld\+json["'][^>]*>)([\s\S]*?)(<\/script\s*>)/gi,(all,open,raw,close)=>{
    try{
      const data=JSON.parse(raw),update=node=>{if(!node||typeof node!=='object')return;if(node['@type']==='CollectionPage'){node.name=p.title;if(description)node.description=description;}for(const value of Object.values(node))if(value&&typeof value==='object')Array.isArray(value)?value.forEach(update):update(value);};
      update(data);return open+JSON.stringify(data).replace(/</g,'\\u003c').replace(/\u2028/g,'\\u2028').replace(/\u2029/g,'\\u2029')+close;
    }catch{return all;}
  });
}
function neutral(source,p,status,label) {
  const styles=(source.match(/<link\b[^>]*>/gi)||[]).filter(tag=>attr(tag,'rel')?.toLowerCase()==='stylesheet').join('');
  const title=p?.title||'Activity unavailable';
  return {status,body:`<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>${escape(title)}</title><meta property="og:title" content="${escape(title)}">${p?.description?`<meta name="description" content="${escape(p.description)}"><meta property="og:description" content="${escape(p.description)}">`:''}${styles}</head><body><main class="${sectionClass(source)}"><h1>${escape(title)}</h1><p>${escape(label)}</p>${p?.description?`<p>${escape(p.description)}</p>`:''}${p?`<p>Published schedule (UTC): ${windowHtml(p)}</p>`:''}</main></body></html>`};
}

// Call with the current validated published projection; immutable source HTML stays unchanged.
export function presentPage({name,body,snapshot,now=Date.now()}={}) {
  const target=route(name);
  if(!routes.has(target))return {status:200,body};
  const source=Buffer.isBuffer(body)?body.toString('utf8'):String(body??'');
  const p=snapshot?.schema_version===1&&snapshot.release_id&&(!snapshot.publication_status||snapshot.publication_status==='published')?snapshot.pages?.find(p=>route(p.path)===target):null;
  if(!p||p.active!==true)return neutral(source,null,404,'This activity is not available.');
  const start=date(p.starts_at),end=date(p.ends_at),clock=Number(new Date(typeof now==='function'?now():now));
  if(!Number.isFinite(clock)||(start!==null&&!Number.isFinite(start))||(end!==null&&!Number.isFinite(end))||(start!==null&&end!==null&&start>=end))return neutral(source,null,404,'This activity is not available.');
  if(end!==null&&end<=clock)return neutral(source,p,410,'This activity has ended.');
  if(start!==null&&start>clock)return neutral(source,p,200,'Upcoming activity — the published start time has not arrived.');
  let html=source.replace(/<section\b[^>]*\bid=["']campaign-published-details["'][^>]*>[\s\S]*?<\/section\s*>/gi,'');
  html=metadata(html,p);
  const banner=`<section id="campaign-published-details" class="${sectionClass(source)}" aria-labelledby="campaign-published-title"><h2 id="campaign-published-title">${escape(p.title)}</h2>${p.description?.trim()?`<p>${escape(p.description)}</p>`:''}<p>Published activity: active</p><p>Published schedule (UTC): ${windowHtml(p)}</p></section>`;
  html=html.replace(/<body\b[^>]*>/i,tag=>tag+banner);
  // Replace the Seasonal source's illustrative caption; its client must retain this published value too.
  html=html.replace(/(<([a-z][a-z0-9]*)\b[^>]*\bid=["']campaign-date["'][^>]*>)[\s\S]*?(<\/\2\s*>)/gi,(all,open,tag,close)=>open+escape(windowText(p))+close);
  return {status:200,body:html};
}

export function projectFcCatalog(originalCatalog,snapshot) {
  const catalog=structuredClone(originalCatalog),products=originalCatalog.products||{};
  const keys=path=>{
    const page=snapshot?.pages?.find(p=>p.active===true&&route(p.path)===path);
    return [...new Set((page?.product_keys||[]).flatMap(key=>{
      const match=/^fc-(.+)-(ps|xbox|pc)$/.exec(key),product=match&&products[match[1]];
      return product?.platforms?.[match[2]]?[match[1]]:[];
    }))];
  };
  const weekly=keys('Weekly-Scout.html').filter(key=>products[key].kind==='player');
  const trioKeys=keys('Player-Trio.html'),sbcKeys=keys('Sbc-Companions.html'),sbcSet=new Set(sbcKeys);
  catalog.weekly.ids=weekly;
  if(weekly.some(key=>products[key].version!=='Team of the Week'))catalog.weekly.edition={zh:'已发布球员精选',en:'Published player picks'};
  catalog.trio.ids=trioKeys.filter(key=>products[key].kind==='player'&&products[key].version===catalog.trio.series);
  catalog.bundles.ids=trioKeys.filter(key=>products[key].kind==='bundle');
  catalog.sbc.ids=sbcKeys.filter(key=>products[key].kind==='sbc');
  catalog.sbc.routes=Object.fromEntries(catalog.sbc.ids.filter(key=>originalCatalog.sbc.routes[key]).map(key=>{
    const original=originalCatalog.sbc.routes[key],selected=ids=>(ids||[]).filter(id=>sbcSet.has(id)&&products[id]?.kind==='player');
    return [key,{...structuredClone(original),picks:selected(original.picks),alternatives:selected(original.alternatives)}];
  }));
  catalog.sbc.defaultId=catalog.sbc.ids.includes(originalCatalog.sbc.defaultId)?originalCatalog.sbc.defaultId:catalog.sbc.ids[0]??null;
  catalog.sbc.fallbackPicks=[...(catalog.sbc.routes[catalog.sbc.defaultId]?.picks||[])];
  catalog.sbc.allListedIds=[...catalog.sbc.ids];
  const selected=new Set([...weekly,...catalog.trio.ids,...catalog.bundles.ids,...catalog.sbc.ids,...Object.values(catalog.sbc.routes).flatMap(r=>[...r.picks,...r.alternatives])]);
  catalog.products=Object.fromEntries(Object.entries(catalog.products).filter(([key])=>selected.has(key)));
  catalog.mode='preview';catalog.manageDocumentLanguage=false;catalog.defaultView='weekly';
  return catalog;
}
