const fs=require('fs'),vm=require('vm'),assert=require('assert');
const code=fs.readFileSync(process.argv[2]||__dirname+'/source/fc27-quote-cloud.js','utf8');
const part=code.slice(code.indexOf('  async function syncAutomaticCycle(){'),code.indexOf('  function selectedNow(){'));
const old={job_id:'auto-old',kind:'auto_cycle',created_at:'2026-10-03T09:47:16Z',status:'ready',request:{policy_revision:23},quote:{status:'ready_for_preview'},result:{status:'no_price_change'}};
const manual={run_id:'manual-new',created_at:'2026-10-03T10:33:51Z',automation_policy_revision:23,status:'ready_for_preview',result:{rows:[{platform:'PS',target_page_usd:'13.09'}]}};
const autoq={...manual,run_id:'auto-old',created_at:'2026-10-03T09:48:40Z',result:{rows:[{platform:'PS',target_page_usd:'13.45'}]}};
const manualJob={job_id:'manual-new',kind:'collect',status:'ready',created_at:'2026-10-03T10:32:30Z',completed_at:'2026-10-03T10:33:51Z',quote:{status:'ready_for_preview'}};
function setup(options={}){
 const c={runId:null,quote:null,preview:null,automation:{system_enabled:true,mode:'auto',platforms:['PS','XBOX','PC'],revision:23,schedule:{status:'waiting',last_job_id:'auto-old'}},automationDirty:false,busy:false,automaticSyncing:false,manualQuoteEpoch:0,displayedAutomaticJobId:null,playerSync:{enabled:true},shown:[],states:[],errors:[],calls:[],Date,Error,activityTime:x=>x,...options};
 c.api=async(path,body)=>{assert.equal(body,undefined,'background restore must be GET only');c.calls.push(path);if(options.onRead)await options.onRead(path,c);if(path==='/monitor')return options.monitor||{latest_attempt:{run_id:'manual-new'},latest_collection:{run_id:'manual-new',created_at:'2026-10-03T10:32:30Z'}};if(path==='/jobs/manual-new')return options.manualJob||manualJob;if(path.startsWith('/jobs/'))return options.job||old;if(path==='/quotes/manual-new'){if(options.quote404){const e=Error('not_found');e.code='not_found';e.status=404;throw e}return options.manual||manual}if(path==='/quotes/auto-old')return autoq;throw Error(path)};
 c.clearOldQuote=()=>{c.runId=null;c.quote=null;c.preview=null};c.showQuote=()=>c.shown.push(c.quote);c.setStatus=(...x)=>c.states.push(x);c.clearProblem=()=>{};c.showProblem=(...x)=>c.errors.push(x);vm.createContext(c);vm.runInContext(part,c);return c;
}
(async()=>{
 let count=0;
 let c=setup();await c.syncAutomaticCycle();assert.equal(c.quote.result.rows[0].target_page_usd,'13.09');assert.equal(c.runId,'manual-new');assert.equal(c.calls.filter(x=>x.includes('/quotes/auto-old')).length,0);count++;
 c=setup({displayedAutomaticJobId:'auto-old'});await c.syncAutomaticCycle();assert.equal(c.runId,'manual-new');count++;
 c=setup({quote:manual,runId:'manual-new'});await c.syncAutomaticCycle();assert.equal(c.quote,manual);assert.equal(c.shown.length,0);count++;
 c=setup({monitor:{latest_attempt:{run_id:'auto-old'},latest_collection:{run_id:'auto-old',created_at:'2026-10-03T09:47:17Z'}}});await c.syncAutomaticCycle();assert.equal(c.quote.result.rows[0].target_page_usd,'13.45');assert(c.states[0][0].includes('跳过改价'));count++;
 const newer={...old,job_id:'auto-new',created_at:'2026-10-03T10:49:00Z',status:'running',quote:null};c=setup({job:newer,quote:manual,runId:'manual-new'});c.automation.schedule.last_job_id='auto-new';await c.syncAutomaticCycle();assert.equal(c.quote,null);assert(c.states[0][0].includes('auto-new'));count++;
 c=setup({manual:{...manual,automation_policy_revision:22}});await c.syncAutomaticCycle();assert.equal(c.quote,null);assert.equal(c.errors.length,1);count++;
 c=setup({manual:{...manual,run_id:'wrong-run'}});await c.syncAutomaticCycle();assert.equal(c.quote,null);assert.equal(c.errors.length,1);count++;
 c=setup({monitor:{latest_attempt:{run_id:'incomplete-newer'},latest_collection:{run_id:'manual-new',created_at:'2026-10-03T10:32:30Z'}}});await c.syncAutomaticCycle();assert.equal(c.quote,null);assert(!c.calls.includes('/quotes/auto-old'));count++;
 c=setup({onRead:async(path,c)=>{if(path==='/quotes/manual-new'){c.manualQuoteEpoch++;c.quote={...manual,run_id:'next-manual'};c.runId='next-manual'}}});await c.syncAutomaticCycle();assert.equal(c.runId,'next-manual');assert.equal(c.shown.length,0);count++;
 c=setup({onRead:async(path,c)=>{if(path==='/quotes/manual-new')c.automation.revision=24}});await c.syncAutomaticCycle();assert.equal(c.quote,null);assert.equal(c.shown.length,0);count++;
 c=setup({onRead:async(path,c)=>{if(path==='/jobs/auto-old'){c.manualQuoteEpoch++;c.quote=manual;c.runId='manual-new';throw Error('late-old-error')}}});await c.syncAutomaticCycle();assert.equal(c.runId,'manual-new');assert.equal(c.errors.length,0);count++;
 c=setup({manualJob:{...manualJob,status:'failed',quote:null,error:'storefront_incomplete'},quote:autoq,runId:'auto-old'});await c.syncAutomaticCycle();assert.equal(c.quote,null);assert(!c.calls.some(x=>x.startsWith('/quotes/')));assert.equal(c.errors[0][0],'采集与报价');assert.equal(c.errors[0][1].code,'storefront_incomplete');assert.equal(c.errors[0][1].jobId,'manual-new');assert.equal(c.errors[0][1].runId,'manual-new');assert.equal(c.errors[0][1].occurredAt,manualJob.completed_at);count++;
 c=setup({manualJob:{...manualJob,status:'running',quote:null},quote:autoq});await c.syncAutomaticCycle();assert.equal(c.quote,null);assert(!c.calls.some(x=>x.startsWith('/quotes/')));assert.equal(c.errors.length,0);assert(c.states[0][0].includes('仍在执行'));count++;
 c=setup({quote404:true});await c.syncAutomaticCycle();assert.equal(c.errors[0][1].code,'not_found');assert.equal(c.errors[0][1].runId,'manual-new');assert.equal(c.errors[0][2],'manual-new');assert.equal(c.quote,null);count++;
 c=setup({manualJob:{...manualJob,job_id:'wrong-id'}});await c.syncAutomaticCycle();assert.equal(c.errors[0][1].message,'job_identity_mismatch');assert(!c.calls.some(x=>x.startsWith('/quotes/')));count++;
 c=setup({onRead:async(path,c)=>{if(path==='/jobs/manual-new')c.manualQuoteEpoch++}});await c.syncAutomaticCycle();assert.equal(c.errors.length,0);assert(!c.calls.some(x=>x.startsWith('/quotes/')));count++;
 c=setup({manualJob:{...manualJob,quote:null},quote:autoq});await c.syncAutomaticCycle();assert.equal(c.errors[0][1].code,'quote_not_ready');assert(!c.calls.some(x=>x.startsWith('/quotes/')));count++;
 c=setup({job:{...old,status:'failed',quote:null,error_detail:'storefront_incomplete'},monitor:{latest_attempt:{run_id:'auto-old'},latest_collection:{run_id:'auto-old',created_at:old.created_at}}});await c.syncAutomaticCycle();assert.equal(c.errors[0][1].jobId,'auto-old');assert.equal(c.errors[0][1].code,'storefront_incomplete');assert(!c.calls.some(x=>x.startsWith('/quotes/')));count++;
 console.log(`${count} result/provenance/reload/ordering cases passed; background calls GET only`);
})().catch(e=>{console.error(e);process.exit(1)});

