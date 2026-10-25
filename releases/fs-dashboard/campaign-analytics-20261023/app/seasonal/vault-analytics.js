/* Adapt the seasonal interface to the existing FS activity_* bridge. No network or identity code here. */
(() => {
  const root=document.querySelector('#fc-activity');
  if(!root)return;
  let view='';
  const rows=[];window.addEventListener('fcactivity:analytics-debug',e=>{rows.push(e.detail);if(rows.length>200)rows.shift();});
  const emit=(name,detail)=>root.dispatchEvent(new CustomEvent('fcactivity:'+name,{detail}));
  window.SeasonalTracking={
    render(theme){if(theme!==view){view=theme;emit('view',{view,platform:'unknown',language:'en'});}else emit('render',{view,platform:'unknown',language:'en'});},
    selection(action,ids=[]){emit('selection',{action,ids,includeSbc:false});},
    review(ids=[]){emit('review',{ids,includeSbc:false});},
    context(){return window.FCActivityAnalytics?.context()||null;}
  };
  document.querySelector('#analytics-diagnostics').addEventListener('click',()=>{
    const dialog=document.querySelector('#event-dialog');document.querySelector('#dialog-title').textContent='Tracking diagnostics';
    const state=window.FCActivityAnalytics.status(),counts={};for(const row of rows)counts[row.event]=(counts[row.event]||0)+1;
    document.querySelector('#dialog-content').innerHTML='<p>This preview uses the activity_* tracking protocol. Local debug records do not confirm real registration, cart or payment events.</p><p>Transmission: <strong>'+(state.transmitting?'enabled':'disabled')+'</strong> · Events on this page: '+rows.length+'</p><pre id="analytics-counts"></pre><p>Recent activity</p><pre id="analytics-recent"></pre>';
    document.querySelector('#analytics-counts').textContent=JSON.stringify(counts,null,2);
    document.querySelector('#analytics-recent').textContent=rows.slice(-12).map(r=>r.event+' | '+r.properties.activity_id+' | '+(r.properties.action||r.properties.product_id||'')).join('\n');
    if(!dialog.open)dialog.showModal();
  });
  // Fixed action labels, never button text, invite code, form values or customer data.
  const actions=new Set(['reveal-all','pool','refresh','confirm-refresh','invite','invite-status','copy-invite','account','cart','save-pool']);
  document.addEventListener('click',e=>{
    const b=e.target.closest('button');if(!b||b.disabled||b.dataset.demoReceipt)return;
    const action=b.dataset.reveal?'reveal-card':b.dataset.keep?'keep-card':b.dataset.product?'view-pack':b.dataset.bagAdd?'preview-bag-add':actions.has(b.dataset.action)?b.dataset.action:b.dataset.storeFilter?'fixed-game-filter':b.dataset.filter?'mystery-game-filter':null;
    if(action)window.SeasonalTracking.selection(action,[]);
  });
})();
