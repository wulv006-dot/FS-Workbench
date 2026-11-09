(function (root) {
  'use strict';
  function discountFromPayPercent(value) {
    // Admin price-discount field is the percentage paid, not percentage saved.
    // Fractional values are not yet verified; do not silently round them.
    const text=String(value);
    if((typeof value!=='number'&&typeof value!=='string')||!/^\d{1,3}$/.test(text))throw new Error('Unverified discount percentage');
    const paid=Number(text);
    if(!Number.isInteger(paid)||paid<1||paid>100)throw new Error('Unverified discount percentage');
    return {payPercent:paid,offPercent:100-paid};
  }
  function minor(value) {
    const text=String(value);
    if(!/^\d{1,8}(?:\.\d{1,2})?$/.test(text)) throw new Error('Invalid display price');
    const [whole,fraction='']=text.split('.');
    return Number(whole)*100+Number(fraction.padEnd(2,'0'));
  }
  // A live listing may legitimately be retitled (rating or promo suffix) while the
  // pinned identity stays the same. The player-name segment must still match.
  function sameListing(current,expected) {
    const name=value=>String(value??'').split('/')[0].trim().toLowerCase();
    return String(current)===String(expected)||name(current)!==''&&name(current)===name(expected);
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
  // Read-only native browser evidence COINS-CONTRACT57. This is serialization
  // only, not a live cart capability or permission to reuse it for other SKUs.
  function coinsPayload(selection) {
    if(selection?.origin!=='https://www.mmoexp.com'||selection.region!=='us'||selection.currency!=='USD'
      ||selection.model_id!=='41217957'||selection.goods_id!=='163329311'||selection.platform!=='ps'
      ||selection.quantity!=='1000'||selection.unit!=='K')throw new Error('Coins selection contract unverified');
    return {category:'new_gold',id:'163329311',group:'1000',num:'1',attr:'',aid:''};
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
        if(Number(raw.aid)!==item.offer.aid||Number(raw.cid)!==Number(item.cid)||Number(raw.gid)!==config.gameId||!sameListing(raw.title,item.title)||Number(raw.status)!==1||Number(raw.auto_off)!==0||raw.has_sku||Object.keys(raw.saleprop||{}).length)throw new Error('Product scope or availability changed');
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
  // Join only existing verified native options to the exact identity/platform.
  // A reference quote is useful without a checkout binding; it never changes availability.
  function nativeModelOffer(model,platform,trade={},pageId=null,now=Date.now()) {
    const slot=model?.platforms?.[platform],ref=slot?.product_ref,aid={ps:'21587',xbox:'21585',pc:'21589'}[platform];
    if(!ref||slot.state!=='verified'&&slot.binding_state!=='verified')return null;
    const sameRef=r=>r&&['site_id','game_id','model_id','goods_id','sku_id'].every(k=>(r[k]??null)===(ref[k]??null));
    const products=(trade.products||[]).filter(p=>p.preview_only!==true&&sameRef(p.product_ref)&&p.platform?.code===platform&&p.platform?.attribute_id===aid);
    if(products.length!==1)return null;const product=products[0],contract=trade.seasonal_model_contracts?.[ref.model_id];
    if(contract?.verified!==true||!['site_id','game_id','model_id'].every(k=>contract.model_ref?.[k]===ref[k]))return null;
    const combos=(contract.combinations||[]).filter(c=>c.product_key===product.key);
    if(combos.length!==1)return null;const combo=combos[0],q=combo.quantity,price=combo.price;
    if(!q||q.unit!=='item'||q.group!==product.quantity?.group||!Array.isArray(combo.attributes)||!price||price.source!=='admin_current'||price.currency!=='USD'||price.minor_unit_scale!==2||!Number.isSafeInteger(price.base_minor)||price.base_minor<=0||!Number.isFinite(Date.parse(price.expires_at))||Date.parse(price.expires_at)<=now||!/^\d+$/.test(price.quantity_value||''))return null;
    const value=Number(price.quantity_value);if(!Number.isSafeInteger(value)||value<1||value<Number(q.min)||value>Number(q.max)||!(Number(q.step)>0)||(value-Number(q.min))%Number(q.step)!==0)return null;
    const stable=v=>JSON.stringify(v,(_k,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.entries(x).sort(([a],[b])=>a.localeCompare(b))):x);
    const policy=trade.native_checkout,active=policy?.status==='configured'&&policy.origin==='https://www.mmoexp.com'&&policy.consumer_behavior_confirmed===true&&Date.parse(policy.valid_from)<=now&&Date.parse(policy.valid_until)>now;
    const bindings=active?(policy.bindings||[]).filter(b=>b.activity_id==='fc27-season2'&&['fc27-trio','fc27-weekly','fc27-sbc'].includes(b.page_id)&&(!pageId||b.page_id===pageId)&&b.product_key===product.key&&b.off_percent===10&&b.quantity?.value===price.quantity_value&&b.quantity.unit===q.unit&&stable(b.attributes)===stable(combo.attributes)&&b.native?.id===ref.goods_id&&b.native?.aid===aid&&b.native?.group===q.group&&b.native?.num===price.quantity_value):[];
    return {product_key:product.key,product_ref:{...ref},quantity:{value:price.quantity_value,unit:q.unit,group:q.group},attributes:combo.attributes.map(a=>({...a})),price:{...price},bindings:bindings.map(b=>({page_id:b.page_id,off_percent:b.off_percent})),checkout_ready:!!pageId&&bindings.length===1};
  }
  const api={nativeModelOffer,discountFromPayPercent,minor,line,activityPrice,selection,payload,coinsPayload,result,catalogForm,refreshLine,createBatch};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.FCActivityCore=api;
})(typeof window==='undefined'?globalThis:window);
