const windowNames={target:'所选期间',observed:'已完成自然日',previous:'此前等长期间',week_ago:'上周同日',baseline7:'此前完整 7 日日均',baseline30:'此前完整 30 日日均'};
const reasonNames={credentials:'登录资料线索',market_locked:'市场未解锁线索',account_restriction:'账户限制线索',cooldown:'冷却等待线索',supply:'供应不足线索',customer_wait:'等待客户线索',unclear:'未识别，需人工核查'};
const metricNames={orders:'支付订单',revenue_usd:'支付销售额',average_order_usd:'客单价',backlog_issues:'当前问题单',backlog_over72h:'当前等待超过 72 小时订单'};
const plus=v=>v===null||v===undefined?'暂缺':(v>0?'+':'')+format(v,'count');
function findingsView(decision){
 const findings=decision?.findings||[];
 return '<div class="decision-heading"><h2>负责人下一步</h2><span class="badge">'+(decision?.status==='succeeded'?'DeepSeek 证据分析':'规则建议 · 待核查')+'</span></div>'+
  findings.map(f=>'<article class="finding"><div class="decision-heading"><h3>'+esc(f.title)+'</h3><span class="badge">'+esc(f.priority)+'</span></div><p><b>证据解读：</b>'+esc(f.observation)+'</p><p class="muted"><b>待证原因：</b>'+esc(f.hypothesis)+'</p><div class="action-box"><p><b>建议行动：</b>'+esc(f.action)+'</p><p><b>采用条件：</b>'+esc(f.condition)+'</p><p><b>风险：</b>'+esc(f.risk)+'</p><p><b>复盘：</b>'+esc(metricNames[f.verify?.metric]||f.verify?.metric)+' · '+esc(f.verify?.window_days)+' 天后核查'+({increase:'是否改善',decrease:'是否减少',review:'变化及证据'}[f.verify?.direction]||'')+'</p></div><small>证据 '+esc((f.refs||[]).join(' · '))+'；建议尚未执行。</small></article>').join('')+
  (decision?.model_status?'<p class="alert">'+esc(aiStatus[decision.model_status]||decision.model_status)+' 已保留规则分析和全部事实。</p>':'')+
  (decision?.response_id?'<p class="foot">'+esc(decision.model)+' · '+esc(decision.tokens)+' tokens · '+esc(decision.response_id)+'</p>':'');
}
function deepView(report){
 const d=report.deep,target=d.windows.find(w=>w.key==='target'),facts=target?.main||{},period=d.plan;
 let h='<div class="hero"><div><h2>FC27 经营分析</h2><span class="muted">'+esc(period.start)+' 至 '+esc(period.end)+' · 北京时间</span></div><span class="badge">'+(period.in_progress?'进行中 · 仅完整日参与比较':'已完成自然日')+'</span></div>';
 h+='<p class="muted">MMOEXP 主站支付明细为分析主口径，卫星站独立汇总。与首页后台区间原值可能不同。</p><div class="stats">'+[
  ['支付订单',facts.orders,'count'],['支付销售额',facts.revenue_usd,'USD'],['客单价',facts.average_order_usd,'USD']
 ].map(([k,v,u])=>'<div class="stat"><small>'+esc(k)+'</small><strong>'+format(v,u)+'</strong></div>').join('')+'</div>';
 h+=findingsView(d.decision);
 h+='<h2>自动历史比较</h2><p class="muted">'+(period.in_progress?'含今天的目标期尚未结束；下表使用已完成自然日。':'使用同一份来源快照核对支付订单与金额。')+' 不将不同处理时长的订单当前状态当作履约趋势。</p><div class="table-wrap"><table><thead><tr><th>比较基线</th><th>基线区间</th><th>订单变化</th><th>销售变化 · USD</th><th>销售变化幅度</th><th>客单变化 · USD</th></tr></thead><tbody>';
 for(const c of d.comparisons){const w=d.windows.find(w=>w.key===c.baseline),v=c.values;h+='<tr><td>'+esc(windowNames[c.baseline])+'</td><td>'+esc(w?.start)+'<br>'+esc(w?.end)+'</td><td>'+plus(v.orders?.delta)+'</td><td>'+plus(v.revenue_usd?.delta)+'</td><td>'+(v.revenue_usd?.zero_baseline?'基线为零，不计算涨幅':format(v.revenue_usd?.pct,'%'))+'</td><td>'+plus(v.average_order_usd?.delta)+'</td></tr>';}
 h+='</tbody></table></div>'+(d.comparisons.length?'':'<p class="alert">尚无完整可比期间，不推断增长或下降。</p>');
 for(const dim of d.contributions){h+='<details><summary>'+esc({platform:'平台',product:'品类',bucket:'金额段'}[dim.dimension])+'：销售变化集中在哪里</summary><p class="muted">与此前等长期间作算术分解，不代表原因。金额均为美元支付销售额。</p><div class="table-wrap"><table><thead><tr><th>分组</th><th>本期销售</th><th>此前销售</th><th>订单变化</th><th>销售变化</th></tr></thead><tbody>'+dim.rows.map(r=>'<tr><td>'+esc(r.label||r.key)+'</td><td>'+format(r.current_revenue_usd,'USD')+'</td><td>'+format(r.previous_revenue_usd,'USD')+'</td><td>'+plus(r.orders_delta)+'</td><td>'+plus(r.revenue_delta_usd)+'</td></tr>').join('')+'</tbody></table></div></details>';}
 const b=d.backlog;
 h+='<h2 class="section-space">当前积压与问题单</h2><p class="muted">这是读取时的当前池，涵盖全部支付日期；不等于所选期间新增积压。</p>';
 if(b){h+='<div class="stats">'+[['当前主站未终结池',b.main.orders],['当前问题标记',b.main.issues],['支付后超过 72 小时',b.age_bands['72to168h']+b.age_bands.over168h]].map(([k,v])=>'<div class="stat"><small>'+k+'</small><strong>'+format(v,'count')+'</strong></div>').join('')+'</div><small>来源读取 '+esc(b.as_of)+' · 缺支付时间 '+esc(b.age_bands.unknown)+' 单</small>';}else h+='<p class="alert">当前池数据不完整，未估计总量。</p>';
 const dx=d.diagnostics;
 if(['available','partial'].includes(dx?.status)){
  h+='<h3 class="section-space">Order 日志抽样线索</h3><p>读取 '+esc(dx.pages)+' 页、'+esc(dx.listed)+' 个去重列表条目，完成 '+esc(dx.sampled)+' 个日志样本。</p><p class="muted">'+esc(dx.coverage)+'。关键词命中不证明当前根因；处理前需复核最新状态。</p><div class="chips">'+Object.entries(dx.categories||{}).filter(([,n])=>n>0).map(([k,n])=>'<span class="badge">'+esc(reasonNames[k]||k)+' '+esc(n)+'</span>').join('')+'</div><details><summary>打开样本证据，人工复核最新记录</summary><ul>';
  for(const s of dx.samples||[]){const valid=/^https:\/\/order\.p2pah\.cn\/order\/admin_order\/look\/id\/\d{1,12}\.html$/.test(s.review_url||'');h+='<li>'+(valid?'<a target="_blank" rel="noopener noreferrer" href="'+esc(s.review_url)+'">'+esc(s.ref)+'</a>':esc(s.ref))+' · '+esc(s.platform)+' · '+esc(reasonNames[s.category]||s.category)+' · '+esc(s.last_matching_log_at||'未识别')+'</li>';}
  h+='</ul><small>只展示分类与时间，未保存或发送原始日志、账户、联系方式。</small></details>';
 }else h+='<p class="alert">'+(dx?.status==='not_run'?(d.investigations?.some(x=>x.kind==='order_problem_sample')?'问题单抽查尚未完成。':'当前事实未触发问题单进一步抽查。'):(dx?.reason==='collector_busy'?'其他数据查询正在运行，本次问题单证据暂缺。':dx?.reason==='reader_timeout'?'问题单读取超时，本次不判断具体原因。':'问题单后台暂未返回可核验数据，本次不判断具体原因。'))+'</p>';
 h+='<details><summary>卫星站与历史记忆</summary><p>本期卫星汇总：'+format(target?.satellite?.orders,'count')+' 单 / '+format(target?.satellite?.revenue_usd,'USD')+'。</p><p>本次采用 '+esc(d.memory?.contexts?.length||0)+' 条有效经营背景、'+esc(d.memory?.observations?.length||0)+' 份同口径历史观察。</p><p class="muted">经营背景来自本人明确输入；旧建议未经执行确认，不把后续变化认定为建议效果。</p>';
 for(const r of d.review||[])h+='<p>'+esc(metricNames[r.metric])+'：此前 '+format(r.previous,'count')+' → 当前 '+format(r.current,'count')+' · '+(r.review_due?'到了复盘窗口':'尚未到复盘窗口')+'<br><small>'+esc(r.conclusion)+'</small></p>';
 h+='</details><details><summary>证据来源、数据缺口与查询记录</summary><ul>'+d.gaps.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul><p>来源快照 '+esc(d.snapshot_id)+'</p><ul>'+d.trace.map(t=>'<li>'+esc(t.tool)+' · '+esc(t.status)+' · '+esc(t.start||'')+' '+esc(t.end||'')+' · '+esc(t.captured_at||'')+'</li>').join('')+'</ul><p>可引用证据：'+d.evidence.map(e=>'<code>'+esc(e.ref)+'</code>').join(' · ')+'</p></details><p class="foot">生成 '+esc(report.generated_at)+' · 报告 '+esc(report.report_id)+' · '+(report.fromDaily?'FC 共享自动日报 · 按现有权限读取':'仅本人可见')+'</p>';
 return h;
}
async function loadMemory(){if(!config?.capabilities?.operations_memory)return;try{const d=await api('?memory=true');$('memory-list').innerHTML=d.contexts.map(m=>'<li><p>'+esc(m.text)+'</p><small>'+esc(m.effective_start)+' → '+esc(m.effective_end||'持续生效')+' · 本人输入，未经源数据核验</small><br><button type="button" data-revoke="'+esc(m.id)+'">撤销此条</button></li>').join('')||'<li class="muted">暂无经营背景。系统会自动保存可核验的报告观察。</li>';}catch(e){if(identity)$('memory-feedback').textContent=e.message;}}
$('memory-form').onsubmit=async e=>{e.preventDefault();if(!config?.can_generate)return;const button=$('memory-save');button.disabled=true;try{await api('',{kind:'memory_add',memory:{request_id:crypto.randomUUID(),project:'FC27',kind:$('memory-kind').value,text:$('memory-text').value,effective_start:$('memory-start').value,effective_end:$('memory-end').value||null}});$('memory-text').value='';$('memory-feedback').textContent='已保存。后续报告按生效期引用，标记为本人输入。';await loadMemory();}catch(e){if(identity)$('memory-feedback').textContent=e.message;}finally{button.disabled=!config?.can_generate;}};
$('memory-list').onclick=async e=>{const b=e.target.closest('[data-revoke]');if(!b)return;b.disabled=true;try{await api('',{kind:'memory_revoke',id:b.dataset.revoke});await loadMemory();}catch(e){if(identity)$('memory-feedback').textContent=e.message;}};
$('memory-forget').onclick=async()=>{if(!config?.can_generate)return;try{await api('',{kind:'memory_forget_observations'});$('memory-feedback').textContent='已清除本人分析记忆中的历史观察；原报告历史仍保留。';}catch(e){if(identity)$('memory-feedback').textContent=e.message;}};
$('daily-read').onclick=async()=>{
 if(activeJob||!identity)return;
 const day=$('daily-date').value;if(!/^\d{4}-\d{2}-\d{2}$/.test(day)){banner('请选择完整自然日。','alert error');return;}
 const button=$('daily-read');button.disabled=true;const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
 try{
  const response=await fetch('/dashboard/fs-home/range.json?mode=fc-daily&date='+encodeURIComponent(day),{credentials:'same-origin',cache:'no-store',signal:controller.signal});
  if(response.status===401||response.redirected){halt('登录已失效，请重新登录后读取日报。');return;}
  if(!response.ok||!response.headers.get('Content-Type')?.includes('application/json'))throw Error('日报暂不可读取，请稍后再试。');
  const value=await response.json();if(!identity)return;
  if(!value.report){banner('这一天还没有已保存的日报。','alert');return;}
  if(!value.report.deep){banner('这一天保留的是旧版简报，可进入 FC 自动日报查看；新生成的日报支持完整深度分析。','alert');return;}
  currentReport=null;$('chat-card').classList.add('hidden');$('conversation').innerHTML='';
  $('report').innerHTML=deepView({...value.report,fromDaily:true});$('progress').textContent='已读取保存的自动日报 · 未另调用模型';banner('');
 }catch(e){if(identity)banner(e.name==='AbortError'?'读取超时，已保存的日报不受影响。':e.message,'alert error');}
 finally{clearTimeout(timer);button.disabled=false;}
};
