"""Exact-scope readback proof and final-job publication protocol; no business writer."""
import copy,hashlib,json,time
from datetime import datetime,timezone
from decimal import Decimal as D
from player_readonly_reconcile_guard import validate_proof,stable_view

def digest(raw):return hashlib.sha256(raw).hexdigest()
def encode(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode("utf-8")
def fail(reason):raise ValueError(reason)

def validate_round(scope,ledger,job,audit,policy,proof,now,approved):
    started=datetime.fromisoformat(proof["started_at"]);ended=datetime.fromisoformat(proof["checked_at"])
    if not 0 <= (now-started).total_seconds() <= 60 or not started <= ended <= now:fail("earliest_observation_expired")
    if proof.get("provenance")!=scope["proof_provenance"]:fail("proof_dependency_origin_changed")
    validate_proof(ledger,job,audit,policy,proof,now)
    if proof.get('read_only') is not True or proof.get('business_posts')!=0:fail('proof_business_write_forbidden')
    if proof.get('ledger_sha256')!=scope['expected_files']['player-sync/'+scope['player_job_id']+'.json']:fail('proof_original_ledger_changed')
    if proof.get('source_sha256')!=scope['expected_sources']['/opt/fc27-cloud-browser/player_sync_job.py']:fail('proof_player_source_changed')
    if proof.get('sample_model_ids')!=scope['sample_model_ids']:fail('proof_sample_identity_changed')
    if proof.get('model_count')!=ledger['model_count'] or proof.get('model_scope_digest')!=ledger['model_ids_sha256']:fail('full_model_scope_changed')
    rates={x['platform']:D(str(x['b2c'])) for x in audit['after']['rows']}
    if len(proof.get('coins_public',[]))!=3:fail('coin_public_scope_incomplete')
    for row in proof['coin_readbacks']:
        expected_id={'PS':{0:163329309,266:163329311},'XBOX':{0:163329275,266:163329277},'PC':{0:163329343,266:163329345}}[row['platform']][row['site_id']]
        if row.get('product_id')!=expected_id:fail('coin_product_identity_changed')
        identity=row['identity']
        if any(int(identity[k])!=v for k,v in {'id':expected_id,'mid':41217957,'gid':1327,'cid':9623,'aid':{'PS':21587,'XBOX':21585,'PC':21589}[row['platform']],'site_id':row['site_id'],'status':1}.items()):fail('coin_backend_identity_changed')
        if row.get('tier_gold')!=scope['tier_gold'] or row.get('tier_give')!=scope['tier_give'] or row.get('tier_discount')!=scope['tier_discount']:fail('coin_quantity_vector_changed')
        if len(row.get('tier_price',[]))!=15:fail('coin_price_vector_incomplete')
        expected=approved[row['platform']]
        if [D(str(x)) for x in row['tier_price']]!=[D(str(x)) for x in expected['price']]:fail('coin_approved_tier_target_changed')
    public_platforms=set()
    for public in proof['coins_public']:
        platform=public['platform'];public_platforms.add(platform)
        backend=next(x for x in proof['coin_readbacks'] if x['platform']==platform and x['site_id']==266)
        if public.get('sku_id')!=backend['product_id'] or len(public.get('tiers',[]))!=15:fail('coin_public_identity_changed')
        for i,tier in enumerate(public['tiers']):
            if (tier['num']!=backend['tier_gold'][i] or tier['give']!=backend['tier_give'][i] or tier['discount']!=backend['tier_discount'][i]
                or D(str(tier['price']))!=D(str(backend['tier_price'][i])) or D(str(tier['price_discount']))!=D(str(backend['tier_price'][i]))):fail('coin_public_price_or_quantity_mismatch')
    if public_platforms!=set(rates):fail('coin_public_platforms_changed')
    for sample in proof['samples']:
        products=sample['products'];parts=sample['public_readback']
        if len(products)!=6 or len({int(x['id']) for x in products})!=6:fail('player_linked_scope_incomplete')
        if sorted(int(x['id']) for x in products)!=scope['sample_product_ids'][str(sample['model_id'])]:fail('player_linked_product_ids_changed')
        if {(x['platform'],int(x['site_id'])) for x in products}!={(p,s) for p in rates for s in (0,266)}:fail('player_linked_platform_scope_changed')
        for product in products:
            if int(product['aid'])!={'PS':21587,'XBOX':21585,'PC':21589}[product['platform']]:fail('player_area_identity_changed')
            if str(product['status'])!='1' or int(product['total'])<0:fail('player_linked_status_changed')
        for part in parts:
            product=next((x for x in products if int(x['id'])==part['product_id']),None)
            if not product or int(product['site_id'])!=266 or product['platform']!=part['platform']:fail('player_public_link_identity_changed')
            if not part['backend_match'] or not part['public_match']:fail('player_match_flags_false')
    return True

def stable(proof):
    return {'samples':stable_view(proof),'linked_identity':[(s['model_id'],sorted((r['id'],r['aid'],r['status'],r['total']) for r in s['products'])) for s in proof['samples']],
            'coins':sorted((r['platform'],r['site_id'],r['product_id'],str(r['actual_unit_price']),r['tier_gold'],r['tier_give'],r['tier_discount'],r['tier_price']) for r in proof['coin_readbacks']),
            'public':proof['coins_public']}

def approved_tiers(all_ledger,audit,scope):
    if all_ledger['status']!='confirmed' or len(all_ledger['steps'])!=3:fail('approved_all_plan_incomplete')
    out={};rates={r['platform']:D(str(r['b2c'])) for r in audit['after']['rows']}
    for step in all_ledger['steps']:
        p=step['platform'];source=step['source'];target=step['payload']
        if p in out or step['status']!='confirmed':fail('approved_all_step_unconfirmed')
        if D(str(source['unit_price']))!=rates[p] or D(str(target['unit_price']))!=rates[p]:fail('approved_all_rate_changed')
        for key,expected in [('gold',scope['tier_gold']),('give',scope['tier_give']),('discount',scope['tier_discount'])]:
            if source['more'][key]!=expected or target['more'][key]!=expected:fail('approved_quantity_contract_changed')
        prices=source['more']['price']
        if len(prices)!=15 or [D(str(x)) for x in prices]!=[D(str(x)) for x in target['more']['price']]:fail('approved_all_site_target_disagreement')
        if any(not D(str(x)).is_finite() or D(str(x))<=0 for x in prices):fail('approved_price_invalid')
        out[p]={'price':prices}
    if set(out)!=set(rates):fail('approved_platform_scope_changed')
    return out

def make_after(scope,originals,proofs,stamp,manifest_sha,backup):
    targets=scope['allowed_metadata_targets'];ledger=json.loads(originals[targets[0]]);job=json.loads(originals[targets[1]])
    old_ledger=copy.deepcopy(ledger);old_job=copy.deepcopy(job)
    ledger.setdefault('recoveries',[]).append({'at':stamp,'method':'two_stable_independent_readbacks','original':old_ledger,'backup':backup,'scope_sha256':digest(encode(scope)),'candidate_manifest_sha256':manifest_sha,'business_posts':0})
    ledger.update(status='confirmed',stage='complete_independent_readback',error=None,completed_at=stamp,updated_at=stamp,sample_readback={str(s['model_id']):s['public_readback'] for s in proofs[-1]['samples']},sample_verified_count=5,verified_count=5,sample_verified_model_ids=sorted(ledger['sample_model_ids']),active_model_id=None)
    result={'status':'confirmed','mode':'category_all','model_count':ledger['model_count'],'sample_count':5,'sample_verified_count':5,'coin_execution_id':scope['coin_execution_id'],'reconciled_by':'two_stable_independent_readbacks'}
    job.setdefault('recovery_history',[]).append({'at':stamp,'original':old_job,'backup':backup,'business_posts':0,'candidate_manifest_sha256':manifest_sha})
    job.update(status='ready',result=result,sync_result=result,error=None,error_detail=None,completed_at=stamp)
    return {targets[0]:encode(ledger),targets[1]:encode(job)}

class Recovery:
    """All backup/receipt/ledger state is durable before final job publication."""
    def __init__(self,store,scope,manifest_sha,context,probe,now=None,wait=None,event=None,monotonic=None):
        self.store=store;self.scope=scope;self.manifest_sha=manifest_sha;self.context=context;self.probe=probe
        self.now=now or (lambda:datetime.now(timezone.utc));self.wait=wait or time.sleep;self.event=event or (lambda stage:None);self.monotonic=monotonic or time.monotonic
        self.targets=scope['allowed_metadata_targets']
        if self.targets!=['player-sync/'+scope['player_job_id']+'.json','jobs/'+scope['player_job_id']+'.json']:fail('metadata_scope_changed')
        self.keys=list(scope['expected_files']);self.before_names={key:'before-'+str(i)+'.json' for i,key in enumerate(self.keys)};self.after_names={self.targets[0]:'after-ledger.json',self.targets[1]:'after-job.json'}
    def load_state(self):
        if not self.store.tx_exists():return None
        try:state=json.loads(self.store.tx_read('transaction.json'))
        except FileNotFoundError:fail('incomplete_backup_requires_review')
        if state['scope_sha256']!=digest(encode(self.scope)) or state['candidate_manifest_sha256']!=self.manifest_sha:fail('transaction_scope_changed')
        if state['phase'] not in ['prepared','ledger_installed','evidence_committed']:fail('transaction_phase_invalid')
        originals=self.originals(state)
        if not state['proof_history']:fail('backup_proof_missing')
        for index,record in enumerate(state['proof_history']):
            if record['name']!='proofs-'+str(index)+'.json':fail('proof_record_path_changed')
            if digest(self.store.tx_read(record['name']))!=record['sha256']:fail('backup_proof_changed')
        first=json.loads(self.store.tx_read('proofs-0.json'));self.validate_batch(originals,first,datetime.fromisoformat(first[-1]['checked_at']))
        after=make_after(self.scope,originals,first,state['created_at'],self.manifest_sha,self.store.backup_path)
        if {k:digest(v) for k,v in after.items()}!=state['after_sha256']:fail('intended_metadata_not_proof_driven')
        for key,raw in after.items():
            if self.store.tx_read(self.after_names[key])!=raw:fail('backup_intended_changed')
        return state
    def originals(self,state):
        out={key:self.store.tx_read(self.before_names[key]) if state else self.store.read_live(key) for key in self.keys}
        if any(digest(raw)!=self.scope['expected_files'][key] for key,raw in out.items()):fail('original_scope_changed')
        return out
    def allowed(self,state):return {key:{self.scope['expected_files'][key]}|({state['after_sha256'][key]} if state else set()) for key in self.targets}
    def validate_batch(self,originals,proofs,now):
        if len(proofs)!=2:fail('two_proof_rounds_required')
        ledger=json.loads(originals[self.targets[0]]);job=json.loads(originals[self.targets[1]]);audit=json.loads(originals['executions/'+self.scope['coin_execution_id']+'.json']);policy=json.loads(originals['config/player-sync.json'])
        approved=approved_tiers(json.loads(originals['all-coin-sync/'+self.scope['coin_execution_id']+'.json']),audit,self.scope)
        for proof in proofs:validate_round(self.scope,ledger,job,audit,policy,proof,now,approved)
        if stable(proofs[0])!=stable(proofs[1]):fail('readback_not_stable')
        if datetime.fromisoformat(proofs[1]['started_at'])<datetime.fromisoformat(proofs[0]['checked_at']):fail('proof_round_order_changed')
    def save_proofs(self,state,proofs):
        name='proofs-'+str(len(state['proof_history']))+'.json';raw=encode(proofs);self.store.tx_write(name,raw)
        state['proof_history'].append({'name':name,'sha256':digest(raw),'started_at':proofs[0]['started_at'],'checked_at':proofs[-1]['checked_at']})
        self.store.tx_write('transaction.json',encode(state))
    def run(self,apply=False):
        state=self.load_state();self.context(self.allowed(state));originals=self.originals(state)
        if state and state['phase']=='evidence_committed' and all(digest(self.store.read_live(k))==state['after_sha256'][k] for k in self.targets):
            if apply:
                try:self.store.sync_visible(self.targets[1]);self.context(self.allowed(state))
                except Exception:return {'status':'metadata_may_be_committed_needs_readback','business_posts':0,'backup':self.store.backup_path}
            return {'status':'already_reconciled_exact_publication' if apply else 'confirmed_metadata_visible_durability_unclaimed','business_posts':0,'backup':self.store.backup_path}
        started=self.monotonic();proofs=[]
        for index in range(2):
            if index:self.wait(5)
            proofs.append(self.probe(json.loads(originals[self.targets[0]]),originals[self.targets[0]]))
        def checkpoint():
            self.context(self.allowed(state))
            self.validate_batch(originals,proofs,self.now())
            if self.monotonic()-started>160:fail('reconcile_total_budget_exceeded')
        checkpoint()
        if not apply:return {'status':'reconcile_preflight_ready','business_posts':0,'two_stable_rounds':proofs,'metadata_targets':self.targets}
        if not state:
            self.store.create_tx()
            for key,raw in originals.items():self.store.tx_write(self.before_names[key],raw)
            stamp=self.now().isoformat();after=make_after(self.scope,originals,proofs,stamp,self.manifest_sha,self.store.backup_path)
            for key,raw in after.items():self.store.tx_write(self.after_names[key],raw)
            state={'phase':'prepared','created_at':stamp,'scope_sha256':digest(encode(self.scope)),'candidate_manifest_sha256':self.manifest_sha,'after_sha256':{key:digest(raw) for key,raw in after.items()},'proof_history':[]}
        self.save_proofs(state,proofs);self.event('prepared');checkpoint()
        ledger=self.targets[0]
        if digest(self.store.read_live(ledger))!=state['after_sha256'][ledger]:self.store.publish(ledger,self.store.tx_read(self.after_names[ledger]),self.allowed(state)[ledger],checkpoint)
        else:self.store.sync_visible(ledger)
        state['phase']='ledger_installed';self.store.tx_write('transaction.json',encode(state));self.event('ledger_installed');checkpoint()
        # Durable receipt and all evidence/ledger are complete BEFORE the gate-readable job.
        state['phase']='evidence_committed';self.store.tx_write('transaction.json',encode(state));self.event('evidence_committed');checkpoint()
        job=self.targets[1]
        try:
            self.store.publish(job,self.store.tx_read(self.after_names[job]),self.allowed(state)[job],checkpoint)
        except Exception as exc:
            return {'status':'metadata_may_be_committed_needs_readback','business_posts':0,'backup':self.store.backup_path,'reason':str(exc)[:100] if isinstance(exc,ValueError) else type(exc).__name__}
        # No state/receipt/metadata write follows the final job publication commit point.
        try:
            self.context(self.allowed(state))
            if digest(self.store.read_live(job))!=state['after_sha256'][job]:fail('final_job_readback_changed')
        except Exception:
            return {'status':'metadata_may_be_committed_needs_readback','business_posts':0,'backup':self.store.backup_path}
        return {'status':'confirmed_by_independent_reconciliation','business_posts':0,'job_id':self.scope['player_job_id'],'backup':self.store.backup_path,'two_stable_rounds':proofs}

