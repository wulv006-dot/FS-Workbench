(function (root) {
  'use strict';
  function minor(value) {
    const text=String(value);
    if(!/^\d{1,8}(?:\.\d{1,2})?$/.test(text)) throw new Error('Invalid display price');
    const [whole,fraction='']=text.split('.');
    return Number(whole)*100+Number(fraction.padEnd(2,'0'));
  }
  function line(product,platform) {
    const offer=product?.platforms?.[platform];
    if(!offer||!Number.isSafeInteger(offer.id)||offer.id<=0||offer.status!==1||offer.autoOff!==0||minor(offer.price)<=0) throw new Error('Product unavailable for selected platform');
    if(!Number.isSafeInteger(offer.quantity)||offer.quantity<1||!Number.isSafeInteger(offer.group)||offer.group<1) throw new Error('Invalid product quantity');
    return {...product,offer,amount:minor(offer.price)*offer.quantity};
  }
  function activityPrice(baseAmount,config) {
    const percent=config.activityPricing?.enabled?config.activityPricing.discountPercent:0;
    if(!Number.isSafeInteger(baseAmount)||baseAmount<0||!Number.isInteger(percent)||percent<0||percent>=100)throw new Error('Invalid activity price');
    const numerator=baseAmount*(100-percent)+50;
    if(!Number.isSafeInteger(numerator))throw new Error('Activity amount exceeds safe precision');
    const amount=Math.floor(numerator/100);
    if(baseAmount>0&&amount===0)throw new Error('Activity amount rounds to zero');
    return {amount,baseAmount,discountAmount:baseAmount-amount,percent};
  }
  function selection(config,state) {
    let keys=state.view==='sbc'?[...(state.coreMode==='service'?[state.core]:[]),...state.companions]:state.view==='trio'?config.trio.ids:[...state.weekly];
    keys=[...new Set([...keys,...state.bundles])];
    return keys.map(key=>line(config.products[key],state.platform));
  }
  function payload(item) {
    return {category:'new_items',id:String(item.offer.id),group:String(item.offer.group),num:String(item.offer.quantity),attr:'',aid:String(item.offer.aid)};
  }
  function result(response) {
    const value=response?.data?.cart?.add||response?.cart?.add;
    if(response?.code===0||response?.status===false||value?.status===false) return {ok:false,message:String(value?.msg||response?.msg||'Cart rejected this item')};
    const ok=response?.code===1||response?.code==='1'||Boolean(value&&(value.details||value.cart||value.total!=null));
    return {ok,message:ok?'':String(response?.msg||'Unrecognized cart response'),unknown:!ok};
  }
  function catalogForm(config,item,page=1) {
    const form={site_id:String(config.siteId),Game_id:String(config.gameId),page:String(page),top_cid:'2',aid:String(item.offer.aid),category_id:String(item.kind==='sbc'?9625:item.kind==='bundle'?9629:9627),level:'1',get_about_multi_by_cid:'1',keyword:item.search};
    if(item.kind==='sbc')form.cid='10203';
    return form;
  }
  async function refreshLine(config,item,read) {
    let totalPages=1;
    for(let page=1;page<=totalPages;page++) {
      const body=await read(config.api.catalog,catalogForm(config,item,page));
      const index=body?.goods?.index;
      if(!index||!Array.isArray(index.list))throw new Error('Catalog response unavailable');
      const raw=index.list.find(row=>Number(row.id)===item.offer.id);
      if(raw) {
        if(Number(raw.aid)!==item.offer.aid||Number(raw.cid)!==Number(item.cid)||Number(raw.gid)!==config.gameId||String(raw.title)!==item.title||Number(raw.status)!==1||Number(raw.auto_off)!==0||raw.has_sku||Object.keys(raw.saleprop||{}).length)throw new Error('Product scope or availability changed');
        const quantity=Number(raw.min_qty),group=Number(raw.num),price=String(raw.price_discount_format);
        if(!Number.isSafeInteger(quantity)||quantity<1||!Number.isSafeInteger(group)||group<1||minor(price)<=0)throw new Error('Invalid current offer');
        return {...item,offer:{...item.offer,quantity,group,price},amount:minor(price)*quantity,currentRaw:raw};
      }
      const perPage=Number(index.perpage),total=Number(index.total);
      if(!Number.isSafeInteger(perPage)||perPage<1||!Number.isSafeInteger(total)||total<0)throw new Error('Catalog pagination unavailable');
      totalPages=Math.ceil(total/perPage);
      if(totalPages>10)throw new Error('Catalog lookup exceeds the selected-product scope');
    }
    throw new Error('Selected product is no longer listed');
  }
  function createBatch(write) {
    const outcomes=[];let started=false;
    return {outcomes,async run(items,onProgress=()=>{}) {
      if(started)throw new Error('This submission has already started; inspect the cart before another attempt');
      started=true;
      for(const item of items) {
        let outcome;
        try {
          const response=await write(payload(item));const answer=result(response);
          outcome={id:item.offer.id,title:item.title,state:answer.ok?'confirmed':answer.unknown?'unknown':'rejected',message:answer.message};
        } catch(error) {outcome={id:item.offer.id,title:item.title,state:'unknown',message:'No conclusive server receipt; inspect the existing cart.'};}
        outcomes.push(outcome);onProgress([...outcomes]);
        if(outcome.state!=='confirmed')break;
      }
      return [...outcomes];
    }};
  }
  const api={minor,line,activityPrice,selection,payload,result,catalogForm,refreshLine,createBatch};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.FCActivityCore=api;
})(typeof window==='undefined'?globalThis:window);
