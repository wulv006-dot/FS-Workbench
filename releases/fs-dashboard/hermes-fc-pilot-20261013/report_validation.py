"""Validate traceability and publication state; business judgement still needs review."""
import json
import re
from datetime import date
from decimal import Decimal,ROUND_HALF_UP
from pilot import encoded
from research import resolve,decimal
from proxy_gateway import sensitive_context

FORMAT = ('最终输出JSON：summary（中文短结论），findings数组（statement、claim_type=fact/hypothesis、'
          'evidence_ids、alternative、missing），actions数组（target、action、condition、cost_risk、review_at、'
          'success_check、evidence_ids），reviews数组（old_report_id、status=improved/worse/pending/retracted、'
          'reason、evidence_ids），limitations字符串数组；number_claims数组，每个数字说明report_field（如/findings/0/statement）、'
          'text（正文数字token，如10.00；美元符号/百分号不放text）、evidence_id、path（证据内JSON-pointer，如/data/total/known_revenue_usd）、'
          'scale=as_stored或times100（/result/ratio等明确比例字段转百分数时用）。数字可用十进制和规范千分逗号。正文所有数字必须与所指字段按显示精度一致；ISO日期及FC27等名称例外。'
          '情景计算含假设的数字只能放hypothesis、action、limitation，并明确假设，不能作为fact。数字可写且需复算；没有证据不能编原因。'
          '每个结论引用实际工具返回的ev_证据编号，不能引用技能作为经营事实。不需要凑固定条数。'
          '请直接输出JSON，行动数字引用的字段是/actions/序号/action，不是statement。日期优先写完整ISO。'
          '跨期商品标题变化不等于商品ID变化，不能按标题倒推历史金币档位。'
          '当前问题池没有历史快照时，不可判断积压上升；多批样本须按脱敏订单身份去重。'
          '复验旧判断前先确认同一目标期间与粒度；前期无支付标签不等于本期新上线。'
          '分页不全的国家或商品样本不能扩为全体；保留分销归属及原生消损定义缺口。')


def decode_output(text):
    if not isinstance(text,str) or not text.strip():raise ValueError('empty_analysis')
    try:return json.loads(text)
    except json.JSONDecodeError:
        blocks=list(re.finditer(r'```(?:json)?\s*(.*?)\s*```',text,re.S))
        if len(blocks)!=1 or '```' in text[:blocks[0].start()]+text[blocks[0].end():]:raise ValueError('ambiguous_analysis_json') from None
        return json.loads(blocks[0].group(1))


def mask_numeric_labels(text,refs,book):
    # Display names and category boundaries are labels, not observed monetary/count values.
    dates=set()
    def source_dates(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in {'date','day','start','end'} and isinstance(item,str) and re.match(r'^\d{4}-\d{2}-\d{2}(?:$|[ T])',item):dates.add(item[5:10])
                elif isinstance(item,(dict,list)):source_dates(item)
        elif isinstance(value,list):
            for item in value:source_dates(item)
    for ref in refs:
        evidence=book.evidence[ref];data=evidence.get('data',{})
        source_dates(evidence)
        if evidence.get('query',{}).get('kind')=='product_sales':
            for row in data.get('rows',[]):
                title=row.get('title')
                if isinstance(title,str) and title:
                    for left,right in (('“','”'),('"','"')):text=text.replace(left+title+right,'LABEL')
        bands={row.get('group',{}).get('age_band') for row in data.get('groups',[])}
        if 'over14d' in bands:text=text.replace('超14天','LABEL')
        if '7to14d' in bands:text=text.replace('7-14天','LABEL')
    text=re.sub(r'\b\d{4}-\d{2}-\d{2}\b','DATE',text)
    def date_sequence(match):
        labels=re.findall(r'\d{2}-\d{2}',match.group())
        try:
            for value in labels:date(2000,int(value[:2]),int(value[3:]))
        except ValueError:return match.group()
        return 'DATE' if set(labels)<=dates else match.group()
    # Multiple MM-DD labels separated as calendar days must occur in cited source dates.
    # A single 10-11 is ambiguous with a count/cost range and is never exempt by itself.
    text=re.sub(r'(?<![\d$¥])(\d{2}-\d{2})(?:\s*(?:至|到|~|～|、|及)\s*\d{2}-\d{2})+(?!\d)(?!\s*(?:USD|usd|%|美元|元|笔|单|个百分点|天|小时|coins))',date_sequence,text)
    def dated_label(match):
        return match.group(1)+'DATE' if match.group(2) in dates else match.group()
    return re.sub(r'(日期[：:]?\s*)(\d{2}-\d{2})(?!\d)',dated_label,text)


def validate_output(text,book):
    result=decode_output(text)
    if not isinstance(result,dict) or set(result)!={'summary','findings','actions','reviews','limitations','number_claims'}:raise ValueError('analysis_fields')
    if not isinstance(result['summary'],str) or not result['summary'].strip():raise ValueError('summary_required')
    if any(not isinstance(result[k],list) for k in ('findings','actions','reviews','limitations','number_claims')):raise ValueError('analysis_lists')
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
    fields={'/summary':result['summary']}
    for name in ('findings','actions','reviews'):
        for i,row in enumerate(result[name]):
            for key,value in row.items():
                if key not in {'evidence_ids','claim_type','status','old_report_id','review_at'}:fields[f'/{name}/{i}/{key}']=value
    fields.update({f'/limitations/{i}':v for i,v in enumerate(result['limitations'])})
    bound={path:set() for path in fields};normalizations=[]
    for claim in result['number_claims']:
        if not isinstance(claim,dict) or set(claim)!={'report_field','text','evidence_id','path','scale'}:raise ValueError('number_claim_fields')
        location=claim['report_field'];ref=claim['evidence_id']
        alias=re.fullmatch(r'/actions/(\d+)/statement',location) if isinstance(location,str) else None
        if alias:
            corrected='/actions/'+alias[1]+'/action'
            token=claim.get('text')
            if corrected in fields and isinstance(token,str) and token in fields[corrected]:
                normalizations.append({'from':location,'to':corrected,'evidence_id':ref,'text':token})
                claim['report_field']=location=corrected
        if location not in fields or ref not in book.evidence or claim['scale'] not in {'as_stored','times100'}:raise ValueError('number_claim_reference')
        token=claim['text'];value=decimal(resolve(book.evidence[ref],claim['path']))
        if not isinstance(token,str) or not re.fullmatch(r'-?\d+(?:,\d{3})*(?:\.\d+)?',token):raise ValueError('number_claim_token')
        if claim['scale']=='times100':
            if not re.search(r'/(?:ratio|[A-Za-z_]+_ratio|fraction|proportion)$',claim['path']):raise ValueError('number_claim_scale')
            value*=100
        precision=len(token.split('.')[1]) if '.' in token else 0
        if value.quantize(Decimal(1).scaleb(-precision),rounding=ROUND_HALF_UP)!=Decimal(token.replace(',','')):raise ValueError('number_claim_mismatch')
        evidence=book.evidence[ref]
        if evidence.get('data',{}).get('basis')=='declared_scenario' and not location.startswith(('/actions/','/limitations/')):
            if not location.startswith('/findings/') or result['findings'][int(location.split('/')[2])]['claim_type']!='hypothesis':raise ValueError('scenario_presented_as_fact')
        if location.startswith(('/findings/','/actions/','/reviews/')) and ref not in result[location.split('/')[1]][int(location.split('/')[2])]['evidence_ids']:raise ValueError('number_claim_reference')
        bound[location].add(token)
    for location,value in fields.items():
        # Labels like FC27 and evidence identities are not numeric business claims.
        refs=[]
        if location.startswith(('/findings/','/actions/','/reviews/')):
            refs=result[location.split('/')[1]][int(location.split('/')[2])]['evidence_ids']
        else:
            refs=list({claim['evidence_id'] for claim in result['number_claims'] if claim['report_field']==location})
        value=mask_numeric_labels(value,refs,book)
        tokens=set(re.findall(r'(?<![A-Za-z0-9_])-?\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z0-9_])',value))
        if tokens-bound[location]:raise ValueError('unbound_report_number')
    if sensitive_context(result) or re.search(r'密码\s*[:：=]|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',encoded(result),re.I):raise ValueError('sensitive_analysis')
    return dict(result,analysis_completed=True,business_acceptance='user_review_required',format_normalizations=normalizations,
                model_generated=True,actions_executed=False,snapshot_id=book.capture_id,
                validation='schema_evidence_and_numeric_binding_not_causal_quality_approval')
