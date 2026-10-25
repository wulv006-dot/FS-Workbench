import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {makeCenterStore,initialCenterDraft,validateDraft} from '../analytics/center-store.mjs';
import {projectRelease,presentationOptions} from '../runtime/snapshot.mjs';
import {presentPage} from '../runtime/presentation.mjs';
const app=new URL('../',import.meta.url),source=fs.readFileSync(new URL('Weekly-Scout.html',app),'utf8');
function storeAt(dir){return makeCenterStore({dir:path.join(dir,'private'),publicDir:path.join(dir,'public'),sourceRevision:'ops-gaps-fixture'});}
test('original configs remain compatible and presentation choices are limited to original page content',()=>{
 const original=initialCenterDraft();assert(original.pages.every(p=>p.default_language==='original'&&p.social_image==='original'));
 for(const mutate of [d=>d.pages[0].default_language='fr',d=>d.pages[3].default_language='zh',d=>d.pages[0].social_image='https://evil.test/x.webp',d=>d.pages[0].social_image='assets/scream-hero.webp',d=>d.pages[0].social_image='../assets/weekly-hero.webp']){const invalid=structuredClone(original);mutate(invalid);assert.throws(()=>validateDraft(invalid),e=>e.code==='INVALID_PRESENTATION_CONFIG');}
 const legacy=structuredClone(original);legacy.pages.forEach(p=>{delete p.default_language;delete p.social_image;});assert.deepEqual(validateDraft(legacy),original);
 for(const options of Object.values(presentationOptions))for(const image of options.images.filter(x=>x!=='original'))assert(fs.existsSync(new URL(image,app)),image);
});
test('save, publish and public English display retains legacy raw fields and approved share assets and exact release readback',()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'campaign-ops-gaps-'));
 try{const store=storeAt(dir),draft=initialCenterDraft();draft.pages[0].title='Published metadata';draft.pages[0].description='Existing campaign text';draft.pages[0].default_language='zh';draft.pages[0].social_image='assets/weekly-hero-mobile.webp';draft.seasonal_theme='christmas';
  const save={revision:0,operation_id:randomUUID(),draft};store.save(save,'fixture');const publish={revision:1,operation_id:randomUUID()};const result=store.publish(publish,'fixture');assert.deepEqual(store.publish(publish,'fixture'),result);
  const published=JSON.parse(fs.readFileSync(path.join(dir,'public/current.json')));assert.equal(published.pages[0].default_language,'zh');assert.equal(published.pages[0].social_image,'assets/weekly-hero-mobile.webp');assert.equal(result.published.source_revision,'ops-gaps-fixture');assert.equal(result.published.pages[0].social_image,published.pages[0].social_image);assert.equal(result.published.config_hash,published.config_hash);
  const body=presentPage({name:'Weekly-Scout.html',body:source,snapshot:published,publicBase:'https://campaign.example/events/'}).body;
  assert.match(body,/<html[^>]*lang="en"/);assert.match(body,/data-default-language="en"/);assert.match(body,/<title>Published metadata<\/title>/);assert.match(body,/property="og:image" content="https:\/\/campaign.example\/events\/assets\/weekly-hero-mobile.webp"/);assert.match(body,/name="twitter:image" content="https:\/\/campaign.example\/events\/assets\/weekly-hero-mobile.webp"/);assert.match(body,/property="og:locale" content="en_US"/);assert.match(body,/"inLanguage":"en"/);assert(body.includes('src="assets/weekly-hero.webp"'));assert(body.includes('href="https://www.mmoexp.com/Fc-27/Weekly-Scout.html"'));
  assert.throws(()=>presentPage({name:'Weekly-Scout.html',body:source,snapshot:published}),e=>e.code==='INVALID_PUBLIC_BASE');
  for(const publicBase of ['javascript:alert(1)','https://user:pass@campaign.example/events/','https://campaign.example/events/?x=1'])assert.throws(()=>presentPage({name:'Weekly-Scout.html',body:source,snapshot:published,publicBase}),e=>e.code==='INVALID_PUBLIC_BASE');
  for(const alter of [s=>s.pages[0].social_image='assets/scream-hero.webp',s=>s.pages[0].social_image='https://evil.test/x.webp',s=>s.pages[3].default_language='zh']){const invalid=structuredClone(published);alter(invalid);assert.throws(()=>projectRelease(invalid),e=>e.code==='INVALID_PRESENTATION_CONFIG');}
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
