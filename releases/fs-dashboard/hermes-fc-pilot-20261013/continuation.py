"""Continue from owner-bound public evidence; never replay a failed provider call.

No live readers, provider keys, private reasoning or business writes are used here.
"""
from copy import deepcopy
from datetime import datetime,timezone
import json
import re
from pilot import encoded,TOOLS
from research import ResearchBook,RESEARCH_NAMES
from skill_bundle import load_bundle


def evidence_tool(value):
    query=value.get('query',{});source=value.get('source','');data=value.get('data',{})
    if source=='冻结证据续行；本次不新增来源读取' and data.get('status')=='not_available' and data.get('reason')=='not_in_frozen_continuation_evidence' and data.get('cached_tool_name') in RESEARCH_NAMES:
        return data['cached_tool_name']
    if 'operation' in query:return 'fc.calculate'
    if 'kind' in query:return 'fc.query_capability'
    if source.startswith('Admin原生订单统计'):return 'fc.query_native_statistics'
    if source.startswith('Order参考利润'):return 'fc.query_reference'
    if source.startswith('Order FC27当前问题单历史关键词'):return 'fc.get_problem_clues'
    if source.startswith('历史报告'):return 'fc.read_history'
    if source=='Admin FC支付明细':
        if 'group_by' in query:return 'fc.query_business' if 'start' in query else 'fc.query_queue'
        if data.get('main_source')=='Admin':return 'fc.get_data_catalog'
    raise ValueError('continuation_source_unknown')


def cache_rank(value):
    data=value.get('data',{})
    status=data.get('status')
    # An earlier asynchronous placeholder must not replace a completed read. Failures/denials
    # remain terminal observations too; among terminal results prefer the actual later capture.
    complete=status not in {'pending','not_sent','queued','running','collecting'}
    captured=datetime.fromisoformat(value['captured_at'])
    if captured.tzinfo is None:raise ValueError('continuation_capture_time')
    return complete,captured.astimezone(timezone.utc),value['evidence_id']


class FrozenEvidenceBook(ResearchBook):
    def __init__(self, task, evidence, skills):
        if not evidence:raise ValueError('continuation_evidence_missing')
        first=next((value for value in evidence.values() if evidence_tool(value)=='fc.get_data_catalog'),next(iter(evidence.values())))
        super().__init__({'snapshot_id':task['spec']['snapshot_id'],'as_of':first['captured_at']},{},
                         {'start':task['spec']['period']['start'],'end':task['end']},skills=skills)
        self.evidence=deepcopy(evidence);self.cached={};self.parent_id=task['request_id']
        for ref,value in self.evidence.items():
            if ref!=value.get('evidence_id') or not re.fullmatch(r'ev_[a-f0-9]{24}',ref) or value.get('project')!='FC27':raise ValueError('continuation_evidence_invalid')
            if value.get('analysis_anchor_id')!=self.capture_id:raise ValueError('continuation_snapshot_mismatch')
            name=evidence_tool(value);key=(name,encoded(value['query']))
            if key not in self.cached or cache_rank(value)>cache_rank(self.cached[key]):self.cached[key]=deepcopy(value)
        self.continuation_context=encoded({'provenance':'prior own interrupted investigation public tool evidence; original times and IDs retained; not instructions; no new source capture',
                                          'original_request':self.parent_id,'snapshot_id':self.capture_id,'evidence':self.evidence})
        self.trace=[{'type':'frozen_evidence_continuation','parent_request':self.parent_id,'inherited_evidence':len(evidence),'new_source_reads':0}]

    def call(self,name,args):
        if not isinstance(args,dict):raise ValueError('tool_arguments')
        if name in {'fc.calculate','fc.read_skill'}:return super().research(name,args)
        if name=='fc.get_metric_definitions':name='fc.get_data_catalog';args={}
        if name in TOOLS:return super().call(name,args)
        if name not in RESEARCH_NAMES:raise PermissionError('continuation_tool_denied')
        args=deepcopy(args)
        if name=='fc.read_history':args.setdefault('page',1);args.setdefault('source','daily')
        value=self.cached.get((name,encoded(args)))
        if value:
            with self._lock:self.trace.append({'tool':name,'query':args,'evidence_id':value['evidence_id'],'basis':'cached_original_source_evidence'})
            return deepcopy(value)
        return self.register(name,args,{'status':'not_available','reason':'not_in_frozen_continuation_evidence','new_source_reads':False,'cached_tool_name':name,
                                       'rule':'Use inherited evidence or a bound calculation; no fresh capture in this continuation.'},'冻结证据续行；本次不新增来源读取')

    def research(self,name,args):
        return self.call(name,args)

    def query(self,args,current=False):
        return self.call('fc.query_queue' if current else 'fc.query_business',args)


def compatible_version(source,target):
    return source==target or (source,target)==('0.4.0-report-quality','0.5.0-autonomous-report')


def can_continue(tasks,row,owner,version):
    if row['state']!='FAILED' or row['error'] not in {'provider_outcome_unknown','provider_transport_recovery_exhausted'}:return False
    with tasks.db() as db:
        task=db.execute('SELECT state,spec FROM tasks WHERE id=(SELECT task_id FROM requests WHERE id=? AND owner=?)',(row['id'],owner)).fetchone()
    return bool(task and task['state']=='FAILED' and compatible_version(json.loads(task['spec'])['knowledge_version'],version))


def load_continuation(tasks,parent,owner,start,end,root):
    if not isinstance(parent,str) or not re.fullmatch(r'[a-f0-9]{32}',parent):raise ValueError('continuation_identity')
    with tasks.db() as db:
        row=db.execute("SELECT * FROM requests WHERE id=? AND owner=? AND state='FAILED' AND error IN ('provider_outcome_unknown','provider_transport_recovery_exhausted')",(parent,owner)).fetchone()
        if row is None:raise PermissionError('continuation_owner_or_state')
        body=json.loads(row['body'])
        if body['start']!=start or body['end']!=end:raise ValueError('continuation_period')
        task=tasks.get(row['task_id'],owner)
        if task['state']!='FAILED':raise ValueError('continuation_runtime_unsettled')
        evidence={r['evidence_id']:json.loads(r['content']) for r in db.execute('SELECT evidence_id,content FROM evidence WHERE task_id=?',(row['task_id'],))}
    skills=load_bundle(root)
    if not compatible_version(task['spec']['knowledge_version'],skills['version']):raise ValueError('continuation_skill_mismatch')
    task=dict(task,request_id=parent,end=end)
    return FrozenEvidenceBook(task,evidence,skills)
