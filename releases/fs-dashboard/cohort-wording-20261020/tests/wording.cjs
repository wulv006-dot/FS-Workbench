const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const s=fs.readFileSync(__dirname+'/../source/data-workspace.js','utf8');
const start=s.indexOf('  function renderCohort('),end=s.indexOf('\n  const panels',start);assert(start>0&&end>start);
const ctx={Intl,el:(tag,text,cls)=>({tag,text,cls}),table:(headers,rows)=>({headers,rows}),facts(){}};vm.createContext(ctx);vm.runInContext(s.slice(start,end),ctx);
function render(d){const rows=[];ctx.renderCohort({append:x=>rows.push(x)},d);return rows;}
let rows=render({members:100,windows:[{days:7,mature_customers:60,immature_customers:40,repeat_customers:12,repeat_rate:.2}]});let t=rows.find(x=>x.headers);
assert.deepEqual(Array.from(t.headers),['观察窗','已满观察期新客','未满观察期新客','已关联组复购客户','已满观察期新客复购率']);assert.deepEqual(Array.from(t.rows[0]),['7 日',60,40,12,'20%']);
rows=render({members:4,windows:[{days:14,mature_customers:0,immature_customers:4,repeat_customers:0,repeat_rate:null}]});assert.equal(rows.find(x=>x.headers).rows[0][4],'尚未满观察期');
rows=render({members:0,windows:[{days:30,mature_customers:0,immature_customers:0,repeat_customers:0,repeat_rate:null}]});assert.equal(rows.find(x=>x.headers).rows[0][4],'暂无已满观察期新客');
assert(!s.includes('成熟客户'));assert(rows.some(x=>x.text?.includes('不计入对应复购率分母')));console.log('PASS wording, counts, percentage, immature and empty states');
