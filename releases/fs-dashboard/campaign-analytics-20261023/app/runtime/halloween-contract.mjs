// One draft/public contract. Missing historical field stays missing on save.
const games=[['fc','FC27','1327'],['aion','Aion2','891'],['diablo','Diablo IV','456'],['maplestory','MapleStory',null]];
const error=()=>{throw Object.assign(Error('INVALID_HALLOWEEN_CONFIG'),{code:'INVALID_HALLOWEEN_CONFIG',status:400});};
const exact=(v,keys)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).every(k=>keys.includes(k));
const numeric=v=>typeof v==='string'&&/^[1-9]\d{0,19}$/.test(v);
export function emptyHalloween(){return {schema_version:1,status:'unconfigured',site_id:'266',promoter_uid:'0',off_percent_tiers:[8,15,10],probabilities:null,tier_product_binding:null,starts_at:null,ends_at:null,wishing_pool:false,games:games.map(([id,label,admin_game_id])=>({id,label,admin_game_id,fixed_model:null,fixed_off_percent:null,fixed_quantity:id==='fc'?{value:'1000',unit:'K',conversion_verified:false}:null,random_source:{mode:'models',category_id:null,snapshot_complete:false},random_models:[],random_count:2}))};}
export function projectHalloween(value){
 if(!exact(value,Object.keys(emptyHalloween()))||value.schema_version!==1||!['unconfigured','configured'].includes(value.status)||value.site_id!=='266'||!['0','739116'].includes(value.promoter_uid)||value.wishing_pool!==false||JSON.stringify(value.off_percent_tiers)!=='[8,15,10]'||!Array.isArray(value.games)||value.games.length!==4)error();
 // Preserve historical metadata on reads; new launch input uses system UID0.
 // This display contract never grants promoter attribution or code eligibility.
 const out=emptyHalloween();out.promoter_uid=value.promoter_uid;
 for(const key of ['starts_at','ends_at']){const v=value[key];if(v!==null&&(typeof v!=='string'||!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v)||!Number.isFinite(Date.parse(v))))error();out[key]=v;}
 if(out.starts_at&&out.ends_at&&Date.parse(out.starts_at)>=Date.parse(out.ends_at))error();
 if(value.tier_product_binding!==null&&value.tier_product_binding!=='independent')error();out.tier_product_binding=value.tier_product_binding;
 if(value.probabilities!==null){
  const rows=value.probabilities;if(!Array.isArray(rows)||rows.length!==3||new Set(rows.map(r=>r.off_percent)).size!==3||rows.some(r=>!exact(r,['off_percent','weight'])||![8,15,10].includes(r.off_percent)||!Number.isInteger(r.weight)||r.weight<0||r.weight>10000)||rows.reduce((s,r)=>s+r.weight,0)!==10000)error();
  out.probabilities=rows.map(r=>({off_percent:r.off_percent,weight:r.weight}));
 }
 out.games=games.map(([id,label,known])=>{
  const rows=value.games.filter(g=>g.id===id);if(rows.length!==1)error();const g=rows[0];
  if(!exact(g,['id','label','admin_game_id','fixed_model','fixed_off_percent','fixed_quantity','random_quantities','random_source','random_models','random_count'])||g.label!==label||g.random_count!==2||g.admin_game_id!==null&&!numeric(g.admin_game_id)||known&&g.admin_game_id!==known||g.fixed_model!==null&&!numeric(g.fixed_model)||g.fixed_off_percent!==null&&![8,15,10].includes(g.fixed_off_percent)||!Array.isArray(g.random_models)||g.random_models.length>100||new Set(g.random_models).size!==g.random_models.length||g.random_models.some(k=>!numeric(k)||k===g.fixed_model))error();
  const source=g.random_source??{mode:'models',category_id:null,snapshot_complete:false};
  if(!exact(source,['mode','category_id','snapshot_complete'])||!['models','category_snapshot','category_dynamic','quantity_tiers'].includes(source.mode)||typeof source.snapshot_complete!=='boolean'||['models','quantity_tiers'].includes(source.mode)&&source.category_id!==null||!['models','quantity_tiers'].includes(source.mode)&&!numeric(source.category_id)||source.mode==='category_dynamic'&&g.random_models.length)error();
  const quantity=g.fixed_quantity??(id==='fc'?{value:'1000',unit:'K',conversion_verified:false}:null);
  if(quantity!==null&&(!exact(quantity,['value','unit','conversion_verified'])||typeof quantity.value!=='string'||!/^\d+(?:\.\d{1,6})?$/.test(quantity.value)||Number(quantity.value)<=0||typeof quantity.unit!=='string'||!quantity.unit||quantity.conversion_verified!==false))error();
  if(id==='fc'&&(quantity?.value!=='1000'||quantity?.unit!=='K'))error();
  if(!g.admin_game_id&&(g.fixed_model||g.random_models.length))error();
  let random_quantities;
  if(source.mode==='quantity_tiers'){
   if(!['aion','diablo'].includes(id)||!quantity||g.random_models.length||!Array.isArray(g.random_quantities)||g.random_quantities.length!==2)error();
   random_quantities=g.random_quantities.map(q=>{if(!exact(q,['value','unit'])||typeof q.value!=='string'||!/^\d+(?:\.\d{1,6})?$/.test(q.value)||Number(q.value)<=0||q.unit!==quantity.unit)error();return {value:q.value,unit:q.unit};});
   if(new Set([quantity.value,...random_quantities.map(q=>q.value)].map(Number)).size!==3)error();
  }else if(g.random_quantities!==undefined&&g.random_quantities.length)error();
  return {id,label,admin_game_id:g.admin_game_id,fixed_model:g.fixed_model,fixed_off_percent:g.fixed_off_percent,fixed_quantity:quantity,...(random_quantities?{random_quantities}:{}),random_source:{...source},random_models:[...g.random_models],random_count:2};
 });
 // Configured describes reviewed input completeness, never live commerce or a
 // granted random benefit. Draft UI cannot grant server quote/cart permission.
 out.status=out.probabilities&&out.tier_product_binding&&out.starts_at&&out.ends_at&&out.games.every(g=>g.admin_game_id&&g.fixed_model&&g.fixed_off_percent!==null&&(g.random_source.mode==='quantity_tiers'||g.random_source.mode==='category_dynamic'||g.random_models.length>=2&&(g.random_source.mode!=='category_snapshot'||g.random_source.snapshot_complete)))?'configured':'unconfigured';
 return out;
}
export function halloweenProductKeys(config,products){
 const h=projectHalloween(config),keys=[];
 for(const game of h.games)for(const model of [game.fixed_model,...game.random_models].filter(Boolean)){
  const rows=products.filter(p=>p.product_ref?.site_id==='266'&&p.product_ref?.game_id===game.admin_game_id&&p.product_ref?.model_id===model);
  if(!rows.length)throw Object.assign(Error('HALLOWEEN_MODEL_NOT_IN_CATALOG'),{code:'HALLOWEEN_MODEL_NOT_IN_CATALOG',status:400});
  keys.push(...rows.map(p=>p.key));
 }return [...new Set(keys)];
}

// A bounded catalog-page result is NOT a complete dynamic pool. This resolver
// accepts normalized, trusted catalog observations, never browser-submitted rows.
// It filters eligibility but intentionally does not draw or invent probabilities.
export function eligibleHalloweenPool(game,observation){
 const source=game.random_source??{mode:'models'};
 if(source.mode==='category_snapshot'&&source.snapshot_complete!==true)return {status:'snapshot_incomplete',models:[]};
 if(!observation||observation.complete!==true||!Array.isArray(observation.models)||observation.models.length>5000)return {status:'catalog_incomplete',models:[]};
 const rows=observation.models.filter(row=>row.site_id==='266'&&row.game_id===game.admin_game_id&&numeric(row.model_id)&&row.sellable===true&&row.model_id!==game.fixed_model&&
  (source.mode==='category_dynamic'?row.category_id===source.category_id:game.random_models.includes(row.model_id)&&(source.mode!=='category_snapshot'||row.category_id===source.category_id)));
 const models=[...new Set(rows.map(row=>row.model_id))];
 return {status:models.length>=2?'eligible_not_drawn':'insufficient_products',models};
}
