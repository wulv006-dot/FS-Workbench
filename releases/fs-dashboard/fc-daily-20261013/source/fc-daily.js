// Runs in the existing FC mount; no new route, identity, or frontend model secret.
let dailyDate='',dailyData=null,dailyError='',dailyAbort=null,dailyTimer=null,dailyRequest='';
const dailyStateNames={pending:'等待生成',running:'生成中',completed:'已完成',degraded:'已生成事实报告 · AI 或部分数据待补',failed:'生成失败，保留上一版'};
const dailyAINames={configuration_missing:'服务端模型配置未就绪',configuration_invalid:'服务端模型配置无效',succeeded:'DeepSeek 解读已生成',skipped_incomplete_data:'数据不全，未调用模型',unknown_transport:'模型请求结果不确定，未自动重试',unknown_previous_attempt:'前次模型请求结果不确定，未重复调用',unknown_model_error:'模型结果不确定',http_rejected:'模型服务拒绝请求',invalid_response:'模型回复未通过校验',daily_model_limit:'已达当日模型调用上限'};
const dailyErrorNames={source_timeout:'读取源数据超时',source_unavailable:'源数据暂不可用',paid_data_incomplete:'支付日数据不完整',source_snapshot_changed:'生成时数据版本变化，请稍后重试',source_period_mismatch:'源数据统计区间不匹配',process_interrupted:'服务重启中断了本次生成',report_generation_failed:'报告生成失败',another_report_running:'另一份日报正在生成',generation_limit:'生成频率或当日次数已达上限',admin_required:'只有管理员可以重生成',same_origin_required:'请求来源校验未通过',complete_day_required:'请选择过去一年内的完整自然日'};

function dailyHost(){return fcHost?.querySelector('#fc-daily-report');}
function dailyMount(){
 const review=fcHost?.querySelector('#fc-panel-review');if(!review||dailyHost())return;
 const host=document.createElement('article');host.id='fc-daily-report';host.className='fc-card';review.prepend(host);
 host.addEventListener('change',e=>{if(e.target.matches('[data-daily-date],[data-daily-history]')){dailyDate=e.target.value;dailyData=null;dailyLoad();}if(e.target.matches('[data-daily-version]'))dailyLoad(false,e.target.value);});
 host.addEventListener('click',e=>{if(e.target.closest('[data-daily-refresh]'))dailyLoad();if(e.target.closest('[data-daily-run]'))dailyLoad(true);});
 if(!dailyDate)dailyDate=new Date(Date.now()+8*3600000-86400000).toISOString().slice(0,10);
 dailyRender();if(!dailyData&&!dailyAbort)dailyLoad();
}
function dailyRender(){
 const host=dailyHost();if(!host)return;const data=dailyData,r=data?.report,a=data?.last_attempt;
 const row=(label,f)=>`<tr><td>${esc(label)}</td><td>${f?.orders??'—'}</td><td>${fcMoney(f?.revenue_usd)}</td><td>${f?.issues??'—'}</td></tr>`;
 host.innerHTML=`<h3>自动经营日报</h3><p>每天北京时间 09:15 生成前一日，主站详细分析与卫星子站合计。历史版本保存；管理员可重生成。</p><div class="fc-actions"><label>日报日期 <input data-daily-date type="date" value="${esc(dailyDate)}" max="${new Date(Date.now()+8*3600000-86400000).toISOString().slice(0,10)}"></label><label>历史日报 <select data-daily-history><option value="${esc(dailyDate)}">选择日期</option>${(data?.history||[]).map(v=>`<option value="${v.day}" ${v.day===dailyDate?'selected':''}>${v.day}</option>`).join('')}</select></label><button type="button" data-daily-refresh>查看状态</button>${data?.can_generate?`<button type="button" data-daily-run ${['pending','running'].includes(a?.state)?'disabled':''}>${r?'重新生成':'生成日报'}</button>`:''}</div><p role="status">${esc(dailyError||(a?dailyStateNames[a.state]||a.state:'尚未生成，可由管理员生成历史日报'))}${a?.error?'：'+esc(dailyErrorNames[a.error]||'生成暂不可用'):''}</p>${data?`<p>下一次定时：${esc(data.schedule.next_run.replace('T',' '))}。${esc(data.schedule.retry)}</p>`:''}${r?`<label>已保存版本 <select data-daily-version>${data.versions.map(v=>`<option value="${v.revision}" ${v.revision===r.revision?'selected':''}>版本 ${v.revision}</option>`).join('')}</select></label><h4>${esc(r.date)} · FC27 经营日报</h4><p>统计：${esc(r.period.start)} 至 ${esc(r.period.end)}（右边界不含，北京时间）<br>数据读取：${esc(r.data_as_of)}；报告生成：${esc(r.generated_at)}<br>来源：${esc(r.source)} · 快照 ${esc(r.snapshot_id)}</p>${fcTable(['范围','订单数','USD 销售额','当前问题标记'],[row('MMOEXP 主站',r.main),row('卫星子站合计',r.satellite),row('总计',r.totals)])}<p>主站客单价：${fcMoney(r.analysis.average_order_usd)}；问题标记占比：${r.analysis.issue_share_pct===null?'暂缺':r.analysis.issue_share_pct+'%'}。${r.comparison?'与前一日日报相比，销售额变化 '+fcMoney(r.comparison.revenue_delta)+'，订单变化 '+r.comparison.orders_delta+'。':'同口径环比暂缺。'}</p>${Object.entries(r.dimensions).map(([key,rows])=>`<h4>主站${key==='platform'?'平台':'产品'}结构</h4>${fcTable(['类别','订单数','USD 销售额','问题标记'],rows.map(v=>row(v.key,v)))}`).join('')}<h4>DeepSeek 解读</h4><p>${esc(dailyAINames[r.ai.status]||'模型暂不可用')}。${r.ai.status==='succeeded'?esc(r.ai.explanation)+'<br>建议：'+esc(r.ai.next_step)+'<br>依据：'+esc(r.ai.evidence_ref):'本页保留已核算的事实，不生成无依据结论。'}</p><h4>当前履约池</h4><p>${r.backlog?'读取时未结案 '+r.backlog.orders+' 单，涉及 '+fcMoney(r.backlog.revenue_usd)+'；不按日报支付日期截断。':'当前履约池数据不完整，暂不汇总。'}</p><details open><summary>数据范围与待核查事项</summary><ul>${r.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></details><p>报告编号 ${esc(r.report_id)}；本页只读分析，不执行调价或订单操作。</p>`:''}`;
}
async function dailyLoad(run=false,revision=''){
 dailyAbort?.abort();clearTimeout(dailyTimer);const controller=new AbortController();dailyAbort=controller;dailyError='';
 const query={mode:'fc-daily',date:dailyDate};if(revision)query.revision=revision;
 if(run){dailyRequest=crypto.randomUUID();query.action='run';query.request_id=dailyRequest;}
 try{const response=await fetch('/dashboard/fs-home/range.json?'+new URLSearchParams(query),{signal:controller.signal,credentials:'same-origin',cache:'no-store',headers:run?{'X-FS-Report-Action':'generate'}:{}});const data=await response.json();if(!response.ok)throw Error(dailyErrorNames[data.error]||`日报暂不可用（${response.status}）`);if(data.contractId!=='fc-daily-v1'||data.date!==dailyDate)throw Error('日报返回区间不一致');dailyData=data;dailyRender();if(['pending','running'].includes(data.last_attempt?.state))dailyTimer=setTimeout(()=>dailyLoad(),5000);
 }catch(error){if(error.name!=='AbortError'){dailyError=error.message;dailyRender();}}
 finally{if(dailyAbort===controller)dailyAbort=null;}
}
scope.signal.addEventListener('abort',()=>{dailyAbort?.abort();clearTimeout(dailyTimer);},{once:true});
