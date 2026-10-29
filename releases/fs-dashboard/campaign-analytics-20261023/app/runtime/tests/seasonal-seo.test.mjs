import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {fileURLToPath} from 'node:url';
import {seasonalSeo,presentPage} from '../presentation.mjs';import {createPublicServer} from '../server.mjs';import {digest} from '../snapshot.mjs';import {halloweenFixture} from './halloween-fixture.mjs';
const app=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..'),base='https://www.mmoexp.com/events/',clock=Date.parse('2026-10-29T12:00:00Z');
function fixture(){const s=halloweenFixture();Object.assign(s.pages[0],{starts_at:s.halloween.starts_at,ends_at:s.halloween.ends_at,description:'Halloween offers end at the published event time.'});return s;}
const policy=(s,options={})=>seasonalSeo({snapshot:s,publicBase:base,enabled:true,now:clock,...options});

test('seasonal indexing is an explicit exact-origin launch switch and fails closed for non-active context',()=>{
 assert.equal(policy(fixture()).canonical,base+'seasonal/');
 for(const opts of [{enabled:false},{publicBase:'https://preview.example/events/'},{publicBase:'http://127.0.0.1/events/'},{publicBase:'https://www.mmoexp.com/elsewhere/'},{mode:'integration_test'},{now:NaN}])assert.equal(policy(fixture(),opts),null);
 for(const change of [s=>s.pages[0].active=false,s=>s.publication_status='draft',s=>s.halloween.status='unconfigured',s=>s.native_checkout.status='unconfigured',s=>s.pages[0].page_id='other',s=>s.pages[0].ends_at='bad',s=>s.pages[0].starts_at='2090-01-01T00:00:00Z',s=>s.pages[0].ends_at='2021-01-01T00:00:00Z',s=>s.pages[0].ends_at='2098-01-01T00:00:00Z']){const s=fixture();change(s);assert.equal(policy(s),null);}
 const s=fixture();assert(policy(s,{now:Date.parse(s.pages[0].ends_at)}));assert.equal(policy(s,{now:Date.parse(s.pages[0].ends_at)+1}),null);
});

test('launched seasonal metadata has one canonical,consistent social/schema URL and no stale robots restrictions',()=>{
 const s=fixture(),source=fs.readFileSync(path.join(app,'seasonal/index.html'),'utf8').replace('</head>','<link rel="canonical" href="https://old.invalid/"><meta name="googlebot" content="noindex"><meta property="og:url" content="https://old.invalid/"></head>');
 const result=presentPage({name:'seasonal/index.html',body:source,snapshot:s,publicBase:base,now:clock,seo:policy(s)});
 assert.equal(result.status,200);assert.equal((result.body.match(/rel="canonical"/g)||[]).length,1);assert.match(result.body,/<link rel="canonical" href="https:\/\/www.mmoexp.com\/events\/seasonal\/">/);assert.match(result.body,/<meta name="robots" content="index,follow">/);assert.doesNotMatch(result.body,/noindex|old\.invalid/);assert.match(result.body,/<meta property="og:url" content="https:\/\/www.mmoexp.com\/events\/seasonal\/">/);
 const jsons=[...result.body.matchAll(/<script[^>]*type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/g)].map(x=>JSON.parse(x[1]));const page=jsons.flatMap(x=>x['@graph']||[x]).find(x=>x['@type']==='CollectionPage');assert.equal(page.url,base+'seasonal/');assert.equal(page.name,s.pages[0].title);
});

test('real HTTP only indexes the active seasonal page;default,test queries,other pages and disabled sitemap remain protected',async()=>{
 const snapshot=fixture();snapshot.pages.push({...snapshot.pages[0],page_id:'weekly',activity_id:'fc-weekly',path:'Weekly-Scout.html',product_keys:[]});
 const names=['seasonal/index.html','Weekly-Scout.html'],manifest=Object.fromEntries(names.map(n=>[n,digest(fs.readFileSync(path.join(app,n)))])),dir=fs.mkdtempSync(path.join(os.tmpdir(),'seasonal-seo-'));
 try{for(const enabled of [false,true]){
  const server=createPublicServer({assetRoot:app,staticManifest:manifest,snapshotProvider:()=>snapshot,dir,origin:'https://www.mmoexp.com',now:()=>clock,seasonalIndexingEnabled:enabled});await new Promise(r=>server.listen(0,'127.0.0.1',r));const local='http://127.0.0.1:'+server.address().port+'/events/';
  try{
   for(const rel of ['seasonal/','seasonal/index.html','seasonal/?utm_source=mail']){const r=await fetch(local+rel);const html=await r.text();assert.equal(r.status,200);assert.equal(r.headers.get('x-robots-tag'),enabled?'index, follow':'noindex, nofollow');assert.equal(r.headers.get('cache-control'),'no-store');assert.equal(html.includes('<meta name="robots" content="index,follow">'),enabled);}
   const head=await fetch(local+'seasonal/',{method:'HEAD'});assert.equal(head.status,200);assert.equal(head.headers.get('x-robots-tag'),enabled?'index, follow':'noindex, nofollow');assert.equal(await head.text(),'');
   for(const rel of ['seasonal/?analytics_test=1','seasonal/?analytics_run=example','Weekly-Scout.html']){const r=await fetch(local+rel);assert.equal(r.headers.get('x-robots-tag'),'noindex, nofollow');assert.match(await r.text(),/noindex/);}
   const sitemap=await fetch(local+'seasonal/sitemap.xml');assert.equal(sitemap.status,enabled?200:404);const xml=await sitemap.text();if(enabled){assert.match(sitemap.headers.get('content-type'),/^application\/xml/);assert.equal((xml.match(/<loc>/g)||[]).length,1);assert.ok(xml.includes('<loc>'+base+'seasonal/</loc>'));assert.ok(!xml.includes('Weekly-Scout'));}
  }finally{await new Promise(r=>server.close(r));}
 }}finally{fs.rmSync(dir,{recursive:true,force:true});}
});
