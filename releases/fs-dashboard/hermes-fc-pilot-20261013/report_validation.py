"""Validate traceability and publication state; business judgement still needs review."""
import json
import re
from pilot import encoded

FORMAT = ('最终输出JSON：summary（中文短结论），findings数组（statement、claim_type=fact/hypothesis、'
          'evidence_ids、alternative、missing），actions数组（target、action、condition、cost_risk、review_at、'
          'success_check、evidence_ids），reviews数组（old_report_id、status=improved/worse/pending/retracted、'
          'reason、evidence_ids），limitations字符串数组。数字可写但必须可复算；没有证据不能编原因。'
          '每个结论引用实际工具返回的ev_证据编号，不能引用技能作为经营事实。不需要凑固定条数。')


def validate_output(text,book):
    if not isinstance(text,str) or not text.strip():raise ValueError('empty_analysis')
    match=re.fullmatch(r'\s*```(?:json)?\s*(.*?)\s*```\s*',text,re.S)
    if match:text=match.group(1)
    result=json.loads(text)
    if not isinstance(result,dict) or set(result)!={'summary','findings','actions','reviews','limitations'}:raise ValueError('analysis_fields')
    if not isinstance(result['summary'],str) or not result['summary'].strip():raise ValueError('summary_required')
    if any(not isinstance(result[k],list) for k in ('findings','actions','reviews','limitations')):raise ValueError('analysis_lists')
    if not result['findings']:raise ValueError('findings_required')
    for row in result['findings']:
        if not isinstance(row,dict) or set(row)!={'statement','claim_type','evidence_ids','alternative','missing'}:raise ValueError('finding_fields')
        if row['claim_type'] not in {'fact','hypothesis'} or row['claim_type']=='hypothesis' and not row['alternative']:raise ValueError('hypothesis_alternative')
    for row in result['actions']:
        if not isinstance(row,dict) or set(row)!={'target','action','condition','cost_risk','review_at','success_check','evidence_ids'}:raise ValueError('action_fields')
        if any(not isinstance(row[k],str) or not row[k].strip() for k in row if k!='evidence_ids'):raise ValueError('action_operability')
    for row in result['reviews']:
        if not isinstance(row,dict) or set(row)!={'old_report_id','status','reason','evidence_ids'} or row['status'] not in {'improved','worse','pending','retracted'}:raise ValueError('review_fields')
    for row in result['findings']+result['actions']+result['reviews']:
        refs=row['evidence_ids']
        if not isinstance(refs,list) or not refs or any(r not in book.evidence for r in refs):raise ValueError('fabricated_evidence')
        if any(not isinstance(v,str) for k,v in row.items() if k!='evidence_ids'):raise ValueError('analysis_text')
    if any(not isinstance(v,str) for v in result['limitations']):raise ValueError('limitation_text')
    if re.search(r'sk-[A-Za-z0-9]|Bearer\s|Cookie\s*[:=]|password\s*[:=]|密码\s*[:：=]|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',encoded(result),re.I):raise ValueError('sensitive_analysis')
    return dict(result,analysis_completed=True,business_acceptance='user_review_required',
                model_generated=True,actions_executed=False,snapshot_id=book.capture_id,
                validation='schema_and_reference_integrity_not_causal_quality_approval')
