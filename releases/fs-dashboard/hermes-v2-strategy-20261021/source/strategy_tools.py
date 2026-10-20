"""Task-bound research records in the existing FS DB; no business execution axis."""
from copy import deepcopy
from datetime import date, datetime
import json
import re
from types import SimpleNamespace
from pathlib import Path

from pilot import digest, encoded
from pricing_simulation import SimulationBridge

NAMES=('fs.strategy.capabilities','fs.strategy.propose','fs.pricing.simulate_candidate','fs.strategy.read_review','fs.learning.propose')
FIELDS={'project','intent','question','evidence_refs','baseline_policy','band_changes','hypothesis','risk_notes','review_plan'}


def schemas():
    text={'type':'string'};identity={'type':'object','properties':{'revision':{'type':'integer','minimum':0},'sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'}},'required':['revision','sha256'],'additionalProperties':False}
    band={'type':'object','properties':{'tier':{'enum':['at_least_40','30_to_40','20_to_30','below_20']},'min_discount_pct':text,'max_discount_pct':text},'required':['tier','min_discount_pct','max_discount_pct'],'additionalProperties':False}
    proposal={k:{'type':'string','minLength':1,'maxLength':4000} for k in ('question','hypothesis','risk_notes','review_plan')}
    proposal.update(project={'const':'FC27'},intent={'const':'draft_only'},evidence_refs={'type':'array','items':text,'minItems':1,'maxItems':100,'uniqueItems':True},baseline_policy=identity,band_changes={'type':'array','items':band,'minItems':1,'maxItems':4})
    proposal['band_changes']['minItems']=0
    idea_fields={k:{'type':'string','minLength':1,'maxLength':4000} for k in ('name','description','entry_conditions','pricing_formula','stop_conditions')}
    proposal['rule_idea']={'type':'object','properties':idea_fields,'required':list(idea_fields),'additionalProperties':False}
    experience={'type':'object','properties':{'kind':{'enum':['experience','method_diff']},'lesson':text,'applies_to':text,'evidence_refs':{'type':'array','items':text},'counterexample':text,'expires_at':text,'base_manifest_sha256':text,'lesson_diff':text},'required':['kind'],'additionalProperties':False}
    definitions=(
        ({},'Read live supported shared-band research scope and policy/engine identity. No production authority. Missing qualified sources do not block other research.'),
        (proposal,'Save evidence-backed new-rule ideas or discount candidates beyond the old 10 percent cap (0 <= research discount < 100). Shared bands affect PS/XBOX/PC; profit floor, gifts and linkage stay protected. Empty band_changes requires a rule_idea; unsupported new algorithms are ideas, never fake numeric simulations. No approval, identity, overrides, paths, commands or business controls.'),
        ({'project':{'const':'FC27'},'intent':{'const':'simulate_only'},'proposal_id':text,'snapshot_id':text,'expected_policy':identity},'Simulate a saved draft against an existing qualified immutable snapshot using the original engine. No collection, browser, writer, production preview or demand forecast. Read precheck and limitations.'),
        ({'decision_id':text,'start':text,'end':text},'Read research axes or an existing frozen action key report:action. Only verified execution can enter outcome evaluation; human notes alone do not create a system receipt. Empty history is unknown, not proof no operations occurred.'),
        ({'source':text,'candidate':experience},'Propose an experience or current-method diff from an owned completed report. Service assigns risk. Method differences require matching base manifest and human review; no publication permission.'))
    return [{'type':'function','function':{'name':'mcp__fcro__'+name.replace('.','_'),'description':description,'parameters':{'type':'object','properties':fields,'required':[k for k in fields if k!='rule_idea'],'additionalProperties':False}}} for name,(fields,description) in zip(NAMES,definitions)]


def schema(db):
    for table,columns in (
        ('strategy_drafts','id TEXT PRIMARY KEY,owner TEXT,project TEXT,task TEXT,content TEXT,content_hash TEXT,created_at TEXT'),
        ('strategy_simulations','id TEXT PRIMARY KEY,proposal TEXT,owner TEXT,task TEXT,input_hash TEXT UNIQUE,content TEXT,created_at TEXT'),
        ('method_candidates','id TEXT PRIMARY KEY,owner TEXT,project TEXT,source TEXT,base_manifest TEXT,content TEXT,risk TEXT,created_at TEXT'),
        ('strategy_control','owner TEXT PRIMARY KEY,enabled INTEGER')):
        db.execute('CREATE TABLE IF NOT EXISTS '+table+'('+columns+')')
        if [r[1] for r in db.execute('PRAGMA table_info('+table+')')]!=[s.strip().split()[0] for s in columns.split(',')]:raise ValueError('strategy_schema_conflict')


def allowed(owner):
    if owner!='wulv':raise PermissionError('strategy_initial_scope_denied')


def text(value):
    from report_delivery import private_report
    if not isinstance(value,str) or not 1<=len(value.strip())<=4000 or private_report(value):raise ValueError('strategy_text')


def policy_identity(value):
    if (not isinstance(value,dict) or set(value)!={'revision','sha256'} or type(value['revision']) is not int or value['revision']<0
            or not isinstance(value['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',value['sha256'])):raise ValueError('strategy_baseline_identity')


def get_draft(db,owner,key):
    schema(db);row=db.execute('SELECT * FROM strategy_drafts WHERE id=? AND owner=? AND project=?',(key,owner,'FC27')).fetchone()
    if row is None:raise PermissionError('strategy_proposal_not_found')
    value=json.loads(row['content'])
    if digest(value)!=row['content_hash']:raise ValueError('strategy_proposal_changed')
    return dict(row),value


def create(db,owner,task,args,refs,bridge,now):
    allowed(owner)
    if not isinstance(args,dict) or not FIELDS<=set(args) or set(args)-FIELDS-{'rule_idea'} or args['project']!='FC27' or args['intent']!='draft_only':raise ValueError('strategy_proposal_fields')
    for field in ('question','hypothesis','risk_notes','review_plan'):text(args[field])
    evidence=args['evidence_refs']
    if not isinstance(evidence,list) or not 1<=len(evidence)<=100 or any(not isinstance(x,str) or x not in refs for x in evidence) or len(set(evidence))!=len(evidence):raise ValueError('strategy_evidence_scope')
    policy_identity(args['baseline_policy']);engine,policy,identity=bridge.baseline()
    if identity!=args['baseline_policy']:raise ValueError('strategy_policy_changed')
    idea=args.get('rule_idea')
    if idea is not None:
        if not isinstance(idea,dict) or set(idea)!={'name','description','entry_conditions','pricing_formula','stop_conditions'}:raise ValueError('strategy_rule_idea_fields')
        for item in idea.values():text(item)
    if args['band_changes']:bridge.rules(engine,policy,args['band_changes'])
    elif args['band_changes']!=[] or idea is None:raise ValueError('strategy_rule_idea_required')
    content=deepcopy(args);key=digest(dict(owner=owner,project='FC27',task=task,content=content));schema(db)
    db.execute('INSERT OR IGNORE INTO strategy_drafts VALUES(?,?,?,?,?,?,?)',(key,owner,'FC27',task,encoded(content),digest(content),now.isoformat()))
    return dict(id=key,proposal_hash=digest(content),research_state='EVIDENCE_READY' if args['band_changes'] else 'DRAFT',authorization_state='NOT_REQUESTED',execution_state='NOT_EXECUTED',outcome_state='NOT_ELIGIBLE',write_performed=False,execution_authorized=False)


def simulate(db,owner,task,args,bridge,now):
    allowed(owner)
    if not isinstance(args,dict) or set(args)!={'project','intent','proposal_id','snapshot_id','expected_policy'} or args['project']!='FC27' or args['intent']!='simulate_only':raise ValueError('strategy_simulation_fields')
    policy_identity(args['expected_policy']);row,draft=get_draft(db,owner,args['proposal_id'])
    if row['task']!=task:raise PermissionError('strategy_task_scope')
    if not draft['band_changes']:
        if bridge.baseline()[2]!=args['expected_policy'] or draft['baseline_policy']!=args['expected_policy']:raise ValueError('simulation_policy_changed')
        return dict(status='unsupported_capability',proposal_id=row['id'],reason='New rule requires a verified evaluator before numerical simulation',research_state='NEEDS_DATA',execution_authorized=False,write_performed=False)
    # Always validate current sources before reusing a prior simulated result.
    result=bridge.simulate(draft,args['snapshot_id'],args['expected_policy'])
    inputs={k:result[k] for k in ('snapshot_id','snapshot_sha256','qualified_quote_sha256','baseline_policy','engine_sha256','candidate_evaluator_sha256','candidate_hash','contract')}
    fingerprint=digest(dict(owner=owner,task=task,proposal_hash=row['content_hash'],input=inputs))
    key='sim_'+fingerprint;old=db.execute('SELECT content FROM strategy_simulations WHERE input_hash=?',(fingerprint,)).fetchone()
    if old:return dict(json.loads(old[0]),reused=True,current_precheck=result['precheck'])
    result=dict(result,id=key,proposal_id=row['id'],proposal_hash=row['content_hash'],research_state='SIMULATED',authorization_state='NOT_REQUESTED',execution_state='NOT_EXECUTED',outcome_state='NOT_ELIGIBLE')
    db.execute('INSERT INTO strategy_simulations VALUES(?,?,?,?,?,?,?)',(key,row['id'],owner,task,fingerprint,encoded(result),now.isoformat()))
    return dict(result,reused=False)


def read_review(db,owner,args,events):
    if not isinstance(args,dict) or set(args)!={'decision_id','start','end'}:raise ValueError('strategy_review_fields')
    lo,hi=date.fromisoformat(args['start']),date.fromisoformat(args['end'])
    if lo>hi or (hi-lo).days>92:raise ValueError('strategy_review_window')
    key=args['decision_id']
    if isinstance(key,str) and re.fullmatch('[a-f0-9]{64}',key):
        row,draft=get_draft(db,owner,key)
        research='SIMULATED' if db.execute('SELECT 1 FROM strategy_simulations WHERE proposal=? AND owner=?',(key,owner)).fetchone() else 'EVIDENCE_READY' if draft['band_changes'] else 'DRAFT'
        return dict(decision_id=key,research_state=research,authorization_state='NOT_REQUESTED',execution_state='NOT_EXECUTED',outcome_state='NOT_ELIGIBLE',reason='Draft/simulation is not an executed action',observations=[],review_plan=draft['review_plan'])
    selected=[e for e in events if e['report']+':'+e['action']==key]
    if not selected:raise PermissionError('strategy_review_not_in_frozen_scope')
    return dict(decision_id=key,events=selected,execution_state='UNKNOWN',outcome_state='INCONCLUSIVE',observations=[],
        source='existing_human_confirmed_action_ledger',limitations=['Human notes retained; no independently verified system execution ID/effective time/coverage linked','Observation window, comparable outcome and confounders require verified evidence; no causal benefit claimed'])


def learning_propose(tasks,owner,args,now,guard):
    if not isinstance(args,dict) or set(args)!={'source','candidate'} or not re.fullmatch('[a-f0-9]{32}',str(args['source'])):raise ValueError('strategy_learning_fields')
    from learning_service import source_snapshot
    import learning_registry as registry
    def job(user,key):
        with tasks.db() as db:row=db.execute('SELECT * FROM requests WHERE id=? AND owner=?',(key,user)).fetchone()
        if row is None:return None
        result=dict(row);result['body']=json.loads(result['body']);return result
    snapshot=source_snapshot(SimpleNamespace(tasks=tasks,root=Path(tasks.path).parent,get_job=job),owner,args['source'])
    source_job=job(owner,args['source'])
    source_task=tasks.get(source_job['task_id'],owner)
    if source_task['state'] not in ('SUCCEEDED','PARTIAL') or not source_task['spec']['snapshot_id'].startswith('fc-detail-'):raise PermissionError('learning_source_project_denied')
    value=args['candidate']
    with tasks.db() as db:
        db.execute('BEGIN IMMEDIATE');schema(db);guard()
        if isinstance(value,dict) and value.get('kind')=='method_diff':
            from report_method import HTML_DESIGN_MANIFEST_SHA256
            if set(value)!={'kind','base_manifest_sha256','lesson_diff'}:raise ValueError('method_candidate_fields')
            if value['base_manifest_sha256']!=HTML_DESIGN_MANIFEST_SHA256:raise ValueError('method_candidate_base_conflict')
            text(value['lesson_diff']);key=digest(dict(owner=owner,source=args['source'],candidate=value))
            db.execute('INSERT OR IGNORE INTO method_candidates VALUES(?,?,?,?,?,?,?,?)',(key,owner,'FS',args['source'],value['base_manifest_sha256'],encoded(value),'L2',now.isoformat()))
            return dict(id=key,state='needs_human_review',risk='L2',publication_state='NOT_PUBLISHED',business_benefit='unverified')
        base=registry.manifest(db,owner,'FS',now);event=registry.enqueue(db,owner,'FS',args['source'],base['sha256'],'completed_report',snapshot)
        if event.get('state')=='paused':return event
        if event['state']=='completed':
            previous=json.loads(event['result']);key=previous.get('id') or previous.get('candidate')
            row=db.execute('SELECT content_hash FROM experience_versions WHERE id=? AND owner=?',(key,owner)).fetchone()
            if row is None or row[0]!=digest(value):raise ValueError('learning_candidate_conflict')
            return dict(previous,reused=True)
        attempt=registry.claim(db,owner,'FS',event['id'])
        return registry.candidate(db,owner,'FS',event['id'],attempt,value,now)


def call(scope,owner,task,lease,name,args):
    allowed(owner);scope.context(owner,task,lease);now=scope.clock();bridge=SimulationBridge()
    if not scope.book.capture_id.startswith('fc-detail-'):raise PermissionError('strategy_task_project_denied')
    with scope.tasks.db() as db:
        db.execute('BEGIN IMMEDIATE');schema(db)
        disabled=db.execute('SELECT enabled FROM strategy_control WHERE owner=?',(owner,)).fetchone()
        if name=='fs.strategy.capabilities':
            if args:raise ValueError('strategy_capability_fields')
            result=dict(bridge.capabilities(),enabled=disabled is None or bool(disabled[0]))
        elif name in ('fs.strategy.propose','fs.pricing.simulate_candidate'):
            if disabled and not disabled[0]:raise PermissionError('strategy_simulation_disabled')
            if name=='fs.strategy.propose':result=create(db,owner,task,args,scope.book.evidence,bridge,now)
            else:result=simulate(db,owner,task,args,bridge,now)
        elif name=='fs.strategy.read_review':result=read_review(db,owner,args,getattr(scope.book,'action_history',[]))
        elif name=='fs.learning.propose':
            db.rollback();result=learning_propose(scope.tasks,owner,args,now,lambda:scope.context(owner,task,lease))
        else:raise PermissionError('strategy_tool_denied')
        scope.context(owner,task,lease)
    return result
