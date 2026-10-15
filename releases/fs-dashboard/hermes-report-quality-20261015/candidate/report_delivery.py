"""Keep the native report usable; structured indexing is a downstream convenience."""
import re
import json
from report_validation import decode_output,validate_output
from proxy_gateway import sensitive_context
from report_semantics import index,structured,CONTRACT


def private_report(text):
    try:
        parsed=decode_output(text)
        if sensitive_context(parsed):return True
        text=text+'\n'+json.dumps(parsed,ensure_ascii=False)
    except (ValueError,TypeError):pass
    return sensitive_context({'content':text}) or bool(re.search(r'密码\s*[:：=]|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',text,re.I))


FORMAT=('请用完整、可读的中文经营调查报告直接回答，可用Markdown标题、表格、列表，不要求长JSON或逐数字绑定表。'
        '优先给关键判断、影响量、替代解释、证据与缺口、最小可执行建议及触发/复查条件。'
        '自主选择只读接口补查，按需要计算，不必为了序号、建议时限或每个数字重复造计算记录。'
        '关键经营量应有来源，正文可引用实际返回的ev_证据ID；估算、范围和情景明示。'
        'Admin经营主源，Order参考利润明确估算；真实改价成本只用已核实订单发货类型，排除采购打款和未知。'
        '原始正文由服务器自动保存并排为HTML，无需再生成版式代码；建议不执行。'
        '为保证原文与老板版兼容，使用“## 关键判断”“## 专题标题”“## 建议与复查”“## 缺口”明确分段。'
        '每条建议单独用“### R1 对象名称”等标题，列对象、责任角色、最小动作、证据、触发条件、投入/风险、复查时间、成功/失败标准、停止条件；'
        '条数按实际调查，不复制样板当周结论或固定阈值。关键判断先写结果及贡献位置，再分事实、竞争解释、缺口和可推翻判断的验证动作。'
        '先核真实工具清单；没有已注册的官方网页读取工具，就写“官方情报未开展（工具未接通）”，不编热点。'
        '出稿前按已加载的report-contract审核同期间/来源/分母、量价精算闭合、成熟度、队列流入流出和因果措辞；Humanizer润色不改变这些边界。'
        '若使用结构化输出，采用report_contract="fs-report-v2"封套：summary短结论、research_text完整Markdown、findings(statement/claim_type/evidence_ids/alternative/missing)、'
        'actions(target/action/condition/cost_risk/review_at/success_check/stop_condition/role/evidence_ids)、limitations，以及可选reviews/hypotheses/context/intel/decisions/timeline数组。'
        '明确对照窗时另给comparison_period:{start:YYYY-MM-DD,end:YYYY-MM-DD}，不要让排版层猜测。'
        '不要求逐数字number_claims表；缺少动作字段明示待补而不是删掉整条，引用只能用本次真实证据。旧结构化合同仍兼容。')


def envelope(parsed,text,book):
    """Recover a complete native body, while disclosing format recovery."""
    from report_constraints import narrative
    value=dict(parsed);warnings=[]
    metadata={'project','scope','snapshot_id','captured_at','period','timezone','currency','grain','skill'}
    core={'report_contract','summary','research_text','comparison_period','findings','actions','reviews','limitations','hypotheses','context','intel','decisions','timeline'}
    if set(value)-core-metadata:return value,warnings
    if value.get('project','FC27')!='FC27' or value.get('snapshot_id',book.capture_id)!=book.capture_id:
        raise ValueError('declared_metadata_conflict')
    target=getattr(book,'target',None)
    if target and value.get('period') and value['period']!={k:target[k] for k in ('start','end')}:
        raise ValueError('declared_period_conflict')
    if set(value)&metadata:
        warnings.append('模型额外元数据仅保留原文；实际范围、快照和加载指纹由运行时绑定。')
        for key in metadata:value.pop(key,None)
    if not value.get('research_text'):
        recovered=narrative(text)
        if recovered==text or not re.search(r'(?m)^#{1,3}\s+',recovered):raise ValueError('complete_research_text_missing')
        value['research_text']=recovered;warnings.append('完整Markdown从JSON围栏后恢复；模型未按约定填research_text，恢复不等于原输出格式合格。')
    for row in value.get('findings',[]):
        if isinstance(row,dict) and row.get('claim_type') not in ('fact','hypothesis','unreviewed'):
            row['claim_type']='unreviewed';warnings.append('非合同claim_type降为待审核，未将其自动认定事实。')
    return value,list(dict.fromkeys(warnings))


def attach_review(result,book):
    target=getattr(book,'target',None)
    if not isinstance(target,dict) or not all(k in target for k in ('start','end')):return result
    from boss_projection import project
    value=dict(result,period={k:target[k] for k in ('start','end')},snapshot_id=book.capture_id)
    try:content=project(value,book.evidence,{},'0'*64)
    except (ValueError,KeyError,TypeError) as error:
        # Native text must still be saved when the optional audit lacks a stable
        # evidence timestamp/population. Record the failed coverage, never green it.
        result['quality_review']={'contract':'fc-report-review-v1','status':'not_evaluable','issues':[],
            'reason':type(error).__name__+':'+str(error),'original_preserved':True,'actions_executed':False,
            'scope':'证据约束审核未能完成，不能据此认定业务通过。'}
        result['limitations']=result.get('limitations',[])+['证据约束审核未能完成；原文保留，自动检查不算通过。']
        return result
    result['quality_review']=content['quality_review'];result['evidence_constraints']=content['evidence_constraints']
    result['deterministic_payment_partition']=content['payment']
    result['business_review_status']=content['quality_review']['status']
    if content['quality_review']['issues']:
        # "ready" is the existing artifact/submission receipt contract. Business
        # approval is separate and must not break idempotent receipt recovery.
        result['summary']='[证据约束待复核] '+content['executive']['summary']
        result['limitations']=result.get('limitations',[])+['证据约束发现待证或未核平内容；阅读版公开拦截原因，原文保留，业务未放行。']
    return result


def deliver_output(text,book,validator=validate_output):
    if not isinstance(text,str) or not text.strip():raise ValueError('empty_analysis')
    if private_report(text):raise ValueError('sensitive_analysis')
    warning=[]
    try:
        parsed=decode_output(text)
    except (ValueError,TypeError):parsed=None
    if isinstance(parsed,dict):
        try:
            recovery=[]
            if parsed.get('report_contract')==CONTRACT:
                parsed,recovery=envelope(parsed,text,book)
                result=structured(parsed,book.evidence)
            else:result=validator(text,book)
            delivered=dict(result,report_format='structured_v2' if parsed.get('report_contract')==CONTRACT else 'structured',delivery_status='ready',raw_model_text=text)
            delivered['format_recovery']=recovery
            if recovery:delivered['report_format']+='_recovered';delivered['limitations']+=recovery
            delivered['semantic_index']=index(delivered,book.evidence)
            return attach_review(delivered,book)
        except Exception as error:
            if isinstance(error,ValueError) and str(error)=='sensitive_analysis':raise
            warning.append('原始报告已保存；结构化索引待整理：'+str(error))
    elif text.lstrip().startswith('{'):warning.append('原始报告已保存；JSON索引未解析，完整原文保留。')
    ids=re.findall(r'\bev_[a-f0-9]{24}\b',text)
    missing=sorted(set(ids)-set(book.evidence))
    if missing:warning.append('部分正文证据编号未匹配，关键结论需复核。')
    refs=list(dict.fromkeys(x for x in ids if x in book.evidence))
    chunks=re.split(r'(?m)(?=^#{1,3}\s+)',text)
    findings=[]
    for part in chunks:
        if part.strip():findings.append({'statement':part.strip(),'claim_type':'report','evidence_ids':list(dict.fromkeys(x for x in re.findall(r'\bev_[a-f0-9]{24}\b',part) if x in book.evidence)),'alternative':'','missing':''})
    candidate={'raw_model_text':text,'findings':findings}
    if isinstance(parsed,dict):
        for key in ('summary','research_text'):
            if isinstance(parsed.get(key),str):candidate[key]=parsed[key]
        for key in ('findings','actions'):
            rows=parsed.get(key,[])
            if isinstance(rows,list):candidate[key]=[dict(row,claim_type='unreviewed') if key=='findings' else row for row in rows if isinstance(row,dict) and all(isinstance(v,str) for k,v in row.items() if k!='evidence_ids') and isinstance(row.get('evidence_ids',[]),list)]
    semantic=index(candidate,book.evidence)
    output={'summary':semantic['summary'],'findings':semantic['findings'],'actions':semantic['actions'],'reviews':[],'limitations':warning,'number_claims':[],
            'analysis_completed':True,'business_acceptance':'user_review_required','model_generated':True,'actions_executed':False,
            'snapshot_id':book.capture_id,'validation':'original_native_report_with_evidence_index_key_conclusions_need_review',
            'report_format':'raw_json' if isinstance(parsed,dict) or text.lstrip().startswith('{') else 'markdown',
            'delivery_status':'raw_saved' if warning else 'ready','raw_model_text':text,'research_text':candidate.get('research_text',text),'report_evidence_ids':refs,'semantic_index':semantic}
    return attach_review(output,book)
