/* Prototype state only. Server-issued offers and verified referrals replace this at integration. */
(function(root){
  'use strict';
  const discounts=[10,15,20,25]; // Fictional, equal-weight design examples, never production pricing.
  function draw(pool,count,previous=[],random=Math.random,featuredGames=[]){
    if(!pool.length)throw new Error('Choose at least one game.');
    const kept=previous.filter(card=>card.locked);
    if(kept.some(card=>!pool.some(p=>p.id===card.id)))throw new Error('Unlock cards outside the selected pool first.');
    const available=pool.filter(p=>!kept.some(card=>card.id===p.id));
    for(let i=available.length-1;i>0;i--){const j=Math.floor(random()*(i+1));[available[i],available[j]]=[available[j],available[i]];}
    const chosen=[];
    for(const game of featuredGames){
      if(kept.some(c=>pool.find(p=>p.id===c.id)?.game===game))continue;
      const index=available.findIndex(p=>p.game===game);
      if(index>=0&&chosen.length+kept.length<Math.min(count,pool.length))chosen.push(...available.splice(index,1));
    }
    chosen.push(...available.slice(0,Math.max(0,Math.min(count,pool.length)-kept.length-chosen.length)));
    return [...kept,...chosen.map(p=>({id:p.id,discount:discounts[Math.floor(random()*discounts.length)],revealed:false,locked:false}))];
  }
  function refresh(state,pool,random=Math.random){
    if(state.credits<1)throw new Error('No refresh key available.');
    if(state.cards.every(c=>c.locked))throw new Error('Unlock at least one card.');
    const cards=draw(pool,8,state.cards,random,state.featuredGames||[]);
    return {...state,cards,credits:state.credits-1,round:state.round+1};
  }
  function award(state,receipt){
    if(!/^DEMO-[1-3]$/.test(receipt)||state.receipts.includes(receipt)||state.receipts.length>=3)return state;
    return {...state,credits:state.credits+1,receipts:[...state.receipts,receipt]};
  }
  function price(base,discount){
    if(!Number.isSafeInteger(base)||base<=0||!Number.isInteger(discount)||discount<0||discount>=100)throw new Error('Invalid demo price.');
    return Math.floor((base*(100-discount)+50)/100);
  }
  function valid(state,ids){
    return state?.version===2&&Array.isArray(state.cards)&&state.cards.length>0&&state.cards.length<=8&&new Set(state.cards.map(c=>c.id)).size===state.cards.length&&state.cards.every(c=>ids.includes(c.id)&&discounts.includes(c.discount)&&typeof c.locked==='boolean'&&typeof c.revealed==='boolean'&&(!c.locked||c.revealed))&&Number.isSafeInteger(state.round)&&state.round>0&&Number.isSafeInteger(state.credits)&&state.credits>=0&&state.credits<=3&&Array.isArray(state.receipts)&&state.receipts.length<=3&&new Set(state.receipts).size===state.receipts.length&&state.receipts.every(r=>/^DEMO-[1-3]$/.test(r))&&Array.isArray(state.selectedGames)&&state.selectedGames.length>0&&state.selectedGames.every(g=>ids.some(id=>id.startsWith(g+'-')))&&['product','discount'].includes(state.mode);
  }
  const api={draw,refresh,award,price,valid,discounts};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.VaultCore=api;
})(globalThis);
