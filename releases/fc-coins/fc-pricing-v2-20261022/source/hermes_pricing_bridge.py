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
        return dict(row) if row else None


def recommendation(conversation,owner,turn,quote):
    with closing(sqlite3.connect((FS/'tasks.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pricing_recommendations'").fetchone()
        rows=db.execute('SELECT content FROM pricing_recommendations WHERE conversation=? AND owner=? AND task=? AND run_id=? ORDER BY rowid DESC',(conversation,owner,turn['task_id'],quote['run_id'])).fetchall() if exists else []
    expected=hashlib.sha256(json.dumps(quote,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    for row in rows:
        value=json.loads(row[0])
        if value.get('quote_sha256')==expected and value.get('source') in {'program_generated_choices','program_verified_evaluation'}:return value
    return None


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
                      'human_authorized_fc_coins_v2_20261022_nonoverridable_10pct',restore_sources=[restore_source] if restore_source else [])
            scope=('本任务为自动周期审核，允许核实、核算并recommend程序给出的候选；FC worker正等待，不能另排采集或写价任务。'
                   if mode=='automatic_review' else '用户已授权本次FC金币操作流程；先核capabilities，只能在本任务授予范围内取数、核算、预览和执行。执行后用read_job核后台CONFIRMED，再state核monitor.publication.execution_id为本次操作、写后时间和三平台matched；缺任一项都只能报告未证，不据accepted或会话完成宣称真实生效。')
            text=('FC Coins本轮真实决策，运行编号'+quote['run_id']+'。'+scope+
                '先读取当前业务知识及fs.pricing.control的capabilities/state，再按需核对经营、成本与营销证据。'
                '用fc.run_pricing_workflow取得固定分析回执；用户最新确认10%采购毛利硬线只检查未使用优惠的前台套餐实际售价，含赠送、阶梯数量及舍入；所有合法VIP/积分/码/券折后允许低于10%或亏损，仍须记录实际让利与损失。不能恢复旧最差优惠红线，也不能把未优惠底线降到10%以下。'
                'PS/Xbox共同成本共同基价，PC独立。不要机械花掉高毛利。先比较baseline/hold/parity；如有新方案，可evaluate并用evaluated选择提交自定console_usd/pc_usd，由程序重新核验。实际调用recommend并引用pricing:quote_sha256或本任务证据；说明采购毛利、广告后贡献、保本销量条件及反证。'
                '不把短期相关当因果，不臆造广告归因或需求增量。终态后原队列受控学习，不用运行中snapshot作为经验来源。最后用通俗中文说明判断。')
            text+=('经营目标是同范围采购毛利额和可归属广告后贡献，不是把利润率做高。平均毛利使用本轮historical_discount_mix/estimated_average_margin的近7日实际折扣总额加权情景，分清100K当前成本估算与历史实绩、平台/套餐缺口；不平均单率，不用每单七折替代平均值。历史结构不是未来固定概率；优惠后亏损可合法，不代表获客成功，获客贡献与后续回收仍须验证。经营判断使用真实优惠核销/净收/历史成本，未来候选须重核资格、门槛、封顶和数量。'
                   '当前Coins数据优先fc.query_pricing_evidence(order_costs)，看promotion_usage和覆盖；没有资格分母就不得称合资格核销率，无码/无券不等于原价。'
                   'PS/Xbox用共同池时间最新已核成本；不同交易时刻的0.45/0.43不是同一时点冲突，旧值只能作为明确压力情景。'
                   '不得用全FC旧毛利、新客订单数或历史区间支持本轮Coins高价有效；新客订单不称人数，公开生效用独立读回时间，后台写入时间另列。'
                   '不得自行设定24–48小时等强制等待期；观察期要有具体数据成熟依据。缺广告或价格弹性只能限制效果结论，不足以无期限否决已合格程序候选。'
                   '若hold高于本轮baseline，必须分别核算保持与调整，并指出当前同范围、同口径可核实的反对调整证据；保本倍数使用清楚的优惠/数量/广告假设，不把所有订单设为最大优惠来预测销量。'
                   '没有具体反证且当前可比竞争位置仍支持调整时，选择本轮程序baseline；这是受红线约束的执行基准，不声称利润最优或已证明需求增量。')
            if mode=='operator_workflow':
                text+='用户这次入口明确交给你核算并受控执行本轮，授权已给，无须再次询问。若本轮合格候选与后台不同，按capabilities.action_fields准确recommend，使用state.quote_evidence_ref原文作为唯一足够引用；apply_recommendation后read_job核原重算终态，再preview、read_job取得预览、execute、read_job及state核后台与公开读回。失败响应不证明没有写入，必须看read_job.execution_audit；changed、PARTIAL、UNCERTAIN或未核原结果时，不得换request_key、预览或ID再execute，只核原操作并报告待对账。未通过任一护栏就停止该动作并报告。不要因参数错误重复collect；按expected_fields/received_fields及native_error修正。state是摘要，完整依据用read_quote逐路径读取。声明scenario或单独100K尾价通过不能替代本轮全套餐evaluate。无变化则核原预览后如实报no_price_change，不制造改价。'
            if restore_source:text+='本次另明确授权协助恢复原操作'+restore_source+'，先restore_preview，核当前成本和优惠红线后才restore；不恢复其他历史操作。'
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
                save(path,record);return record
        if time.monotonic()>=deadline:
            record.update(phase='submitted' if wait_seconds==0 else 'timeout',reason='model_still_running_no_late_auto_apply',applied=False)
            save(path,record);return record
        time.sleep(1)
