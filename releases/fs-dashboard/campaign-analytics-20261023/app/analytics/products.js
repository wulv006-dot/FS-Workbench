(function(){
  'use strict';
  const $=id=>document.getElementById(id),escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const publicPrefix=document.documentElement.dataset.campaignPublicPrefix||'/events/',publicPrefixValid=/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(publicPrefix);
  const storageKey='fs-center-pending:'+location.pathname.replace(/products\.html$/, 'center.html');
  let savedDraft=null,state=null,catalog=[],busy=false,dirty=false,pending=null,discovered=[],discoveredGame=null,selectedPage='fc27-weekly',searchPage=1,hasMore=false,inspected=null;
  try{pending=JSON.parse(sessionStorage.getItem(storageKey)||'null');}catch{$('center-error').textContent='无法读取原操作记录；请保留当前会话并联系维护人员核对。';return;}
  const stable=v=>JSON.stringify(v,(_k,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,x[k]])):x);
  const same=(a,b)=>stable(a)===stable(b);
  function acceptedState(value){state=value;savedDraft=structuredClone(value.draft);dirty=false;if($('restore-review'))$('restore-review').hidden=true;}
  function persist(value){sessionStorage.setItem(storageKey,JSON.stringify(value));pending=value;}
  async function request(path,body){const response=await fetch(path,{credentials:'same-origin',cache:'no-store',...(body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify(body)}:{})});let data;try{data=await response.json();}catch{throw Object.assign(Error('响应无法确认，请核对原操作。'),{status:response.status});}if(!response.ok)throw Object.assign(Error(data.message||data.code||'请求失败'),{status:response.status});return data;}
  function lock(){ dirty=Boolean(state&&savedDraft&&!same(state.draft,savedDraft));renderChanges();$('restore-draft').disabled=busy||Boolean(pending)||!state?.canEdit||dirty||!state?.restore_candidate;$('confirm-restore').disabled=$('restore-draft').disabled; $('center-fields').disabled=busy||!state?.canEdit||Boolean(pending);$('read-benefits').disabled=busy||!state?.canEdit||Boolean(pending);$('publish-center').disabled=dirty;$('read-published').disabled=busy||!state?.published||Boolean(pending);$('discovery-fields').disabled=busy||!state?.canEdit||Boolean(pending);$('discover-search').disabled=busy;$('discover-product').disabled=!discoveredGame;$('inspect-product').disabled=busy||!discoveredGame||!$('discover-product').value;$('add-product').disabled=busy||!inspected||!state?.canEdit||Boolean(pending);$('discovery-prev').disabled=busy||searchPage<=1;$('discovery-next').disabled=busy||!hasMore; }
  function local(value){return value?new Date(value).toISOString().slice(0,16):'';}
  function benefitLabel(ref){const item=catalog.find(x=>x.kind===ref.kind&&x.native_id===ref.native_id);return (ref.kind==='coupon'?'优惠券':'折扣')+' · '+(item?.title||ref.native_id)+(item?' · 原始状态 '+String(item.raw_status??'未知'):' · 尚未核验');}
  function bindings(page,i){return '<ul class="bindings">'+(page.benefit_refs||[]).map((ref,j)=>'<li><span>'+escape(benefitLabel(ref))+'</span><button class="fs-btn" type="button" data-remove="'+i+':'+j+'">移除绑定</button></li>').join('')+'</ul><label for="benefit-'+i+'">选择后台优惠<select id="benefit-'+i+'" data-benefit="'+i+'"><option value="">请选择原生优惠</option>'+catalog.map((ref,j)=>'<option value="'+j+'">'+escape(benefitLabel(ref))+'</option>').join('')+'</select></label><button class="fs-btn" type="button" data-add="'+i+'">添加绑定</button>';}
  const imageChoices={
    'fc27-weekly':['assets/weekly-hero.webp','assets/weekly-hero-mobile.webp'],
    'fc27-sbc':['assets/reward-hero.webp','assets/reward-hero-mobile.webp'],
    'fc27-trio':['assets/scream-hero.webp','assets/scream-hero-mobile.webp'],
    'seasonal-vault':['halloween','thanksgiving','christmas','black-friday'].map(theme=>'seasonal/assets/hero-'+theme+'.webp')
  };
  function presentationControls(page,i){
    const seasonal=page.page_id==='seasonal-vault',language=page.default_language||'original',image=page.social_image||'original';
    return '<div class="config-grid"><label for="language-'+i+'">首次打开语言<select id="language-'+i+'" name="default_language" required>'+[['original','保留原页面默认'],['en','English'],...(!seasonal?[['zh','中文']]:[])].map(([value,label])=>'<option value="'+value+'" '+(value===language?'selected':'')+'>'+label+'</option>').join('')+'</select></label><label for="share-image-'+i+'">社交分享图（已接受素材）<select id="share-image-'+i+'" name="social_image" required>'+['original',...(imageChoices[page.page_id]||[])].map(value=>'<option value="'+value+'" '+(value===image?'selected':'')+'>'+escape(value==='original'?'保留原分享图':value)+'</option>').join('')+'</select></label></div><p class="muted">原主视觉来源：'+escape(seasonal?'已有四套主题 hero，随限定活动主题消费':(imageChoices[page.page_id]||[]).join(' / '))+'。不支持上传、任意 URL 或跨页替换。</p>';
  }
  function publicationSummary(){
    const p=state.published;$('published-readback').textContent='尚未核对当前发布版本的公开运行时；保存记录不等于部署或真实交易启用。';
    if(!p){$('published-summary').textContent='尚无已发布版本；草稿不会进入公开运行时。';return;}
    const rows=[['发布 ID',p.release_id],['配置哈希',p.config_hash],['规则哈希',p.rule_hash],['源码版本',p.source_revision||'旧记录未保存'],['发布时间',p.published_at],['限定活动素材主题',p.seasonal_theme||'旧记录未保存'],['模式','preview · 主站交易未开放']];
    $('published-summary').innerHTML='<dl>'+rows.map(([label,value])=>'<div><dt>'+escape(label)+'</dt><dd style="overflow-wrap:anywhere">'+escape(value)+'</dd></div>').join('')+'</dl>'+(Array.isArray(p.pages)?'<ul>'+p.pages.map(page=>'<li>'+escape(page.title+' · '+page.path+' · '+(page.preview_enabled?'允许预览':'预览关闭')+' · 默认语言 '+(page.default_language||'original')+' · 分享图 '+(page.social_image||'original')+' · UTC '+(page.starts_at||'不限')+' — '+(page.ends_at||'不限'))+(publicPrefixValid&&['Weekly-Scout.html','Sbc-Companions.html','Player-Trio.html','seasonal/index.html'].includes(page.path)?' <a href="'+escape(publicPrefix+page.path)+'" target="_blank" rel="noopener">打开发布预览</a>':'')+'</li>').join('')+'</ul>':'<p>旧发布记录未保存页面摘要，请保存并发布后核对。</p>');
  }
  function render(){
    $('draft-state').textContent='修订 '+state.revision;$('publish-state').textContent=state.published?'已有预览发布':'尚未发布';
    $('page-select').innerHTML=state.draft.pages.map(p=>'<option value="'+escape(p.page_id)+'" '+(p.page_id===selectedPage?'selected':'')+'>'+escape(p.title||p.page_id)+'</option>').join('');
    $('seasonal-theme-label').hidden=selectedPage!=='seasonal-vault';
    $('page-guidance').textContent=selectedPage==='seasonal-vault'?'限定活动：独立主题、跨游戏商品池；演示抽奖/邀请规则保持原稿，真实奖励未启用。':'FC 页面：保留原球员、SBC搭档、三人组与捆绑包编排；新增未适配商品仅展示资料，不自动变成可买卡或组合。';
    $('center-pages').innerHTML=state.draft.pages.map((p,i)=>'<fieldset '+(p.page_id===selectedPage?'':'hidden ')+'data-page="'+i+'"><legend>'+escape(p.title||p.page_id)+'</legend><p class="muted">'+escape(p.activity_id+' / '+p.page_id+' · '+p.path)+'</p><div class="config-grid"><label for="title-'+i+'">页面标题<input id="title-'+i+'" name="title" required maxlength="160" value="'+escape(p.title)+'"></label><label class="check"><input name="preview_enabled" type="checkbox" '+(p.preview_enabled?'checked':'')+'>允许预览</label><label for="start-'+i+'">开始时间 (UTC)<input id="start-'+i+'" name="starts_at" type="datetime-local" value="'+local(p.starts_at)+'" aria-errormessage="date-error-'+i+'"><span class="error-msg" id="date-error-'+i+'">结束时间必须晚于开始时间。</span></label><label for="end-'+i+'">结束时间 (UTC)<input id="end-'+i+'" name="ends_at" type="datetime-local" value="'+local(p.ends_at)+'" aria-errormessage="end-error-'+i+'"><span class="error-msg" id="end-error-'+i+'">结束时间必须晚于开始时间。</span></label></div><label for="description-'+i+'">SEO 描述<textarea id="description-'+i+'" name="description" maxlength="320">'+escape(p.description)+'</textarea></label>'+presentationControls(p,i)+'<div data-bindings="'+i+'">'+bindings(p,i)+'</div></fieldset>').join('');
    const theme=$('seasonal-theme'),value=state.draft.seasonal_theme||'halloween';
    if(typeof value==='string'){if(![...theme.options].some(o=>o.value===value))theme.add(new Option(value,value));theme.value=value;}else theme.disabled=true;
    renderPageProducts();renderFcLayout();publicationSummary();lock();
  }
  function readForm(){
    const draft=structuredClone(state.draft);
    if($('seasonal-theme').value!==(draft.seasonal_theme??'halloween'))draft.seasonal_theme=$('seasonal-theme').value;
    for(const fieldset of document.querySelectorAll('[data-page]')){
      const p=draft.pages[Number(fieldset.dataset.page)],get=name=>fieldset.querySelector('[name="'+name+'"]');
      const assign=(key,value,shown)=>{if(value!==shown)p[key]=value;};
      for(const key of ['title','description']){
        const value=get(key).value;assign(key,value,p[key]??'');
        get(key).setCustomValidity(/[<>\u0000-\u001f]/.test(value)?'不能含尖括号或控制字符。':'');
      }
      for(const key of ['default_language','social_image'])assign(key,get(key).value,p[key]??'original');
      assign('preview_enabled',get('preview_enabled').checked,p.preview_enabled===true);
      for(const key of ['starts_at','ends_at'])if(get(key).value!==local(p[key]))p[key]=get(key).value?new Date(get(key).value+'Z').toISOString():null;
      get('ends_at').setCustomValidity(p.starts_at&&p.ends_at&&Date.parse(p.starts_at)>=Date.parse(p.ends_at)?'结束时间必须晚于开始时间。':'');
    }
    return draft;
  }
  const fieldNames={product_keys:'商品选择与顺序',product_roles:'商品展示位置',sbc_companions:'SBC搭档',fc_layout:'FC编排',title:'标题',description:'说明',preview_enabled:'预览开关',starts_at:'开始时间',ends_at:'结束时间',default_language:'默认语言',social_image:'分享图',benefit_refs:'优惠绑定',seasonal_theme:'限定活动主题'};
  function renderChanges(){
    if(!$('draft-changes')||!state||!savedDraft)return;
    const rows=[],compare=(before,after,label)=>{
      for(const key of new Set([...Object.keys(before),...Object.keys(after)])){
        if(key==='pages'||same(before[key],after[key]))continue;
        const inherited=['product_keys','fc_layout'].includes(key);
        rows.push(label+(fieldNames[key]||key)+(inherited&&!Object.hasOwn(before,key)?'：从继承改为明确配置':inherited&&!Object.hasOwn(after,key)?'：恢复继承':'：已修改'));
      }
    };
    compare(savedDraft,state.draft,'');
    for(const page of state.draft.pages)compare(savedDraft.pages.find(p=>p.page_id===page.page_id)||{},page,(page.title||page.page_id)+' · ');
    $('draft-changes').innerHTML=rows.length?'<strong>本次保存变化（尚未保存）</strong><ul>'+rows.map(x=>'<li>'+escape(x)+'</li>').join('')+'</ul><p>未修改字段保持原有缺省与继承；保存不会发布。</p>':'未修改配置；切换页面不会固定继承数据。';
  }
  async function load(){busy=true;lock();state=null;try{acceptedState(await request('api/center'));render();if(pending){$('center-status').textContent='已重读服务器状态，正在用原操作 ID 核对结果。';await resolve();}else $('center-status').textContent=state.canEdit?'已读取服务器配置。':'当前账号为只读。';}catch(error){$('center-error').textContent=error.message;}finally{busy=false;lock();}}
  async function resolve(){const receipt=await request(pending.path,pending.body);const refreshed=await request('api/center');persist(null);acceptedState(refreshed);render();$('center-status').textContent='原操作已确认，已重新读取服务器状态。';return receipt;}
  async function mutate(path,draft,extra={}){if(busy||pending||!state?.canEdit)return;busy=true;lock();$('center-error').textContent='';try{persist({path,body:{revision:state.revision,operation_id:crypto.randomUUID(),...(draft?{draft}:{}),...extra}});await resolve();$('center-status').textContent=path.endsWith('/publish')?'预览配置已发布；主站交易仍待接入。':path.endsWith('/restore')?'已恢复上一份草稿的原始字段与继承；未改变公开预览。':'草稿已保存；尚未发布预览。';}catch(error){if([400,403,409,422].includes(error.status)){persist(null);state=null;acceptedState(await request('api/center'));render();}$('center-error').textContent=error.message+(pending?' 原操作记录已保留；请点击重新读取核对，勿新建操作。':' 已重新读取服务器状态，请核对后修改。');}finally{busy=false;lock();}}
  $('center-form').addEventListener('submit',event=>{event.preventDefault();const draft=readForm();if(!$('center-form').reportValidity())return;if(same(draft,savedDraft)){$('center-status').textContent='没有配置变化，未提交保存。';return;}mutate('api/center',draft);});
  $('restore-draft').addEventListener('click',()=>{
    const candidate=state?.restore_candidate;if(!candidate||dirty||busy||pending)return;
    $('restore-summary').textContent='恢复到修订 '+candidate.revision+' 的原始草稿字段（包含缺省继承）。涉及页面：'+(candidate.changed_pages||[]).join('、')+'；配置：'+(candidate.changed_fields||[]).map(k=>fieldNames[k]||k).join('、')+'。仅恢复草稿，保留全部历史，不回退公开发布。';
    $('restore-review').hidden=false;
  });
  $('cancel-restore').addEventListener('click',()=>{$('restore-review').hidden=true;});
  $('confirm-restore').addEventListener('click',()=>{if(!state?.restore_candidate||dirty)return;mutate('api/center/restore',null,{restore_revision:state.restore_candidate.revision});});
  $('publish-center').addEventListener('click',()=>mutate('api/center/publish'));
  $('reload-center').addEventListener('click',()=>{if(!busy)load();});
  for(const type of ['input','change'])$('center-form').addEventListener(type,event=>{if(event.target.id==='page-select'||event.target.closest('#page-products')||event.target.closest('#fc-layout'))return;state.draft=readForm();lock();});
  $('center-pages').addEventListener('click',event=>{const add=event.target.closest('[data-add]'),remove=event.target.closest('[data-remove]');if(!add&&!remove)return;state.draft=readForm();if(add){const i=Number(add.dataset.add),select=$('benefit-'+i);if(!select.value){select.setCustomValidity('请选择后台目录中的原生优惠。');select.reportValidity();select.setCustomValidity('');return;}const ref=catalog[Number(select.value)],refs=state.draft.pages[i].benefit_refs||=[];if(!refs.some(x=>x.kind===ref.kind&&x.native_id===ref.native_id))refs.push({kind:ref.kind,native_id:ref.native_id});}else{const [i,j]=remove.dataset.remove.split(':').map(Number);state.draft.pages[i].benefit_refs.splice(j,1);}dirty=true;render();});
  $('read-benefits').addEventListener('click',async()=>{if(busy)return;busy=true;lock();try{state.draft=readForm();const result=await request('api/center/backend-read',{action:'benefits_read',site_id:'266'});catalog=[...(result.data?.coupons||[]),...(result.data?.discounts||[])];$('backend-state').textContent='已读 '+catalog.length+' 项';$('catalog-status').textContent='站点 266 原始目录已读；状态语义、适用范围及有效期仍须核验，不代表优惠可用。';render();}catch(error){$('catalog-status').textContent=error.message;}finally{busy=false;lock();}});
  $('read-published').addEventListener('click',async()=>{
    if(busy||!state?.published)return;busy=true;lock();
    try{
      if(!publicPrefixValid)throw Error('公开预览路径尚未核验。');
      const response=await fetch(publicPrefix+'api/campaign/config',{credentials:'same-origin',cache:'no-store'}),published=await response.json();
      if(!response.ok)throw Error('公开运行时尚未成功回读。');
      if(published.release_id!==state.published.release_id||published.config_hash!==state.published.config_hash||published.rule_hash!==state.published.rule_hash)throw Error('公开运行时版本与已发布记录不匹配，仍待部署或核对。');
      $('published-readback').textContent='已回读运行时 '+published.release_id+'，配置与规则哈希吻合。这里只确认发布配置，主站交易仍未开放。';
    }catch(error){$('published-readback').textContent=error.message+' 保存记录不代表运行时已生效。';}finally{busy=false;lock();}
  });
  function pageKeys(page){return page.product_keys??state.page_product_keys?.[page.page_id]??[];}
  const roleOptions={'fc27-weekly':['preview','player'],'fc27-trio':['preview','player','bundle'],'fc27-sbc':['preview','core','companion'],'seasonal-vault':['preview','pool','fixed','both']};
  const roleLabels={preview:'资料预览 / 未分配',player:'球员展示',bundle:'固定组合展示',core:'SBC 核心展示',companion:'搭档展示',pool:'随机池',fixed:'固定区',both:'随机池及固定区'};
  function renderPageProducts(){
    const page=state.draft.pages.find(p=>p.page_id===selectedPage),items=[...(state.catalog_products||[]),...(state.draft.imported_products||[])];
    const allowed=items.filter(p=>p.preview_only||selectedPage==='seasonal-vault'&&p.key.startsWith('seasonal-')||selectedPage==='fc27-weekly'&&p.display_kind==='player'||selectedPage==='fc27-trio'&&['player','bundle'].includes(p.display_kind)||selectedPage==='fc27-sbc'&&['player','sbc'].includes(p.display_kind)).filter(p=>!pageKeys(page).includes(p.key)&&(!selectedPage.startsWith('fc27-')||p.product_ref?.game_id==='1327'));
    $('page-products').innerHTML='<label>重新选入已核原稿或已导入商品<select id="existing-product"><option value="">请选择</option>'+allowed.map(p=>'<option value="'+escape(p.key)+'">'+escape(p.title||p.key)+' · '+escape(p.key)+'</option>').join('')+'</select></label><button type="button" class="fs-btn" id="add-existing-product">选入本页（尚未保存）</button>'+ '<ol>'+pageKeys(page).map((key,i)=>{const p=items.find(p=>p.key===key);return '<li>'+escape(p?.title||key)+' <small>'+escape(key)+(p?.preview_only?' · 资料预览 / 规格与价格待核':' · 原稿映射 / 购买保持关闭')+'</small> <label>本页展示位置<select data-role-key="'+escape(key)+'"><option value="">沿用原稿 / 新商品未分配</option>'+roleOptions[selectedPage].map(role=>'<option value="'+role+'" '+(page.product_roles?.[key]===role?'selected':'')+'>'+roleLabels[role]+'</option>').join('')+'</select></label> <button type="button" class="fs-btn" data-product-up="'+i+'" '+(i?'':'disabled')+'>上移</button> <button type="button" class="fs-btn" data-product-remove="'+i+'">从本页移除</button></li>';}).join('')+'</ol>'+'<p>本页选择与编排均保存在同一草稿；未核定商品仅作资料预览，不生成购买规格或价格。</p>';
    if(selectedPage==='fc27-sbc'){
      const cores=pageKeys(page).filter(k=>page.product_roles?.[k]==='core'),companions=pageKeys(page).filter(k=>page.product_roles?.[k]==='companion'),name=key=>items.find(p=>p.key===key)?.title||key;
      $('page-products').insertAdjacentHTML('beforeend','<h4>资料预览的核心与搭档关联</h4><p>仅控制展示分组，不验证游戏内化学或购买资格；原已核 SBC 方案在本页下方编排区域维护，使用同一草稿。</p>'+cores.map(core=>'<fieldset><legend>'+escape(name(core))+'</legend>'+companions.map(key=>'<label class="check"><input type="checkbox" data-core-key="'+escape(core)+'" data-companion-key="'+escape(key)+'" '+(page.sbc_companions?.[core]?.includes(key)?'checked':'')+'>'+escape(name(key))+'</label>').join('')+'</fieldset>').join(''));
    }

  }
  function prunePairs(page){if(!page.sbc_companions)return;const keys=new Set(pageKeys(page));page.sbc_companions=Object.fromEntries(Object.entries(page.sbc_companions).filter(([key])=>keys.has(key)&&page.product_roles?.[key]==='core').map(([key,values])=>[key,values.filter(k=>keys.has(k)&&page.product_roles?.[k]==='companion')]));}
  $('page-select').addEventListener('change',()=>{state.draft=readForm();selectedPage=$('page-select').value;inspected=null;render();});
  $('page-products').addEventListener('click',event=>{const up=event.target.closest('[data-product-up]'),remove=event.target.closest('[data-product-remove]');if(!up&&!remove||busy||pending)return;state.draft=readForm();const page=state.draft.pages.find(p=>p.page_id===selectedPage);page.product_keys=[...pageKeys(page)];const i=Number(up?up.dataset.productUp:remove.dataset.productRemove);if(up&&i>0)[page.product_keys[i-1],page.product_keys[i]]=[page.product_keys[i],page.product_keys[i-1]];else if(remove){const [key]=page.product_keys.splice(i,1);if(page.product_roles)delete page.product_roles[key];prunePairs(page);}dirty=true;renderPageProducts();lock();});
  $('page-products').addEventListener('change',event=>{if(!event.target.dataset.roleKey||busy||pending)return;state.draft=readForm();const page=state.draft.pages.find(p=>p.page_id===selectedPage);page.product_keys=[...pageKeys(page)];page.product_roles||={};if(event.target.value)page.product_roles[event.target.dataset.roleKey]=event.target.value;else delete page.product_roles[event.target.dataset.roleKey];prunePairs(page);dirty=true;renderPageProducts();lock();});
  $('page-products').addEventListener('click',event=>{if(event.target.id!=='add-existing-product'||busy||pending)return;const key=$('existing-product').value;if(!key)return;state.draft=readForm();const page=state.draft.pages.find(p=>p.page_id===selectedPage);page.product_keys=[...pageKeys(page)];if(!page.product_keys.includes(key))page.product_keys.push(key);dirty=true;renderPageProducts();lock();});
  $('page-products').addEventListener('change',event=>{const core=event.target.dataset.coreKey,key=event.target.dataset.companionKey;if(!core||!key||busy||pending)return;state.draft=readForm();const page=state.draft.pages.find(p=>p.page_id===selectedPage);page.sbc_companions||={};const selected=new Set(page.sbc_companions[core]||[]);if(event.target.checked)selected.add(key);else selected.delete(key);page.sbc_companions[core]=[...selected];dirty=true;lock();});


  function renderFcLayout(){
    const box=$('fc-layout'),c=state.fc_catalog,d=state.draft.fc_layout??state.effective_fc_layout;
    box.hidden=!selectedPage.startsWith('fc27-')||!c||!d;if(box.hidden){box.innerHTML='';return;}
    const products=Object.values(c.products),players=products.filter(p=>p.kind==='player'),label=p=>p.title||p.name||p.key;
    const options=(list,id)=>list.map(p=>'<option value="'+escape(p.key)+'" '+(p.key===id?'selected':'')+'>'+escape(label(p))+'</option>').join('');
    const boxes=(list,chosen,name)=>list.map(p=>'<label class="product-choice"><input type="checkbox" data-layout-list="'+name+'" value="'+escape(p.key)+'" '+(chosen.includes(p.key)?'checked':'')+'>'+escape(label(p))+'</label>').join('');
    let html='<h3>本页已核 FC 结构</h3><p>与上方商品选择使用同一份草稿、同一次保存；保存不发布。未知后台商品仍只作资料预览。</p>';
    if(selectedPage==='fc27-weekly')html+='<fieldset><legend>每周推荐 · 1–6 张</legend>'+boxes(players,d.weekly,'weekly')+'</fieldset>';
    if(selectedPage==='fc27-trio')html+='<fieldset><legend>三人组 · 三个固定位置</legend>'+d.trio.map((id,i)=>'<label>位置 '+(i+1)+'<select data-trio="'+i+'">'+options(players.filter(p=>p.version===c.trio.series),id)+'</select></label>').join('')+'</fieldset><fieldset><legend>固定组合</legend>'+boxes(products.filter(p=>p.kind==='bundle'),d.bundles,'bundles')+'</fieldset>';
    if(selectedPage==='fc27-sbc'){
      html+='<fieldset><legend>SBC 核心、搭档与备选</legend>'+boxes(products.filter(p=>p.kind==='sbc'),d.sbc,'sbc')+'<label>默认核心<select id="layout-default-core">'+options(products.filter(p=>d.sbc.includes(p.key)),d.defaultCore)+'</select></label>';
      for(const key of d.sbc){const route=d.routes[key]||{picks:c.sbc.fallbackPicks,alternatives:[]};html+='<fieldset data-layout-core="'+escape(key)+'"><legend>'+escape(label(c.products[key]))+'</legend>'+route.picks.map((id,i)=>'<label>搭档 '+(i+1)+'<select data-layout-pick="'+i+'">'+options(players,id)+'</select></label>').join('')+'<details><summary>备选搭档</summary>'+boxes(players,route.alternatives,'alternatives')+'</details></fieldset>';}
      html+='</fieldset>';
    }
    box.innerHTML=html;
  }
  function syncLayoutSelection(page,d,previous){
    const ids=layout=>selectedPage==='fc27-weekly'?layout.weekly:selectedPage==='fc27-trio'?[...layout.trio,...layout.bundles]:[...layout.sbc,...layout.sbc.flatMap(key=>[...(layout.routes[key]?.picks||[]),...(layout.routes[key]?.alternatives||[])])];
    const before=new Set(ids(previous)),after=new Set(ids(d)),removed=new Set([...before].filter(id=>!after.has(id))),added=[...after].filter(id=>!before.has(id));
    // Apply only this edit's selection delta; never repopulate previously removed items.
    const retained=pageKeys(page).filter(key=>!removed.has(/^fc-(.+)-(ps|xbox|pc)$/.exec(key)?.[1]));
    page.product_keys=[...new Set([...retained,...added.flatMap(id=>(state.catalog_products||[]).filter(p=>p.key.startsWith('fc-'+id+'-')).map(p=>p.key))])];
    if(selectedPage==='fc27-trio'){
      const rank=key=>d.trio.indexOf(/^fc-(.+)-(ps|xbox|pc)$/.exec(key)?.[1]);
      // Slot changes reorder existing platform-specific references; never rebuild them.
      page.product_keys=[...page.product_keys.filter(key=>rank(key)>=0).sort((a,b)=>rank(a)-rank(b)),...page.product_keys.filter(key=>rank(key)<0)];
    }
    if(page.product_roles)page.product_roles=Object.fromEntries(Object.entries(page.product_roles).filter(([key])=>page.product_keys.includes(key)));
    prunePairs(page);
  }
  $('fc-layout').addEventListener('change',event=>{
    if(busy||pending||!state?.canEdit)return;state.draft=readForm();const source=state.draft.fc_layout??state.effective_fc_layout,el=event.target;if(!source)return;const d=structuredClone(source),previous=structuredClone(source);
    if(['weekly','bundles','sbc'].includes(el.dataset.layoutList)){
      const field=el.dataset.layoutList;d[field]=[...$('fc-layout').querySelectorAll('[data-layout-list="'+field+'"]:checked')].map(x=>x.value);
      if(field==='sbc'){for(const key of d.sbc)d.routes[key]||={picks:[...state.fc_catalog.sbc.fallbackPicks],alternatives:[]};if(!d.sbc.includes(d.defaultCore))d.defaultCore=d.sbc[0]||null;}
    }else if(el.dataset.trio!=null){const index=Number(el.dataset.trio),other=d.trio.indexOf(el.value),previousId=d.trio[index];if(other>=0&&other!==index)d.trio[other]=previousId;d.trio[index]=el.value;}
    else if(el.id==='layout-default-core')d.defaultCore=el.value;
    else {const core=el.closest('[data-layout-core]')?.dataset.layoutCore;if(!core)return;
      if(el.dataset.layoutPick!=null)d.routes[core].picks[Number(el.dataset.layoutPick)]=el.value;
      else if(el.dataset.layoutList==='alternatives')d.routes[core].alternatives=[...el.closest('[data-layout-core]').querySelectorAll('[data-layout-list="alternatives"]:checked')].map(x=>x.value);
    }
    if(same(d,previous))return;state.draft.fc_layout=d;
    syncLayoutSelection(state.draft.pages.find(p=>p.page_id===selectedPage),d,previous);dirty=true;renderPageProducts();renderFcLayout();lock();
  });

  const allowedGames=new Set(['1327','1329','1309','456','552','891']);
  function clearDiscovery(){discovered=[];discoveredGame=null;inspected=null;hasMore=false;$('discover-product').innerHTML='<option value="">请搜索商品</option>';$('product-inspection').hidden=true;lock();}
  function filterProducts(){
    $('discover-product').innerHTML='<option value="">请选择真实商品 ID</option>'+discovered.map(p=>'<option value="'+escape(p.product_ref.goods_id)+'">'+escape(p.title||'未提供标题')+' · 商品 '+escape(p.product_ref.goods_id)+' · 模型 '+escape(p.product_ref.model_id||'未提供')+'</option>').join('');
    $('product-inspection').hidden=true;$('discovery-page').textContent='第 '+searchPage+' 页';lock();
  }
  function scalar(value){return ['string','number','boolean'].includes(typeof value)?String(value):'未提供 / 待核验';}
  function inspect(product){
    $('inspection-title').textContent=product.title||'未提供商品标题';
    const ref=product.product_ref||{};
    const fields=[['站点 ID',ref.site_id],['游戏 ID',ref.game_id],['商品 ID',ref.goods_id],['模型 ID',ref.model_id],['模型名称',product.model_title],['平台属性 ID',product.platform_attribute_id],['服务器 ID',product.server_id],['分类 ID',product.category_id],['最小数量',product.minimum_quantity],['数量单位',product.unit],['SKU 开关原值',product.sku_switch],['属性开关原值',product.attr_switch],['商品状态原值',product.raw_status],['购买状态原值',product.raw_buy_status],['状态语义','未知，仍待核验'],['购买入口','未开放']];
    $('inspection-fields').innerHTML=fields.map(([label,value])=>'<div><dt>'+escape(label)+'</dt><dd>'+escape(scalar(value))+'</dd></div>').join('');
    const reasons=Array.isArray(product.purchase_mapping_reasons)?product.purchase_mapping_reasons.filter(x=>typeof x==='string'):[];
    $('inspection-reasons').innerHTML=(reasons.length?reasons:[product.purchase_mapping_required===false?'未观察到额外规格选择要求；这不代表购买映射已核验或可以结算，正式购买未开放。':'商品规格、数量单位和主站购买映射仍待核验；未开放购买。']).map(reason=>'<li>'+escape(reason)+'</li>').join('');
    const sources=product.specification_sources,readable=[];
    if(sources&&typeof sources==='object'&&!Array.isArray(sources))for(const [scope,label] of [['goods','商品'],['model','模型']]){
      const group=sources[scope];if(!group||typeof group!=='object')continue;
      for(const [key,name] of [['saleprop','销售规格'],['skuTableSet','SKU 表']]){
        const source=group[key];if(!source||typeof source!=='object')continue;
        const semantics={empty:'已观察为空',mapping_required:'待映射',unknown:'未知'}[source.schema_status]||'未知';
        readable.push(label+' · '+name+'：'+(source.present===false?'未观察到来源；':'')+semantics+'；条数 '+(Number.isSafeInteger(source.entry_count)&&source.entry_count>=0?source.entry_count:'未知'));
      }
    }
    $('inspection-specifications').innerHTML=(readable.length?readable:['未提供可核验的规格来源；规格映射仍待补齐，不能据此生成 SKU 或购买选项。']).map(source=>'<li>'+escape(source)+'</li>').join('');$('product-inspection').hidden=false;
  }
  function resetSearch(){searchPage=1;clearDiscovery();$('discovery-page').textContent='第 1 页';$('discovery-status').textContent='检索条件已改变，请搜索第一页；未修改活动草稿。';}
  $('discover-game').addEventListener('change',resetSearch);
  for(const field of ['discover-search','discover-goods-id','discover-model-id','discover-platform','discover-category'])$(field).addEventListener('input',resetSearch);
  $('discover-product').addEventListener('change',()=>{inspected=null;$('product-inspection').hidden=true;lock();});
  async function search(page=1){
    if(busy||pending||!state?.canEdit)return;const game=$('discover-game').value;if(!allowedGames.has(game))return;
    const keyword=$('discover-search').value.trim(),goods=$('discover-goods-id').value.trim(),model=$('discover-model-id').value.trim();
    if([keyword,goods,model].filter(Boolean).length!==1){$('discovery-status').textContent='请只填关键词、准确商品 ID、模型 ID 中的一项。';return;}
    if(keyword&&(keyword.length<2||keyword.length>80)){$('discovery-status').textContent='关键词需为 2–80 个字符；查询当前游戏后台商品，不限原页面预设。';return;}
    const query={action:'catalog_search',site_id:'266',game_id:game,page,page_size:20,...(keyword?{keyword}:goods?{goods_id:goods}:{model_id:model})};
    for(const [id,key] of [['discover-platform','platform_attribute_id'],['discover-category','category_id']])if($(id).value.trim())query[key]=$(id).value.trim();
    clearDiscovery();busy=true;lock();$('discovery-status').textContent='正在读取站点 266 当前游戏的第 '+page+' 页后台商品；不是原页面预设，不会保存草稿。';
    try{const result=await request('api/center/backend-read',query),data=result.data;
      if(result.status!=='ok'||!Array.isArray(data?.items))throw Error('商品查询未返回可核对结果。');
      if(data.items.some(p=>p.product_ref?.site_id!=='266'||p.product_ref?.game_id!==game))throw Error('商品范围不匹配。');
      discovered=data.items;discoveredGame=game;searchPage=page;hasMore=data.has_more===true;filterProducts();
      $('discovery-status').textContent='本页 '+discovered.length+' 项；共 '+data.total+' 项。后台元数据仅供配置，购买保持关闭。'+(data.search_verification?' 搜索协议来源已记录；字段语义以实际只读核验为准。':'');
    }catch(error){$('discovery-status').textContent=error.status===504||error.message==='CATALOG_SEARCH_TIMEOUT'?'后台商品搜索超时，本次未取得结果，不代表没有商品。未自动重试；可调整关键词或可选平台/类型后重新搜索。':error.status===401||error.status===403||error.message==='CATALOG_SEARCH_HTTP_REJECTED'?'后台拒绝此次只读搜索；未重试，请核对当前会话权限。':'后台商品搜索失败，本次未取得可核对结果，不代表没有商品。'+(error.message==='响应无法确认，请核对原操作。'?' 返回了非预期格式，请联系维护人员。':error.message);}finally{busy=false;lock();}
  }
  $('discover-products').addEventListener('click',()=>search(1));
  $('discovery-prev').addEventListener('click',()=>search(searchPage-1));
  $('discovery-next').addEventListener('click',()=>search(searchPage+1));
  $('add-product').addEventListener('click',async()=>{
    if(busy||pending||!inspected||!state?.canEdit)return;
    const draft=readForm();if(!$('center-form').reportValidity())return;
    busy=true;lock();try{persist({path:'api/center/import-product',body:{revision:state.revision,operation_id:crypto.randomUUID(),draft,page_id:selectedPage,product_ref:inspected.product_ref}});await resolve();$('center-status').textContent='商品已核验并选入本页草稿；未发布，未开放购买。';}
    catch(error){if([400,403,409,422].includes(error.status)){persist(null);acceptedState(await request('api/center'));render();}$('center-error').textContent=error.message+(pending?' 原操作已保留，请核对原操作；不要重复选入。':' 请求未接受，已重读配置，请核对后再编辑。');}finally{busy=false;lock();}
  });
  $('inspect-product').addEventListener('click',async()=>{
    if(busy||pending||!state?.canEdit||!discoveredGame)return;
    const goods=$('discover-product').value;if(!discovered.some(p=>p.product_ref.goods_id===goods))return;
    const game=discoveredGame;busy=true;lock();$('product-inspection').hidden=true;$('discovery-status').textContent='正在读取所选商品资料。';
    try{const result=await request('api/center/backend-read',{action:'product_read',site_id:'266',game_id:game,goods_id:goods});const product=result.data?.product;
      if(result.status!=='ok'||product?.product_ref?.site_id!=='266'||product.product_ref.game_id!==game||product.product_ref.goods_id!==goods)throw Error('商品资料 ID 或所属游戏不匹配，仍待核验。');
      inspected=product;inspect(product);$('discovery-status').textContent='商品 '+goods+' 资料已读取；只供核对，正式购买未开放。';
    }catch(error){$('discovery-status').textContent=error.message;}finally{busy=false;lock();}
  });
  function sync(event){const el=event.target;if(!el.matches?.('input,select,textarea'))return;if(el.matches(':user-invalid'))el.setAttribute('aria-invalid','true');else el.removeAttribute('aria-invalid');}
  document.addEventListener('blur',sync,true);document.addEventListener('focus',sync,true);document.addEventListener('input',event=>{if(event.target.hasAttribute('aria-invalid'))sync(event);});
  load();
})();
