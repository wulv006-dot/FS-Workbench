/* Suggested selection contract only. A browser flag never enables commerce. */
(function(root){
  'use strict';
  const fail=code=>Object.assign(new Error(code),{code});
  const clone=value=>JSON.parse(JSON.stringify(value));
  function decimal(value){
    if(typeof value!=='string'||value.length>32||!/^\d+(?:\.\d{1,6})?$/.test(value))throw fail('QUANTITY_INVALID');
    const [whole,fraction='']=value.split('.');return BigInt(whole)*1000000n+BigInt(fraction.padEnd(6,'0'));
  }
  function create(input,{now=Date.now}={}){
    // This is data validation, not proof of backend verification or purchase permission.
    if(input?.schema_version!==1||input.verified!==true||typeof input.catalog_version!=='string'||!input.catalog_version||['model_id','site_id','game_id'].some(id=>typeof input.model_ref?.[id]!=='string'||!input.model_ref[id]))throw fail('MODEL_OPTIONS_UNAVAILABLE');
    const contract=clone(input),fields=contract.fields,combos=contract.combinations;
    if(!Array.isArray(fields)||!fields.length||!Array.isArray(combos)||!combos.length)throw fail('MODEL_OPTIONS_UNAVAILABLE');
    const ids=[];
    for(const field of fields){
      if(typeof field.id!=='string'||!/^[a-z][a-z0-9_-]*$/i.test(field.id)||['constructor','prototype'].includes(field.id)||ids.includes(field.id)||!Array.isArray(field.values)||!field.values.length||!Array.isArray(field.depends_on)||field.depends_on.some(id=>!ids.includes(id)))throw fail('MODEL_OPTIONS_UNAVAILABLE');
      if(field.values.some(v=>typeof v.id!=='string'||!v.id)||new Set(field.values.map(v=>v.id)).size!==field.values.length)throw fail('MODEL_OPTIONS_UNAVAILABLE');
      ids.push(field.id);
    }
    const fingerprints=new Set();
    for(const combo of combos){
      if(!combo.product_key||!Array.isArray(combo.attributes)||combo.attributes.some(a=>!a.attribute_id||!a.value_id)||fields.some(f=>!f.values.some(v=>v.id===combo.choices?.[f.id]))||Object.keys(combo.choices).length!==fields.length)throw fail('MODEL_OPTIONS_UNAVAILABLE');
      const signature=JSON.stringify(ids.map(id=>combo.choices[id]));if(fingerprints.has(signature))throw fail('MODEL_OPTIONS_UNAVAILABLE');fingerprints.add(signature);
      const q=combo.quantity;
      try{if(typeof q?.unit!=='string'||!q.unit||decimal(q.min)<=0n||decimal(q.max)<decimal(q.min)||decimal(q.step)<=0n)throw fail('MODEL_OPTIONS_UNAVAILABLE');}catch{throw fail('MODEL_OPTIONS_UNAVAILABLE');}
    }
    let choices={},quantity='',revision=0,quote=null;
    const invalidate=()=>{revision++;quote=null;};
    const matching=()=>combos.filter(c=>fields.every(f=>choices[f.id]===c.choices[f.id]));
    function options(id){const field=fields.find(f=>f.id===id);if(!field||field.depends_on.some(id=>!choices[id]))return [];
      return field.values.filter(v=>combos.some(c=>c.choices[id]===v.id&&field.depends_on.every(dep=>c.choices[dep]===choices[dep]))).map(clone);
    }
    function line(){
      const matches=matching();if(matches.length!==1)throw fail('SPEC_REQUIRED');const combo=matches[0],q=combo.quantity;
      const amount=decimal(quantity),min=decimal(q.min);if(amount<min||amount>decimal(q.max)||(amount-min)%decimal(q.step)!==0n)throw fail('QUANTITY_INVALID');
      return {product_key:combo.product_key,quantity:{value:quantity,unit:q.unit,...(q.group?{group:q.group}:{})},attributes:clone(combo.attributes)};
    }
    const api={
      fields:()=>clone(fields),options,
      select(id,value){const index=ids.indexOf(id);if(index<0||value!==''&&!options(id).some(v=>v.id===value))throw fail('SPEC_INVALID');if(value==='')delete choices[id];else choices[id]=value;for(const dependent of ids.slice(index+1))delete choices[dependent];quantity='';invalidate();},
      setQuantity(value){quantity=String(value);invalidate();},
      quantity(){const matches=matching();return matches.length===1?clone(matches[0].quantity):null;},
      choices:()=>clone(choices),ready(){try{line();return true;}catch{return false;}},
      serialize(){line();return {catalog_version:contract.catalog_version,model_ref:clone(contract.model_ref),choices:clone(choices),quantity};},
      line,
      beginQuote(){return {revision,signature:JSON.stringify(line()),line:line()};},
      acceptQuote(ticket,response){
        if(ticket.revision!==revision||ticket.signature!==JSON.stringify(line()))return false;
        quote=null;const expires=Date.parse(response?.expires_at);
        if(response?.authoritative!==true||response.test_only===true||!response.quote_id||response.currency!=='USD'||!Number.isSafeInteger(response.total_minor)||response.total_minor<0||!Number.isFinite(expires)||expires<=now())return false;
        quote={quote_id:response.quote_id,total_minor:response.total_minor,currency:response.currency,expires_at:response.expires_at};return true;
      },
      quote(){if(quote&&Date.parse(quote.expires_at)<=now())quote=null;return quote&&clone(quote);},
      invalidate,
      contractVersion:contract.catalog_version,modelRef:clone(contract.model_ref)
    };return api;
  }
  const api={create};if(typeof module==='object'&&module.exports)module.exports=api;else root.SeasonalModelSelection=api;
})(typeof globalThis==='undefined'?this:globalThis);
