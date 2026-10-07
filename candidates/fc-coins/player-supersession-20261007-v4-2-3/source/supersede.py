"""Read-only proof and CAS metadata supersession. No business price writer."""
import copy,json,time
from datetime import datetime,timezone
from decimal import Decimal as D
from reconcile import digest,encode,fail,approved_tiers,stable

def validate_supersession_round(scope,ledger,job,audit,policy,proof,now,approved):
    old=scope['supersession']['old_coin_execution_id'];cid=scope['coin_execution_id']
    if ledger.get('status')!='needs_reconcile' or ledger.get('stage')!='stopped' or ledger.get('mode')!='category_all' or ledger.get('error')!='player_sample_readback_timeout' or ledger.get('coin_execution_id')!=old:fail('historical_failure_changed')
    if job.get('kind')!='player_sync' or job.get('status')!='failed' or job.get('error_detail')!='player_sample_readback_timeout' or job.get('job_id')!=scope['player_job_id'] or ledger.get('job_id')!=job['job_id']:fail('historical_job_changed')
    if proof.get('job_id')!=job['job_id'] or proof.get('coin_execution_id')!=cid or audit.get('execution_id')!=cid or audit.get('status')!='CONFIRMED' or audit.get('sync_confirmed') is not True:fail('supersession_current_basis_changed')
    if not policy.get('enabled') or policy['revision']!=job['request']['config_revision'] or proof['player_policy']!=policy:fail('supersession_player_policy_changed')
    start=datetime.fromisoformat(proof['started_at']);end=datetime.fromisoformat(proof['checked_at'])
    if not start<=end<=now or not 0<=(now-start).total_seconds()<=60:fail('supersession_proof_expired')
    if proof.get('provenance')!=scope['proof_provenance'] or proof.get('read_only') is not True or proof.get('business_posts')!=0:fail('supersession_proof_origin_changed')
    if proof.get('ledger_sha256')!=scope['expected_files']['player-sync/'+scope['player_job_id']+'.json'] or proof.get('source_sha256')!=scope['expected_sources']['/opt/fc27-cloud-browser/player_sync_job.py']:fail('supersession_proof_source_changed')
    if proof.get('model_count')!=ledger['model_count'] or proof.get('model_scope_digest')!=ledger['model_ids_sha256'] or proof.get('sample_model_ids')!=scope['sample_model_ids'] or len(proof.get('samples',[]))!=5:fail('supersession_model_scope_changed')
    rates={r['platform']:D(str(r['b2c'])) for r in audit['after']['rows']}
    if set(rates)!={'PS','XBOX','PC'} or {p:D(v) for p,v in proof['expected_rates'].items()}!=rates:fail('supersession_rates_changed')
    reads=proof['coin_readbacks']
    if len(reads)!=6 or {(r['platform'],r['site_id']) for r in reads}!={(p,s) for p in rates for s in (0,266)}:fail('supersession_coin_scope_changed')
    if any(r['http_status']!=200 or r['response_code']!=1 or D(str(r['actual_unit_price']))!=rates[r['platform']] for r in reads):fail('supersession_coin_price_changed')
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
    if [s['model_id'] for s in proof['samples']]!=ledger['sample_model_ids']:fail('supersession_samples_changed')
    for sample in proof['samples']:
        mid=sample['model_id'];model=sample['model'];products=sample['products'];parts=sample['public_readback']
        if int(model['id'])!=mid or int(model['gid'])!=1327 or int(model['cid'])!=9627 or str(model['status'])!='1':fail('supersession_model_identity_changed')
        if len(products)!=6 or sorted(int(p['id']) for p in products)!=scope['sample_product_ids'][str(mid)] or {(p['platform'],int(p['site_id'])) for p in products}!={(p,s) for p in rates for s in (0,266)}:fail('supersession_linked_identity_changed')
        for p in products:
            if int(p['mid'])!=mid or int(p['gid'])!=1327 or int(p['cid'])!=9627 or int(p['aid'])!={'PS':21587,'XBOX':21585,'PC':21589}[p['platform']] or str(p['status'])!='1' or int(p['total'])<0:fail('supersession_linked_scope_changed')
        before=ledger['sample_before'][str(mid)]
        if len(parts)!=3 or {p['platform'] for p in parts}!=set(rates) or {p['product_id'] for p in parts}!={p['product_id'] for p in before}:fail('supersession_public_identity_changed')
        for part in parts:
            p=part['platform']
            # Historical quantities belong to the failed plan; current collection may change them.
            # Supersession authorizes a new job, never replay or confirmation of that plan.
            if D(sample['model_inputs'][p])!=D(part['our_price_coins']) or D(sample['model_inputs']['coefficient'])!=D(part['coefficient']):fail('supersession_player_inputs_changed')
            target=D(part['our_price_coins'])/1000*rates[p]*D(part['coefficient'])
            if D(part['target_usd'])!=target or type(part['backend_match']) is not bool or type(part['public_match']) is not bool or part['backend_match']!=(abs(D(part['backend_usd'])-target)<=D('.001')) or part['public_match']!=(abs(D(part['public_usd'])-target)<=D('.001')):fail('supersession_player_observation_inconsistent')
    return True

def supersession_after(scope,originals,proofs,stamp,manifest_sha,backup):
    marker={'old_coin_execution_id':scope['supersession']['old_coin_execution_id'],'superseding_coin_execution_id':scope['coin_execution_id'],'player_revision':scope['player_revision'],'reason':'later_confirmed_coin_execution','needs_fresh_auto_cycle':True,'readback_proof_sha256':digest(encode(proofs)),'at':stamp}
    out={}
    for key in scope['allowed_metadata_targets']:
        value=json.loads(originals[key]);value['status']='superseded';value['supersession']=marker
        # Preserve error, error_detail, result, stage and original completion timestamps.
        out[key]=encode(value)
    return out

class Supersession:
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
        after=supersession_after(self.scope,originals,first,state['created_at'],self.manifest_sha,self.store.backup_path)
        if {k:digest(v) for k,v in after.items()}!=state['after_sha256']:fail('intended_metadata_not_proof_driven')
        for key,raw in after.items():
            if self.store.tx_read(self.after_names[key])!=raw:fail('backup_intended_changed')
        if state['phase']=='evidence_committed':
            receipt=json.loads(self.store.tx_read('supersession-receipt.json'))
            marker=json.loads(after[self.targets[0]])['supersession']
            basis={k:v for k,v in self.scope['expected_files'].items() if k.startswith(('executions/','all-coin-sync/'))}
            if receipt!={'status':'superseded','player_job_id':self.scope['player_job_id'],'marker':marker,'after_sha256':state['after_sha256'],'basis_sha256':basis}:fail('supersession_receipt_changed')
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
        for proof in proofs:validate_supersession_round(self.scope,ledger,job,audit,policy,proof,now,approved)
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
            return {'status':'already_superseded_exact_publication' if apply else 'superseded_metadata_visible_durability_unclaimed','business_posts':0,'backup':self.store.backup_path}
        started=self.monotonic();proofs=[]
        for index in range(2):
            if index:self.wait(5)
            proofs.append(self.probe(json.loads(originals[self.targets[0]]),originals[self.targets[0]]))
        def checkpoint():
            self.context(self.allowed(state))
            self.validate_batch(originals,proofs,self.now())
            if self.monotonic()-started>160:fail('reconcile_total_budget_exceeded')
        checkpoint()
        if not apply:return {'status':'supersession_preflight_ready','business_posts':0,'two_stable_rounds':proofs,'metadata_targets':self.targets}
        if not state:
            self.store.create_tx()
            for key,raw in originals.items():self.store.tx_write(self.before_names[key],raw)
            stamp=self.now().isoformat();after=supersession_after(self.scope,originals,proofs,stamp,self.manifest_sha,self.store.backup_path)
            for key,raw in after.items():self.store.tx_write(self.after_names[key],raw)
            state={'phase':'prepared','created_at':stamp,'scope_sha256':digest(encode(self.scope)),'candidate_manifest_sha256':self.manifest_sha,'after_sha256':{key:digest(raw) for key,raw in after.items()},'proof_history':[]}
        self.save_proofs(state,proofs);self.event('prepared');checkpoint()
        ledger=self.targets[0]
        if digest(self.store.read_live(ledger))!=state['after_sha256'][ledger]:self.store.publish(ledger,self.store.tx_read(self.after_names[ledger]),self.allowed(state)[ledger],checkpoint)
        else:self.store.sync_visible(ledger)
        state['phase']='ledger_installed';self.store.tx_write('transaction.json',encode(state));self.event('ledger_installed');checkpoint()
        # Durable receipt and all evidence/ledger are complete BEFORE the gate-readable job.
        marker=json.loads(self.store.tx_read(self.after_names[self.targets[0]]))['supersession']
        basis={k:v for k,v in self.scope['expected_files'].items() if k.startswith(('executions/','all-coin-sync/'))}
        receipt={'status':'superseded','player_job_id':self.scope['player_job_id'],'marker':marker,'after_sha256':state['after_sha256'],'basis_sha256':basis}
        self.store.tx_write('supersession-receipt.json',encode(receipt))
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
        return {'status':'historical_failure_superseded_current_coin_readback','business_posts':0,'job_id':self.scope['player_job_id'],'backup':self.store.backup_path,'two_stable_rounds':proofs}

