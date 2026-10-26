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


def turn_state(conversation,request_id,owner):
    with closing(sqlite3.connect((FS/'conversations/conversations.db').as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
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


def recommendation(conversation,owner,turn,quote):
    with closing(sqlite3.connect((FS/'tasks.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pricing_recommendations'").fetchone()
        rows=db.execute('SELECT content FROM pricing_recommendations WHERE conversation=? AND owner=? AND task=? AND run_id=? ORDER BY rowid DESC',(conversation,owner,turn['task_id'],quote['run_id'])).fetchall() if exists else []
    expected=hashlib.sha256(json.dumps(quote,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    for row in rows:
        value=json.loads(row[0])
        if value.get('quote_sha256')==expected and value.get('source') in {'v3_program_confirmed_assignment'}:return value
    return None


def review_text(quote,mode):
    scope=('本任务为自动周期审核，允许核实、核算并recommend程序给出的候选；FC worker正等待，不能另排采集或写价任务。'
           if mode=='automatic_review' else '用户已授权本次FC金币操作流程；先核capabilities，只能在本任务授予范围内取数、核算、预览和执行。执行后用read_job核后台CONFIRMED，再state核monitor.publication.execution_id为本次操作、写后时间和三平台matched；缺任一项都只能报告未证，不据accepted或会话完成宣称真实生效。')
    text=(scope+'FC27 Pricing V3经营复核，原运行编号'+quote['run_id']+'。'
        '只比较daily/acquisition/backlog/flash_sale/revenue_sprint五个目标；保持是动作。'
        '先读五策略API state/market/region-rules/experiments/shadow，再比较总贡献、首次付款客户、完整交付能力、活动期限和月度净收入目标。'
        '全球Console共价、PC独立；地区21按PS/Xbox/PC独立系数，英国0.9100保持并重核实际价格。'
        '未优惠与近7完整日真实优惠金额加权平均采购毛利均至少10%，包含所有赠送、档位/整数K和真实舍入；合法单笔优惠仍可亏损。'
        '冲额仅用新鲜Lootbar/ItemD2R最低可比价98%~100%，Arab普通发货仅在真实平台覆盖和地区证明齐全时进入对应范围。'
        '原80/15/5、临时ItemD2R钉价、baseline/hold/parity、尾价与旧fallback均已退役，不得调用旧recommend/evaluated执行。'
        '金额和候选由程序负责。影子和预测不称实绩；目标未配置保持空，不编造流量、收入或归因。'
        '所有写入只能通过V3计划/授权/原操作接口；UNKNOWN按原ID只读对账，不能改ID重放。'
        'Hermes负责当前经营目标的业务选价与审核：从同一run、同一模式已通过财务/市场/预算的候选中选动作，解释参数、真实基数、假设和反证并实际recommend。程序保留所有硬检查与唯一writer。只有无有效模型建议时才用明确V3程序路径并标示未经模型审核，不能把超时写成通过。'
        '本轮fs.pricing.control recommend参数用当前run_id、bundle_sha256、action_sha256、request_key、reason、evidence_refs；evidence_refs包含pricing:'+quote['result']['decision_receipt']['sha256']+'。选择当前模式已验证候选的action_sha256；有效差异建议会记录原分配偏离并重新验证，不能改写原随机记录。换模式须另建计划。'
        '当前run_id:'+quote['run_id']+'；当前bundle_sha256:'+quote['result']['decision_receipt']['sha256']+'。'
        '请从V3 strategy-decisions按此run读取同一模式的全部候选摘要，需要完整证明时按action_sha256读取candidate_detail；原始完整报价和历史订单只在私库，勿要求模型读取逐单附件。')
    if len(text)>12000:
        raise ValueError('pricing_hermes_prompt_too_long')
    return text


def review(job,quote,*,mode='automatic_review',wait_seconds=180):
    owner='wulv' if mode=='automatic_review' else job['actor']
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
    text=review_text(quote,mode)
    if path.exists():
        record=json.loads(path.read_text('utf-8'))
        if record.get('owner')!=owner or record.get('run_id')!=quote['run_id'] or record.get('mode')!=mode or record.get('restore_source_execution_id')!=restore_source:
            raise ValueError('pricing_hermes_intent_conflict')
        if record.get('phase') in {'completed','failed','timeout','unknown'}:return record
        if not record.get('conversation_id'):
            record.update(phase='unknown',reason='original_create_receipt_required');save(path,record);return record
    else:
        record=dict(owner=owner,mode=mode,job_id=job['job_id'],run_id=quote['run_id'],request_id=request_id,
                    phase='creating',created_at=created.isoformat(),price_write_performed=False,restore_source_execution_id=restore_source)
        # O_EXCL reserves the intent before an FS call that may create or bill work.
        with path.open('x',encoding='utf-8') as stream:
            json.dump(record,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
        os.chmod(path,0o640);os.chown(path,0,11028)
        try:
            result=request(owner,'/api/hermes/conversations',{})
            conversation=result['conversation_id'];record.update(conversation_id=conversation,phase='created');save(path,record)
            sys.path.insert(0,'/opt/fs-hermes-fc')
            from pricing_operations import grant
            with closing(sqlite3.connect(FS/'tasks.sqlite3',timeout=5)) as db,db:
                grant(db,owner,conversation,quote['run_id'],mode,(created+timedelta(hours=1)).isoformat(),
                      'human_authorized_fc_pricing_v3_20261026_inherited_review_and_dual10',restore_sources=[restore_source] if restore_source else [])
            record.update(phase='submitting',input_sha256=hashlib.sha256(text.encode()).hexdigest());save(path,record)
            submitted=request(owner,'/api/hermes/conversations/'+conversation+'/turns',{'text':text,'client_request_id':request_id})
            record.update(phase='submitted',turn_id=submitted['turn_id']);save(path,record)
        except Exception as exc:
            existing=turn_state(record['conversation_id'],request_id,owner) if record.get('conversation_id') else None
            if existing:
                record.update(phase='submitted',turn_id=existing['id'],submission_reconciled_from_original_request=True)
                save(path,record)
            else:
                record.update(phase='unknown',reason=type(exc).__name__,do_not_replay=True);save(path,record);return record
    deadline=time.monotonic()+wait_seconds
    while True:
        turn=turn_state(record['conversation_id'],request_id,owner)
        if turn:
            record.update(turn=turn,task_id=turn.get('task_id'),run_id=quote['run_id'])
            if turn['state'] in {'completed','failed','cancelled','interrupted'}:
                selected=recommendation(record['conversation_id'],owner,turn,quote) if turn['state']=='completed' else None
                record.update(phase='completed' if turn['state']=='completed' else 'failed',recommendation=selected,
                              completed_at=datetime.now(timezone.utc).isoformat(),applied=False)
                if turn.get('dispatch_failure'):
                    record.update(failure=turn['dispatch_failure'],reason=turn['dispatch_failure']['reason_code'])
                save(path,record);return record
        if time.monotonic()>=deadline:
            record.update(phase='submitted' if wait_seconds==0 else 'timeout',reason='model_still_running_no_late_auto_apply',applied=False)
            save(path,record);return record
        time.sleep(1)
