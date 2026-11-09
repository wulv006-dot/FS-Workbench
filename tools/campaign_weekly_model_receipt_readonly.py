"""Read-only operation-scoped Sol ledger receipt; no prompts, sessions or other users printed.
Usage: python3 SCRIPT --operation-id UUID --tasks-db /exact/tasks.sqlite3 --daily-db /exact/daily.sqlite3
Only opens existing databases using SQLite mode=ro and query_only. Never imports service code.
"""
import argparse,json,re,sqlite3
from pathlib import Path

def db(filename):
    path=Path(filename).resolve(strict=True)
    conn=sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=5)
    conn.row_factory=sqlite3.Row;conn.execute('PRAGMA query_only=ON')
    return conn

def usage(value):
    if not isinstance(value,dict):return {}
    return {k:v for k,v in value.items() if k in ('input_tokens','output_tokens','prompt_tokens','completion_tokens','total_tokens') and type(v) is int and v>=0}

def ident(value):
    return value if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}',value) else None

def selection_counts(result,source):
    rows=result.get('recommendations') if isinstance(result,dict) else None
    if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):return {'status':'evidence_unavailable'}
    cores=next((p.get('core_product_keys',[]) for p in source.get('pages',[]) if p.get('page_id')=='fc27-sbc'),[])
    catalog={p['key']:p.get('product_ref',{}).get('model_id') for p in source.get('catalog',[])}
    sbc=[row for row in rows if row.get('page_id')=='fc27-sbc'];counts=[sum(row.get('core_product_key')==core for row in sbc) for core in cores]
    models={catalog.get(row.get('product_key')) for row in sbc};model_count=len(models-{None})
    pages={page:sum(row.get('page_id')==page for row in rows) for page in ('fc27-trio','fc27-weekly','fc27-sbc')}
    bound=result.get('source_revision')==source.get('source_revision') and result.get('sbc_update_id')==source.get('sbc_update',{}).get('id')
    return dict(status='observed',rows=len(rows),page_counts=pages,core_count=len(cores),per_core_counts=counts,distinct_companion_models=model_count,binding_matches=bound,
        nine_by_two=bound and len(rows)==24 and pages=={'fc27-trio':3,'fc27-weekly':3,'fc27-sbc':18} and len(cores)==9 and counts==[2]*9 and model_count==18)

def main():
    args=argparse.ArgumentParser();args.add_argument('--operation-id',required=True);args.add_argument('--tasks-db',required=True);args.add_argument('--daily-db',required=True);a=args.parse_args()
    if not re.fullmatch(r'[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-4[a-fA-F0-9]{3}-[89abAB][a-fA-F0-9]{3}-[a-fA-F0-9]{12}',a.operation_id):raise ValueError('operation_id')
    tasks=db(a.tasks_db)
    try:
        rows=tasks.execute('SELECT owner,state,task_id,run_id,network_started,result,input FROM campaign_recommendations WHERE operation_id=?',(a.operation_id,)).fetchall()
        task=tasks.execute('SELECT state,run_id FROM tasks WHERE id=? AND owner=?',(rows[0]['task_id'],rows[0]['owner'])).fetchone() if len(rows)==1 else None
    finally:tasks.close()
    if len(rows)!=1:
        print(json.dumps(dict(status='evidence_unavailable',reason='operation_missing_or_ambiguous',operation_id=a.operation_id)));return 2
    row=rows[0];result=json.loads(row['result']) if row['result'] else {};receipt=result.get('receipt') or {};source=json.loads(row['input']);selected=result.get('result')
    daily=db(a.daily_db)
    try:calls=daily.execute('SELECT m.state,m.content,r.turn,r.policy FROM model_calls m JOIN hermes_reservations r ON r.fingerprint=m.fingerprint WHERE r.owner=? AND r.task=? ORDER BY r.turn',(row['owner'],row['task_id'])).fetchall()
    finally:daily.close()
    summaries=[]
    for call in calls:
        content=json.loads(call['content']) if call['content'] else {};policy=json.loads(call['policy']);validation=content.get('model_validation') or {}
        summaries.append(dict(turn=call['turn'],state=call['state'],policy_model=ident(policy.get('model')),response_model=ident(content.get('model')),reasoning_effort=ident(content.get('reasoning_effort')),finish_reason=ident(content.get('finish_reason')),usage=usage(content.get('usage')),model_validation={k:ident(validation[k]) for k in ('status','requested_model','response_model','actual_backend_version','provider_response_id','requested_effort','provider_effort_echo') if k in validation},forwarded_verified=validation.get('forwarded_verified') is True))
        if selected is None and call['state']=='succeeded':
            try:selected=json.loads(content.get('message',{}).get('content',''))
            except (ValueError,TypeError,AttributeError):pass
    print(json.dumps(dict(status='receipt_read',operation_id=a.operation_id,recommendation_state=row['state'],network_started=bool(row['network_started']),task_id=ident(row['task_id']),run_id=ident(row['run_id']),task_state=ident(task['state']) if task else None,task_run_matches=bool(task and task['run_id']==row['run_id']),selection_counts=selection_counts(selected,source),receipt_model=ident(receipt.get('model')),receipt_usage=usage(receipt.get('usage')),ledger_call_count=len(summaries),ledger_calls=summaries,cost_usd=None,cost_note='No invoice or verified rate supplied; tokens are not a monetary charge receipt.',scope='original_operation_only_no_prompt_or_session_output'),ensure_ascii=False,indent=2));return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error):
        print(json.dumps(dict(status='evidence_unavailable',reason='readonly_receipt_query_failed')));raise SystemExit(1)
