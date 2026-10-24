const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'source/player_web/static/app.js'),'utf8');
const code=source.slice(source.indexOf('  async function loadJobs()'),source.indexOf('  async function showJob('));
class Element{
  constructor(tag,text,cls){Object.assign(this,{tag,textContent:text,cls,children:[],open:false});}
  append(...children){this.children.push(...children);}
  replaceChildren(){this.children=[];this.textContent='';}
}
(async()=>{
  const root=new Element('div'),opened=[],calls=[];
  let items=[];
  const context={api:async route=>{calls.push(route);return {items};},$:id=>{assert.equal(id,'jobsList');return root;},
    node:(...args)=>new Element(...args),button:(text,onclick)=>Object.assign(new Element('button',text),{onclick}),
    showJob:async id=>opened.push(id),msg:()=>assert.fail('unexpected error'),Math};
  vm.createContext(context);vm.runInContext(code,context);
  for(const count of [0,1,5,6,20]){
    items=Array.from({length:count},(_,index)=>({id:'job-'+index,created_at:'time-'+index,status:'completed_readback',step:'done'}));
    await vm.runInContext('loadJobs()',context);
    const rows=root.children.filter(child=>child.cls==='job-row'),details=root.children.find(child=>child.tag==='details');
    assert.equal(rows.length,Math.min(5,count));
    assert.equal(!!details,count>5);
    if(!count)assert.equal(root.textContent,'暂无任务');
    if(details){
      assert.equal(details.open,false);
      assert.equal(details.children[0].tag,'summary');
      assert.equal(details.children[0].textContent,`较早任务（${count-5} 条）`);
      assert.equal(details.children.length-1,count-5);
      await details.children[1].children[3].onclick();assert.equal(opened.at(-1),'job-5');
    }
    if(rows.length){await rows[0].children[3].onclick();assert.equal(opened.at(-1),'job-0');}
    assert.equal(rows.length+(details?details.children.length-1:0),count);
  }
  assert.ok(calls.every(route=>route==='/api/jobs'));
  console.log('job history: empty/1/5/6/20, latest five, collapsed older rows, result callbacks and read-only route passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
