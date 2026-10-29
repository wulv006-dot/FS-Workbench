import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {randomUUID} from 'node:crypto';
import {makeStore,initialLayout,validateLayout,previewCatalog} from '../analytics/store.mjs';
const c=JSON.parse(fs.readFileSync(new URL('../catalog.json',import.meta.url))),registry=[{id:'fc27-weekly',name:'Weekly',path:'/Fc-27/Weekly.html'}];
test('persistent configuration, restart readback, CAS conflict and operation deduplication',()=>{const dir=fs.mkdtempSync(path.join(os.tmpdir(),'campaign-store-'));try{const store=makeStore(dir,c,registry),body={revision:0,operationId:randomUUID(),registry,layout:initialLayout(c)};assert.equal(store.save(body,'admin').revision,1);assert.equal(makeStore(dir,c,registry).read().revision,1);assert.equal(store.save(body,'admin').revision,1);assert.throws(()=>store.save({...body,operationId:randomUUID()},'admin'),/其他人/);assert.throws(()=>store.save({...body,registry:[...registry,{id:'new-campaign',name:'new',path:'/New.html'}]},'admin'),/另一份/);}finally{fs.rmSync(dir,{recursive:true,force:true});}});
test('product layout validates real type and version without changing price or enabling checkout',()=>{const d=initialLayout(c);assert.deepEqual(validateLayout(d,c),d);assert.throws(()=>validateLayout({...d,trio:d.weekly},c),/版本/);assert.throws(()=>validateLayout({...d,weekly:['unlisted']},c));const preview=previewCatalog(c,d);assert.equal(preview.mode,'preview');assert.deepEqual(preview.products,c.products);assert.deepEqual(preview.pricing,c.pricing);});

test("mixed weekly drafts use accurate edition labels",()=>{const d=initialLayout(c);d.weekly=[Object.keys(c.products).find(id=>c.products[id].kind==='player'&&c.products[id].version!=='Team of the Week')];assert.equal(previewCatalog(c,d).weekly.edition.en,'WEEKLY PLAYER PICKS');});

test('registry-only save retains accepted layout after catalog drift, without allowing new invalid layouts',()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'campaign-registry-drift-'));
 try{
  const store=makeStore(dir,c,registry),layout=initialLayout(c);
  assert.throws(()=>store.save({revision:0,operationId:randomUUID(),registry,layout:{...layout,trio:layout.weekly}},'admin'));
  store.save({revision:0,operationId:randomUUID(),registry,layout},'admin');
  const drifted=structuredClone(c);drifted.trio.series='A newer catalog series';
  assert.throws(()=>validateLayout(layout,drifted));
  const restarted=makeStore(dir,drifted,registry),next=[...registry,{id:'mmoexp-seasonal',name:'Halloween',path:'/events/seasonal/'}];
  const request={revision:1,operationId:randomUUID(),registry:next,layout:structuredClone(layout)};
  const saved=restarted.save(request,'admin');assert.equal(saved.revision,2);assert.deepEqual(saved.layout,layout);assert.equal(saved.registry.length,2);
  assert.deepEqual(restarted.save(request,'admin'),saved);
  assert.throws(()=>restarted.save({...request,operationId:randomUUID()},'admin'),e=>e.status===409);
  assert.throws(()=>restarted.save({...request,revision:2,operationId:randomUUID(),layout:{...layout,weekly:[layout.weekly[0]]}},'admin'));
  assert.throws(()=>restarted.save({...request,revision:2,operationId:randomUUID(),registry},'admin'));
  assert.deepEqual(restarted.read(),saved);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
