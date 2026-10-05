(() => {
  'use strict';

  async function readAdminSnapshot() {
    const url = new URL(location.href);
    const isRoute = url.pathname === '/game/admin_game_price/index.html';
    if (location.origin !== 'https://order.p2pah.cn') return null;
    if (!isRoute) return {isRoute:false,origin:location.origin,path:url.pathname,href:location.href,
      login:/login/i.test(url.pathname) || /登录|验证码/.test(document.body?.innerText || '')};

    const savedValue = cell => {
      if (!cell) return '';
      const span = cell.querySelector('span');
      if (span) return String(span.textContent || '').trim();
      return String(cell.querySelector('input')?.value ?? cell.textContent ?? '').trim();
    };
    const platformIds = {'21942':'PS','21944':'XBOX','21946':'PC'};
    const rows = [...document.querySelectorAll('table.table-list tbody tr[data-id]')].map(tr => {
      const id=String(tr.getAttribute('data-id') || '');
      const gameCell = [...tr.querySelectorAll('td')].find(td => td.getAttribute('title') === '1322');
      const nameCell = tr.querySelector('td[data-type="title"]');
      const platformSpan=String(nameCell?.querySelector('span')?.textContent || '').trim().toUpperCase();
      const platformInput=String(nameCell?.querySelector('input')?.value || '').trim().toUpperCase();
      const actualPlatform=platformInput || platformSpan;
      return {
        id:String(tr.getAttribute('data-id') || ''),
        gameId:String(gameCell?.getAttribute('title') || ''),
        platform:actualPlatform,
        platformSpan,
        expectedPlatform:platformIds[id] || '',
        costPrice:savedValue(tr.querySelector('td[data-type="costprice"]')),
        lirunlv:savedValue(tr.querySelector('td[data-type="lirunlv"]')),
        b2c:savedValue(tr.querySelector('td[data-type="b2c"]'))
      };
    });
    const game = document.querySelector('#lot-game');
    const allServer = [...document.querySelectorAll('input[name="allserver"]')];
    const websiteSelect = document.querySelector('#b2c-website');
    const selectedSelectOptions = websiteSelect ?
      [...websiteSelect.options].filter(option => option.selected && String(option.value || '')).length : 0;
    const selectedWebsiteInputs = [...document.querySelectorAll('input[name="website[]"]')]
      .filter(input => input.checked).length;
    const form = document.querySelector('form.js-ajax-form[action*="saveprice.html"]');
    return {
      isRoute:true,
      origin:location.origin,
      path:url.pathname,
      href:location.href,
      queryGid:url.searchParams.get('gid') || '',
      login:/login/i.test(url.pathname) || /请登录|登录后/.test(document.body?.innerText || ''),
      gameId:String(game?.value || ''),
      exchangeRate:String(document.querySelector('input[name="exchange_rate[rmb]"]')?.value || ''),
      allServerCount:allServer.length,
      allServerChecked:allServer.some(input => input.checked),
      websiteSelectCount:document.querySelectorAll('#b2c-website').length,
      selectedWebsites:selectedSelectOptions + selectedWebsiteInputs,
      b2cCount:document.querySelectorAll('.jq_web[value="b2c"]').length,
      b2cSelected:document.querySelector('.jq_web[value="b2c"]')?.checked === true,
      rows,
      saveFormCount:document.querySelectorAll('form.js-ajax-form[action*="saveprice.html"]').length,
      saveFormAction:form ? new URL(form.getAttribute('action') || '', location.href).pathname : '',
      saveFormOrigin:form ? new URL(form.getAttribute('action') || '', location.href).origin : '',
      saveFormMethod:form ? (form.getAttribute('method') || 'get').toLowerCase() : '',
      syncButtonCount:document.querySelectorAll('button.jq-update-button, input.jq-update-button').length,
      feedback:[...document.querySelectorAll('.layui-layer-content,.aui_content,.noty_text,.noty_message,[role="alert"],.toast,.alert')]
        .filter(el => el.getClientRects().length > 0).map(el => String(el.innerText || el.textContent || '').trim())
        .filter(Boolean)
    };
  }

  async function prepareAdminFilter() {
    const url = new URL(location.href);
    if (location.origin !== 'https://order.p2pah.cn' ||
        url.pathname !== '/game/admin_game_price/index.html' || url.searchParams.get('gid') !== '1322')
      throw new Error('后台页面地址不符');
    const game = document.querySelector('#lot-game');
    if (!game) throw new Error('未找到游戏筛选项 #lot-game');
    if (String(game.value) !== '1322') {
      const option = [...game.options].find(item => String(item.value) === '1322');
      if (!option) throw new Error('筛选项中没有 FC 27（1322）');
      game.value = '1322';
      game.dispatchEvent(new Event('change',{bubbles:true}));
    }
    const rows = [...document.querySelectorAll('table.table-list tbody tr[data-id]')];
    if (rows.length !== 3 || rows.some(row =>
        [...row.querySelectorAll('td')].every(td=>td.getAttribute('title')!=='1322'))) {
      const buttons = [...document.querySelectorAll('button,input[type="submit"],input[type="button"]')]
        .filter(el => /^(搜索|查询|search)$/i.test(String(el.innerText || el.value || '').trim()));
      if (buttons.length !== 1) throw new Error('FC 27 筛选未完成，且无法唯一识别搜索按钮');
      buttons[0].click();
    }

    // The sync action must never submit an all-server or region selection.
    for (const input of document.querySelectorAll('input[name="allserver"],input[name="website[]"]')) {
      if (input.checked) input.checked = false;
    }
    const select = document.querySelector('#b2c-website');
    if (select) {
      for (const option of select.options) {
        if (option.selected) {
          option.selected = false;
        }
      }
    }
    const b2cControls=[...document.querySelectorAll('.jq_web[value="b2c"]')];
    if (!select || document.querySelectorAll('#b2c-website').length!==1 || b2cControls.length!==1)
      throw new Error('地区或 B2C 控件缺失');
    const b2c = b2cControls[0];
    if (b2c && !b2c.checked) {
      b2c.checked = true;
    }
    return true;
  }

  async function setCost(platform, id, expectedBefore, targetCost, expectedB2c = null) {
    const url=new URL(location.href);
    if (location.origin!=='https://order.p2pah.cn' ||
        url.pathname!=='/game/admin_game_price/index.html' || url.searchParams.get('gid')!=='1322')
      throw new Error('后台地址或 FC 27 URL 筛选已变化');
    if (String(document.querySelector('#lot-game')?.value||'')!=='1322')
      throw new Error('后台 FC 27 筛选已变化');
    if (Number(document.querySelector('input[name="exchange_rate[rmb]"]')?.value)!==6.65)
      throw new Error('后台汇率已变化');
    const allServerControls=[...document.querySelectorAll('input[name="allserver"]')];
    const websiteSelect=document.querySelector('#b2c-website');
    const b2cControls=[...document.querySelectorAll('.jq_web[value="b2c"]')];
    const form=document.querySelector('form.js-ajax-form[action*="saveprice.html"]');
    const formAction=form?new URL(form.getAttribute('action')||'',location.href):null;
    if (allServerControls.length!==1 || allServerControls[0].checked || !websiteSelect ||
        document.querySelectorAll('#b2c-website').length!==1 || b2cControls.length!==1 ||
        [...websiteSelect.options].some(option=>option.selected&&String(option.value||'')) ||
        [...document.querySelectorAll('input[name="website[]"]')].some(input=>input.checked) ||
        !b2cControls[0].checked || !form || formAction?.origin!=='https://order.p2pah.cn' ||
        formAction?.pathname!=='/game/admin_game_price/saveprice.html' ||
        document.querySelectorAll('form.js-ajax-form[action*="saveprice.html"]').length!==1 ||
        document.querySelectorAll('button.jq-update-button,input.jq-update-button').length!==1)
      throw new Error('后台地区或 B2C 选项已变化');
    const expectedIds = {PS:'21942',XBOX:'21944',PC:'21946'};
    if (expectedIds[platform] !== String(id)) throw new Error('平台与商品 ID 不匹配');
    if (!/^\d+\.\d{6}$/.test(String(targetCost))) throw new Error('目标成本必须为六位小数');
    const tr = document.querySelector(`table.table-list tr[data-id="${id}"]`);
    if (!tr || [...tr.querySelectorAll('td')].every(td => td.getAttribute('title') !== '1322'))
      throw new Error(`${platform} 行不存在或游戏 ID 不符`);
    const nameCell = tr.querySelector('td[data-type="title"]');
    const platformInput = nameCell?.querySelector('input');
    const name = String(platformInput?.value || '').trim().toUpperCase();
    const nameSpan=String(nameCell?.querySelector('span')?.textContent || '').trim().toUpperCase();
    if (name !== platform || nameSpan !== platform) throw new Error(`${platform} 行的平台字段不符`);
    if (Number(tr.querySelector('td[data-type="lirunlv"] span')?.textContent)!==0.2)
      throw new Error(`${platform} 后台利润率已变化`);
    const cell = tr.querySelector('td[data-type="costprice"]');
    if (!cell) throw new Error(`${platform} 成本字段缺失`);
    const visible = input => {
      if (!input || input.hidden || input.type==='hidden' || input.getAttribute('aria-hidden')==='true') return false;
      const style=window.getComputedStyle(input);
      return style.display!=='none' && style.visibility!=='hidden' && input.getClientRects().length>0;
    };
    const current = () => String(cell.querySelector('span')?.textContent ?? '').trim();
    if (current() !== String(expectedBefore)) throw new Error(`${platform} 后台成本已变化，需重新读取`);
    const b2cBefore=String(tr.querySelector('td[data-type="b2c"] span')?.textContent||'').trim();
    if(expectedB2c!=null&&b2cBefore!==String(expectedB2c))throw new Error(`${platform} B2C 现值已变化，需重新读取`);
    if (![...cell.querySelectorAll('input')].some(visible))
      cell.dispatchEvent(new MouseEvent('dblclick',{bubbles:true,view:window}));
    let input;
    for (let attempt=0;attempt<30;attempt++) {
      input=[...cell.querySelectorAll('input')].find(visible);
      if (input) break;
      await new Promise(resolve => setTimeout(resolve,100));
    }
    if (!input) throw new Error(`${platform} 成本编辑框未打开`);
    input.value=String(targetCost);
    input.dispatchEvent(new Event('input',{bubbles:true}));
    input.dispatchEvent(new Event('change',{bubbles:true}));
    for (let attempt=0;attempt<120;attempt++) {
      await new Promise(resolve => setTimeout(resolve,100));
      const display=String(cell.querySelector('span')?.textContent ?? '').trim();
      const editorVisible=[...cell.querySelectorAll('input')].some(visible);
      if (display===String(targetCost) && !editorVisible)
        return {platform,id:String(id),costPrice:display,changed:true};
    }
    throw new Error(`${platform} 成本字段未收到页面保存回读`);
  }

  async function clickSync(site = null) {
    const url=new URL(location.href);
    if (location.origin!=='https://order.p2pah.cn' ||
        url.pathname!=='/game/admin_game_price/index.html' || url.searchParams.get('gid')!=='1322' ||
        String(document.querySelector('#lot-game')?.value||'')!=='1322')
      throw new Error('后台地址或 FC 27 筛选已变化');
    if (Number(document.querySelector('input[name="exchange_rate[rmb]"]')?.value)!==6.65)
      throw new Error('后台汇率已变化');
    const form=document.querySelector('form.js-ajax-form[action*="saveprice.html"]');
    const actionUrl=form?new URL(form.getAttribute('action')||'',location.href):null;
    const action=actionUrl?.pathname||'';
    const allServer=[...document.querySelectorAll('input[name="allserver"]')];
    const websiteSelect=document.querySelector('#b2c-website');
    const selectedOptions=websiteSelect?[...websiteSelect.options].filter(option=>option.selected&&String(option.value||'')).length:0;
    const selectedInputs=[...document.querySelectorAll('input[name="website[]"]')].filter(input=>input.checked).length;
    if (!form || action!=='/game/admin_game_price/saveprice.html' ||
        actionUrl.origin!=='https://order.p2pah.cn' ||
        (form.getAttribute('method')||'get').toLowerCase()!=='get' ||
        document.querySelectorAll('form.js-ajax-form[action*="saveprice.html"]').length!==1)
      throw new Error('同步表单结构与已核验契约不符');
    if (allServer.length!==1 || allServer.some(input=>input.checked)) throw new Error('所有区选项缺失或已勾选，已阻止同步');
    if (!websiteSelect || document.querySelectorAll('#b2c-website').length!==1 ||
        document.querySelectorAll('.jq_web[value="b2c"]').length!==1 ||
        selectedOptions+selectedInputs!==0) throw new Error('地区选项缺失或已勾选，已阻止同步');
    if (!websiteSelect || document.querySelectorAll('#b2c-website').length!==1 ||
        document.querySelectorAll('.jq_web[value="b2c"]').length!==1 ||
        document.querySelector('.jq_web[value="b2c"]')?.checked!==true)
      throw new Error('B2C 选项未勾选，已阻止同步');
    if (site !== null) {
      if (site !== 'mmoexp.com' || form.querySelector('[name="server_id"]')?.value !== '1322' ||
          form.querySelector('[name="selected_web"]')?.value !== 'b2c' ||
          form.querySelector('[name="getweb"]')?.value !== '0')
        throw new Error('FC27 MMOEXP 同步范围未核实');
      const matching=[...websiteSelect.options].filter(option=>option.value==='mmoexp.com');
      if (matching.length!==1) throw new Error('MMOEXP 网站选项缺失或重复');
      for (const option of websiteSelect.options) option.selected=option.value==='mmoexp.com';
      websiteSelect.dispatchEvent(new Event('change',{bubbles:true}));
      if ([...websiteSelect.options].filter(option=>option.selected).length!==1 ||
          !matching[0].selected) throw new Error('MMOEXP 网站选择未生效');
    }
    const buttons=[...document.querySelectorAll('button.jq-update-button,input.jq-update-button')];
    if (buttons.length!==1) throw new Error('同步按钮缺失或重复');
    if(typeof MutationObserver!=='function'||!document.documentElement)
      throw new Error('当前页面不支持及时监听同步反馈，已阻止同步');
    const previousBars=new Set([...document.querySelectorAll('.noty_bar')]);
    const dialogSelector='.aui_content,.layui-layer-content';
    const previousDialogs=new Set([...document.querySelectorAll(dialogSelector)]);
    const previousDialogText=new Map([...previousDialogs].map(el=>[el,String(el.innerText||el.textContent||'').trim()]));
    const pendingFreshBars=new Set();
    const elementFor=node=>node?.nodeType===1?node:node?.parentElement||null;
    const nearest=(node,selector)=>{
      const el=elementFor(node);
      if(!el)return null;
      if(el.matches?.(selector))return el;
      return el.closest?.(selector)||null;
    };
    const visible=el=>Boolean(el&&el.getClientRects?.().length);
    const messageText=el=>String(el?.querySelector?.('.noty_text')?.textContent||el?.innerText||el?.textContent||'').trim().slice(0,160);
    return new Promise((resolve,reject)=>{
      let settled=false;
      const observer=new MutationObserver(records=>{
        if(settled)return;
        const candidateBars=new Set();
        let touchedDialog=false;
        for(const record of records){
          if(!['childList','characterData','attributes'].includes(record.type))continue;
          const target=elementFor(record.target);
          const targetBar=nearest(target,'.noty_bar');
          const targetText=nearest(target,'.noty_text');
          const targetDialog=nearest(target,dialogSelector);
          if(targetBar&&targetText&&(record.type==='childList'||record.type==='characterData'))pendingFreshBars.add(targetBar);
          if(targetBar&&!previousBars.has(targetBar)&&record.type==='attributes'&&record.attributeName==='class')
            pendingFreshBars.add(targetBar);
          if(targetBar&&pendingFreshBars.has(targetBar)&&
              (record.type==='childList'||record.type==='characterData'||record.type==='attributes'))candidateBars.add(targetBar);
          if(targetDialog)touchedDialog=true;
          for(const node of record.addedNodes||[]){
            const added=elementFor(node);
            if(!added)continue;
            if(added.matches?.('.noty_bar')&&!previousBars.has(added))pendingFreshBars.add(added);
            for(const bar of added.querySelectorAll?.('.noty_bar')||[])if(!previousBars.has(bar))pendingFreshBars.add(bar);
            if(nearest(added,dialogSelector))touchedDialog=true;
          }
          for(const node of record.removedNodes||[]){
            if(nearest(node,dialogSelector))touchedDialog=true;
          }
        }
        for(const bar of [...pendingFreshBars]){
          if(visible(bar)){candidateBars.add(bar);pendingFreshBars.delete(bar)}
        }
        const outcomes=[];
        for(const bar of candidateBars){
          if(!visible(bar))continue;
          const classes=String(bar.className?.baseVal||bar.className||'').split(/\s+/);
          const typeClass=classes.find(name=>/^noty_type_[a-z0-9_-]+$/i.test(name));
          if(!typeClass){outcomes.push({type:'unknown',text:messageText(bar)});continue}
          const type=typeClass.slice('noty_type_'.length).toLowerCase();
          const text=messageText(bar)||`后台 Noty type=${type}`;
          outcomes.push({type,text});
        }
        if(outcomes.length){
          const failure=outcomes.find(item=>item.type!=='success'||
            /请先调整价格|同步失败|未同步|失败/.test(item.text));
          settled=true;observer.disconnect();clearTimeout(timer);
          if(failure){
            const text=failure.text||`后台 Noty type=${failure.type}`;
            reject(new Error(failure.type==='error'?`后台同步失败：${text}`:`后台提示类型 ${failure.type}，同步未确认：${text}`));
          }else resolve({success:true,message:outcomes[0].text,type:'success'});
          return;
        }
        if(touchedDialog){
          const fresh=[...document.querySelectorAll(dialogSelector)].find(el=>visible(el)&&
            String(el.innerText||el.textContent||'').trim()&&
            (!previousDialogs.has(el)||previousDialogText.get(el)!==String(el.innerText||el.textContent||'').trim()));
          if(fresh){settled=true;observer.disconnect();clearTimeout(timer);
            reject(new Error('后台未返回成功 Noty，收到对话框反馈：'+messageText(fresh)));}
        }
      });
      const timer=setTimeout(()=>{
        if(settled)return;settled=true;observer.disconnect();
        reject(new Error('后台未出现新的成功类型 Noty；未确认同步完成'));
      },15000);
      observer.observe(document.documentElement,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['class','style']});
      try{buttons[0].click()}
      catch(error){settled=true;observer.disconnect();clearTimeout(timer);reject(error)}
    });
  }

  const api=Object.freeze({readAdminSnapshot,prepareAdminFilter,setCost,clickSync});
  globalThis.FC27RepricingDOM=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})();
