// Private, reviewable commerce proposals. Preparation never installs policy or publishes.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomUUID,createHash} from 'node:crypto';
import {execFile} from 'node:child_process';
import {backendRead} from './backend-client.mjs';
import {weeklyNativeCandidates} from './weekly-native-candidates.mjs';
import {projectNativeCatalog} from './native-catalog.mjs';
import {canonical,digest} from '../runtime/snapshot.mjs';
import handoff from '../native-code-handoff.js';

const pages=['fc27-weekly','fc27-trio','fc27-sbc'],categories={player:'9627',sbc:'10203',bundle:'10255'};
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const fail=code=>{throw Object.assign(Error(code),{code,status:409});};
const uuid=value=>{if(typeof value!=='string'||!/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}/.test(value)||value.length!==36)fail('WEEKLY_COMMERCE_ID_INVALID');};
const hashDraft=draft=>digest(canonical(draft));
const policyBytes=read=>{const raw=read();if(!Buffer.isBuffer(raw)&&typeof raw!=='string')fail('WEEKLY_COMMERCE_RAW_POLICY_REQUIRED');return Buffer.from(raw);};
const entryKey=p=>canonical([p.model_ref,p.quantity_value,p.quantity_unit]);
const empty=s=>s?.present===true&&s.observed&&typeof s.observed==='object'&&Object.keys(s.observed).length===0;
function discountEvidence(detail,now){
 const f=detail?.fields,number=(value,target)=>(typeof value==='string'||Number.isSafeInteger(value))&&/^(?:0|[1-9]\d*)(?:\.0+)?$/.test(String(value))&&Number(value)===target;
 const ids=value=>Array.isArray(value)&&value.every(v=>typeof v==='string'||Number.isSafeInteger(v))?value.map(String):null;
 if(detail?.kind!=='discount'||detail.native_id!=='6049'||detail.scope_status!=='exact_site'||!f||f.code!=='FCSCOUT10'||!number(f.uid,0))fail('WEEKLY_COMMERCE_DISCOUNT_IDENTITY_UNVERIFIED');
 if(!number(f.status,1)||!number(f.type,1)||!number(f.discount,90)||!number(f.attain,0))fail('WEEKLY_COMMERCE_DISCOUNT_RULE_UNVERIFIED');
 if(!number(f.site_id,266)||canonical(ids(f.gid))!==canonical(['1327'])||canonical(ids(f.cid))!==canonical(['2'])||!ids(f.exclude_gids)||ids(f.exclude_gids).includes('1327'))fail('WEEKLY_COMMERCE_DISCOUNT_SCOPE_UNVERIFIED');
 const stamp=value=>{if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value))fail('WEEKLY_COMMERCE_DISCOUNT_WINDOW_UNVERIFIED');const ms=Date.parse(value.replace(' ','T')+'+08:00');if(!Number.isFinite(ms)||new Date(ms+8*3600000).toISOString().slice(0,19).replace('T',' ')!==value)fail('WEEKLY_COMMERCE_DISCOUNT_WINDOW_UNVERIFIED');return ms;};
 const start=stamp(f.timestart),end=stamp(f.timeend);if(start>=end||now<start||now>end)fail('WEEKLY_COMMERCE_DISCOUNT_WINDOW_UNVERIFIED');
 // aid=0 is the native unrestricted-platform value, not a missing platform ID.
 if(f.aid!=null&&!/^(?:0|[1-9]\d*)$/.test(String(f.aid)))fail('WEEKLY_COMMERCE_DISCOUNT_SCOPE_UNVERIFIED');
 return {native_id:'6049',code:'FCSCOUT10',before_hash:detail.before_hash,observed_at:new Date(now).toISOString(),valid_until:new Date(end).toISOString(),aid:f.aid==null?null:String(f.aid)};
}
async function selected(draft,catalog,policy,call){
 const l=draft?.fc_layout;if(!l||!Array.isArray(l.weekly)||!Array.isArray(l.trio)||!Array.isArray(l.sbc))fail('WEEKLY_COMMERCE_LAYOUT_REQUIRED');
 const scope={'fc27-weekly':l.weekly,'fc27-trio':[...l.trio,...(l.bundles||[])],'fc27-sbc':[...l.sbc,...l.sbc.flatMap(k=>[...(l.routes?.[k]?.picks||[]),...(l.routes?.[k]?.alternatives||[])])]};
 const models=new Map(),legacyPlatforms=new Map();
 for(const [page,keys] of Object.entries(scope)){
  const selectedMids=[];for(const key of [...new Set(keys)]){
   const model=draft.fc_models?.[key],legacy=catalog?.products?.[key];let mid=model?.model_id,kind=model?.kind||legacy?.kind;
   if(!mid&&legacy){const goods=Object.values(legacy.platforms||{}).map(p=>String(p.id));const ids=new Set((policy.native_catalog?.products||[]).filter(p=>p.product_ref.game_id==='1327'&&goods.includes(p.product_ref.goods_id)).map(p=>p.product_ref.model_id));if(ids.size===1)mid=[...ids][0];}
   if(!mid&&legacy){const goods_id=String(legacy.platforms?.ps?.id||'');if(!/^[1-9]\d*$/.test(goods_id))fail('WEEKLY_COMMERCE_MODEL_UNVERIFIED');const row=(await call({action:'product_read',site_id:'266',game_id:'1327',goods_id}))?.product?.product_ref;if(row?.site_id!=='266'||row.game_id!=='1327'||row.goods_id!==goods_id)fail('WEEKLY_COMMERCE_MODEL_UNVERIFIED');mid=row.model_id;}
   if(!/^[1-9]\d{0,19}$/.test(mid||'')||!categories[kind])fail('WEEKLY_COMMERCE_MODEL_UNVERIFIED');
   if(models.has(mid)&&models.get(mid)!==kind)fail('WEEKLY_COMMERCE_MODEL_UNVERIFIED');models.set(mid,kind);selectedMids.push(mid);if(legacy)legacyPlatforms.set(mid,legacy.platforms);
  }scope[page]=[...new Set(selectedMids)];
 }
 if(models.size>60)fail('WEEKLY_COMMERCE_SELECTION_LIMIT');
 return {scope,models,legacyPlatforms};
}
function runner({script,input}){return new Promise((resolve,reject)=>{
 const child=execFile('/opt/python39/bin/python3',['-B',script],{timeout:60000,maxBuffer:1000000,windowsHide:true},(error,stdout)=>{
  if(error)return reject(Object.assign(Error('WEEKLY_COMMERCE_INSTALL_UNKNOWN'),{code:'WEEKLY_COMMERCE_INSTALL_UNKNOWN'}));
  try{resolve(JSON.parse(stdout));}catch{reject(Object.assign(Error('WEEKLY_COMMERCE_INSTALL_UNKNOWN'),{code:'WEEKLY_COMMERCE_INSTALL_UNKNOWN'}));}
 });child.stdin.on('error',()=>{});child.stdin.end(JSON.stringify(input));
});}
export function makeWeeklyCommerce({dir,readPolicy,catalog,call=backendRead,now=Date.now,installRunner=runner}={}){
 const file=id=>{uuid(id);return path.join(dir,id+'.json');},candidateFile=id=>path.join(dir,id+'.policy.json');
 const privateFile=filename=>{const s=fs.lstatSync(filename);if(s.isSymbolicLink()||!s.isFile()||s.size>4194304||process.platform!=='win32'&&(s.mode&0o077)!==0)fail('WEEKLY_COMMERCE_PRIVATE_FILE_REQUIRED');return fs.readFileSync(filename);};
 function check(proposal,{revision,draft,publication_operation_id},owner){
  if(proposal.owner!==owner)fail('WEEKLY_COMMERCE_OWNER_MISMATCH');
  if(proposal.revision!==revision||proposal.draft_hash!==hashDraft(draft))fail('WEEKLY_COMMERCE_DRAFT_CHANGED');
  if(now()>=Date.parse(proposal.valid_until))fail('WEEKLY_COMMERCE_PROPOSAL_EXPIRED');
  const current=sha(policyBytes(readPolicy));if(current!==proposal.policy_before_sha){if(!publication_operation_id||current!==proposal.candidate_sha)fail('WEEKLY_COMMERCE_POLICY_CHANGED');uuid(publication_operation_id);}
  if(sha(privateFile(candidateFile(proposal.proposal_id)))!==proposal.candidate_sha)fail('WEEKLY_COMMERCE_CANDIDATE_CHANGED');
  return proposal;
 }
 return {
  previewCatalog({revision,draft},owner){
   if(!Number.isSafeInteger(revision)||revision<0||!draft||typeof draft!=='object'||Array.isArray(draft))return null;
   if(!fs.existsSync(dir))return null;
   const proposals=fs.readdirSync(dir).filter(name=>/^[0-9a-f-]{36}\.json$/.test(name)).map(name=>JSON.parse(privateFile(path.join(dir,name)))).filter(proposal=>proposal.owner===owner);
   for(const proposal of proposals)if(!Number.isFinite(Date.parse(proposal.created_at)))fail('WEEKLY_COMMERCE_PROPOSAL_INVALID');
   proposals.sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at));
   for(const proposal of proposals){
    try{check(proposal,{revision,draft},owner);}catch(error){
     if(['WEEKLY_COMMERCE_DRAFT_CHANGED','WEEKLY_COMMERCE_PROPOSAL_EXPIRED','WEEKLY_COMMERCE_POLICY_CHANGED'].includes(error.code))continue;
     throw error;
    }
    return structuredClone(proposal.preview_catalog);
   }
   return null;
  },
  async prepare({operation_id,revision,draft},owner){
   try{
   uuid(operation_id);if(!Number.isSafeInteger(revision)||revision<0||!draft||typeof owner!=='string'||!/^[-A-Za-z0-9_]{1,80}$/.test(owner))fail('WEEKLY_COMMERCE_REQUEST_INVALID');
   const before=policyBytes(readPolicy);let policy;try{policy=JSON.parse(before);}catch{fail('WEEKLY_COMMERCE_POLICY_INVALID');}const {scope,models,legacyPlatforms}=await selected(draft,catalog,policy,call),identities=[],normal=[];
   const discount=discountEvidence(await call({action:'benefit_detail',kind:'discount',native_id:'6049',site_id:'266'}),now());
   // Only server-owned backend reads can resolve manual additions; no browser prices or refs.
   const rows=[...models];let cursor=0;
   await Promise.all(Array.from({length:Math.min(4,rows.length)},async()=>{while(cursor<rows.length){const [model_id,kind]=rows[cursor++];const r=await call({action:'model_resolve',site_id:'266',game_id:'1327',model_id,kind});
    const model=r?.model;if(!r.resolution_complete||model?.model_id!==model_id||model.kind!==kind||model.site_id!=='266'||model.game_id!=='1327'||Object.values(model.platforms||{}).some(p=>p.state!=='verified'))fail('WEEKLY_COMMERCE_MODEL_UNVERIFIED');
    const stored=Object.values(draft.fc_models||{}).find(m=>m.model_id===model_id);
    if(stored&&Object.keys(model.platforms).some(code=>canonical(stored.platforms?.[code]?.product_ref)!==canonical(model.platforms[code].product_ref)))fail('WEEKLY_COMMERCE_DRAFT_IDENTITY_CHANGED');
    const legacy=legacyPlatforms.get(model_id);if(legacy&&Object.keys(legacy).some(code=>String(legacy[code].id)!==model.platforms?.[code]?.product_ref?.goods_id))fail('WEEKLY_COMMERCE_DRAFT_IDENTITY_CHANGED');
    if(kind==='player'&&r.player_type!=='normal')fail('WEEKLY_COMMERCE_NORMAL_PLAYER_REQUIRED');identities.push(model);if(kind==='player')normal.push({model_id,player_type:'normal'});
   }}));
   const items=rows.map(([model_id,kind])=>({key:model_id,site_id:'266',game_id:'1327',model_id,category_id:categories[kind]}));
   const readings=(await call({action:'model_provider_batch',site_id:'266',items},{timeout:300000}))?.readings;
   const observations=rows.map(([mid])=>{const r=readings?.[mid];if(r?.status!=='ok')fail('WEEKLY_COMMERCE_OBSERVATION_UNAVAILABLE');const o=structuredClone(r.data);
    if(o.model?.model_id!==mid||o.model.game_id!=='1327'||o.model.category_id!==categories[models.get(mid)])fail('WEEKLY_COMMERCE_OBSERVATION_UNAVAILABLE');
    for(const p of o.products||[])p.option_structures_observed=empty(p.specification?.saleprop)&&empty(p.specification?.skuTableSet);return o;});
   const source={observed_at:new Date(Math.min(...observations.map(o=>Date.parse(o.observed_at)))).toISOString(),models:identities,observations:normal,provider_observations:observations};
   const projected=weeklyNativeCandidates({source,pricePolicy:policy.admin_reference_prices,nativeCatalog:policy.native_catalog,now:now()});
   const candidate=projected.native_catalog_candidate;if(!candidate||projected.price_policy_candidates.length!==models.size||candidate.products.length!==models.size*3)fail('WEEKLY_COMMERCE_MAPPING_INCOMPLETE');
   const next=structuredClone(policy),cat=next.native_catalog;if(!cat||!next.native_checkout||next.native_checkout.status!=='configured')fail('WEEKLY_COMMERCE_ORIGINAL_CONTRACT_REQUIRED');
   const trusted=projectNativeCatalog(candidate,{now:now()}),added={prices:0,products:0,contracts:0,bindings:0},replaced={prices:0,products:0,bindings:0};
   for(const {policy:p} of projected.price_policy_candidates){const i=next.admin_reference_prices.entries.findIndex(x=>entryKey(x)===entryKey(p));if(i<0){next.admin_reference_prices.entries.push(p);added.prices++;}else if(canonical(next.admin_reference_prices.entries[i])!==canonical(p)){next.admin_reference_prices.entries[i]=p;replaced.prices++;}}
   for(const p of trusted.products){const i=cat.products.findIndex(x=>x.key===p.key);if(i<0){cat.products.push(p);added.products++;}else{if(canonical(cat.products[i].product_ref)!==canonical(p.product_ref)||canonical(cat.products[i].platform)!==canonical(p.platform))fail('WEEKLY_COMMERCE_IDENTITY_CHANGED');cat.products[i]=p;replaced.products++;}}
   for(const [mid,c] of Object.entries(trusted.model_contracts)){if(!cat.model_contracts[mid])added.contracts++;cat.model_contracts[mid]=c;}
   // Mapping lifetime and all unrelated policies remain from the original installed contract.
   projectNativeCatalog(cat,{now:now()});
   const bindings=next.native_checkout.bindings;
   for(const b of bindings)if(pages.includes(b.page_id)){if(b.off_percent!==10||b.activity_id!=='fc27-season2')fail('WEEKLY_COMMERCE_DISCOUNT_CONFLICT');if(b.code!=='FCSCOUT10'){b.code='FCSCOUT10';replaced.bindings++;}}
   const activeBindings=[];
   for(const [page,mids] of Object.entries(scope))for(const p of trusted.products.filter(p=>mids.includes(p.product_ref.model_id))){
    const explicit=draft.pages.find(x=>x.page_id===page)?.product_keys;
    if(Array.isArray(explicit)&&!explicit.some(key=>key===p.key||key==='fc-model-266-1327-'+p.product_ref.model_id+'-'+p.platform.code||Object.entries(catalog?.products||{}).some(([legacy,x])=>key==='fc-'+legacy+'-'+p.platform.code&&String(x.platforms?.[p.platform.code]?.id)===p.product_ref.goods_id)))continue;
    const b={activity_id:'fc27-season2',page_id:page,product_key:p.key,quantity:{value:'1',unit:'item'},attributes:[],off_percent:10,code:'FCSCOUT10',native:{category:'new_items',id:p.product_ref.goods_id,group:'1',num:'1',attr:'',aid:p.platform.attribute_id}};
    activeBindings.push(b);
    const i=bindings.findIndex(x=>x.page_id===page&&x.product_key===p.key&&x.off_percent===10&&canonical(x.quantity)===canonical(b.quantity)&&canonical(x.attributes)===canonical(b.attributes));if(i<0){bindings.push(b);added.bindings++;}else if(canonical(bindings[i])!==canonical(b)){bindings[i]=b;replaced.bindings++;}
   }
   const selectedBindings=activeBindings;
   if(discount.aid&&discount.aid!=='0'&&selectedBindings.some(b=>b.native.aid!==discount.aid))fail('WEEKLY_COMMERCE_DISCOUNT_PLATFORM_SCOPE');
   const allPages=pages.map(page_id=>{const p=draft.pages.find(p=>p.page_id===page_id);if(!p)fail('WEEKLY_COMMERCE_ORIGINAL_PAGE_REQUIRED');return {...p,product_keys:selectedBindings.filter(b=>b.page_id===page_id).map(b=>b.product_key)};});
   handoff.projectConfiguration({...next.native_checkout,bindings:selectedBindings},allPages,trusted.products);
   if(next.admin_reference_prices.entries.length>300||cat.products.length>1000||bindings.length>3000)fail('WEEKLY_COMMERCE_CAPACITY_EXCEEDED');
   if(now()>Date.parse(discount.valid_until))fail('WEEKLY_COMMERCE_DISCOUNT_WINDOW_UNVERIFIED');
   if(sha(policyBytes(readPolicy))!==sha(before))fail('WEEKLY_COMMERCE_POLICY_CHANGED');
   const proposal_id=randomUUID(),candidateBytes=Buffer.from(JSON.stringify(next)),candidate_sha=sha(candidateBytes),draft_hash=hashDraft(draft);
   const expires_at=new Date(Math.min(Date.parse(candidate.valid_until),Date.parse(discount.valid_until))).toISOString();
   const proposal={schema_version:1,status:'prepared',proposal_id,operation_id,owner,revision,draft_hash,policy_before_sha:sha(before),candidate_sha,created_at:new Date(now()).toISOString(),valid_until:expires_at,expires_at,models_count:models.size,policy_write_required:canonical(policy)!==canonical(next),can_publish:true,blockers:[],discount_verification:discount,
    checks:{native_field_contract:'existing_fc_one_item',player_type:'observed_normal',price:'admin_current_reference',discount_code:'FCSCOUT10',benefit_id:'6049',coupon_write:false,publication:false},diff:{added,replaced,price_entries:next.admin_reference_prices.entries.length,native_products:cat.products.length,bindings:bindings.length},
    resolved_models:identities,preview_catalog:candidate,candidate_path:candidateFile(proposal_id),proposal_path:file(proposal_id)};
   fs.mkdirSync(dir,{recursive:true,mode:0o700});if(fs.lstatSync(dir).isSymbolicLink())fail('WEEKLY_COMMERCE_PRIVATE_FILE_REQUIRED');
   for(const [filename,bytes] of [[candidateFile(proposal_id),candidateBytes],[file(proposal_id),Buffer.from(JSON.stringify(proposal))]]){const fd=fs.openSync(filename,'wx',0o600);try{fs.writeFileSync(fd,bytes);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}}
   return {...proposal,proposal_sha:sha(privateFile(file(proposal_id)))};
   }catch(error){if(typeof error.code==='string'&&/^[A-Z][A-Z0-9_]{1,100}$/.test(error.code))return {status:'blocked',operation_id,revision,can_publish:false,blockers:[error.code],models_count:0,policy_write_required:false,preview_catalog:null,expires_at:null,diff:null};throw error;}
  },
  validate({proposal_id,revision,draft,publication_operation_id},owner){const bytes=privateFile(file(proposal_id)),proposal=JSON.parse(bytes);check(proposal,{revision,draft,publication_operation_id},owner);return {...proposal,proposal_sha:sha(bytes)};},
  async install(proposal,publicationOperationId){
   uuid(publicationOperationId);const bytes=privateFile(file(proposal.proposal_id)),saved=JSON.parse(bytes);
   if(sha(bytes)!==proposal.proposal_sha||saved.owner!==proposal.owner||saved.candidate_sha!==proposal.candidate_sha)fail('WEEKLY_COMMERCE_PROPOSAL_CHANGED');
   const result=await installRunner({script:path.join(path.dirname(fileURLToPath(import.meta.url)),'weekly-commerce-install.py'),input:{action:'install',confirm:true,operation_id:publicationOperationId,proposal_id:saved.proposal_id,proposal_sha:sha(bytes),owner:saved.owner}});
   if(!['installed','already_installed'].includes(result?.state)||result.operation_id!==publicationOperationId||result.candidate_sha!==saved.candidate_sha)fail('WEEKLY_COMMERCE_INSTALL_UNKNOWN');return result;
  }
 };
}
