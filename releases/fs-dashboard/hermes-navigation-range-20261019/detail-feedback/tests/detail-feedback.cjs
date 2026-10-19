const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(__dirname+'/../candidate/page.js','utf8');
const fragment=source.slice(source.indexOf('  function detailFeedback'),source.indexOf('  function shanghaiYesterday'));
function element(tag='div'){return {tag,dataset:{},attrs:{},children:[],disabled:false,hidden:false,textContent:'',classList:{toggle(){}},setAttribute(k,v){this.attrs[k]=v},append(x){this.children.push(x)},insertBefore(x){this.children.unshift(x);if(x.id)els[x.id]=x},replaceChildren(){this.children=[]},get childElementCount(){return this.children.length},focus(){this.focused=true},scrollIntoView(){this.scrolled=(this.scrolled||0)+1},querySelectorAll(){return buttons},closest(){return this}}}
const ids=['tracked-list','detail-section','detail','refresh-detail'];const els=Object.fromEntries(ids.map(x=>[x,element()]));const a='a'.repeat(32),b='b'.repeat(32);const buttons=[a,b].map(id=>{let x=element('button');x.dataset.detailId=id;return x});
let requests=[];const ctx={console,AbortController,Date,setTimeout:()=>0,clearTimeout(){},document:{hidden:false,createElement:element},window:{matchMedia:()=>({matches:false})},$:id=>els[id],node:(tag,text,parent,cls)=>{const n=element(tag);n.textContent=text;n.className=cls;parent.append(n);return n},idPattern:/^[a-f0-9]{32}$/,chosen:null,detailEpoch:0,detailAbort:null,detailTimer:null,detailPollStarted:0,detailLoading:false,get:(view,args,signal)=>new Promise((resolve,reject)=>requests.push({args,signal,resolve,reject})),detailRow(){},asText:String,uidText:String,timeText:String,money:String,orderStatus:String,denied(){ctx.deniedCalled=true}};
vm.createContext(ctx);vm.runInContext(fragment,ctx);
const good={email:'synthetic@example.invalid',history_status:'ready',history_coverage:{complete:true},orders:[],milestones:[]};
(async()=>{
 let p=ctx.loadDetail(a,{interactive:true});assert.equal(buttons[0].disabled,true);assert.equal(buttons[0].textContent,'正在加载订单与节点…');assert.equal(els['detail-section'].attrs['aria-busy'],'true');assert.equal(els['detail-section'].scrolled,1);
 await ctx.loadDetail(a,{interactive:true});assert.equal(requests.length,1,'duplicate click must not duplicate request');
 let q=ctx.loadDetail(b,{interactive:true});assert.equal(requests[0].signal.aborted,true);requests[0].resolve(good);await p;assert.equal(buttons[1].disabled,true,'old completion must not clear new pending state');requests[1].resolve(good);await q;assert.equal(buttons[1].disabled,false);assert.equal(buttons[1].attrs['aria-expanded'],'true');assert.equal(buttons[0].attrs['aria-expanded'],'false');
 let scrolls=els['detail-section'].scrolled;p=ctx.loadDetail(b);requests[2].resolve(good);await p;assert.equal(els['detail-section'].scrolled,scrolls,'background polling must not move focus/scroll');
 p=ctx.loadDetail(b,{interactive:true});requests[3].reject(Error('synthetic timeout'));await p;assert.equal(els['detail-section'].dataset.state,'error');assert.equal(buttons[1].disabled,false);assert.equal(els['refresh-detail'].disabled,false);
 p=ctx.loadDetail(b,{interactive:true});requests[4].resolve(good);await p;assert.equal(els['detail-section'].dataset.state,'ready');
 p=ctx.loadDetail(a,{interactive:true});const denied=Error('forbidden');denied.status=403;requests[5].reject(denied);await p;assert.equal(ctx.deniedCalled,true);
 console.log('PASS: loading, focus, selection, double click, superseded request, quiet polling, failure/retry, permission denial');
})().catch(e=>{console.error(e);process.exitCode=1});
