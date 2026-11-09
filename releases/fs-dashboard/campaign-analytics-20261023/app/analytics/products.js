(function(){
  'use strict';
  const $=id=>document.getElementById(id),escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const publicPrefix=document.documentElement.dataset.campaignPublicPrefix||'/events/',publicPrefixValid=/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(publicPrefix);
  let publicBase=null;try{const origin=document.documentElement.dataset.campaignPublicOrigin||location.origin,site=new URL(origin);if(publicPrefixValid&&site.origin===origin&&(site.protocol==='https:'||site.protocol==='http:'&&['127.0.0.1','localhost'].includes(site.hostname)))publicBase=new URL(publicPrefix,site).href;}catch{}
  const storageKey='fs-center-pending:'+location.pathname.replace(/products\.html$/, 'center.html');
  let modelPreviewPlatform='ps';
  let stagedModels=[],stagedProducts=[],previewSignature=null,halloweenDirty=false,halloweenShown=new Map();
  let savedDraft=null,state=null,catalog=[],busy=false,dirty=false,pending=null,discovered=[],discoveredGame=null,selectedPage='fc27-weekly',modelDetail=null,modelSearchKind=null,uploadRecord=null,searchPage=1,hasMore=false,inspected=null;
  const embedParams=new URLSearchParams(location.search),embedRun=embedParams.get('run_operation_id'),embedded=embedParams.get('embedded')==='weekly'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(embedRun||'')&&window.parent!==window;
  if(embedded){document.documentElement.dataset.weeklyEmbedded='true';document.documentElement.dataset.fsTheme=embedParams.get('theme')==='dark'?'dark':'light';}
  const editorDirty=()=>dirty||stagedModels.length>0||stagedProducts.length>0||!!uploadRecord||!!pending;
  if(embedded)window.fsWeeklyEditor={isDirty:editorDirty,canDiscard:()=>!busy&&!pending&&!uploadRecord?.unknown,discard:()=>{dirty=false;stagedModels=[];stagedProducts=[];uploadRecord=null;}};
  const requestedPage=new URLSearchParams(location.search).get('page');if(['fc27-sbc','fc27-trio','fc27-weekly'].includes(requestedPage))selectedPage=requestedPage;
  try{pending=JSON.parse(sessionStorage.getItem(storageKey)||'null');}catch{$('center-error').textContent='无法读取原操作记录；请保留当前会话并联系维护人员核对。';return;}
  const stable=v=>JSON.stringify(v,(_k,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,x[k]])):x);
  const same=(a,b)=>stable(a)===stable(b);
  function acceptedState(value){stagedModels=[];stagedProducts=[];halloweenDirty=false;state=value;if(uploadRecord?.page_id){if(state.draft.pages.some(p=>p.page_id===uploadRecord.page_id))selectedPage=uploadRecord.page_id;else $('media-status').textContent='原上传目标页不存在，已保留原操作与文件，请联系维护核对；未绑定到其他页。';}savedDraft=structuredClone(value.draft);dirty=false;if($('restore-review'))$('restore-review').hidden=true;}
  function persist(value){sessionStorage.setItem(storageKey,JSON.stringify(value));pending=value;}
  async function request(path,body){const response=await fetch(path,{credentials:'same-origin',cache:'no-store',...(body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify(body)}:{})});let data;try{data=await response.json();}catch{throw Object.assign(Error('响应无法确认，请核对原操作。'),path==='api/center/backend-read'||path==='api/center/preview'?{status:response.status}:{});}if(!response.ok)throw Object.assign(Error(data.message||data.code||'请求失败'),{status:response.status});return data;}
  function lock(){ $('page-select').disabled=busy||Boolean(pending)||Boolean(uploadRecord);$('upload-media').disabled=busy||!state?.canEdit||Boolean(pending)||Boolean(uploadRecord);$('recover-upload').hidden=!uploadRecord?.unknown;dirty=Boolean(state&&savedDraft&&!same(state.draft,savedDraft))||halloweenDirty;if(previewSignature&&(halloweenDirty||previewSignature!==stable({page_id:selectedPage,draft:state?.draft,model_imports:modelImports(),product_imports:productImports()}))){$('draft-preview').hidden=true;$('preview-status').textContent='配置已变化，请重新整页预览。';previewSignature=null;}renderChanges();$('restore-draft').disabled=busy||Boolean(pending)||!state?.canEdit||dirty||!state?.restore_candidate;$('confirm-restore').disabled=$('restore-draft').disabled; $('center-fields').disabled=busy||!state?.canEdit||Boolean(pending);$('read-benefits').disabled=busy||!state?.canEdit||Boolean(pending);$('publish-center').disabled=Boolean(uploadRecord?.unknown);$('preview-draft').disabled=busy||Boolean(pending)||!state?.canEdit||Boolean(uploadRecord?.unknown);$('read-published').disabled=busy||!state?.published||Boolean(pending);$('discovery-fields').disabled=busy||!state?.canEdit||Boolean(pending);$('discover-search').disabled=busy;$('discover-product').disabled=!discoveredGame;$('inspect-product').disabled=busy||!discoveredGame||!$('discover-product').value;$('add-product').disabled=busy||!inspected||!state?.canEdit||Boolean(pending);$('discovery-prev').disabled=busy||searchPage<=1;$('discovery-next').disabled=busy||!hasMore;if(embedded)window.parent.postMessage({type:'fs-weekly-editor-state',operation_id:embedRun,dirty:editorDirty()},location.origin); }
  function local(value){return value?new Date(value).toISOString().slice(0,16):'';}
  function benefitLabel(ref){const item=catalog.find(x=>x.kind===ref.kind&&x.native_id===ref.native_id);return (ref.kind==='coupon'?'优惠券':'折扣')+' · '+(item?.title||ref.native_id)+(item?' · 原始状态 '+String(item.raw_status??'未知'):' · 尚未核验');}
  function bindings(page,i){return '<ul class="bindings">'+(page.benefit_refs||[]).map((ref,j)=>'<li><span>'+escape(benefitLabel(ref))+'</span><button class="fs-btn" type="button" data-remove="'+i+':'+j+'">移除绑定</button></li>').join('')+'</ul><label for="benefit-'+i+'">选择后台优惠<select id="benefit-'+i+'" data-benefit="'+i+'"><option value="">请选择原生优惠</option>'+catalog.map((ref,j)=>'<option value="'+j+'">'+escape(benefitLabel(ref))+'</option>').join('')+'</select></label><button class="fs-btn" type="button" data-add="'+i+'">添加绑定</button>';}
  const imageChoices={
    'fc27-weekly':['assets/weekly-hero.webp','assets/weekly-hero-mobile.webp'],
    'fc27-sbc':['assets/reward-hero.webp','assets/reward-hero-mobile.webp'],
    'fc27-trio':['assets/scream-hero.webp','assets/scream-hero-mobile.webp'],
    'seasonal-vault':['halloween','thanksgiving','christmas','black-friday'].map(theme=>'seasonal/assets/hero-'+theme+'.webp')
  };
  function copyControls(page,i){
    if(!['fc27-weekly','fc27-sbc','fc27-trio'].includes(page.page_id))return '';
    const copy=page.copy||{};
    return '<fieldset data-copy-block><legend>可见文案（英文）</legend><p class="muted">这三个字段直接决定页面上的推荐位标题、导语和主视觉说明，改完保存并发布即生效，不用改代码。留空表示沿用默认文案。只接受英文（公开页面固定英文），长度上限 120 / 320 / 400 字符。</p>'
      +[['heading','推荐位大标题',120],['intro','导语',320],['body','主视觉说明',400]].map(([key,label,max])=>'<label for="copy-'+key+'-'+i+'">'+label+'<textarea id="copy-'+key+'-'+i+'" name="copy_'+key+'" maxlength="'+max+'" data-copy="'+key+'" rows="2">'+escape(copy[key]||'')+'</textarea><span class="error-msg" data-copy-error="'+key+'">公开页面只接受英文，不能含尖括号或控制字符。</span></label>').join('')
      +'</fieldset>';
  }
  function presentationControls(page,i){
    const seasonal=page.page_id==='seasonal-vault',language=page.default_language||'original',image=page.social_image||'original';
    return '<div class="config-grid"><label for="language-'+i+'">公开页面语言（固定英文）<select id="language-'+i+'" name="default_language" required>'+[['original','保留原配置（对外英文）'],['en','English'],...(language==='zh'?[['zh','历史演示中文（对外固定英文）']]:[])].map(([value,label])=>'<option value="'+value+'" '+(value===language?'selected':'')+(value==='zh'?' disabled':'')+'>'+label+'</option>').join('')+'</select></label><label for="share-image-'+i+'">社交分享图（已接受素材）<select id="share-image-'+i+'" name="social_image" required>'+['original',...(imageChoices[page.page_id]||[])].map(value=>'<option value="'+value+'" '+(value===image?'selected':'')+'>'+escape(value==='original'?'保留原分享图':value)+'</option>').join('')+'</select></label></div><p class="muted">原主视觉来源：'+escape(seasonal?'已有四套主题 hero，随限定活动主题消费':(imageChoices[page.page_id]||[]).join(' / '))+'。可在上方替换素材，填写英文说明并确认后统一整页预览或发布。</p>';
  }
  function publicationSummary(){
    const p=state.published;$('published-readback').textContent='尚未核对当前发布版本的公开运行时；保存记录不等于部署或真实交易启用。';
    if(!p){$('published-summary').textContent='尚无已发布版本；草稿不会进入公开运行时。';return;}
    const rows=[['发布 ID',p.release_id],['配置哈希',p.config_hash],['规则哈希',p.rule_hash],['源码版本',p.source_revision||'旧记录未保存'],['发布时间',p.published_at],['限定活动素材主题',p.seasonal_theme||'旧记录未保存'],['模式','preview · 主站交易未开放']];
    $('published-summary').innerHTML='<dl>'+rows.map(([label,value])=>'<div><dt>'+escape(label)+'</dt><dd style="overflow-wrap:anywhere">'+escape(value)+'</dd></div>').join('')+'</dl>'+(Array.isArray(p.pages)?'<ul>'+p.pages.map(page=>'<li>'+escape(page.title+' · '+page.path+' · '+(page.preview_enabled?'允许预览':'预览关闭')+' · 默认语言 '+(page.default_language||'original')+' · 分享图 '+(page.social_image||'original')+' · UTC '+(page.starts_at||'不限')+' — '+(page.ends_at||'不限'))+(publicBase&&['Weekly-Scout.html','Sbc-Companions.html','Player-Trio.html','seasonal/index.html'].includes(page.path)?' <a href="'+escape(new URL(page.path,publicBase).href)+'" target="_blank" rel="noopener">打开已发布页面</a>':'')+'</li>').join('')+'</ul>':'<p>旧发布记录未保存页面摘要，请保存并发布后核对。</p>');
  }
  function renderPreview(){
    const routes={'fc27-weekly':'Weekly-Scout.html','fc27-sbc':'Sbc-Companions.html','fc27-trio':'Player-Trio.html','seasonal-vault':'seasonal/index.html'},link=$('preview-page'),route=routes[selectedPage];
    link.hidden=!route||!publicBase;
    if(!route||!publicBase){link.removeAttribute('href');return;}
    link.href=new URL(route,publicBase).href;
    link.textContent='查看已发布页面 ↗';
  }
  function render(){
    if(halloweenDirty&&!collectHalloween()){$('center-error').textContent=$('halloween-status').textContent;return;}
    $('draft-state').textContent='修订 '+state.revision;$('publish-state').textContent=state.published?'已有预览发布':'尚未发布';
    const pageLabel=p=>p.page_id==='fc27-trio'&&['Star Performer Trio','Star Performer 三人组'].includes(p.title)?'Player Trio':p.title||p.page_id;
    $('page-select').innerHTML=state.draft.pages.map(p=>'<option value="'+escape(p.page_id)+'" '+(p.page_id===selectedPage?'selected':'')+'>'+escape(pageLabel(p))+'</option>').join('');
    $('seasonal-theme-label').hidden=selectedPage!=='seasonal-vault';$('fc-business').hidden=selectedPage==='seasonal-vault';$('discovery-fields').closest('section').hidden=selectedPage!=='seasonal-vault';
    $('page-guidance').textContent=selectedPage==='seasonal-vault'?'万圣节：四款游戏，每游戏固定模型 + 两个随机商品槽；未配置概率、商品或有效期时保持不可抽取。旧配置记录保留，不自动迁移。':'FC 页面：保留原球员、SBC搭档、三人组与捆绑包编排；新增未适配商品仅展示资料，不自动变成可买卡或组合。';
    $('center-pages').innerHTML=state.draft.pages.map((p,i)=>'<fieldset '+(p.page_id===selectedPage?'':'hidden ')+'data-page="'+i+'"><legend>'+escape(p.title||p.page_id)+'</legend><p class="muted">'+escape(p.activity_id+' / '+p.page_id+' · '+p.path)+'</p><div class="config-grid"><label for="title-'+i+'">页面标题<input id="title-'+i+'" name="title" required maxlength="160" value="'+escape(p.title)+'"></label><label class="check"><input name="preview_enabled" type="checkbox" '+(p.preview_enabled?'checked':'')+'>允许预览</label><label for="start-'+i+'">开始时间 (UTC)<input id="start-'+i+'" name="starts_at" type="datetime-local" value="'+local(p.starts_at)+'" aria-errormessage="date-error-'+i+'"><span class="error-msg" id="date-error-'+i+'">结束时间必须晚于开始时间。</span></label><label for="end-'+i+'">结束时间 (UTC)<input id="end-'+i+'" name="ends_at" type="datetime-local" value="'+local(p.ends_at)+'" aria-errormessage="end-error-'+i+'"><span class="error-msg" id="end-error-'+i+'">结束时间必须晚于开始时间。</span></label></div><label for="description-'+i+'">SEO 描述<textarea id="description-'+i+'" name="description" maxlength="320">'+escape(p.description)+'</textarea></label>'+copyControls(p,i)+presentationControls(p,i)+'<div data-bindings="'+i+'">'+bindings(p,i)+'</div></fieldset>').join('');
    const theme=$('seasonal-theme'),value=state.draft.seasonal_theme||'halloween';
    if(typeof value==='string'){if(![...theme.options].some(o=>o.value===value))theme.add(new Option(value,value));theme.value=value;}else theme.disabled=true;
    renderPageProducts();renderFcLayout();renderHalloween();renderMaterials();renderPreview();publicationSummary();lock();
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
      // Visible hero copy: blank means "keep the built-in default", so the field
      // is removed from the draft instead of being stored as an empty string.
      const copy={};
      for(const key of ['heading','intro','body']){
        const field=get('copy_'+key);if(!field)continue;
        const value=field.value.trim();
        field.setCustomValidity(/[<>\u0000-\u001f]/.test(value)?'不能含尖括号或控制字符。':(/\p{Script=Han}/u.test(value)?'公开页面只接受英文，请填英文文案。':''));
        if(value)copy[key]=value;
      }
      if(!same(copy,p.copy||{})){if(Object.keys(copy).length)p.copy=copy;else delete p.copy;}
      assign('preview_enabled',get('preview_enabled').checked,p.preview_enabled===true);
      for(const key of ['starts_at','ends_at'])if(get(key).value!==local(p[key]))p[key]=get(key).value?new Date(get(key).value+'Z').toISOString():null;
      get('ends_at').setCustomValidity(p.starts_at&&p.ends_at&&Date.parse(p.starts_at)>=Date.parse(p.ends_at)?'结束时间必须晚于开始时间。':'');
    }
    return draft;
  }
  const fieldNames={product_keys:'商品选择与顺序',product_roles:'商品展示位置',sbc_companions:'SBC搭档',fc_layout:'FC编排',title:'标题',description:'说明',copy:'可见文案',preview_enabled:'预览开关',starts_at:'开始时间',ends_at:'结束时间',default_language:'默认语言',social_image:'分享图',benefit_refs:'优惠绑定',halloween:'万圣节四游戏槽位',seasonal_theme:'限定活动主题'};
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
    $('draft-changes').innerHTML=rows.length?'<strong>整页未保存修改</strong><ul>'+rows.map(x=>'<li>'+escape(x)+'</li>').join('')+'</ul><p>统一预览可检查所有修改；保存仅保留配置，发布整页时一次验证全部修改。</p>':'未修改配置；切换页面不会固定继承数据。';
  }
  async function load(){busy=true;lock();state=null;try{acceptedState(await request('api/center'));render();if(pending){$('center-status').textContent='已重读服务器状态，正在用原操作 ID 核对结果。';await resolve();}else $('center-status').textContent=state.canEdit?'已读取服务器配置。':'当前账号为只读。';}catch(error){$('center-error').textContent=error.message;}finally{busy=false;lock();}}
  async function resolve(){const savedPath=pending.path;if(embedded&&savedPath.endsWith('/publish'))throw Error('请在周更台审阅后确认发布');const receipt=await request(pending.path,pending.body);const refreshed=await request('api/center');persist(null);acceptedState(refreshed);render();$('center-status').textContent='原操作已确认，已重新读取服务器状态。';if(embedded&&savedPath==='api/center')window.parent.postMessage({type:'fs-weekly-draft-saved',operation_id:embedRun,revision:state.revision},location.origin);return receipt;}
  async function mutate(path,draft,extra={}){if(busy||pending||!state?.canEdit)return;busy=true;lock();$('center-error').textContent='';$('center-status').textContent='正在执行本次草稿操作，请等待原操作结果。';try{persist({path,body:{revision:state.revision,operation_id:crypto.randomUUID(),...(draft?{draft}:{}),...extra}});await resolve();$('center-status').textContent=path.endsWith('/publish')?'预览配置已发布；主站交易仍待接入。':path.endsWith('/restore')?'已恢复上一份草稿的原始字段与继承；未改变公开预览。':'草稿已保存；尚未发布预览。';}catch(error){if([400,403,409,422].includes(error.status)){persist(null);const fresh=await request('api/center');if(fresh.revision===state.revision&&same(fresh.draft,savedDraft)){state.csrf=fresh.csrf;state.canEdit=fresh.canEdit;}else if(embedded){state.csrf=fresh.csrf;state.canEdit=fresh.canEdit;}else{acceptedState(fresh);render();}}$('center-error').textContent=error.message+(pending?' 原操作记录已保留；请点击重新读取核对，勿新建操作。':embedded?' 未保存修改已保留；服务器版本可能已变化，请核对后决定是否重新读取。':' 已重新读取服务器状态，请核对后修改。');}finally{busy=false;lock();}}
  function collectPage(){
    $('center-error').textContent='';state.draft=readForm();if(!$('center-form').reportValidity())return null;
    try{if(!collectHalloween())throw Error($('halloween-status').textContent);applyPendingMedia();lock();return structuredClone(state.draft);}catch(error){$('center-error').textContent=error.message;return null;}
  }
  function modelImports(){return stagedModels.filter(m=>state?.draft.pages.find(p=>p.page_id===m.page_id)?.product_keys?.some(key=>key.startsWith('fc-model-266-1327-'+m.model_id+'-')));}
  function productImports(){return stagedProducts.filter(m=>state?.draft.pages.find(p=>p.page_id===m.page_id)?.product_keys?.includes(m.key)).map(({page_id,product_ref})=>({page_id,product_ref}));}
  $('center-form').addEventListener('submit',event=>{event.preventDefault();const draft=collectPage();if(!draft)return;if(same(draft,savedDraft)){$('center-status').textContent='没有配置变化，未提交保存。';return;}mutate('api/center',draft,{model_imports:modelImports(),product_imports:productImports()});});
  $('restore-draft').addEventListener('click',()=>{
    const candidate=state?.restore_candidate;if(!candidate||dirty||busy||pending)return;
    $('restore-summary').textContent='恢复到修订 '+candidate.revision+' 的原始草稿字段（包含缺省继承）。涉及页面：'+(candidate.changed_pages||[]).join('、')+'；配置：'+(candidate.changed_fields||[]).map(k=>fieldNames[k]||k).join('、')+'。仅恢复草稿，保留全部历史，不回退公开发布。';
    $('restore-review').hidden=false;
  });
  $('cancel-restore').addEventListener('click',()=>{$('restore-review').hidden=true;});
  $('confirm-restore').addEventListener('click',()=>{if(!state?.restore_candidate||dirty)return;mutate('api/center/restore',null,{restore_revision:state.restore_candidate.revision});});
  $('publish-center').addEventListener('click',()=>{if(embedded)return;const draft=collectPage();if(draft)mutate('api/center/publish',draft,{model_imports:modelImports(),product_imports:productImports()});});
  $('preview-draft').addEventListener('click',async()=>{
    if(busy||pending||!state?.canEdit)return;const draft=collectPage();if(!draft)return;
    busy=true;lock();$('preview-status').textContent='正在生成整页预览；不会保存或发布。';
    try{
      const body={revision:state.revision,draft,page_id:selectedPage,model_imports:modelImports(),product_imports:productImports()},result=await request('api/center/preview',body),url=new URL(result.preview_url,location.href);
      if(url.origin!==location.origin||!url.pathname.startsWith(new URL('preview/',location.href).pathname))throw Error('整页预览地址未通过同源校验。');
      previewSignature=stable({page_id:selectedPage,draft,model_imports:body.model_imports,product_imports:body.product_imports});$('draft-preview-frame').src=url.href;$('draft-preview').hidden=false;
      $('preview-status').textContent='当前整页未发布预览：包含本页素材、模型编排与优惠配置；交易未启用。预览到期后可重新打开。';
    }catch(error){$('draft-preview').hidden=true;$('preview-status').textContent=error.message+' 未保存或发布任何配置。';}finally{busy=false;lock();}
  });
  window.addEventListener('beforeunload',event=>{if(dirty||stagedModels.length||stagedProducts.length||uploadRecord){event.preventDefault();event.returnValue='';}});
  $('reload-center').addEventListener('click',()=>{if(!busy&&(!embedded||!editorDirty()||confirm('有未保存修改，确定放弃并重新读取吗？')))load();});
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
  function renderHalloween(){
    const box=$('halloween-business');if(!box)return;box.hidden=selectedPage!=='seasonal-vault';if(box.hidden)return;
    const h=state.draft.halloween??state.effective_halloween;
    if(!h){$('halloween-fields').textContent='服务器尚未提供四游戏配置合同；未改旧配置。';return;}
    const products=[...(state.catalog_products||[]),...(state.draft.imported_products||[])];
    $('halloween-fields').innerHTML=h.games.map((g,index)=>{
      const rows=products.filter(p=>p.product_ref?.site_id==='266'&&p.product_ref?.game_id===g.admin_game_id&&p.product_ref?.model_id),models=[...new Map(rows.map(p=>[p.product_ref.model_id,p])).values()];
      const options='<option value="">尚未配置</option>'+models.map(p=>'<option value="'+escape(p.product_ref.model_id)+'" '+(p.product_ref.model_id===g.fixed_model?'selected':'')+'>'+escape(p.title)+' · 模型 '+escape(p.product_ref.model_id)+'</option>').join('');
      const source=g.random_source||{mode:'models',category_id:null,snapshot_complete:false};
      const quantities=['aion','wow'].includes(g.id)?'<fieldset class="quantity-tier-fields"><legend>金币档位（选择数量档位模式时生效）</legend><label>单位<input data-h-qunit="'+index+'" value="'+escape(g.fixed_quantity?.unit||'')+'" placeholder="按主站实际单位填写"></label><label>固定卡数量<input data-h-qfixed="'+index+'" value="'+escape(g.fixed_quantity?.value||'')+'" inputmode="decimal"></label>'+[0,1].map(n=>'<label>随机卡档位 '+(n+1)+'<input data-h-qrandom'+n+'="'+index+'" value="'+escape(g.random_quantities?.[n]?.value||'')+'" inputmode="decimal"></label>').join('')+'<p>三个不同数量档位复用固定模型；服务器由客户选择，不将不同区服伪装为不同商品。</p></fieldset>':'';
      return '<fieldset><legend>'+escape(g.label)+'</legend>'+ (g.id==='fc'?'<p>固定商品业务量：1000K Coins。尚须核实模型及实际购买单位换算，不能用任意SKU代替。</p>':'')+'<label>随机池来源<select data-h-source="'+index+'">'+[['models','指定模型'],['category_snapshot','类目批量快照（本次明确模型列表）'],['category_dynamic','类目动态全可售（抽取前服务端读取）'],...(['aion','wow'].includes(g.id)?[['quantity_tiers','同一金币模型的三个数量档位']]:[])].map(([v,label])=>'<option value="'+v+'" '+(source.mode===v?'selected':'')+'>'+label+'</option>').join('')+'</select></label><label>Admin 类目 ID<input data-h-category="'+index+'" value="'+escape(source.category_id||'')+'" inputmode="numeric"></label><p>快照不随新增/下架自动扩展；动态规则不会把当前分页当完整目录。实际可售、去重及排除固定项在抽取前重新核验，不足两款保持不可抽取。</p><label>Admin 游戏 ID（须按真实目录核对）<input data-h-game="'+index+'" inputmode="numeric" value="'+escape(g.admin_game_id||'')+'" '+(['fc','aion'].includes(g.id)?'readonly':'')+'></label><label>固定模型<select data-h-fixed="'+index+'">'+options+'</select></label><label>固定模型优惠<select data-h-off="'+index+'"><option value="">尚未配置</option>'+[8,15,10].map(v=>'<option value="'+v+'" '+(v===g.fixed_off_percent?'selected':'')+'>'+v+'% OFF / Admin '+(100-v)+'</option>').join('')+'</select></label>'+quantities+'<p>模型随机池（数量档位模式不使用此列表；其他模式排除固定模型）</p>'+(source.mode==='quantity_tiers'?'<p>数量档位模式统一调度固定模型，不逐条列出该游戏的产品模型；具体区服产品在商品检索区关联。</p>':models.filter(p=>p.product_ref.model_id!==g.fixed_model).map(p=>'<label class="check"><input type="checkbox" data-h-pool="'+index+'" value="'+escape(p.product_ref.model_id)+'" '+(g.random_models.includes(p.product_ref.model_id)?'checked':'')+'>'+escape(p.title)+' · 模型 '+escape(p.product_ref.model_id)+'</label>').join(''))+'<p>这里只选模型，关联产品保留用于规格解析；不是把某个SKU当模型价格。请先在真实商品检索区核对并导入相关模型的关联产品。未核游戏ID和未取得目录不会虚构选项。</p></fieldset>';
    }).join('')+'<fieldset><legend>抽取档位（万分比权重，总和10000；留空未配置）</legend>'+[8,15,10].map(off=>'<label>'+off+'% OFF<input data-h-weight="'+off+'" type="number" min="0" max="10000" step="1" value="'+escape(h.probabilities?.find(r=>r.off_percent===off)?.weight??'')+'"></label>').join('')+'<label>档位与商品关系<select id="h-binding"><option value="">尚未确定</option><option value="independent" '+(h.tier_product_binding==='independent'?'selected':'')+'>已确认独立抽取（需运营明确选择）</option></select></label><label>万圣节开始时间（含时区ISO格式）<input id="h-start" value="'+escape(h.starts_at||'')+'" placeholder="未配置，不套用FC时间"></label><label>万圣节结束时间（含时区ISO格式）<input id="h-end" value="'+escape(h.ends_at||'')+'"></label><p class="muted">这些字段随整页预览、保存或发布统一校验，无需逐项确认。</p></fieldset>';
    addHalloweenReadControls();halloweenShown=new Map([...document.querySelectorAll('#halloween-fields input,#halloween-fields select')].map(el=>[el,el.type==='checkbox'?el.checked:el.value]));
  }
  function addHalloweenReadControls(){
    document.querySelectorAll('#halloween-fields [data-h-fixed]').forEach(select=>{
      const index=select.dataset.hFixed,box=select.closest('fieldset');
      if(box.querySelector('[data-h-observation]'))return;
      for(const [mode,label] of [['model','只读核对固定模型关联产品与档位'],['pool','只读核对类目第一页及最多3个模型关联']]){
        const button=document.createElement('button');button.type='button';button.className='fs-btn';button.dataset.hRead=mode;button.dataset.hIndex=index;button.textContent=label;box.append(button);
      }
      const output=document.createElement('pre');output.dataset.hObservation=index;output.style.whiteSpace='pre-wrap';output.style.overflowWrap='anywhere';output.setAttribute('role','status');box.append(output);
    });
  }
  $('halloween-business')?.addEventListener('input',()=>{halloweenDirty=true;lock();});
  // Reads remain in the sole editor and never mutate the draft or publish data.
  $('halloween-business')?.addEventListener('click',async event=>{
    const mode=event.target.dataset.hRead,index=event.target.dataset.hIndex;
    if(!mode||busy||pending||!state?.canEdit)return;
    const field=name=>document.querySelector('[data-h-'+name+'="'+index+'"]');
    const output=document.querySelector('[data-h-observation="'+index+'"]');
    const game_id=field('game').value.trim(),category_id=field('category').value.trim(),model_id=field('fixed').value;
    if(!/^[1-9]\d{0,19}$/.test(game_id)||!/^[1-9]\d{0,19}$/.test(category_id)||(mode==='model'&&!model_id)){output.textContent='请先选择真实游戏、类目及需要核对的模型。';return;}
    busy=true;lock();output.textContent='正在只读核对 Admin；不会保存或改变活动配置。';
    try{
      const query={action:mode==='model'?'model_provider_read':'model_category_pool',site_id:'266',game_id,category_id,...(mode==='model'?{model_id}:{max_pages:1,page_size:10,resolve_associations:true,exclude_model_ids:model_id?[model_id]:[]})};
      const {data}=await request('api/center/backend-read',query);
      // Explicit source fields only; no raw response HTML or customer data.
      const summary=mode==='model'?{observed_at:data.observed_at,source:data.source,model:data.model,products:data.products,coverage:data.coverage,currency:data.currency,authoritative:false,checkout_enabled:false}
        :{observed_at:data.observed_at,source:data.source,items:data.items,coverage:data.coverage,association_coverage:data.association_coverage,available:false,checkout_enabled:false};
      output.textContent='只读观测（不是已核权威售价或可售权益池）：\n'+JSON.stringify(summary,null,2);
    }catch(error){output.textContent='读取未完成：'+error.message+'；不会用空结果替代原配置。';}
    finally{busy=false;lock();}
  });
  function collectHalloween(){
    if(!halloweenDirty||selectedPage!=='seasonal-vault'||!document.querySelector('[data-h-fixed]'))return true;
    const original=state.draft.halloween??state.effective_halloween,h=structuredClone(original);if(!h)return true;
    const changed=el=>halloweenShown.get(el)!==(el.type==='checkbox'?el.checked:el.value),field=(name,i)=>document.querySelector('[data-h-'+name+'="'+i+'"]');
    const invalid=message=>{$('halloween-status').textContent=message;return false;};
    for(let i=0;i<h.games.length;i++){
      const g=h.games[i],game=field('game',i),fixed=field('fixed',i),off=field('off',i),source=field('source',i),category=field('category',i),pool=[...document.querySelectorAll('[data-h-pool="'+i+'"]')];
      if(changed(game)){const id=game.value.trim();if(id&&!/^[1-9]\d{0,19}$/.test(id))return invalid('游戏ID须为已核实的数字ID。');if(g.fixed_model||g.random_models.length)return invalid('改变游戏范围前请先明确清除原模型选择，防止串游戏。');g.admin_game_id=id||null;}
      if(changed(fixed))g.fixed_model=fixed.value||null;
      if(changed(off))g.fixed_off_percent=off.value?Number(off.value):null;
      if(pool.some(changed))g.random_models=pool.filter(el=>el.checked).map(el=>el.value);
      if(changed(source)||changed(category)){
        const mode=source.value,id=category.value.trim();if(!['models','quantity_tiers'].includes(mode)&&!/^[1-9]\d{0,19}$/.test(id))return invalid('类目来源须填写已核实的 Admin 类目 ID；不猜类目。');
        g.random_source={...(g.random_source||{}),mode,category_id:['models','quantity_tiers'].includes(mode)?null:id,snapshot_complete:false};
      }
      if(g.random_source?.mode==='quantity_tiers'){
        const unit=field('qunit',i)?.value.trim(),fixedQuantity=field('qfixed',i)?.value.trim(),random=[field('qrandom0',i)?.value.trim(),field('qrandom1',i)?.value.trim()];
        if(!unit||[fixedQuantity,...random].some(v=>!/^\d+(?:\.\d{1,6})?$/.test(v||'')||Number(v)<=0)||new Set([fixedQuantity,...random].map(Number)).size!==3)return invalid('请填写同一单位下三个不同的有效数量档位，不能用区服代替。');
        g.fixed_quantity={value:fixedQuantity,unit,conversion_verified:false};g.random_quantities=random.map(value=>({value,unit}));g.random_models=[];
      }else if(g.random_quantities)delete g.random_quantities;
      if(g.random_source?.mode==='category_dynamic'&&g.random_models.length)return invalid('动态类目不能混合静态勾选模型，请明确取消本地列表。');
      if(g.fixed_model&&g.random_models.includes(g.fixed_model))return invalid('固定模型不能同时进入随机池。');
    }
    const weights=[...document.querySelectorAll('[data-h-weight]')];
    if(weights.some(changed)){
      if(weights.every(el=>el.value===''))h.probabilities=null;
      else{
        if(weights.some(el=>el.value===''||!Number.isInteger(Number(el.value))||Number(el.value)<0)||weights.reduce((sum,el)=>sum+Number(el.value),0)!==10000)return invalid('三个权重必须同时配置为非负整数，合计10000；不会默认等概率。');
        const values=new Map(weights.map(el=>[Number(el.dataset.hWeight),Number(el.value)])),order=h.probabilities?.map(row=>row.off_percent)||weights.map(el=>Number(el.dataset.hWeight));
        h.probabilities=order.map(off_percent=>({off_percent,weight:values.get(off_percent)}));
      }
    }
    if(changed($('h-binding')))h.tier_product_binding=$('h-binding').value||null;
    for(const [key,id] of [['starts_at','h-start'],['ends_at','h-end']])if(changed($(id))){const v=$(id).value.trim();if(v&&(!/(Z|[+-]\d{2}:\d{2})$/.test(v)||!Number.isFinite(Date.parse(v))))return invalid('时间须含明确时区；留空保持未配置。');h[key]=v||null;}
    if(h.starts_at&&h.ends_at&&Date.parse(h.starts_at)>=Date.parse(h.ends_at))return invalid('截止时间必须晚于开始时间。');
    if(!same(original,h))state.draft.halloween=h;halloweenDirty=false;halloweenShown=new Map([...halloweenShown.keys()].map(el=>[el,el.type==='checkbox'?el.checked:el.value]));return true;
  }

  const roleOptions={'seasonal-vault':['preview','pool','fixed','both']};
  const roleLabels={preview:'资料预览 / 未分配',player:'球员展示',bundle:'固定组合展示',core:'SBC 核心展示',companion:'搭档展示',pool:'随机池',fixed:'固定区',both:'随机池及固定区'};
  function renderPageProducts(){
    if(selectedPage.startsWith('fc27-')){$('page-products').parentElement.hidden=true;$('page-products').innerHTML='';return;}$('page-products').parentElement.hidden=false;
    const page=state.draft.pages.find(p=>p.page_id===selectedPage),items=[...(state.catalog_products||[]),...(state.draft.imported_products||[])];
    const allowed=items.filter(p=>p.preview_only||p.key.startsWith('seasonal-')).filter(p=>!pageKeys(page).includes(p.key)&&(!selectedPage.startsWith('fc27-')||p.product_ref?.game_id==='1327'));
    $('page-products').innerHTML='<label>重新选入已核原稿或已导入商品<select id="existing-product"><option value="">请选择</option>'+allowed.map(p=>'<option value="'+escape(p.key)+'">'+escape(p.title||p.key)+' · '+escape(p.key)+'</option>').join('')+'</select></label><button type="button" class="fs-btn" id="add-existing-product">选入本页（尚未保存）</button>'+ '<ol>'+pageKeys(page).map((key,i)=>{const p=items.find(p=>p.key===key);return '<li>'+escape(p?.title||key)+' <small>'+escape(key)+(p?.preview_only?' · 资料预览 / 规格与价格待核':' · 原稿映射 / 购买保持关闭')+'</small> <label>本页展示位置<select data-role-key="'+escape(key)+'"><option value="">沿用原稿 / 新商品未分配</option>'+roleOptions[selectedPage].map(role=>'<option value="'+role+'" '+(page.product_roles?.[key]===role?'selected':'')+'>'+roleLabels[role]+'</option>').join('')+'</select></label> <button type="button" class="fs-btn" data-product-up="'+i+'" '+(i?'':'disabled')+'>上移</button> <button type="button" class="fs-btn" data-product-remove="'+i+'">从本页移除</button></li>';}).join('')+'</ol>'+'<p>本页选择与编排均保存在同一草稿；未核定商品仅作资料预览，不生成购买规格或价格。</p>';
  }

  function prunePairs(page){if(!page.sbc_companions)return;const keys=new Set(pageKeys(page));page.sbc_companions=Object.fromEntries(Object.entries(page.sbc_companions).filter(([key])=>keys.has(key)&&page.product_roles?.[key]==='core').map(([key,values])=>[key,values.filter(k=>keys.has(k)&&page.product_roles?.[k]==='companion')]));}
  $('page-select').addEventListener('change',()=>{state.draft=readForm();if(!collectHalloween()){$('page-select').value=selectedPage;$('center-error').textContent=$('halloween-status').textContent;return;}selectedPage=$('page-select').value;inspected=null;modelDetail=null;render();});
  $('page-products').addEventListener('click',event=>{const up=event.target.closest('[data-product-up]'),remove=event.target.closest('[data-product-remove]');if(!up&&!remove||busy||pending)return;state.draft=readForm();const page=state.draft.pages.find(p=>p.page_id===selectedPage);page.product_keys=[...pageKeys(page)];const i=Number(up?up.dataset.productUp:remove.dataset.productRemove);if(up&&i>0)[page.product_keys[i-1],page.product_keys[i]]=[page.product_keys[i],page.product_keys[i-1]];else if(remove){const [key]=page.product_keys.splice(i,1);if(page.product_roles)delete page.product_roles[key];prunePairs(page);}dirty=true;renderPageProducts();lock();});
  $('page-products').addEventListener('change',event=>{if(!event.target.dataset.roleKey||busy||pending)return;state.draft=readForm();const page=state.draft.pages.find(p=>p.page_id===selectedPage);page.product_keys=[...pageKeys(page)];page.product_roles||={};if(event.target.value)page.product_roles[event.target.dataset.roleKey]=event.target.value;else delete page.product_roles[event.target.dataset.roleKey];prunePairs(page);dirty=true;renderPageProducts();lock();});
  $('page-products').addEventListener('click',event=>{if(event.target.id!=='add-existing-product'||busy||pending)return;const key=$('existing-product').value;if(!key)return;state.draft=readForm();const page=state.draft.pages.find(p=>p.page_id===selectedPage);page.product_keys=[...pageKeys(page)];if(!page.product_keys.includes(key))page.product_keys.push(key);dirty=true;renderPageProducts();lock();});
  $('page-products').addEventListener('change',event=>{const core=event.target.dataset.coreKey,key=event.target.dataset.companionKey;if(!core||!key||busy||pending)return;state.draft=readForm();const page=state.draft.pages.find(p=>p.page_id===selectedPage);page.sbc_companions||={};const selected=new Set(page.sbc_companions[core]||[]);if(event.target.checked)selected.add(key);else selected.delete(key);page.sbc_companions[core]=[...selected];dirty=true;lock();});


  const platformNames={ps:'PS',xbox:'Xbox',pc:'PC'};
  const layout=()=>state.draft.fc_layout??state.effective_fc_layout;
  const page=()=>state.draft.pages.find(p=>p.page_id===selectedPage);
  const productFor=key=>{const p=state.fc_catalog?.products?.[key];if(!p||p.platforms)return p;const variants=(state.catalog_products||[]).filter(row=>row.key.startsWith('fc-'+key+'-'));return {...p,image:p.image||variants.find(row=>row.image)?.image,platforms:Object.fromEntries(['ps','xbox','pc'].map(code=>{const row=variants.find(row=>row.key==='fc-'+key+'-'+code);return [code,{id:row?.product_ref?.goods_id??null,binding_state:row?'accepted_snapshot':'unknown'}];}))};};
  const refsFor=key=>['ps','xbox','pc'].map(platform=>'fc-'+key+'-'+platform);
  const selectedPlatforms=key=>['ps','xbox','pc'].filter(platform=>pageKeys(page()).includes('fc-'+key+'-'+platform));
  function layoutIds(d){return selectedPage==='fc27-weekly'?d.weekly:selectedPage==='fc27-trio'?[...d.trio,...d.bundles]:[...d.sbc,...d.sbc.flatMap(key=>[...(d.routes[key]?.picks||[]),...(d.routes[key]?.alternatives||[])])];}
  function bindingMarkup(p){return '<details><summary>三平台关联 / 当前本页选择'+(refsFor(p.key).some(ref=>page().product_roles?.[ref]==='preview')?' · 仅资料预览，不进入此业务位':'')+'</summary>'+['ps','xbox','pc'].map(code=>{const row=p.platforms?.[code],selected=selectedPlatforms(p.key).includes(code);const role=page().product_roles?.['fc-'+p.key+'-'+code];return '<p class="platform-row">'+platformNames[code]+' · '+(selected?'本页已选':'本页未选')+' · 商品 '+escape(row?.id??row?.product_ref?.goods_id??'暂无可用关联')+' · '+escape(row?.binding_state??row?.state??(row?.id?'原快照':'unknown'))+' · 原角色 '+escape(role||'继承原业务')+(role==='preview'?'（仅资料预览，不进入此业务位）':'')+'</p>';}).join('')+'</details>';}
  function modelCard(key,actions=''){
    const p=productFor(key);if(!p)return '<article class="model-card">保留的模型 '+escape(key)+'：资料暂不可读，请核对后再修改。</article>';
    const mask=selectedPlatforms(key),partial=mask.length!==3||refsFor(key).some(ref=>page().product_roles?.[ref]==='preview');
    return '<article class="model-card" data-model-card="'+escape(key)+'">'+(p.preview_only?'<div class="fc-activity">'+window.FCActivityContent.previewCard(p,{platform:modelPreviewPlatform,...(mediaRef('card:'+key)?{image:'api/center/assets/'+mediaRef('card:'+key).asset_id,alt:mediaRef('card:'+key).alt}:{})})+'</div>':p.image?'<img src="'+escape(p.image.startsWith('https://')?p.image:'../'+p.image)+'" alt="'+escape(p.title||p.name)+'">':'<div class="image-placeholder">图片缺失，待上传本版本图片</div>')+'<h4>'+escape(p.title||p.name||key)+'</h4><p>模型 '+escape(p.model_id??'原已接受卡')+' · 版本 '+escape(p.version??'未核实')+(p.preview_only?' · 仅预览，无报价/购买':' · 原卡逻辑保留')+'</p>'+bindingMarkup(p)+(partial?'<p>保留旧平台选择：'+escape(mask.map(x=>platformNames[x]).join(' / ')||'无')+'。读取不会自动补全。</p><button type="button" class="fs-btn" data-whole-card="'+escape(key)+'">用于本页业务位置，并选择 PS / Xbox / PC</button>':'')+actions+'</article>';
  }
  function targetOptions(d){
    if(selectedPage==='fc27-weekly')return [['weekly','Weekly 推荐卡','player']];
    if(selectedPage==='fc27-trio')return [...d.trio.map((_,i)=>['trio:'+i,'Trio 位置 '+(i+1),'player']),['bundle','固定包','bundle']];
    return [['core','SBC 核心服务','sbc'],...d.sbc.flatMap(key=>[['pick:'+key+':0',(productFor(key)?.name||key)+' · 搭档 1','player'],['pick:'+key+':1',(productFor(key)?.name||key)+' · 搭档 2','player'],['alternative:'+key,(productFor(key)?.name||key)+' · 备选搭档','player']])];
  }
  function renderFcLayout(){
    const box=$('fc-layout'),c=state.fc_catalog,d=layout();box.hidden=!selectedPage.startsWith('fc27-')||!c||!d;if(box.hidden){box.innerHTML='';return;}
    const oldTarget=$('model-target').value,targets=targetOptions(d);$('model-target').innerHTML=targets.map(([key,title,kind])=>'<option value="'+escape(key)+'" data-kind="'+kind+'">'+escape(title)+'</option>').join('');if(targets.some(x=>x[0]===oldTarget))$('model-target').value=oldTarget;
    const products=Object.values(c.products),players=products.filter(p=>p.kind==='player'),options=(list,id)=>list.map(p=>'<option value="'+escape(p.key)+'" '+(p.key===id?'selected':'')+'>'+escape(p.title||p.name||p.key)+'</option>').join('');
    let html='';
    if(selectedPage==='fc27-weekly')html='<h3>Weekly · 1–6 张模型卡</h3>'+d.weekly.map((key,i)=>modelCard(key,'<button type="button" class="fs-btn" data-card-up="'+i+'" '+(i?'':'disabled')+'>卡片上移</button><button type="button" class="fs-btn" data-layout-remove="weekly:'+escape(key)+'">移除此卡</button>')).join('');
    if(selectedPage==='fc27-trio')html='<h3>Trio · 三个固定位置</h3>'+d.trio.map((key,i)=>'<fieldset><legend>位置 '+(i+1)+'</legend><label>已接受的球员版本<select data-trio="'+i+'">'+options(players,key)+'</select></label>'+modelCard(key)+'</fieldset>').join('')+'<h3>独立固定包</h3>'+d.bundles.map(key=>modelCard(key,'<button type="button" class="fs-btn" data-layout-remove="bundles:'+escape(key)+'">移除固定包</button>')).join('');
    if(selectedPage==='fc27-sbc')html='<h3>SBC 核心 / 搭档</h3><label>默认核心<select id="layout-default-core">'+options(products.filter(p=>d.sbc.includes(p.key)),d.defaultCore)+'</select></label>'+d.sbc.map(key=>{const route=d.routes[key]||{picks:[],alternatives:[]};return '<fieldset data-layout-core="'+escape(key)+'"><legend>'+escape(c.products[key]?.title||key)+'</legend>'+modelCard(key,'<button type="button" class="fs-btn" data-layout-remove="sbc:'+escape(key)+'">移除此核心</button>')+[0,1].map(i=>'<label>搭档 '+(i+1)+'<select data-layout-pick="'+i+'"><option value="">请选择</option>'+options(players,route.picks[i])+'</select></label>'+(route.picks[i]?modelCard(route.picks[i]):'')).join('')+'<details><summary>备选搭档</summary>'+players.map(p=>'<label class="check"><input type="checkbox" data-alternative="'+escape(p.key)+'" '+(route.alternatives.includes(p.key)?'checked':'')+'>'+escape(p.title||p.name)+'</label>').join('')+'</details></fieldset>';}).join('');
    const legacy=state.page_bindings?.[selectedPage]?.legacy_refs??pageKeys(page()).filter(key=>!key.startsWith('fc-'));
    box.innerHTML=html+(legacy.length?'<details><summary>保留的旧导入引用（不冒充推荐模型卡）</summary><p>这些旧记录仍在草稿，只有明确移除才改变；请用模型检索核对后替换。</p>'+legacy.map(key=>'<p>'+escape(key)+' <button type="button" class="fs-btn" data-remove-legacy="'+escape(key)+'">明确从本页移除</button></p>').join('')+'</details>':'');
    $('model-detail').hidden=!modelDetail;if(!modelDetail)$('model-results').innerHTML='';
  }
  function syncLayoutSelection(p,d,previous,whole=[]){
    const before=new Set(layoutIds(previous)),after=new Set(layoutIds(d)),removed=new Set([...before].filter(id=>!after.has(id))),added=[...after].filter(id=>!before.has(id));
    p.product_keys=[...new Set([...pageKeys(p).filter(key=>![...removed].some(id=>refsFor(id).includes(key))),...[...added,...whole].flatMap(refsFor)])];
    const rank=key=>layoutIds(d).findIndex(id=>refsFor(id).includes(key));const ordered=p.product_keys.filter(key=>rank(key)>=0).sort((a,b)=>rank(a)-rank(b));p.product_keys=p.product_keys.map(key=>rank(key)<0?key:ordered.shift());
    if(added.length||whole.length){p.product_roles||={};for(const id of [...added,...whole])for(const ref of refsFor(id))p.product_roles[ref]=selectedPage==='fc27-sbc'?(d.sbc.includes(id)?'core':'companion'):selectedPage==='fc27-trio'&&d.bundles.includes(id)?'bundle':'player';}
    if(p.product_roles)p.product_roles=Object.fromEntries(Object.entries(p.product_roles).filter(([key])=>p.product_keys.includes(key)));prunePairs(p);
  }
  function applyLayout(d,previous,whole=[]){state.draft.fc_layout=d;syncLayoutSelection(page(),d,previous,whole);renderFcLayout();renderMaterials();lock();}
  $('fc-layout').addEventListener('click',event=>{
    if(busy||pending||!state?.canEdit)return;const preview=event.target.closest('[data-preview-platform]');if(preview){modelPreviewPlatform=preview.dataset.previewPlatform;renderFcLayout();return;}const up=event.target.closest('[data-card-up]'),remove=event.target.closest('[data-layout-remove]'),whole=event.target.closest('[data-whole-card]'),legacy=event.target.closest('[data-remove-legacy]');if(!up&&!remove&&!whole&&!legacy)return;
    state.draft=readForm();const previous=structuredClone(layout()),d=structuredClone(previous);
    if(legacy){page().product_keys=pageKeys(page()).filter(key=>key!==legacy.dataset.removeLegacy);if(page().product_roles)delete page().product_roles[legacy.dataset.removeLegacy];prunePairs(page());renderFcLayout();lock();return;}
    if(whole){applyLayout(d,previous,[whole.dataset.wholeCard]);return;}
    if(up){const i=Number(up.dataset.cardUp);[d.weekly[i-1],d.weekly[i]]=[d.weekly[i],d.weekly[i-1]];}
    if(remove){const [list,key]=remove.dataset.layoutRemove.split(':');if(['weekly','sbc'].includes(list)&&d[list].length<=1){$('center-error').textContent='此结构至少保留一张卡，请先选择替换版本。';return;}d[list]=d[list].filter(id=>id!==key);if(list==='sbc'){delete d.routes[key];if(d.defaultCore===key)d.defaultCore=d.sbc[0]||null;}}
    applyLayout(d,previous);
  });
  $('fc-layout').addEventListener('change',event=>{
    if(busy||pending||!state?.canEdit)return;state.draft=readForm();const previous=structuredClone(layout()),d=structuredClone(previous),el=event.target;
    if(el.dataset.trio!=null){const index=Number(el.dataset.trio),other=d.trio.indexOf(el.value),old=d.trio[index];if(other>=0&&other!==index)d.trio[other]=old;d.trio[index]=el.value;}
    else if(el.id==='layout-default-core')d.defaultCore=el.value;
    else{const key=el.closest('[data-layout-core]')?.dataset.layoutCore;if(!key)return;if(el.dataset.layoutPick!=null)d.routes[key].picks[Number(el.dataset.layoutPick)]=el.value;else if(el.dataset.alternative)d.routes[key].alternatives=[...el.closest('[data-layout-core]').querySelectorAll('[data-alternative]:checked')].map(x=>x.dataset.alternative);else return;}
    if(!same(d,previous))applyLayout(d,previous);
  });

  function modelKind(){return $('model-target').selectedOptions[0]?.dataset.kind;}
  function modelIdentity(p){return ['ps','xbox','pc'].map(code=>{const row=(p.platforms? p:productFor(p.key))?.platforms?.[code];return row?.id??row?.product_ref?.goods_id??null;});}
  function matchingKey(model){
    if(productFor(model.key))return model.key;const ids=modelIdentity(model);if(ids.some(x=>!x))return model.key;
    return Object.values(state.fc_catalog.products).find(p=>modelIdentity(p).every((id,i)=>id!=null&&String(id)===String(ids[i])))?.key||model.key;
  }
  function targetLayout(d,key){
    const [slot,core,index]=$('model-target').value.split(':');
    if(slot==='weekly'){if(!d.weekly.includes(key)){if(d.weekly.length>=6)throw Error('Weekly 最多 6 张卡，请先明确移除一张。');d.weekly.unshift(key);}}
    if(slot==='core'){if(!d.sbc.includes(key))d.sbc.push(key);const picks=[0,1].map(i=>$('new-core-pick-'+i)?.value);if(picks.some(x=>!x)||picks[0]===picks[1])throw Error('请明确选择两位不同搭档，再加入新核心。');d.routes[key]||={picks,alternatives:[],label:{en:'Companion ideas'}};d.defaultCore||=key;}
    if(slot==='trio'){const i=Number(core),other=d.trio.indexOf(key),previous=d.trio[i];if(other>=0&&other!==i)d.trio[other]=previous;d.trio[i]=key;}
    if(slot==='bundle'&&!d.bundles.includes(key))d.bundles.push(key);
    if(slot==='pick'){if(d.routes[core].picks[1-Number(index)]===key)throw Error('两位搭档必须不同。');d.routes[core].picks[Number(index)]=key;}
    if(slot==='alternative'&&!d.routes[core].alternatives.includes(key))d.routes[core].alternatives.push(key);
    return d;
  }
  function modelError(error){const code=error.message||error.code;const messages={MODEL_ALIAS_REQUIRED:'该中文名称尚未配置别名，请使用英文名称或模型 ID；没有退回全部商品。',CATALOG_SEARCH_TIMEOUT:'查询超时，未取得结果，请稍后重试。',MODEL_SITE_ASSOCIATION_MISSING:'这个模型尚未关联 MMOEXP 商品，不能据此添加可用平台。',MODEL_SCOPE_MISMATCH:'模型类型不符合当前业务位置，请选择对应的 Player、SBC 或固定包。',MODEL_BINDING_CHANGED:'同一模型的后台关联已变化，为避免影响其他页，本次未覆盖，请核对原配置。',DUPLICATE_PAGE_PRODUCT:'同一平台商品已在本页其他模型卡中，请复用原卡，避免重复。'};return messages[code]?(messages[code]+' ['+code+']'):code;}
  async function resolveModel(id){
    if(busy||pending)return;busy=true;lock();modelDetail=null;$('model-detail').hidden=true;
    try{const result=await request('api/center/backend-read',{action:'model_resolve',site_id:'266',game_id:'1327',kind:modelKind(),model_id:id});modelDetail=result.data?.model;if(!modelDetail||modelDetail.model_id!==id)throw Error('模型回执 ID 不匹配。');
      const normalized={...modelDetail,version:modelDetail.version_label,image:modelDetail.image_url,preview_only:true};
      $('model-detail').innerHTML='<h4>'+escape(modelDetail.title||'模型标题未知')+'</h4><p>模型 '+escape(id)+' · '+escape(modelDetail.version_label||'版本未验证')+'</p><div class="fc-activity" id="resolved-preview">'+window.FCActivityContent.previewCard(normalized,{platform:modelPreviewPlatform})+'</div><p>这份回执只核对身份和平台，不是报价或成交。</p>'+(modelKind()==='sbc'?[0,1].map(i=>'<label>新核心搭档 '+(i+1)+'<select id="new-core-pick-'+i+'"><option value="">请选择已有 Player 版本</option>'+Object.values(state.fc_catalog.products).filter(p=>p.kind==='player').map(p=>'<option value="'+escape(p.key)+'">'+escape(p.title||p.name)+'</option>').join('')+'</select></label>').join(''):'')+'<button id="choose-model" class="fs-btn" type="button">'+(selectedPage==='fc27-weekly'?'添加到推荐首位':'加入当前业务位置')+(matchingKey(modelDetail)!==modelDetail.key?'（复用原卡）':'（未保存）')+'</button>';$('model-detail').hidden=false;
      $('model-status').textContent=matchingKey(modelDetail)!==modelDetail.key?'三平台商品与已接受卡精确相同，将复用原卡，避免重复。':'请核对完整版本与三平台状态；缺图须上传本版本素材。';
    }catch(error){$('model-status').textContent=modelError(error);}finally{busy=false;lock();}
  }
  $('model-target').addEventListener('change',()=>{modelDetail=null;$('model-detail').hidden=true;$('model-results').innerHTML='';$('model-status').textContent='业务位置已变更，请重新检索对应模型类型。';});
  $('search-model').addEventListener('click',async()=>{
    if(busy||pending||!state?.canEdit)return;const query=$('model-query').value.trim(),kind=modelKind();if(!query||!kind)return;
    if(/^\d+$/.test(query)){$('model-status').textContent='数字输入按准确模型 ID 查询；不是商品 ID 或 SKU。';await resolveModel(query);return;}
    if(query.length<2||query.length>80){$('model-status').textContent='请输入 2–80 字符的名称，或准确模型 ID。';return;}
    busy=true;lock();modelDetail=null;$('model-detail').hidden=true;$('model-results').innerHTML='';
    try{const result=await request('api/center/backend-read',{action:'model_search',site_id:'266',game_id:'1327',kind,keyword:query,page:1,page_size:10}),data=result.data;if(!Array.isArray(data?.items))throw Error('模型检索未返回可核对结果。');const receipt=data.name_query;
      $('model-status').textContent=(receipt?.alias_applied?'名称别名回执：'+receipt.input+' → '+receipt.resolved+'（'+receipt.source+'）。':'按原名称检索；未做隐式翻译。')+' 共 '+data.total+' 个版本；请选择完整标题。'+(data.has_more?' 当前展示前 10 项，请缩小名称。':'');
      $('model-results').innerHTML=data.items.map(item=>'<p><button class="fs-btn" type="button" data-model-id="'+escape(item.model_id)+'">'+escape(item.title||'模型标题未知')+' · 模型 '+escape(item.model_id)+'</button></p>').join('');
    }catch(error){$('model-status').textContent=modelError(error);}finally{busy=false;lock();}
  });
  $('model-results').addEventListener('click',event=>{const button=event.target.closest('[data-model-id]');if(button)resolveModel(button.dataset.modelId);});
  $('model-detail').addEventListener('click',async event=>{
    const platform=event.target.closest('[data-preview-platform]');if(platform&&modelDetail){modelPreviewPlatform=platform.dataset.previewPlatform;$('resolved-preview').innerHTML=window.FCActivityContent.previewCard({...modelDetail,version:modelDetail.version_label,image:modelDetail.image_url,preview_only:true},{platform:modelPreviewPlatform});return;}
    if(event.target.id!=='choose-model'||busy||pending||!modelDetail||!state?.canEdit)return;
    try{state.draft=readForm();const previous=structuredClone(layout()),key=matchingKey(modelDetail),d=targetLayout(structuredClone(previous),key);if(layoutIds(previous).includes(key)&&same(previous,d)&&selectedPlatforms(key).length===3&&!refsFor(key).some(ref=>page().product_roles?.[ref]==='preview')){$('model-status').textContent='同一模型版本已在本页该结构内，未重复添加或改变旧平台选择。';return;}
      const draft=structuredClone(state.draft);state.draft=draft;state.draft.fc_layout=d;syncLayoutSelection(page(),d,previous,[key]);
      if(productFor(key)&&!key.startsWith('model-')){modelDetail=null;render();return;}
      if(!productFor(key)){
        stagedModels.push({page_id:selectedPage,model_id:modelDetail.model_id,kind:modelKind()});
        state.fc_catalog.products[key]={...modelDetail,version:modelDetail.version_label,image:modelDetail.image_url,preview_only:true};
      }else if(key.startsWith('model-')&&!state.draft.fc_models?.[key]&&!stagedModels.some(m=>m.model_id===modelDetail.model_id&&m.page_id===selectedPage))stagedModels.push({page_id:selectedPage,model_id:modelDetail.model_id,kind:modelKind()});
      modelDetail=null;render();$('model-status').textContent='已加入本页未保存配置；可继续配置素材与优惠，统一预览或发布。';
    }catch(error){$('model-status').textContent=modelError(error);}
  });
  const uploadStorageKey='fs-media-upload:'+location.pathname;
  function uploadDB(){return new Promise((resolve,reject)=>{const request=indexedDB.open('fs-campaign-uploads',1);request.onupgradeneeded=()=>request.result.createObjectStore('bytes');request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(Error('无法保留上传原始文件，未发起上传。'));});}
  async function uploadBytes(id,value,remove=false){const db=await uploadDB();return new Promise((resolve,reject)=>{const transaction=db.transaction('bytes',value||remove?'readwrite':'readonly'),store=transaction.objectStore('bytes'),request=remove?store.delete(id):value?store.put(value,id):store.get(id);let result;request.onsuccess=()=>{result=request.result;};request.onerror=()=>reject(Error('无法保留原始上传文件。'));transaction.oncomplete=()=>{db.close();resolve(result);};transaction.onerror=()=>reject(Error('无法保留原始上传文件。'));});}
  function retainUpload(record){sessionStorage.setItem(uploadStorageKey,JSON.stringify(record));uploadRecord=record;lock();}
  function mediaRef(target){return target.startsWith('card:')?page().media?.cards?.[target.slice(5)]:page().media?.[target];}
  function originalMaterial(target){if(selectedPage==='seasonal-vault'&&target.startsWith('card:game:')){const n=['fc','aion','wow','maplestory'].indexOf(target.slice(10));return n<0?null:'../seasonal/assets/game-'+(n+1)+'.png';}if(target.startsWith('card:')){const image=productFor(target.slice(5))?.image;return image?(image.startsWith('https://')?image:'../'+image):null;}const choices=imageChoices[selectedPage]||[],seasonal=selectedPage==='seasonal-vault';if(seasonal)return '../seasonal/assets/hero-'+(state.draft.seasonal_theme||'halloween')+'.webp';if(target==='share'&&page().social_image&&page().social_image!=='original')return '../'+page().social_image;return choices.length?'../'+choices[target==='hero_mobile'?1:0]:null;}
  function renderMaterials(){
    const d=layout(),keys=selectedPage.startsWith('fc27-')&&d?[...new Set(layoutIds(d))]:selectedPage==='seasonal-vault'?['game:fc','game:aion','game:wow','game:maplestory',...pageKeys(page())]:[],slots=[['hero_desktop','主视觉 · 桌面'],['hero_mobile','主视觉 · 手机'],['share','社交分享图'],...keys.map(key=>['card:'+key,'卡图 · '+(productFor(key)?.title||key)])],old=$('media-target').value;
    $('media-target').innerHTML=slots.map(([key,label])=>'<option value="'+escape(key)+'">'+escape(label)+'</option>').join('');if(slots.some(x=>x[0]===old))$('media-target').value=old;
    $('page-materials').innerHTML=slots.map(([key,label])=>{const ref=mediaRef(key),original=originalMaterial(key);return '<div><h4>'+escape(label)+'</h4>'+(ref?'<img class="material-thumb" src="api/center/assets/'+escape(ref.asset_id)+'" alt="'+escape(ref.alt)+'"><p>已绑定草稿素材 · '+escape(ref.asset_id)+'</p><button class="fs-btn" type="button" data-clear-media="'+escape(key)+'">清除本页覆盖，沿用原图</button>':(original?'<img class="material-thumb" src="'+escape(original)+'" alt="Original material preview"><p>沿用原页面 / 本版本原图；未添加覆盖。</p>':'<div class="image-placeholder">本版本缺图，待上传；不拿其他版本替代。</div>'))+'</div>';}).join('');
  }
  function showUpload(){if(!uploadRecord?.asset)return;$('media-preview').src=uploadRecord.preview_url;$('media-candidate').hidden=false;$('media-status').textContent='目标 '+uploadRecord.page_id+' / '+uploadRecord.target+'；上传已完成，仅私有预览；尚未绑定草稿或发布。';$('media-confirm').checked=false;}
  async function sendUpload(){
    if(!uploadRecord||busy)return;busy=true;lock();
    try{const file=await uploadBytes(uploadRecord.id);if(!file)throw Error('原文件尚不可恢复；请保留原操作记录并联系维护。');const response=await fetch('api/center/assets/upload?operation_id='+encodeURIComponent(uploadRecord.id),{method:'POST',credentials:'same-origin',headers:{'Content-Type':file.type,'X-CSRF-Token':state.csrf},body:file});const result=await response.json();if(!response.ok)throw Object.assign(Error(result.code||'上传未确认'),{status:response.status});retainUpload({...uploadRecord,unknown:false,asset:result.asset,preview_url:result.preview_url});await uploadBytes(uploadRecord.id,null,true);showUpload();
    }catch(error){if([400,403,413,415,422].includes(error.status)){retainUpload({...uploadRecord,unknown:false,rejected:true});await uploadBytes(uploadRecord.id,null,true);$('media-candidate').hidden=false;$('media-preview').hidden=true;$('media-status').textContent=error.message+' 上传已明确拒绝，可取消后重新选文件，草稿未改变。';}else $('media-status').textContent=error.message+' 原上传 ID 与原始文件已保留，请核对原上传，不另建 ID。';}finally{busy=false;lock();}
  }
  $('upload-media').addEventListener('click',async()=>{if(busy||pending||uploadRecord||!state?.canEdit)return;const file=$('media-file').files[0];if(!file||!['image/png','image/jpeg','image/webp'].includes(file.type)){$('media-status').textContent='请选择 PNG、JPEG 或 WebP 图片。';return;}try{const id=crypto.randomUUID();await uploadBytes(id,file);retainUpload({id,page_id:selectedPage,target:$('media-target').value,unknown:true});await sendUpload();}catch(error){$('media-status').textContent=error.message;}});
  $('recover-upload').addEventListener('click',sendUpload);
  $('cancel-media').addEventListener('click',async()=>{if(uploadRecord?.unknown){$('media-status').textContent='原上传结果未知；请先核对原操作，不更换 ID。';return;}if(uploadRecord)await uploadBytes(uploadRecord.id,null,true);retainUpload(null);$('media-candidate').hidden=true;$('media-preview').hidden=false;$('media-file').value='';$('media-status').textContent='已取消素材绑定，草稿保持原形。';});
  function applyPendingMedia(){
    if(!uploadRecord)return true;
    if(uploadRecord.unknown||uploadRecord.rejected||!uploadRecord.asset)throw Error('素材上传尚未确认，请核对原上传或取消已拒绝的文件。');
    if(selectedPage!==uploadRecord.page_id)throw Error('请返回原素材目标页后继续，未改变其他页面。');
    const alt=$('media-alt').value.trim();
    if(!$('media-confirm').checked||!alt||/[<>\u0000-\u001f]|\p{Script=Han}/u.test(alt))throw Error('请预览素材，确认没有中文，并填写英文图片说明。');
    const p=page(),ref={asset_id:uploadRecord.asset.asset_id,alt,public_english_confirmed:true};p.media||={};
    if(uploadRecord.target.startsWith('card:')){p.media.cards||={};p.media.cards[uploadRecord.target.slice(5)]=ref;}else p.media[uploadRecord.target]=ref;
    retainUpload(null);$('media-candidate').hidden=true;renderMaterials();return true;
  }
  $('page-materials').addEventListener('click',event=>{const button=event.target.closest('[data-clear-media]');if(!button||busy||pending)return;state.draft=readForm();const key=button.dataset.clearMedia;if(key.startsWith('card:')){delete page().media.cards[key.slice(5)];if(!Object.keys(page().media.cards).length)delete page().media.cards;}else delete page().media[key];if(!Object.keys(page().media).length)delete page().media;renderMaterials();lock();});
  try{uploadRecord=JSON.parse(sessionStorage.getItem(uploadStorageKey)||'null');if(uploadRecord?.asset)showUpload();else if(uploadRecord?.rejected){$('media-candidate').hidden=false;$('media-preview').hidden=true;$('media-status').textContent='原上传已明确拒绝，可取消后选择其他文件。';}}catch{$('media-status').textContent='原上传记录不可读，请保留会话并核对。';}

  const allowedGames=new Set(['1327','1329','1309','456','552','891','1367','1333']);
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
  $('add-product').addEventListener('click',()=>{
    if(busy||pending||!inspected||!state?.canEdit)return;state.draft=readForm();if(!collectHalloween()){$('center-error').textContent=$('halloween-status').textContent;return;}
    const ref=inspected.product_ref,aid=inspected.platform_attribute_id&&inspected.platform_attribute_id!=='0'?inspected.platform_attribute_id:'unknown',key='admin-'+[ref.site_id,ref.game_id,ref.goods_id,aid].join('-')+(ref.sku_id?'-sku-'+ref.sku_id:'');
    if(!pageKeys(page()).includes(key)){page().product_keys=[...pageKeys(page()),key];stagedProducts.push({page_id:selectedPage,product_ref:structuredClone(ref),key});}
    if(!state.catalog_products.some(p=>p.key===key))state.catalog_products.push({key,title:inspected.title,product_ref:structuredClone(ref),preview_only:true,available:false,quantity:null,platform:{...(aid==='unknown'?{}:{attribute_id:aid})}});
    renderPageProducts();renderHalloween();lock();$('center-status').textContent='商品已选入本页未保存配置；统一预览或发布时重新核验，不会立即保存。';
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
