// Read-only evidence helper: no network, subprocess, session reads, model call or business write.
// snapshot --data-dir DIR --public-dir DIR > before.json
// verify --operation-id UUID --before before.json [--data-dir DIR --public-dir DIR]
// --pid PID reads ONLY CAMPAIGN_DATA/CAMPAIGN_PUBLIC_RELEASE_DIR from the existing process environment.
import fs from 'node:fs';import path from 'node:path';import {createHash} from 'node:crypto';
const canonical=v=>JSON.stringify(v,(_k,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,x[k]])):x);
const hash=v=>createHash('sha256').update(canonical(v)).digest('hex'),read=p=>JSON.parse(fs.readFileSync(p,'utf8')),exists=p=>fs.existsSync(p);
const args=process.argv.slice(2),mode=args.shift(),options={};for(let i=0;i<args.length;i+=2){if(!['--data-dir','--public-dir','--operation-id','--before','--pid'].includes(args[i])||!args[i+1])throw Error('INVALID_ARGUMENT');options[args[i].slice(2)]=args[i+1];}
let env={};if(options.pid){if(!/^[1-9]\d*$/.test(options.pid))throw Error('INVALID_PID');for(const entry of fs.readFileSync('/proc/'+options.pid+'/environ','utf8').split('\0')){const n=entry.indexOf('=');if(['CAMPAIGN_DATA','CAMPAIGN_PUBLIC_RELEASE_DIR'].includes(entry.slice(0,n)))env[entry.slice(0,n)]=entry.slice(n+1);}}
const data=options['data-dir']||env.CAMPAIGN_DATA||'/var/lib/fs-campaign-dashboard',pub=options['public-dir']||env.CAMPAIGN_PUBLIC_RELEASE_DIR||'/var/lib/fs-campaign-public',center=path.join(data,'center'),fc=new Set(['fc27-trio','fc27-weekly','fc27-sbc']);
const published=()=>{const f=path.join(pub,'current.json');return exists(f)?hash(read(f)):null;};
function summary(s){const d=s.draft;return {revision:s.revision,state_hash:hash(s),published_hash:published(),published_metadata_hash:hash(s.published??null),other_pages_hash:hash(d.pages.filter(p=>!fc.has(p.page_id))),all_page_benefits_hash:hash(d.pages.map(p=>({page_id:p.page_id,benefit_refs:p.benefit_refs??null,benefit_binding_version:p.benefit_binding_version??null}))),halloween_hash:hash({halloween:d.halloween??null,seasonal_theme:d.seasonal_theme??null}),fc_page_copy_hash:hash(d.pages.filter(p=>fc.has(p.page_id)).map(({product_keys,product_roles,sbc_companions,...p})=>p))};}
try{
 const state=read(path.join(center,'state.json')),after=summary(state);
 if(mode==='snapshot'){console.log(JSON.stringify({schema_version:1,captured_at:new Date().toISOString(),...after},null,2));}
 else if(mode==='verify'){
 const id=options['operation-id'];if(!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id||'')||!options.before)throw Error('OPERATION_AND_BEFORE_REQUIRED');
 const before=read(options.before),plan=read(path.join(center,'weekly-plans',id+'.json')),receipt=read(path.join(center,'operations',id+'.json')),result=receipt.result,draft=result.draft,layout=draft.fc_layout,source=plan.source,checks={};
 const expected=plan.save_request?hash({kind:'save',revision:plan.save_request.revision,draft:plan.save_request.draft,model_imports:plan.save_request.model_imports,...(plan.save_request.model_refresh_digest?{model_refresh_digest:plan.save_request.model_refresh_digest}:{})}):null;
 checks.operation_receipt=!!expected&&receipt.hash===expected&&result.last_operation?.hash===expected&&result.last_operation.operation_id===id&&result.last_operation.kind==='save'&&result.revision===plan.base_revision+1;
 checks.live_center_matches_receipt=state.revision===result.revision&&hash(state)===hash(result);
 checks.before_matches_plan=before.revision===plan.base_revision;
 for(const field of ['published_hash','published_metadata_hash','other_pages_hash','all_page_benefits_hash','halloween_hash','fc_page_copy_hash'])checks[field+'_unchanged']=before[field]===after[field];
 const mid=k=>draft.fc_models?.[k]?.model_id,unique=a=>new Set(a).size===a.length;
 checks.scout_source_order=layout.weekly.length===3&&unique(layout.weekly)&&canonical(layout.weekly.map(mid))===canonical(source.scout_model_ids);
 checks.trio_source_pool=layout.trio.length===3&&unique(layout.trio)&&layout.trio.every(k=>source.trio_player_ids.includes(mid(k)));
 checks.sbc_source_order=layout.sbc.length===9&&unique(layout.sbc)&&canonical(layout.sbc.map(mid))===canonical(source.sbc_model_ids)&&layout.defaultCore===layout.sbc[0];
 const selected=[...new Set([...layout.weekly,...layout.trio,...layout.sbc,...layout.sbc.flatMap(k=>[...(layout.routes[k]?.picks||[]),...(layout.routes[k]?.alternatives||[])])])];
 const models=selected.map(key=>{const m=draft.fc_models?.[key];if(!m)return {key,missing:true};const platforms=['ps','xbox','pc'].map(code=>{const p=m.platforms?.[code],r=p?.product_ref;return {platform:code,state:p?.state??'missing',goods_id:r?.goods_id??null,same_model:r?.model_id===m.model_id&&r?.game_id==='1327'&&r?.site_id==='266'};});return {key,model_id:m.model_id,title:m.title,kind:m.kind,image_provenance:m.image_provenance,has_image:!!m.image_url,platforms};});
 checks.three_platform_identities=models.every(m=>!m.missing&&m.platforms.every(p=>p.state==='verified'&&p.same_model)&&unique(m.platforms.map(p=>p.goods_id)));
 const routes=layout.sbc.map(core=>{const r=layout.routes[core]||{};return {core_model_id:mid(core),pick_model_ids:(r.picks||[]).map(mid),alternative_model_ids:(r.alternatives||[]).map(mid)};});
 checks.sbc_companion_structure=routes.every(r=>r.pick_model_ids.length===2&&r.alternative_model_ids.length===16&&unique([...r.pick_model_ids,...r.alternative_model_ids])&&[...r.pick_model_ids,...r.alternative_model_ids].every(x=>x&&x!==r.core_model_id));
 checks.sbc_has_multiple_choices=routes.every(r=>r.alternative_model_ids.length===16);
 const picked=routes.flatMap(r=>r.pick_model_ids),pool=new Set(picked),observations=source.observations||[];
 const normal=key=>{const m=draft.fc_models?.[key],facts=observations.filter(o=>o.model_id===m?.model_id);return m?.kind==='player'&&facts.length>0&&facts.every(o=>o.player_type==='normal');};
 checks.scout_and_trio_normal=[...layout.weekly,...layout.trio].every(normal);
 checks.sbc_nine_cores=layout.sbc.length===9&&layout.sbc.every(k=>draft.fc_models?.[k]?.kind==='sbc');
 checks.sbc_eighteen_distinct_normal=picked.length===18&&pool.size===18&&layout.sbc.flatMap(k=>layout.routes[k]?.picks||[]).every(normal);
 checks.sbc_shared_eighteen_pool=routes.every(r=>{const ids=[...r.pick_model_ids,...r.alternative_model_ids];return ids.length===18&&unique(ids)&&ids.every(id=>pool.has(id));});
 checks.selected_images_have_sources=selected.every(k=>{const m=draft.fc_models?.[k];try{const u=new URL(m?.image_url);return ['historical_accepted_model_asset','admin_model_uploaded_asset','storefront_player_id_asset'].includes(m.image_provenance)&&u.protocol==='https:'&&['assets.mmoexp.com','b2c-static.p2pah.cn'].includes(u.hostname)&&!u.username&&!u.password&&!u.port&&!u.search&&!u.hash&&/\.(png|jpe?g|webp)$/i.test(u.pathname);}catch{return false;}});
 checks.source_goods_coverage=(source.observations||[]).length>0&&source.observations.every(o=>o.goods_complete===true);
 const verified=Object.values(checks).every(Boolean);console.log(JSON.stringify({schema_version:1,status:verified?'checks_passed':'review_required',scope:'local_center_draft_and_receipts_not_publication_or_natural_run',operation_id:id,before_revision:before.revision,draft_revision:result.revision,current_revision:state.revision,checks,source:{observed_at:source.observed_at,rules_version:source.rules_version,latest_order:source.evidence?.latest_order,latest_semantics:source.evidence?.latest_semantics,popular_tag_id:source.evidence?.popular_tag_id,popular_order:source.evidence?.popular_order,popular_scanned:source.evidence?.popular_scanned,popular_total:source.evidence?.popular_total,snapshot_atomic:source.evidence?.snapshot_atomic,latest_player_ids:source.latest_player_ids,trio_pool_ids:source.trio_player_ids,scout_model_ids:source.scout_model_ids,sbc_model_ids:source.sbc_model_ids},layout:{weekly:layout.weekly.map(mid),trio:layout.trio.map(mid),default_core:mid(layout.defaultCore),routes},models,publication_executed:false,price_and_checkout_verification:'not_asserted'},null,2));if(!verified)process.exitCode=2;
 }else throw Error('MODE_MUST_BE_SNAPSHOT_OR_VERIFY');
}catch(e){console.error(JSON.stringify({status:'evidence_unavailable',reason:e.code||'READ_OR_CONTRACT_FAILED'}));process.exitCode=1;}
