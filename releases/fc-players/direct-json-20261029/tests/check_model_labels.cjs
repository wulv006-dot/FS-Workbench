// Run the actual table renderer against the captured 23700 response, without network or writes.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/tag-labels-23700.json'),'utf8').replace(/^\uFEFF/,''));
const source=fs.readFileSync(path.join(__dirname,'../source/app.js'),'utf8');
const helper=source.slice(source.indexOf('  function node('),source.indexOf('  function clearPlan('));
const render=source.slice(source.indexOf('  function renderModels()'),source.indexOf('  function renderModelSelection()'));
assert.ok(helper&&render,'actual candidate renderer must be present');
class Element {
  constructor(tag){Object.assign(this,{tag,textContent:'',children:[],attrs:{},disabled:false});}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=[];this.append(...children);}
  setAttribute(key,value){this.attrs[key]=String(value);}
}
function run(row,catalog){
  const before=JSON.stringify(row), roots=Object.fromEntries(['modelRows','modelSummary','snapshotInfo','pageInfo','prev','next'].map(id=>[id,new Element('div')]));
  const state={snapshot:fixture.snapshot_id,modelSelected:new Set(),modelPage:1,pageSize:20,
    modelResult:{items:[row],filtered_total:1,total:fixture.snapshot_total,read_count:fixture.snapshot_total,created_at:fixture.captured_at,tag_catalog:catalog}};
  const context={state,$:id=>{assert.ok(roots[id],id);return roots[id];},document:{createElement:tag=>new Element(tag)},
    msg:(id,text)=>{roots[id].textContent=text;},renderModelSelection:()=>{},clearPlan:()=>{},Math,
    fetch:()=>assert.fail('rendering labels must never make a request')};
  vm.createContext(context);vm.runInContext(helper+render+'\nrenderModels();',context);
  assert.equal(JSON.stringify(row),before,'rendering cannot modify business IDs or cached names');
  const cells=roots.modelRows.children[0].children;
  assert.equal(cells[1].textContent,'45274659');assert.equal(cells[2].textContent,'23700');
  assert.equal(cells[0].children[0].attrs['aria-label'],'选择模型 45274659');
  return cells[5].textContent;
}
assert.equal(run(fixture.cached_row,fixture.tag_catalog),'12307 Newest；12411 TOTW');
assert.equal(run({...fixture.cached_row,tag_names:['Wrong','Also wrong']},fixture.tag_catalog),'12307 Newest；12411 TOTW');
assert.equal(run({...fixture.cached_row,tag_ids:[12307,99999,12411]},fixture.tag_catalog),'12307 Newest；99999；12411 TOTW');
assert.equal(run(fixture.cached_row,{'12307':'Same name','12411':'Same name'}),'12307 Same name；12411 Same name');
console.log('model labels DOM: 4 passed; real 23700 fixture, catalog by ID, no requests or business changes');
