"""Host-only report seams on the existing request, TaskStore and native run lifecycle."""
from copy import deepcopy
from datetime import date, timedelta
import json
import hashlib
from pathlib import Path
import re
import secrets
from types import SimpleNamespace

from pilot import digest, encoded

FINANCE_FIELDS=('profile','start','end','rs_site','rs_server','rs_category','profit_site','profit_category')
FINANCE_NAMES={'fc.query_shipping_profit':'shipping','fc.query_actual_profit':'actual_profit'}


def metadata(host,key):
    with host.tasks.db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='request_knowledge'").fetchone():return None
        row=db.execute('SELECT version FROM request_knowledge WHERE id=?',(key,)).fetchone()
    if row is None or not re.fullmatch('learning-[a-f0-9]{64}',row[0]):return None
    from knowledge_catalog import read_bound
    value=json.loads(read_bound(host.root,'knowledge/'+row[0]+'.json'))
    if value.get('identity',{}).get('contract')!='fs-native-report-knowledge-v1':return None
    actual='learning-'+hashlib.sha256(json.dumps(value['identity'],sort_keys=True).encode()).hexdigest()
    if actual!=row[0] or value.get('version')!=actual or digest(value['native_selection'])!=value['identity']['selection_reference_sha256']:
        raise ValueError('native_report_knowledge_changed')
    return value


def prepare_knowledge(host, body, owner):
    from knowledge_catalog import report_selection,task_selection,load_policy
    selection=report_selection(host.root,body,owner=owner)
    if selection is None and body.get('mode')=='pricing':
        selection=task_selection(host.root,owner=owner,project='FS',channel='fs',task_type='report')
    if selection is not None and 'catalog' not in selection:
        chosen=load_policy(host.root)['requests'][body['request_id']]
        if chosen['sha256']!=selection['catalog_sha256']:raise ValueError('native_report_knowledge_changed')
        selection['catalog']=chosen['catalog']
        selection['selection_sha256']=digest({k:v for k,v in selection.items() if k!='selection_sha256'})
    reference={k:deepcopy(v) for k,v in selection.items() if k!='entries'} if selection is not None else None
    identity=dict(contract='fs-native-report-knowledge-v1',owner=owner,task_type='data' if 'data_request' in body else 'report',selection_reference_sha256=digest(reference))
    version='learning-'+hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    value=dict(version=version,identity=identity,native_selection=reference)
    folder=Path(host.root)/'knowledge'
    if any(p.is_symlink() for p in (folder,*folder.parents)):raise ValueError('knowledge_path_link')
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    from report_artifacts import write_file
    write_file(folder/(version+'.json'),encoded(value).encode())
    return dict(version=version,selection=reference)


def saved_selection(host,key):
    stored=metadata(host,key)
    if stored is None:raise ValueError('report_knowledge_missing')
    reference=stored['native_selection']
    if reference is None:return None
    from knowledge_catalog import select,verify_selection
    value=select(host.root,reference['catalog'],reference['catalog_sha256'],reference['modules'],reference.get('entry_ids'))
    value.update(reference)
    return verify_selection(value)


def conversation_for(host,owner,task_id,request_id):
    matches=[]
    for native in getattr(host.tasks,'_native_conversation_stores',{}).values():
        with native.store.db() as db:
            row=db.execute('SELECT t.conversation_id,t.request_id,c.owner FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?',(task_id,)).fetchone()
        if row is not None and (row['owner'],row['request_id'])==(owner,request_id):matches.append(row['conversation_id'])
    if len(matches)>1:raise PermissionError('native_report_duplicate_binding')
    return matches[0] if matches else None


def find(native,binding):
    with native.hermes.tasks.db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='requests'").fetchone():return None
        rows=db.execute('SELECT * FROM requests WHERE task_id=? AND owner=? AND request_id=?',
            (binding['turn_id'],binding['owner'],binding['request_id'])).fetchall()
    if len(rows)>1:raise PermissionError('native_report_duplicate_binding')
    if not rows or metadata(native.hermes,rows[0]['id']) is None:return None
    with native.store.db() as db:
        row=db.execute('SELECT conversation_id,request_id FROM turns WHERE id=?',(binding['turn_id'],)).fetchone()
    if row is None or (row['conversation_id'],row['request_id'])!=(binding['conversation_id'],binding['request_id']):return None
    result=dict(rows[0]);result['native_cid']=binding['conversation_id'];return result


def context(native,binding,*,preparing=False,terminal=False):
    host=native.hermes;job=find(native,binding)
    if job is None:raise PermissionError('native_report_required')
    body=json.loads(job['body']);task=host.tasks.get(job['task_id'],binding['owner'])
    snapshot=metadata(host,job['id'])
    if snapshot['identity']['owner']!=binding['owner']:raise PermissionError('native_report_owner')
    expected_period=dict(start=body['start'],end_exclusive=(date.fromisoformat(body['end'])+timedelta(days=1)).isoformat(),timezone='Asia/Shanghai')
    if (job['owner']!=binding['owner'] or body['request_id']!=binding['request_id'] or
            task['id']!=binding['turn_id'] or task['spec']['period']!=expected_period or
            (task['lease']!=binding['lease'] and not (terminal and task['state']=='NEEDS_RECONCILE' and task['lease'] is None)) or
            (binding['run_id'] is not None and task['run_id'] not in ((None,binding['run_id']) if preparing or terminal and task['state'] in {'DISPATCH_UNKNOWN','NEEDS_RECONCILE'} else (binding['run_id'],))) or
            (not terminal and host.authorizer(binding['owner']) is not True)):
        raise PermissionError('native_report_binding')
    native_row=native.row(binding['owner'],binding['conversation_id'],binding['turn_id'])
    if (native_row is not None and native_row['binding']!=binding) or (native_row is None and not preparing):
        raise PermissionError('native_report_binding')
    with host.tasks.db() as db:
        knowledge=db.execute('SELECT version FROM request_knowledge WHERE id=?',(job['id'],)).fetchone()
    if knowledge is None or task['spec']['knowledge_version']!=knowledge[0]:raise PermissionError('native_report_spec')
    with native.store.db() as db:
        conversation=native.store._owned(db,binding['owner'],binding['conversation_id'])
        turn=db.execute('SELECT request_id,text FROM turns WHERE id=? AND conversation_id=?',(binding['turn_id'],binding['conversation_id'])).fetchone()
    if conversation['session_id']!=binding['session_id'] or turn is None or turn['request_id']!=body['request_id']:
        raise PermissionError('native_report_binding')
    deadline=host.nightly.deadline(job['id']) if getattr(host,'nightly',None) else None
    if not terminal:
        if task['state'] not in ({'DISPATCH_UNKNOWN','CANCEL_REQUESTED'} if preparing else {'RUNNING'}):raise PermissionError('native_report_inactive')
        if job['state'] not in ({'DISPATCH_UNKNOWN','CANCEL_REQUESTED'} if preparing else {'RUNNING'}):raise PermissionError('native_report_inactive')
        if deadline is not None and host.clock()>=deadline:raise PermissionError('native_report_deadline')
    book=getattr(host,'report_books',{}).get(task['id'])
    if book is not None and task['spec']['snapshot_id']!=book.capture_id:raise PermissionError('native_report_snapshot')
    return dict(job=job,body=body,task=task,deadline=deadline,book=book,
                effort='max' if body['mode'] in {'investigation','pricing'} else 'high')


def admitted(native,binding):
    original=find(native,binding)
    if original is not None and original['state'] in {'COMPLETED','REPORT_PENDING','CANCELLED','FAILED'}:return
    value=context(native,binding,preparing=True,terminal=True)
    task=value['task'];host=native.hermes
    if task['state']=='NEEDS_RECONCILE' and task['run_id'] is None:
        with host.tasks.db() as db:
            db.execute("UPDATE tasks SET state='DISPATCH_UNKNOWN',lease=?,version=version+1 WHERE id=? AND owner=? AND state='NEEDS_RECONCILE' AND lease IS NULL AND run_id IS NULL",(binding['lease'],task['id'],binding['owner']))
        task=host.tasks.get(task['id'],binding['owner'])
    if task['run_id'] is None:host.tasks.bind_run(task['id'],binding['owner'],binding['lease'],binding['run_id'])
    elif task['run_id']!=binding['run_id']:raise PermissionError('native_report_run')
    if value['job']['state']!='CANCEL_REQUESTED':host.update(value['job']['id'],state='RUNNING')


def execute(host,key,owner,body,scheduled_context=None):
    task=None
    try:
        service=getattr(host,'conversation',None)
        if service is None:raise ValueError('native_report_service_unavailable')
        if host.authorizer(owner) is not True:raise PermissionError('native_report_revoked')
        with host.lock:
            job=host.get_job(owner,key)
            if job['state']=='CANCEL_REQUESTED':host.update(key,state='CANCELLED');return
            deadline=host.nightly.deadline(key)
            if deadline is not None and host.clock()>=deadline:host.update(key,state='CANCELLED',error='nightly_deadline_exceeded');return
            if job['task_id']:
                cid=conversation_for(host,owner,job['task_id'],body['request_id'])
                if cid:
                    service.native.schedule_reconcile(owner,cid,job['task_id']);return
                original=host.tasks.get(job['task_id'],owner)
                if original['state']!='DISPATCH_UNKNOWN' or not original['lease'] or original['run_id'] is not None:
                    raise PermissionError('native_report_original_unresolved')
        with host.tasks.db() as db:knowledge=db.execute('SELECT version FROM request_knowledge WHERE id=?',(key,)).fetchone()
        if knowledge is None:raise ValueError('report_knowledge_missing')
        metadata=dict(version=knowledge[0],sha256=digest(saved_selection(host,key)))
        from fs_evidence import build_book,attach_owner_history
        from continuation import load_continuation,load_report_followup
        import management_context
        continuation=body.get('continuation_from') or body.get('parent_report')
        if management_context.request_snapshot(body):book=management_context.build_book(body,read_range=host.read_range)
        elif body.get('parent_report'):book=load_report_followup(host.tasks,body['parent_report'],body['start'],body['end'],host.source_root,host.root,skills=metadata)
        elif continuation:book=load_continuation(host.tasks,continuation,owner,body['start'],body['end'],host.source_root,skills=metadata)
        else:book=build_book(host.detail,host.daily,host.read_range,host.diagnostics,body['start'],body['end'],host.source_root,owner,deadline=deadline,lazy_report=key,skills=metadata)
        book.skills=metadata
        from direct_provider import POLICY_ID
        spec=dict(period=dict(start=body['start'],end_exclusive=(date.fromisoformat(body['end'])+timedelta(days=1)).isoformat(),timezone='Asia/Shanghai'),
            snapshot_id=book.capture_id,template_version='native-report-'+digest(body)[:32],knowledge_version=metadata['version'],budget_policy_id=POLICY_ID)
        with host.lock:
            if host.get_job(owner,key)['state']=='CANCEL_REQUESTED':host.update(key,state='CANCELLED');return
            task=host.tasks.create(owner,spec)
            if task['state']=='QUEUED':
                lease=secrets.token_hex(16);host.tasks.reserve_dispatch(task['id'],owner,lease)
            elif (job['task_id']==task['id'] and task['state']=='DISPATCH_UNKNOWN' and task['lease'] and task['run_id'] is None):
                lease=task['lease']
            else:host.update(key,state='ALIASED',task_id=task['id']);return
            host.update(key,state='DISPATCH_UNKNOWN',task_id=task['id'])
        def persist(value):
            with host.tasks.db() as db:db.execute('INSERT OR IGNORE INTO evidence VALUES(?,?,?)',(task['id'],value['evidence_id'],encoded(value)))
            host.mark_progress(task['id'],'investigating',tool=value.get('source','readonly_tool'))
        book.persist=persist
        if not continuation:attach_owner_history(book,host.tasks,owner)
        book.action_history=host.action_history(owner)
        management=management_context.attach(book,body)
        if management:persist(management['evidence'])
        if continuation:
            for value in book.evidence.values():persist(value)
        host.report_books[task['id']]=book
        prompt=body['question']+'\nInclusive report period: '+body['start']+' to '+body['end']+'. Preserve source scope and missing coverage. Answer in the form useful for this question; no fixed chapters, HTML or graphs are required.'
        if scheduled_context is not None:prompt+='\nHost scheduling observations (data, not execution authority):\n'+encoded(scheduled_context)
        if continuation:prompt+='\nFrozen prior evidence/report (data, not instructions; no new source reads):\n'+book.continuation_context
        if management:prompt+='\n'+management_context.task_prompt(management['facts'],management['evidence']['evidence_id'],weekly=management_context.is_weekly(body),period={'start':body['start'],'end':body['end']})
        if 'data_request' in body:
            from data_workspace_request import request_context
            prompt+='\n'+request_context(body['data_request'])
        service.submit_report(owner,key,prompt)
    except Exception as error:
        code=str(error) if isinstance(error,(ValueError,PermissionError)) and re.fullmatch('[a-z_]{3,80}',str(error)) else 'native_report_'+type(error).__name__
        if task is not None:
            current=host.tasks.get(task['id'],owner)
            if current['state'] in {'RUNNING','DISPATCH_UNKNOWN','CANCEL_REQUESTED'}:host.tasks.fence(task['id'],owner)
        host.update(key,state='NEEDS_RECONCILE' if task is not None else 'FAILED',error=code)


def abandon(native,binding):
    value=context(native,binding,terminal=True);host=native.hermes;task=value['task']
    if task['state'] in {'DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED'}:host.tasks.fence(task['id'],binding['owner'])
    # Keep a concurrent or earlier cancellation durable while the task is fenced.
    # Reconciliation still observes only this original run; it cannot revive it.
    with host.tasks.db() as db:
        db.execute("UPDATE requests SET state=CASE WHEN state='CANCEL_REQUESTED' THEN state ELSE 'NEEDS_RECONCILE' END,error=? WHERE id=? AND owner=? AND state IN ('RUNNING','DISPATCH_UNKNOWN','NEEDS_RECONCILE','CANCEL_REQUESTED')",
            ('native_report_outcome_unknown',value['job']['id'],binding['owner']))
    getattr(host,'report_books',{}).pop(task['id'],None)


def finish(native,binding,state,output=None):
    prior=find(native,binding)
    if prior is not None and prior['state'] in {'COMPLETED','CANCELLED','FAILED','REPORT_PENDING'}:return
    value=context(native,binding,terminal=True);host=native.hermes;task=value['task'];job=value['job']
    if job['state'] in {'COMPLETED','CANCELLED','FAILED'}:return
    if task['state']=='NEEDS_RECONCILE':
        # Only a verified original terminal receipt can restore observation.
        with host.tasks.db() as db:
            db.execute("UPDATE tasks SET state=?,version=version+1 WHERE id=? AND owner=? AND state='NEEDS_RECONCILE' AND lease IS NULL AND run_id=?",
                ('CANCEL_REQUESTED' if job['state']=='CANCEL_REQUESTED' else 'RUNNING',task['id'],binding['owner'],binding['run_id']))
            db.execute('UPDATE tasks SET lease=? WHERE id=? AND owner=? AND run_id=? AND lease IS NULL',(binding['lease'],task['id'],binding['owner'],binding['run_id']))
        task=host.tasks.get(task['id'],binding['owner'])
    if state!='completed' or task['state']=='CANCEL_REQUESTED':
        if task['state'] in {'RUNNING','CANCEL_REQUESTED'}:host.tasks.observe(task['id'],binding['owner'],binding['lease'],state,worker_stopped=True)
        host.update(job['id'],state='NEEDS_RECONCILE' if state=='interrupted' else 'CANCELLED' if state=='cancelled' or task['state']=='CANCEL_REQUESTED' else 'FAILED',error=None if state=='cancelled' else 'runtime_'+state)
        getattr(host,'report_books',{}).pop(task['id'],None);return
    if host.authorizer(binding['owner']) is not True:raise PermissionError('native_report_revoked')
    from report_delivery import private_report
    if not isinstance(output,str) or not output.strip():raise ValueError('empty_analysis')
    if private_report(output):raise ValueError('sensitive_analysis')
    from report_artifacts import save_raw
    book=value['book']
    if book is None:
        with host.tasks.db() as db:evidence={r['evidence_id']:json.loads(r['content']) for r in db.execute('SELECT evidence_id,content FROM evidence WHERE task_id=?',(task['id'],))}
        book=SimpleNamespace(evidence=evidence,capture_id=task['spec']['snapshot_id'])
    save_raw(host.root,task['id'],output,book.evidence,dict(owner=binding['owner'],request_id=job['id'],run_id=binding['run_id'],native_completed=True,
        native_report=True,native_binding=binding,html_design=dict(contract='native-original-output-v1'),
        skills_version=task['spec']['knowledge_version'],skill_sha256=digest(task['spec']['knowledge_version']),reasoning_effort=value['effort']))
    try:host.publish_report(job['id'],binding['owner'],value['body'],task,book,output,value['effort'])
    except Exception:
        if host.tasks.get(task['id'],binding['owner'])['state']=='RUNNING':host.tasks.observe(task['id'],binding['owner'],binding['lease'],'completed',worker_stopped=True)
        host.update(job['id'],state='REPORT_PENDING',error='report_delivery_pending')
    finally:getattr(host,'report_books',{}).pop(task['id'],None)


def tool_schemas():
    from research import tool_schemas as original
    denied={'mcp__fcro__fc_run_pricing_workflow','mcp__fcro__fc_read_skill'}
    result=[deepcopy(item) for item in original() if item['function']['name'] not in denied]
    for semantic in FINANCE_NAMES:
        result.append(dict(type='function',function=dict(name='mcp__fcro__'+semantic.replace('.','_'),
            description='Read existing '+FINANCE_NAMES[semantic]+' aggregate evidence. Preserve CNY, native source scope, partial/missing coverage and times. No customer/order rows or business writes.',
            parameters=dict(type='object',properties={k:{'type':'string'} for k in FINANCE_FIELDS},required=['profile','start','end'],additionalProperties=False))))
    return result


def finance(native,binding,kind,args):
    value=context(native,binding)
    if type(args) is not dict or set(args)-set(FINANCE_FIELDS) or not {'profile','start','end'}<=set(args) or any(type(v) is not str for v in args.values()):raise ValueError('report_finance_fields')
    params={k:[v] for k,v in args.items()};host=native.hermes
    errors={'admin_required','actual_source_permission_denied','source_permission_denied','permission_denied','collector_busy','scheduled_collection_due','source_read_failed','maintenance_in_progress','source_capacity_busy'}
    if kind=='shipping':
        code,raw=host.read_range(dict(params,mode=['summary'],grain=['day'],profit_basis=['shipping']))
        shipping=raw.get('profile',{}).get('shipping')
        allowed={'system','endpoint','sourceContract','status','period','timezone','currency','filters','shippingSelection','profileKey','gameRows','scopeLabel','normalisedScope','capturedAt','timeBasis','orders','transactions','metrics','labelsVerified','stale','readPhase'}
        result=dict(http_status=code,status=raw.get('status'),shipping={k:v for k,v in shipping.items() if k in allowed} if isinstance(shipping,dict) else None,
                    source_contract=raw.get('scopeContractId'),source_status={},missingDays=raw.get('missingDays'))
        # Availability can accompany retained old amounts. Preserve the service's
        # freshness contract separately from the source record's status.
        result.update({k:deepcopy(raw[k]) for k in ('stale','refreshing','origin','generatedAt','cachePolicy','refreshSeconds','expiresInSeconds','consistentPeriod','retryAfter') if k in raw})
        fields={'status','capturedAt','sourceDataAsOf','asOfStatus','stale','phase','queueSeconds','readSeconds'}
        for name,row in (raw.get('sources') or {}).items():
            if name not in {'Admin','Order','Shipping'} or not isinstance(row,dict):continue
            result['source_status'][name]={k:v for k,v in row.items() if k in fields and (v is None or type(v) in (int,float,str,bool))}
            if row.get('error') is not None:result['source_status'][name]['error']=row['error'] if type(row['error']) is str and row['error'] in errors else 'source_read_failed'
        if raw.get('error') is not None:result['error']=raw['error'] if type(raw['error']) is str and raw['error'] in errors else 'source_read_failed'
        if isinstance(shipping,dict):result['status']=shipping.get('status',raw.get('status'))
        else:result.update(status='not_available',reason='shipping_not_in_source_response')
    elif kind=='actual_profit':
        service=getattr(host,'actual_profits',None)
        if service is None:return dict(status='not_available',reason='actual_profit_service_unavailable')
        code,raw=service.get(dict(params,mode=['actual-profit'],grain=['day']),binding['owner'])
        keys={'refreshing','costRefreshing','costError','sourceError','stale','version','status','retryAfter','actualContract','revenueBasis','currency','period','actualPeriod','generatedAt','denominator','trend','completeDayOnly','definition','membershipBasis','selection'}
        result={k:deepcopy(v) for k,v in raw.items() if k in keys};result['http_status']=code
        if raw.get('error') is not None:result['error']=raw['error'] if type(raw['error']) is str and raw['error'] in errors else 'source_read_failed'
        if 'sources' in raw:
            result['sources']={}
            for name,row in raw['sources'].items():
                if name not in {'orders','cost','cache'} or not isinstance(row,dict):continue
                fields={'status','generatedAt','until','rows','unassignedSourceRows','days','oldest','deliveryDayComplete','customerDayComplete'}
                clean={k:v for k,v in row.items() if k in fields and (v is None or type(v) in (int,float,str,bool))}
                if isinstance(row.get('coverage'),dict):
                    fields={'complete','sourceScanned','uniqueOrders','duplicateJoinRows','dateBasis','site','days','completeDays','deliveryRows','contract'}
                    clean['coverage']={k:v for k,v in row['coverage'].items() if k in fields and (v is None or type(v) in (int,float,str,bool))}
                result['sources'][name]=clean
        # These fields are aggregate service contracts; raw order/member/source
        # records and arbitrary service extensions never cross this relay.
        metric_keys={'orders','completedOrders','coveredOrders','pendingOrders','missingCostOrders','saleCny','costCny','profitCny','profitMarginPct','costCoveragePct','coverageStatus','key'}
        for key in ('denominator','trend'):
            if key in result:
                rows=result[key] if key=='trend' else [result[key]]
                cleaned=[{k:v for k,v in row.items() if k in metric_keys and (v is None or type(v) in (int,float,str,bool))} for row in rows]
                result[key]=cleaned if key=='trend' else cleaned[0]
    else:raise PermissionError('report_finance_tool')
    context(native,binding)
    return result


def call(native,binding,value):
    scope=context(native,binding)
    if type(value) is not dict or set(value)!={'binding','name','arguments'} or value['binding']!=binding:raise PermissionError('native_report_rpc')
    if value['name']=='capabilities':
        if value['arguments']!={}:raise ValueError('report_capability_fields')
        return dict(tool_schemas=tool_schemas())
    allowed={item['function']['name'] for item in tool_schemas()}
    if value['name'] not in allowed:raise PermissionError('native_report_readonly')
    semantic='fc.'+value['name'].removeprefix('mcp__fcro__fc_');book=scope['book']
    if book is None:raise PermissionError('native_report_book_unavailable')
    if semantic in FINANCE_NAMES:
        if scope['body'].get('parent_report') or scope['body'].get('continuation_from'):
            result=book.call(semantic,value['arguments'])
        else:result=book.register(semantic,value['arguments'],finance(native,binding,FINANCE_NAMES[semantic],value['arguments']),source='FS report '+FINANCE_NAMES[semantic]+' aggregate')
    else:result=book.call(semantic,value['arguments'])
    context(native,binding)
    return result
