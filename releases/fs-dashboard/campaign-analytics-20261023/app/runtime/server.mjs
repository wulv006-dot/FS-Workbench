import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createCommerce,createIntegrationTestAdapter} from './commerce.mjs';
import {fail,loadStatic,projectRelease} from './snapshot.mjs';
import {presentPage,projectFcCatalog,publicEnglishRelease,seasonalSeo} from './presentation.mjs';
import {readPublishedMedia} from './published-media.mjs';
import {pageMedia} from './media-contract.mjs';
import {applyPublicPriceCache,readPublicPriceCache} from './admin-price-cache.mjs';
import {publicConfigCache,referenceDeadline} from './public-config-cache.mjs';
import {createCarnival} from './carnival.mjs';

const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.xml':'application/xml','.txt':'text/plain; charset=utf-8','.webp':'image/webp','.png':'image/png','.svg':'image/svg+xml','.jpg':'image/jpeg','.jpeg':'image/jpeg','.gif':'image/gif','.woff2':'font/woff2'};
const headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin','X-Frame-Options':'SAMEORIGIN'};
function json(req,res,status,body) {res.writeHead(status,{...headers,'Content-Type':'application/json; charset=utf-8'});res.end(req.method==='HEAD'?undefined:JSON.stringify(body));}
async function body(req) {
  let raw='';for await (const chunk of req) {raw+=chunk;if (Buffer.byteLength(raw)>64000) fail('REQUEST_TOO_LARGE',413);}
  try {return JSON.parse(raw);} catch {fail('INVALID_REQUEST');}
}
export function createPublicServer({assetRoot,staticManifest,snapshot,snapshotProvider,priceCacheProvider,publishedDir,releaseFile,configCacheMs=0,configStampProvider,staticCacheEnabled=false,seasonalIndexingEnabled=false,dir,mode='preview',origin,prefix='/events/',testAdapter,now,halloweenCatalogProvider}={}) {
  const parsed=new URL(origin);
  if (parsed.origin!==origin || (parsed.protocol!=='https:' && !(parsed.protocol==='http:'&&['127.0.0.1','localhost'].includes(parsed.hostname)))) fail('INVALID_ORIGIN');
  if (!/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(prefix)) fail('INVALID_PUBLIC_PATH');
  const frozen=snapshotProvider?null:{publication_status:'published',...projectRelease(snapshot)};
  const source=snapshotProvider||(()=>frozen),cache=priceCacheProvider||(()=>publishedDir?readPublicPriceCache(path.join(publishedDir,'admin-reference-prices.json')):null);
  const snapshotWithPrices=()=>{
  const snapshot=source(),current=cache();
  const waitingForPrices=!current||current.release_id!==snapshot.release_id||current.config_hash!==snapshot.config_hash||current.status==='refreshing';
  const initial=publishedDir&&waitingForPrices
   &&/^campaign-preview-\d+$/.test(snapshot.release_id)
   ?readPublicPriceCache(path.join(publishedDir,snapshot.release_id+'-initial-prices.json')):null;
  return applyPublicPriceCache(snapshot,current,{now:(now||Date.now)(),initial});
 };
 const files=loadStatic(assetRoot,staticManifest),commerce=createCommerce({snapshotProvider:snapshotWithPrices,dir,mode,testAdapter,now,halloweenCatalogProvider});
  const carnival=createCarnival({dir:dir||path.join(process.cwd(),'.carnival-runtime'),publishedDir,now:now||Date.now});
  const fileStamp=file=>{try{const s=fs.statSync(file,{bigint:true});return [String(s.ino),String(s.size),String(s.mtimeNs)].join(':');}catch(error){if(error.code==='ENOENT')return 'absent';throw error;}};
  const stamp=configStampProvider||(releaseFile&&publishedDir?()=>fileStamp(releaseFile)+'|'+fileStamp(path.join(publishedDir,'admin-reference-prices.json')):null);
  const configBody=publicConfigCache({ttlMs:configCacheMs,now:now||Date.now,stamp,render:()=>{
    const config=publicEnglishRelease(commerce.config());
    // Cache only the masked public response; selected codes still need a fresh
    // server claim and all POST/receipt paths retain their original validation.
    if(config.native_checkout?.status==='configured'){
      config.native_checkout={...config.native_checkout,bindings:config.native_checkout.bindings.map(b=>({...b,code:'CLAIM_REQUIRED'}))};config.native_checkout_claim_required=true;
    }
    return {body:JSON.stringify({...config,page_media:pageMedia(config.pages,prefix),integration_mode:mode,live_checkout:false}),expiresAt:referenceDeadline(config)};
  }});
  const server=http.createServer(async(req,res)=>{
    try {
      if (!['127.0.0.1','::ffff:127.0.0.1','::1'].includes(req.socket.remoteAddress)) return json(req,res,403,{code:'LOOPBACK_REQUIRED'});
      let pathname;try {pathname=decodeURIComponent(req.url.split('?')[0]);}catch {return json(req,res,400,{code:'INVALID_PUBLIC_PATH'});}
      if (!pathname.startsWith(prefix) || /[\\\u0000-\u001f%]/.test(pathname) || pathname.split('/').some(p=>p==='.'||p==='..')) return json(req,res,404,{code:'NOT_FOUND'});
      const relative=pathname.slice(prefix.length),read=['GET','HEAD'].includes(req.method);
      if (!read) {
        if (req.method!=='POST') return json(req,res,405,{code:'METHOD_NOT_ALLOWED'});
        if (req.headers.origin!==origin || req.headers['content-type']!=='application/json' || req.headers['sec-fetch-site']==='cross-site') return json(req,res,403,{code:'ORIGIN_REQUIRED'});
        const routes={'api/campaign/native_plan':b=>commerce.nativePlan(b),'api/campaign/intents':b=>commerce.intent(b),'api/campaign/quote':b=>commerce.quote(b),'api/campaign/prepare_checkout':b=>commerce.prepare(b),
          'api/campaign/halloween/reveal':b=>commerce.halloweenReveal(b),'api/campaign/halloween/resolve':b=>commerce.halloweenResolve(b),
          'api/carnival/mystery/draw':b=>carnival.draw(b),'api/carnival/mystery/verify':b=>carnival.verify(b)};
        if (!Object.hasOwn(routes,relative)) return json(req,res,404,{code:'NOT_FOUND'});
        return json(req,res,200,await routes[relative](await body(req)));
      }
      if (relative==='api/campaign/config'){
        const content=configBody();res.writeHead(200,{...headers,'Content-Type':'application/json; charset=utf-8'});return res.end(req.method==='HEAD'?undefined:content);
      }
      if (relative==='api/campaign/capabilities') return json(req,res,200,commerce.capabilities());
      if (relative==='api/carnival/schedule') return json(req,res,200,carnival.schedule());
      if (relative==='api/carnival/mystery') return json(req,res,200,carnival.state(new URL(req.url,origin).searchParams));
      if(relative==='seasonal/sitemap.xml'){
        const seo=seasonalSeo({snapshot:commerce.config(),publicBase:new URL(prefix,origin).href,enabled:seasonalIndexingEnabled,mode,now:now||Date.now});
        if(!seo)return json(req,res,404,{code:'NOT_FOUND'});
        res.writeHead(200,{...headers,'Content-Type':'application/xml; charset=utf-8'});return res.end(req.method==='HEAD'?undefined:`<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>${seo.canonical}</loc></url></urlset>`);
      }
      if(relative.startsWith('api/campaign/halloween/reveals/'))return json(req,res,200,commerce.halloweenRead(relative.slice('api/campaign/halloween/reveals/'.length)));
      if (relative.startsWith('api/campaign/intents/request/')) return json(req,res,200,commerce.lookupIntent(relative.slice('api/campaign/intents/request/'.length)));
      if (relative.startsWith('api/campaign/operations/')) return json(req,res,200,await commerce.lookup(relative.slice('api/campaign/operations/'.length)));
      if(relative.startsWith('media/')){
        if(!publishedDir)fail('MEDIA_NOT_FOUND',404);const {info,bytes}=readPublishedMedia(publishedDir,commerce.config(),relative.slice('media/'.length));
        res.writeHead(200,{...headers,'Content-Type':info.mime});return res.end(req.method==='HEAD'?undefined:bytes);
      }
      const name=relative==='seasonal/'?'seasonal/index.html':relative||'index.html';let content=files.get(name),status=200,pageSeo=null;
      if (!content) return json(req,res,404,{code:'NOT_FOUND'});
      if(name==='catalog.js'){
        const match=/^\s*window\.FC_ACTIVITY_CONFIG\s*=\s*([\s\S]*?);?\s*$/.exec(content.toString('utf8'));
        if(!match)fail('INVALID_CATALOG',503);
        const config=commerce.config(),catalog=projectFcCatalog(JSON.parse(match[1].replace(/;\s*$/,'')),config);catalog.page_media=pageMedia(config.pages,prefix);
        content='window.FC_ACTIVITY_CONFIG='+JSON.stringify(catalog).replace(/</g,'\\u003c')+';';
      }else if(name.endsWith('.html')){
        const current=commerce.config(),publicBase=new URL(prefix,origin).href;
        const query=new URL(req.url,origin).searchParams;
        if(name==='seasonal/index.html')pageSeo=seasonalSeo({snapshot:current,publicBase,enabled:seasonalIndexingEnabled&&!query.has('analytics_test')&&!query.has('analytics_run'),mode,now:now||Date.now});
        const rendered=presentPage({name,body:content,snapshot:current,now:now||Date.now,publicBase,seo:pageSeo,assetVersion:asset=>asset==='catalog.js'?current.config_hash:staticManifest[asset]});content=rendered.body;status=rendered.status;
        if(status!==200)pageSeo=null;
      }
      const responseHeaders={...headers,'Content-Type':types[path.extname(name)],'X-Robots-Tag':pageSeo?'index, follow':'noindex, nofollow'};
      if(staticCacheEnabled&&name!=='catalog.js'&&/\.(?:js|css|webp|png|svg|jpg|jpeg|gif|woff2)$/.test(name)){
        const query=new URL(req.url,origin).searchParams,version=query.getAll('v'),etag='"'+staticManifest[name]+'"';
        const immutable=version.length===1&&version[0]===staticManifest[name]&&[...query.keys()].every(k=>k==='v');
        responseHeaders['Cache-Control']=immutable?'public, max-age=31536000, immutable':'no-cache';responseHeaders.ETag=etag;
        if(req.headers['if-none-match']?.split(',').map(x=>x.trim()).some(x=>x===etag||x==='*')){res.writeHead(304,responseHeaders);return res.end();}
      }
      res.writeHead(status,responseHeaders);res.end(req.method==='HEAD'?undefined:content);
    } catch(error) {
      json(req,res,error.status||500,{code:error.status?error.code:'RUNTIME_UNAVAILABLE',...(error.dispatch_state==='not_started'?{dispatch_state:'not_started'}:{}),integration_mode:mode,live_checkout:false});
    }
  });
  server.requestTimeout=15000;server.headersTimeout=10000;
  return server;
}

if (process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  const readJSON=file=>JSON.parse(fs.readFileSync(file,'utf8'));
  const mode=process.env.CAMPAIGN_PUBLIC_MODE||'preview';
  const server=createPublicServer({assetRoot:process.env.CAMPAIGN_PUBLIC_ROOT||path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),
    staticManifest:readJSON(process.env.CAMPAIGN_PUBLIC_MANIFEST),snapshotProvider:()=>readJSON(process.env.CAMPAIGN_PUBLIC_RELEASE),
    publishedDir:process.env.CAMPAIGN_PUBLIC_RELEASE_DIR||path.dirname(process.env.CAMPAIGN_PUBLIC_RELEASE),
    releaseFile:process.env.CAMPAIGN_PUBLIC_RELEASE,configCacheMs:Number(process.env.CAMPAIGN_PUBLIC_CONFIG_CACHE_MS||0),staticCacheEnabled:process.env.CAMPAIGN_PUBLIC_STATIC_CACHE==='1',seasonalIndexingEnabled:process.env.CAMPAIGN_SEASONAL_INDEXING==='1',
    dir:process.env.CAMPAIGN_RUNTIME_DATA||'/var/lib/fs-campaign-runtime',mode,origin:process.env.CAMPAIGN_PUBLIC_ORIGIN,
    prefix:process.env.CAMPAIGN_PUBLIC_PREFIX||'/events/',
    ...(mode==='integration_test'&&process.env.CAMPAIGN_TEST_PRICES?{testAdapter:createIntegrationTestAdapter(readJSON(process.env.CAMPAIGN_TEST_PRICES))}:{})});
  server.listen(Number(process.env.CAMPAIGN_PUBLIC_PORT||8949),'127.0.0.1',()=>console.log('FS public campaign runtime listening on loopback'));
}
