import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import {randomUUID} from 'node:crypto';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {makeCenterStore,initialCenterDraft} from '../center-store.mjs';
import {centerSeed} from '../center-seed.mjs';
import {pageCopyFields,COPY_FIELDS} from '../../runtime/snapshot.mjs';

const require=createRequire(import.meta.url);
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const content=require(path.join(root,'activity-content.js'));

function seed(){
  const box={};
  vm.runInNewContext(fs.readFileSync(path.join(root,'seasonal/campaign-data.js'),'utf8'),box);
  return centerSeed(JSON.parse(fs.readFileSync(path.join(root,'catalog.json'),'utf8')),box.SeasonalData);
}
const weekly={page_id:'fc27-weekly',path:'Weekly-Scout.html'};

test('visible hero copy accepts English text and trims it',()=>{
  assert.deepEqual(pageCopyFields({...weekly,copy:{heading:'  Ballon d’Or shortlist  ',intro:'Three winners.',body:'Compare exact items.'}}),
    {copy:{heading:'Ballon d’Or shortlist',intro:'Three winners.',body:'Compare exact items.'}});
  assert.deepEqual(pageCopyFields(weekly),{});
  assert.deepEqual(pageCopyFields({...weekly,copy:{}}),{});
});

test('visible hero copy rejects Chinese, markup, unknown keys, oversize and unscoped pages',()=>{
  const bad=[
    {...weekly,copy:{heading:'金球奖得主'}},
    {...weekly,copy:{heading:'<b>bold</b>'}},
    {...weekly,copy:{heading:'line\nbreak'}},
    {...weekly,copy:{subtitle:'nope'}},
    {...weekly,copy:{heading:'   '}},
    {...weekly,copy:{heading:'x'.repeat(COPY_FIELDS.heading+1)}},
    {...weekly,copy:'not-an-object'},
    {page_id:'seasonal-vault',path:'seasonal/index.html',copy:{heading:'Seasonal'}}
  ];
  for(const page of bad)assert.throws(()=>pageCopyFields(page),error=>error.code==='INVALID_PAGE_COPY');
});

test('published snapshot carries the operator copy; invalid copy blocks publish',()=>{
  const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'campaign-copy-'));
  try{
    const options={dir:path.join(tmp,'private'),publicDir:path.join(tmp,'public'),sourceRevision:'candidate-copy',...seed()};
    const store=makeCenterStore(options);
    const draft=initialCenterDraft();
    draft.pages[0].copy={heading:'Ballon d’Or 2026 shortlist',intro:'Kane, Putellas, Yamal.',body:'Compare exact FC 27 items.'};
    assert.equal(store.save({revision:0,operation_id:randomUUID(),draft},'admin').revision,1);
    assert.equal(store.publish({revision:1,operation_id:randomUUID()},'admin').revision,2);
    const published=JSON.parse(fs.readFileSync(path.join(tmp,'public/current.json'),'utf8'));
    const page=published.pages.find(row=>row.page_id==='fc27-weekly');
    assert.deepEqual(page.copy,{heading:'Ballon d’Or 2026 shortlist',intro:'Kane, Putellas, Yamal.',body:'Compare exact FC 27 items.'});
    assert.equal(published.pages.find(row=>row.page_id==='fc27-trio').copy,undefined);
    // A stored draft that bypasses the editor still cannot smuggle Chinese into the public page.
    const chinese=initialCenterDraft();
    chinese.pages[0].copy={heading:'金球奖'};
    assert.throws(()=>store.save({revision:2,operation_id:randomUUID(),draft:chinese},'admin'),error=>error.code==='INVALID_PAGE_COPY');
  }finally{fs.rmSync(tmp,{recursive:true,force:true});}
});

test('hero renderer applies published copy and keeps defaults when absent',()=>{
  const raw=JSON.parse(fs.readFileSync(path.join(root,'catalog.json'),'utf8'));
  const plain=content.create(content.publicConfig(structuredClone(raw)),false).heroes.weekly;
  assert.equal(plain.heading[1],'Current Popular player picks');
  const defaults=content.create(raw,false).heroes;
  assert(!/Ballon|BALLON|winners|Kane|Putellas|Yamal|C罗|帕尔默|卢克巴|罗纳尔多/.test(JSON.stringify(defaults)));

  const sbc=content.create(raw,false).heroes.sbc;
  for(const key of ['body','heading','intro'])assert(!/Emre Mor|Nick Woltemade|Ultimate Scream|actually link|chemistry-matched/.test(sbc[key][1]));
  assert.match(sbc.intro[1],/do not guarantee full chemistry/);
  const customSbc=structuredClone(raw);customSbc.copy={sbc:{body:'Operator SBC body',heading:'Operator SBC heading',intro:'Operator SBC intro'}};
  const custom=content.create(customSbc,false).heroes.sbc;
  for(const key of ['body','heading','intro'])assert.equal(custom[key][1],customSbc.copy.sbc[key]);

  const overridden=structuredClone(raw);
  overridden.copy={weekly:{heading:'Copy from the admin',intro:'Intro from the admin',body:'Body from the admin'}};
  const hero=content.create(content.publicConfig(overridden),false).heroes.weekly;
  // Public pages are English-only, so the override fills both language slots.
  assert.deepEqual(hero.heading,['Copy from the admin','Copy from the admin']);
  assert.equal(hero.heading[1],'Copy from the admin');
  assert.equal(hero.intro[1],'Intro from the admin');
  assert.equal(hero.body[1],'Body from the admin');
  // Untouched fields and other pages keep their defaults.
  assert.equal(hero.kicker,plain.kicker);
  assert.notEqual(content.create(content.publicConfig(overridden),false).heroes.trio.heading[1],'Copy from the admin');
});

test('the admin editor exposes the copy fields and submits them with the draft',()=>{
  const editor=fs.readFileSync(path.join(root,'analytics/products.js'),'utf8');
  assert.match(editor,/function copyControls\(page,i\)/);
  // The fields are generated in a loop, so assert on the template that emits them.
  assert.ok(editor.includes('data-copy="\'+key+\'"'));
  assert.ok(editor.includes('name="copy_\'+key+\'"'));
  assert.ok(editor.includes("['heading','intro','body']"));
  assert.ok(editor.includes("if(!same(copy,p.copy||{}))"));
  assert.ok(editor.includes('if(Object.keys(copy).length)p.copy=copy;else delete p.copy;'));
  assert.ok(editor.includes("copy:'\u53ef\u89c1\u6587\u6848'"));
  // Public pages stay English-only: the editor blocks Han input before submit.
  assert.ok(editor.includes('\u516c\u5f00\u9875\u9762\u53ea\u63a5\u53d7\u82f1\u6587'));
});
