"""Keep the native report usable; structured indexing is a downstream convenience."""
import re
import json
from report_validation import decode_output,validate_output
from proxy_gateway import sensitive_context


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
        '原始正文由服务器自动保存并排为HTML，无需再生成版式代码；建议不执行。')


def deliver_output(text,book,validator=validate_output):
    if not isinstance(text,str) or not text.strip():raise ValueError('empty_analysis')
    if private_report(text):raise ValueError('sensitive_analysis')
    warning=[]
    try:
        parsed=decode_output(text)
    except (ValueError,TypeError):parsed=None
    if isinstance(parsed,dict):
        try:
            result=validator(text,book)
            return dict(result,report_format='structured',delivery_status='ready',raw_model_text=text)
        except ValueError as error:
            if str(error)=='sensitive_analysis':raise
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
    summary=next((part.strip()[:1600] for part in chunks if part.strip()),'原始报告已保存。')
    return {'summary':summary,'findings':findings,'actions':[],'reviews':[],'limitations':warning,'number_claims':[],
            'analysis_completed':True,'business_acceptance':'user_review_required','model_generated':True,'actions_executed':False,
            'snapshot_id':book.capture_id,'validation':'original_native_report_with_evidence_index_key_conclusions_need_review',
            'report_format':'raw_json' if isinstance(parsed,dict) or text.lstrip().startswith('{') else 'markdown',
            'delivery_status':'raw_saved' if warning else 'ready','raw_model_text':text,'report_evidence_ids':refs}
