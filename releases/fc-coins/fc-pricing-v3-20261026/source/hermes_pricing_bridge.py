"""Use original FS conversations/model receipts; never retry unknown model submissions."""
from contextlib import closing
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid
from urllib.request import Request,build_opener,HTTPRedirectHandler

ROOT=Path('/var/lib/fc27-cloud')
FS=Path('/var/lib/fs-hermes-fc/fs')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):return None


def request(owner,path,body=None,timeout=30):
    req=Request('http://127.0.0.1:8931'+path,data=None if body is None else json.dumps(body,ensure_ascii=False).encode(),
        headers={'X-Auth-User':owner,'Content-Type':'application/json','X-FS-Advisor-Action':'submit',
                 'Sec-Fetch-Site':'same-origin'},method='GET' if body is None else 'POST')
    with build_opener(NoRedirect()).open(req,timeout=timeout) as response:
        raw=response.read(1024*1024+1)
    if len(raw)>1024*1024:raise ValueError('pricing_hermes_reply_too_large')
    return json.loads(raw)


def save(path,value):
    from snapshot_layer import atomic_json
    atomic_json(path,value);os.chmod(path,0o640);os.chown(path,0,11028)


def turn_state(conversation,request_id,owner,channel='conversation'):
    store='pricing-reviews' if channel=='pricing_review_v3' else 'conversations'
    with closing(sqlite3.connect((FS/store/'conversations.db').as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT t.id,t.state,t.task_id,t.run_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.conversation_id=? AND t.request_id=? AND c.owner=?',(conversation,request_id,owner)).fetchone()
        turn=dict(row) if row else None
    if turn is not None:
        path=FS/'contexts'/(turn['id']+'-dispatch-error.json')
        try:
            if path.is_file() and not path.is_symlink():
                if path.stat().st_size>4096:raise ValueError('dispatch_diagnostic_size')
                value=json.loads(path.read_text('utf-8'))
                if all(value.get(k)==v for k,v in {'owner':owner,'conversation_id':conversation,'turn_id':turn['id'],'request_id':request_id}.items()):
                    turn['dispatch_failure']={k:value.get(k) for k in ('stage','error_type','reason_code','do_not_replay')}
        except (OSError,ValueError,TypeError):
            turn['diagnostic_error']='dispatch_diagnostic_unreadable'
    return turn


def daily_review_text(quote):
    report=dict(quote['daily_report'])
    report['actual']={k:v for k,v in (report.get('actual') or {}).items() if k!='hourly'}
    text=('FC27每日一次经营效果复盘。你负责效果判断和方案建议；正常每轮由程序定价，不等待你审核。'
        '本任务只读，不推荐待执行价格、不调用recommend、不创建/执行/切换计划、不补采竞品。'
        '按附带真实六小时时段订单与收入分布比较低估期和高峰期，说明预测与实绩差异及其数据覆盖。'
        '前期先追踪；影子与真实样本成熟后才建议何时切策略，本次没有自动切换授权。'
        '说明当前策略参数、基数如何核算，哪些是实际、哪些是初始弹性等假设，下一日如何追踪和反证。'
        '双10%采购毛利底线、赠送/优惠/地区/舍入由程序每轮校验，不能豁免。目标未设就说明收入优化试验。'
        '输出一次简明中文复盘：效果判断、分时段比较、基数与假设、建议及次日观察。模拟收益不能叫真实增收。'
        '实际及影子摘要：'+json.dumps(report,ensure_ascii=False,separators=(',',':')))
    if len(text)>12000:raise ValueError('pricing_daily_prompt_too_long')
    return text


def review(job,quote,*,mode='automatic_review',wait_seconds=180):
    if mode!='daily_review':raise ValueError('pricing_per_cycle_model_review_retired')
    owner='wulv'
    restore_source=job.get('request',{}).get('restore_source_execution_id')
    if restore_source:
        if mode!='operator_workflow':raise ValueError('pricing_restore_grant_scope')
        restore_source=str(uuid.UUID(restore_source))
        audit=json.loads((ROOT/'executions'/(restore_source+'.json')).read_text('utf-8'))
        if audit.get('execution_id')!=restore_source or audit.get('status')!='CONFIRMED' or not audit.get('sync_confirmed'):
            raise ValueError('pricing_restore_source_not_confirmed')
    request_id='fc_pricing_'+job['job_id'].replace('-','')
    path=ROOT/'evidence'/('hermes-pricing-'+job['job_id']+'.json')
    created=datetime.now(timezone.utc)
    text=daily_review_text(quote)
    if path.exists():
        record=json.loads(path.read_text('utf-8'))
        if record.get('owner')!=owner or record.get('run_id')!=quote['run_id'] or record.get('mode')!=mode or record.get('restore_source_execution_id')!=restore_source:
            raise ValueError('pricing_hermes_intent_conflict')
        if record.get('phase') in {'completed','failed','timeout','unknown'}:return record
        if not record.get('conversation_id'):
            record.update(phase='unknown',reason='original_create_receipt_required');save(path,record);return record
    else:
        record=dict(owner=owner,mode=mode,job_id=job['job_id'],run_id=quote['run_id'],request_id=request_id,
                    channel='pricing_review_v3',
                    phase='creating',created_at=created.isoformat(),price_write_performed=False,restore_source_execution_id=restore_source)
        # O_EXCL reserves the intent before an FS call that may create or bill work.
        with path.open('x',encoding='utf-8') as stream:
            json.dump(record,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
        os.chmod(path,0o640);os.chown(path,0,11028)
        try:
            result=request(owner,'/api/hermes/conversations/pricing-reviews',{})
            conversation=result['conversation_id'];record.update(conversation_id=conversation,phase='created');save(path,record)
            sys.path.insert(0,'/opt/fs-hermes-fc')
            from pricing_operations import grant
            with closing(sqlite3.connect(FS/'tasks.sqlite3',timeout=5)) as db,db:
                grant(db,owner,conversation,quote['run_id'],mode,(created+timedelta(hours=1)).isoformat(),
                      'human_authorized_fc_pricing_v3_daily_effect_review_readonly' if mode=='daily_review' else 'human_authorized_fc_pricing_v3_20261026_inherited_review_and_dual10',restore_sources=[restore_source] if restore_source else [])
            record.update(phase='submitting',input_sha256=hashlib.sha256(text.encode()).hexdigest());save(path,record)
            submitted=request(owner,'/api/hermes/conversations/pricing-reviews/'+conversation+'/turns',
                              {'text':text,'client_request_id':request_id,'run_id':quote['run_id']})
            record.update(phase='submitted',turn_id=submitted['turn_id']);save(path,record)
        except Exception as exc:
            existing=turn_state(record['conversation_id'],request_id,owner,record.get('channel','conversation')) if record.get('conversation_id') else None
            if existing:
                record.update(phase='submitted',turn_id=existing['id'],submission_reconciled_from_original_request=True)
                save(path,record)
            else:
                record.update(phase='unknown',reason=type(exc).__name__,do_not_replay=True);save(path,record);return record
    deadline=time.monotonic()+wait_seconds
    while True:
        turn=turn_state(record['conversation_id'],request_id,owner,record.get('channel','conversation'))
        if turn:
            record.update(turn=turn,task_id=turn.get('task_id'),run_id=quote['run_id'])
            if turn['state'] in {'completed','failed','cancelled','interrupted'}:
                selected=None
                record.update(phase='completed' if turn['state']=='completed' else 'failed',recommendation=selected,
                              completed_at=datetime.now(timezone.utc).isoformat(),applied=False)
                if mode=='daily_review' and turn['state']=='completed':
                    detail=request(owner,'/api/hermes/conversations/pricing-reviews/'+record['conversation_id'])
                    record['evaluation']=detail
                if turn.get('dispatch_failure'):
                    record.update(failure=turn['dispatch_failure'],reason=turn['dispatch_failure']['reason_code'])
                save(path,record);return record
        if time.monotonic()>=deadline:
            record.update(phase='submitted' if wait_seconds==0 else 'timeout',reason='model_still_running_no_late_auto_apply',applied=False)
            save(path,record);return record
        time.sleep(1)
