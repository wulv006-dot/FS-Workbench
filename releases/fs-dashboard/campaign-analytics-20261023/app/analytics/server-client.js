(function(){
 if(!window.FC_ANALYTICS_CONFIG?.serverManaged)return;
 const foot=document.querySelector('.sidebar-foot'),footer=document.querySelector('footer'),brand=document.querySelector('.brand');
 if(foot)foot.textContent='FS 服务器 · PostHog × FS';if(footer)footer.textContent='服务器保存活动配置与商品草稿 · 结账沿用原站；付款统计以各活动接入状态为准';if(brand)brand.href='/dashboard/';
 const save=document.querySelector('#editor-form button[type=submit]');if(save)save.textContent='保存服务器配置';
 const cards=document.querySelectorAll('#integration .check-grid > div');
 if(cards.length){cards[0].querySelector('p').textContent='项目 682816 / US。管理员在连接页配置只读密钥，服务器保存，重启自动恢复。';cards[0].querySelector('.pill').textContent='连接配置';cards[2].querySelector('p').textContent='复用 FS 登录权限。活动配置保存在服务器，修改后立即用于查询筛选；数据查询使用短期缓存。';cards[2].querySelector('.pill').textContent='服务器接入';}
 let state,pending=null;
 async function read(){const r=await fetch('api/config',{credentials:'same-origin'}),v=await r.json();if(!r.ok)throw Error(v.message||'服务器配置读取失败');state=v;return v;}
 window.CampaignServer={read,get state(){return state;},async save(changes){
  if(!state?.canEdit)throw Error('当前账号仅可查看');
  const data={registry:state.registry,layout:state.layout,...changes},serialized=JSON.stringify(data);
  if(pending&&pending.serialized!==serialized)throw Error('上一次保存结果未确认，请重新加载核对后再修改');
  pending=pending||{serialized,operationId:crypto.randomUUID(),revision:state.revision};
  const r=await fetch('api/config',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({...data,revision:pending.revision,operationId:pending.operationId})});const v=await r.json();
  if(!r.ok){if(r.status===409||r.status===400)pending=null;throw Error(v.message||'保存失败');}
  state={...state,...v};pending=null;return state;
 }};
})();
