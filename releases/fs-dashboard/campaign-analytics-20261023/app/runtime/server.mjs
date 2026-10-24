import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createCommerce,createIntegrationTestAdapter} from './commerce.mjs';
import {fail,loadStatic} from './snapshot.mjs';
import {presentPage,projectFcCatalog} from './presentation.mjs';

const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.xml':'application/xml','.txt':'text/plain; charset=utf-8','.webp':'image/webp','.png':'image/png','.svg':'image/svg+xml','.jpg':'image/jpeg','.jpeg':'image/jpeg','.gif':'image/gif','.woff2':'font/woff2'};
const headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin','X-Frame-Options':'SAMEORIGIN'};
function json(req,res,status,body) {res.writeHead(status,{...headers,'Content-Type':'application/json; charset=utf-8'});res.end(req.method==='HEAD'?undefined:JSON.stringify(body));}
async function body(req) {
  let raw='';for await (const chunk of req) {raw+=chunk;if (Buffer.byteLength(raw)>64000) fail('REQUEST_TOO_LARGE',413);}
  try {return JSON.parse(raw);} catch {fail('INVALID_REQUEST');}
}
export function createPublicServer({assetRoot,staticManifest,snapshot,snapshotProvider,dir,mode='preview',origin,prefix='/events/',testAdapter,now}={}) {
  const parsed=new URL(origin);
  if (parsed.origin!==origin || (parsed.protocol!=='https:' && !(parsed.protocol==='http:'&&['127.0.0.1','localhost'].includes(parsed.hostname)))) fail('INVALID_ORIGIN');
  if (!/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(prefix)) fail('INVALID_PUBLIC_PATH');
  const files=loadStatic(assetRoot,staticManifest),commerce=createCommerce({snapshot,snapshotProvider,dir,mode,testAdapter,now});
  const server=http.createServer(async(req,res)=>{
    try {
      if (!['127.0.0.1','::ffff:127.0.0.1','::1'].includes(req.socket.remoteAddress)) return json(req,res,403,{code:'LOOPBACK_REQUIRED'});
      let pathname;try {pathname=decodeURIComponent(req.url.split('?')[0]);}catch {return json(req,res,400,{code:'INVALID_PUBLIC_PATH'});}
      if (!pathname.startsWith(prefix) || /[\\\u0000-\u001f%]/.test(pathname) || pathname.split('/').some(p=>p==='.'||p==='..')) return json(req,res,404,{code:'NOT_FOUND'});
      const relative=pathname.slice(prefix.length),read=['GET','HEAD'].includes(req.method);
      if (!read) {
        if (req.method!=='POST') return json(req,res,405,{code:'METHOD_NOT_ALLOWED'});
        if (req.headers.origin!==origin || req.headers['content-type']!=='application/json' || req.headers['sec-fetch-site']==='cross-site') return json(req,res,403,{code:'ORIGIN_REQUIRED'});
        const routes={'api/campaign/intents':b=>commerce.intent(b),'api/campaign/quote':b=>commerce.quote(b),'api/campaign/prepare_checkout':b=>commerce.prepare(b)};
        if (!Object.hasOwn(routes,relative)) return json(req,res,404,{code:'NOT_FOUND'});
        return json(req,res,200,await routes[relative](await body(req)));
      }
      if (relative==='api/campaign/config') return json(req,res,200,{...commerce.config(),integration_mode:mode,live_checkout:false});
      if (relative==='api/campaign/capabilities') return json(req,res,200,commerce.capabilities());
      if (relative.startsWith('api/campaign/intents/request/')) return json(req,res,200,commerce.lookupIntent(relative.slice('api/campaign/intents/request/'.length)));
      if (relative.startsWith('api/campaign/operations/')) return json(req,res,200,await commerce.lookup(relative.slice('api/campaign/operations/'.length)));
      const name=relative==='seasonal/'?'seasonal/index.html':relative||'index.html';let content=files.get(name),status=200;
      if (!content) return json(req,res,404,{code:'NOT_FOUND'});
      if(name==='catalog.js'){
        const match=/^\s*window\.FC_ACTIVITY_CONFIG\s*=\s*([\s\S]*?);?\s*$/.exec(content.toString('utf8'));
        if(!match)fail('INVALID_CATALOG',503);
        const catalog=projectFcCatalog(JSON.parse(match[1].replace(/;\s*$/,'')),commerce.config());
        content='window.FC_ACTIVITY_CONFIG='+JSON.stringify(catalog).replace(/</g,'\\u003c')+';';
      }else if(name.endsWith('.html')){
        const rendered=presentPage({name,body:content,snapshot:commerce.config(),now:now||Date.now});content=rendered.body;status=rendered.status;
      }
      res.writeHead(status,{...headers,'Content-Type':types[path.extname(name)],'X-Robots-Tag':'noindex, nofollow'});res.end(req.method==='HEAD'?undefined:content);
    } catch(error) {
      json(req,res,error.status||500,{code:error.status?error.code:'RUNTIME_UNAVAILABLE',integration_mode:mode,live_checkout:false});
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
    dir:process.env.CAMPAIGN_RUNTIME_DATA||'/var/lib/fs-campaign-runtime',mode,origin:process.env.CAMPAIGN_PUBLIC_ORIGIN,
    prefix:process.env.CAMPAIGN_PUBLIC_PREFIX||'/events/',
    ...(mode==='integration_test'&&process.env.CAMPAIGN_TEST_PRICES?{testAdapter:createIntegrationTestAdapter(readJSON(process.env.CAMPAIGN_TEST_PRICES))}:{})});
  server.listen(Number(process.env.CAMPAIGN_PUBLIC_PORT||8949),'127.0.0.1',()=>console.log('FS public campaign runtime listening on loopback'));
}
