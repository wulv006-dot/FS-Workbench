"""FS-owned adapters reuse source services and return only explicit projections."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import threading

from research import ResearchBook, label
from skill_bundle import load_bundle


class AsyncRead:
    def __init__(self, reader):
        self.reader=reader;self.future=None;self.lock=threading.Lock()
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='hermes-evidence-read')

    def get(self):
        with self.lock:
            if self.future is None:self.future=self.pool.submit(self.reader)
            future=self.future
        if not future.done():return {'status':'pending','reason':'source_read_running','retryAfter':3}
        try:return future.result()
        except Exception:return {'status':'unavailable','reason':'source_read_failed'}


def source_capture(detail,start,end):
    from fc_deep_sources import EvidenceReader
    return EvidenceReader(detail).capture({'read_start':start,'read_end':end})


def problem_projection(value, scope):
    out={k:value[k] for k in ('contract','status','reason','captured_at','sampled','listed','pages','coverage','categories','platform_counts','errors','note') if k in value}
    out['samples']=[{'case_ref':'case_'+hashlib.sha256((scope+str(r.get('ref'))).encode()).hexdigest()[:24],
                     **{k:r[k] for k in ('platform','amount_usd','category','last_matching_log_at','basis','requires_latest_state_review') if k in r}}
                    for r in value.get('samples',[])]
    out['case_identity']='task_scoped_pseudonym_not_cross_task_cohort'
    return out


def old_report_projection(report):
    out={k:report[k] for k in ('day','date','revision','report_id','generated_at','status','data_status') if k in report}
    out['model_status']=report.get('ai',{}).get('status')
    out['main']=report.get('main')
    deep=report.get('deep') or {}
    out['readings']=[{k:e[k] for k in ('ref','kind','value','source','scope','captured_at','period','snapshot_id','state_basis') if k in e}
                      for e in deep.get('evidence',[]) if e.get('kind')=='period_facts']
    out['previous_judgments']=[{k:label(r[k]) if k=='title' else r[k] for k in ('priority','type','title','observation','hypothesis','action','condition','risk','refs','verify') if k in r}
                               for r in deep.get('decision',{}).get('findings',[])]
    out['rule']='历史模型/规则判断仅供复盘；同业务日多时点不等于同成熟度，未执行建议不得归因效果'
    return out


def build_book(detail,daily,read_range,diagnostics,start,end,source_root,owner,*,persist=None):
    lo,hi=date.fromisoformat(start),date.fromisoformat(end)
    read_start=(lo-timedelta(days=max(7,(hi-lo).days+1))).isoformat()
    dataset,config=source_capture(detail,read_start,end)
    skills=load_bundle(source_root)
    scope=hashlib.sha256((owner+dataset['snapshot_id']).encode()).hexdigest()
    clue_read=AsyncRead(lambda:problem_projection(diagnostics(),scope))
    def history(args):
        with daily.db() as db:
            rows=db.execute('SELECT content FROM reports WHERE day>=? AND day<=? ORDER BY job_id DESC LIMIT 30',(args['start'],args['end'])).fetchall()
        return {'status':'available' if rows else 'empty','reports':[old_report_projection(json.loads(r[0])) for r in rows],
                'max_versions':30,'scope':'FC已存日报版本；Admin支付主站口径与各原生聚合需核来源后比较'}
    def reference(args):
        params={k:[v] for k,v in dict(mode='profit-history',grain='day',**args).items()}
        status,raw=read_range(params)
        return {'status':raw.get('status'),'http_status':status,'query':args,'source_scope':'Order/all-websites',
                'reference_only':True,'not_verified_pricing_cost':True,'captured_at':datetime.now(timezone.utc).isoformat(),
                'missingDays':raw.get('missingDays'), 'rows':raw.get('history',{}).get('daily',[]),'error':raw.get('error') or raw.get('lastError')}
    def native(args):
        params={k:[v] for k,v in dict(mode='summary',grain='day',**args).items()}
        status,raw=read_range(params)
        if raw.get('scopeContractId') not in (None,'admin-main-order-labelled-supplement-v1'):raise ValueError('native_source_contract')
        profile=raw.get('profile') or {}
        return {'http_status':status,'status':raw.get('status'),'query':args,'source_contract':raw.get('scopeContractId'),
                'source_records':{k:{field:profile[k][field] for field in ('system','status','period','currency','orders','revenueUsd','metrics','dimensions','capturedAt','sourceDataAsOf','stale') if field in profile[k]} for k in ('primary','supplement') if isinstance(profile.get(k),dict)},
                'source_status':raw.get('sources'),'consistentPeriod':raw.get('consistentPeriod'),
                'rule':'须读取各记录system/source/scope；Admin权威主源，Order仅参考，不按primary字段名猜实际源'}
    return ResearchBook(dataset,config,{'start':start,'end':end},history=history,reference=reference,
                        clues=clue_read.get,skills=skills,persist=persist,native=native)
