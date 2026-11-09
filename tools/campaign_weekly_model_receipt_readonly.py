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

def main():
    args=argparse.ArgumentParser();args.add_argument('--operation-id',required=True);args.add_argument('--tasks-db',required=True);args.add_argument('--daily-db',required=True);a=args.parse_args()
    if not re.fullmatch(r'[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-4[a-fA-F0-9]{3}-[89abAB][a-fA-F0-9]{3}-[a-fA-F0-9]{12}',a.operation_id):raise ValueError('operation_id')
    tasks=db(a.tasks_db)
    try:rows=tasks.execute('SELECT owner,state,task_id,run_id,network_started,result FROM campaign_recommendations WHERE operation_id=?',(a.operation_id,)).fetchall()
    finally:tasks.close()
    if len(rows)!=1:
        print(json.dumps(dict(status='evidence_unavailable',reason='operation_missing_or_ambiguous',operation_id=a.operation_id)));return 2
    row=rows[0];result=json.loads(row['result']) if row['result'] else {};receipt=result.get('receipt') or {}
    daily=db(a.daily_db)
    try:calls=daily.execute('SELECT m.state,m.content,r.turn,r.policy FROM model_calls m JOIN hermes_reservations r ON r.fingerprint=m.fingerprint WHERE r.owner=? AND r.task=? ORDER BY r.turn',(row['owner'],row['task_id'])).fetchall()
    finally:daily.close()
    summaries=[]
    for call in calls:
        content=json.loads(call['content']) if call['content'] else {};policy=json.loads(call['policy']);validation=content.get('model_validation') or {}
        summaries.append(dict(turn=call['turn'],state=call['state'],policy_model=ident(policy.get('model')),response_model=ident(content.get('model')),usage=usage(content.get('usage')),model_validation={k:ident(validation[k]) for k in ('status','requested_model','response_model','actual_backend_version','provider_response_id','requested_effort','provider_effort_echo') if k in validation},forwarded_verified=validation.get('forwarded_verified') is True))
    print(json.dumps(dict(status='receipt_read',operation_id=a.operation_id,recommendation_state=row['state'],network_started=bool(row['network_started']),task_id=ident(row['task_id']),run_id=ident(row['run_id']),receipt_model=ident(receipt.get('model')),receipt_usage=usage(receipt.get('usage')),ledger_call_count=len(summaries),ledger_calls=summaries,cost_usd=None,cost_note='No invoice or verified rate supplied; tokens are not a monetary charge receipt.',scope='original_operation_only_no_prompt_or_session_output'),ensure_ascii=False,indent=2));return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error):
        print(json.dumps(dict(status='evidence_unavailable',reason='readonly_receipt_query_failed')));raise SystemExit(1)
