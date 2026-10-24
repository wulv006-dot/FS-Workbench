(function(){
  'use strict';
  const $=id=>document.getElementById(id),escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const publicPrefix=document.documentElement.dataset.campaignPublicPrefix||'/events/',publicPrefixValid=/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(publicPrefix);
  const storageKey='fs-center-pending:'+location.pathname;
  let state=null,catalog=[],busy=false,dirty=false,pending=null,discovered=[],discoveredGame=null;
  try{pending=JSON.parse(sessionStorage.getItem(storageKey)||'null');}catch{$('center-error').textContent='无法读取原操作记录；请保留当前会话并联系维护人员核对。';return;}
  function persist(value){sessionStorage.setItem(storageKey,JSON.stringify(value));pending=value;}
  async function request(path,body){const response=await fetch(path,{credentials:'same-origin',cache:'no-store',...(body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify(body)}:{})});let data;try{data=await response.json();}catch{throw Error('响应无法确认，请核对原操作。');}if(!response.ok)throw Object.assign(Error(data.message||data.code||'请求失败'),{status:response.status});return data;}
  function lock(){ $('center-fields').disabled=busy||!state?.canEdit||Boolean(pending);$('read-benefits').disabled=busy||!state?.canEdit||Boolean(pending);$('publish-center').disabled=dirty;$('read-published').disabled=busy||!state?.published||Boolean(pending);$('discovery-fields').disabled=busy||!state?.canEdit||Boolean(pending);$('discover-search').disabled=!discoveredGame;$('discover-product').disabled=!discoveredGame;$('inspect-product').disabled=!discoveredGame||!$('discover-product').value; }
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
    $('center-pages').innerHTML=state.draft.pages.map((p,i)=>'<fieldset data-page="'+i+'"><legend>'+escape(p.title||p.page_id)+'</legend><p class="muted">'+escape(p.activity_id+' / '+p.page_id+' · '+p.path)+'</p><div class="config-grid"><label for="title-'+i+'">页面标题<input id="title-'+i+'" name="title" required maxlength="160" value="'+escape(p.title)+'"></label><label class="check"><input name="preview_enabled" type="checkbox" '+(p.preview_enabled?'checked':'')+'>允许预览</label><label for="start-'+i+'">开始时间 (UTC)<input id="start-'+i+'" name="starts_at" type="datetime-local" value="'+local(p.starts_at)+'" aria-errormessage="date-error-'+i+'"><span class="error-msg" id="date-error-'+i+'">结束时间必须晚于开始时间。</span></label><label for="end-'+i+'">结束时间 (UTC)<input id="end-'+i+'" name="ends_at" type="datetime-local" value="'+local(p.ends_at)+'" aria-errormessage="end-error-'+i+'"><span class="error-msg" id="end-error-'+i+'">结束时间必须晚于开始时间。</span></label></div><label for="description-'+i+'">SEO 描述<textarea id="description-'+i+'" name="description" maxlength="320">'+escape(p.description)+'</textarea></label>'+presentationControls(p,i)+'<div data-bindings="'+i+'">'+bindings(p,i)+'</div></fieldset>').join('');
    const theme=$('seasonal-theme'),value=state.draft.seasonal_theme||'halloween';
    if(typeof value==='string'){if(![...theme.options].some(o=>o.value===value))theme.add(new Option(value,value));theme.value=value;}else theme.disabled=true;
    publicationSummary();lock();
  }
  function readForm(){const draft=structuredClone(state.draft);draft.integration_mode='preview';if(typeof draft.seasonal_theme==='string'||draft.seasonal_theme==null)draft.seasonal_theme=$('seasonal-theme').value;
    for(const fieldset of document.querySelectorAll('[data-page]')){const p=draft.pages[Number(fieldset.dataset.page)],get=name=>fieldset.querySelector('[name="'+name+'"]');p.default_language=get('default_language').value;p.social_image=get('social_image').value;p.title=get('title').value.trim();p.description=get('description').value.trim();get('title').setCustomValidity(/[<>\u0000-\u001f]/.test(p.title)?'标题不能含尖括号或控制字符。':'');get('description').setCustomValidity(/[<>\u0000-\u001f]/.test(p.description)?'描述不能含尖括号或控制字符。':'');p.preview_enabled=get('preview_enabled').checked;p.starts_at=get('starts_at').value?new Date(get('starts_at').value+'Z').toISOString():null;p.ends_at=get('ends_at').value?new Date(get('ends_at').value+'Z').toISOString():null;get('ends_at').setCustomValidity(p.starts_at&&p.ends_at&&p.starts_at>=p.ends_at?'结束时间必须晚于开始时间。':'');}
    return draft;
  }
  async function load(){busy=true;lock();state=null;try{state=await request('api/center');dirty=false;render();if(pending){$('center-status').textContent='已重读服务器状态，正在用原操作 ID 核对结果。';await resolve();}else $('center-status').textContent=state.canEdit?'已读取服务器配置。':'当前账号为只读。';}catch(error){$('center-error').textContent=error.message;}finally{busy=false;lock();}}
  async function resolve(){const receipt=await request(pending.path,pending.body);const refreshed=await request('api/center');persist(null);state=refreshed;dirty=false;render();$('center-status').textContent='原操作已确认，已重新读取服务器状态。';return receipt;}
  async function mutate(path,draft){if(busy||pending||!state?.canEdit)return;busy=true;lock();$('center-error').textContent='';try{persist({path,body:{revision:state.revision,operation_id:crypto.randomUUID(),...(draft?{draft}:{})}});await resolve();$('center-status').textContent=path.endsWith('/publish')?'预览配置已发布；主站交易仍待接入。':'草稿已保存；尚未发布预览。';}catch(error){if([400,403,409,422].includes(error.status)){persist(null);state=null;state=await request('api/center');dirty=false;render();}$('center-error').textContent=error.message+(pending?' 原操作记录已保留；请点击重新读取核对，勿新建操作。':' 已重新读取服务器状态，请核对后修改。');}finally{busy=false;lock();}}
  $('center-form').addEventListener('submit',event=>{event.preventDefault();const draft=readForm();if(!$('center-form').reportValidity())return;mutate('api/center',draft);});
  $('publish-center').addEventListener('click',()=>mutate('api/center/publish'));
  $('reload-center').addEventListener('click',()=>{if(!busy)load();});
  $('center-form').addEventListener('input',()=>{dirty=true;readForm();lock();});
  $('center-form').addEventListener('change',()=>{dirty=true;readForm();lock();});
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
  const allowedGames=new Set(['1327','1329','1309','456','552','891']);
  function clearDiscovery(){discovered=[];discoveredGame=null;$('discover-search').value='';$('discover-product').innerHTML='<option value="">请先读取目录</option>';$('product-inspection').hidden=true;lock();}
  function filterProducts(){
    const query=$('discover-search').value.trim().toLocaleLowerCase();
    const rows=discovered.filter(p=>String(p.title||'').toLocaleLowerCase().includes(query)||p.product_ref.goods_id.includes(query));
    $('discover-product').innerHTML='<option value="">请选择真实商品 ID</option>'+rows.map(p=>'<option value="'+escape(p.product_ref.goods_id)+'">'+escape(p.title||'未提供标题')+' · 商品 '+escape(p.product_ref.goods_id)+' · 模型 '+escape(p.product_ref.model_id)+'</option>').join('');
    $('product-inspection').hidden=true;$('discovery-status').textContent='已完整读取 '+discovered.length+' 项；本地匹配 '+rows.length+' 项。选择仅用于资料核对，正式购买未开放。';lock();
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
  $('discover-game').addEventListener('change',()=>{clearDiscovery();$('discovery-status').textContent='游戏已变更，请重新读取该游戏完整目录。';});
  $('discover-search').addEventListener('input',filterProducts);
  $('discover-product').addEventListener('change',()=>{$('product-inspection').hidden=true;lock();});
  $('discover-products').addEventListener('click',async()=>{
    if(busy||pending||!state?.canEdit)return;const game=$('discover-game').value;if(!allowedGames.has(game))return;
    clearDiscovery();busy=true;lock();$('discovery-status').textContent='正在读取该游戏完整目录。';
    try{const result=await request('api/center/backend-read',{action:'catalog_discover',site_id:'266',game_id:game});const data=result.data;
      if(result.status!=='ok'||data?.completeness!=='complete'||!Array.isArray(data.products))throw Error('目录尚未完整读取；请核对后重试，不使用部分结果。');
      if(data.products.some(p=>p.product_ref?.site_id!=='266'||p.product_ref?.game_id!==game||typeof p.product_ref?.goods_id!=='string'||!p.product_ref.goods_id||typeof p.product_ref?.model_id!=='string'||!p.product_ref.model_id))throw Error('目录商品命名空间不完整或不匹配，仍待核验。');
      discovered=data.products;discoveredGame=game;filterProducts();
    }catch(error){$('discovery-status').textContent=error.message;}finally{busy=false;lock();}
  });
  $('inspect-product').addEventListener('click',async()=>{
    if(busy||pending||!state?.canEdit||!discoveredGame)return;
    const goods=$('discover-product').value;if(!discovered.some(p=>p.product_ref.goods_id===goods))return;
    const game=discoveredGame;busy=true;lock();$('product-inspection').hidden=true;$('discovery-status').textContent='正在读取所选商品资料。';
    try{const result=await request('api/center/backend-read',{action:'product_read',site_id:'266',game_id:game,goods_id:goods});const product=result.data?.product;
      if(result.status!=='ok'||product?.product_ref?.site_id!=='266'||product.product_ref.game_id!==game||product.product_ref.goods_id!==goods)throw Error('商品资料 ID 或所属游戏不匹配，仍待核验。');
      inspect(product);$('discovery-status').textContent='商品 '+goods+' 资料已读取；只供核对，正式购买未开放。';
    }catch(error){$('discovery-status').textContent=error.message;}finally{busy=false;lock();}
  });
  function sync(event){const el=event.target;if(!el.matches?.('input,select,textarea'))return;if(el.matches(':user-invalid'))el.setAttribute('aria-invalid','true');else el.removeAttribute('aria-invalid');}
  document.addEventListener('blur',sync,true);document.addEventListener('focus',sync,true);document.addEventListener('input',event=>{if(event.target.hasAttribute('aria-invalid'))sync(event);});
  load();
})();
