"""Evidence-constrained projections and visible review gates. No queries or model calls.

These checks cover specific verifiable contracts, not arbitrary causal truth.
Original model text is never changed; warnings stay visible and hard assertions
are withheld individually.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import re


def numeric(value):
    if isinstance(value,bool):raise ValueError('boolean_number')
    out=Decimal(str(value))
    if not out.is_finite():raise ValueError('non_finite')
    return out


def measure(row):
    revenue,orders=numeric(row['revenue_usd']),numeric(row['orders'])
    if revenue<0 or orders<0 or orders!=orders.to_integral_value() or numeric(row['unpriced_orders'])!=0:
        raise ValueError('incomplete_measure')
    return revenue,orders


def complete_projection(evidence,dimension,lo,hi,captured,eligible,expected=None,pool=False):
    """Marginalize only full, disjoint, reconciled normalizer group populations.

    Separate group_by schemas stay separate until independently reconciled.
    All pages, tuple uniqueness, totals, filters and timestamps must agree.
    Conflicting complete schemas withhold the result, rather than choosing one.
    """
    schemas=defaultdict(list)
    for key,row in sorted(evidence.items()):
        q=row.get('query',{});data=row.get('data',{});axes=q.get('group_by')
        if (not eligible(row) or row.get('captured_at')!=captured or not isinstance(axes,list)
                or not 1<=len(axes)<=3 or len(set(axes))!=len(axes) or dimension not in axes
                or q.get('start')!=lo or q.get('end')!=hi or q.get('filters')!={} or data.get('filters_applied')!={}
                or (len(axes)>1 and data.get('source_grain')!='deduplicated_paid_order')
                or (len(axes)==1 and data.get('source_grain') not in (None,'deduplicated_paid_order'))):continue
        if pool and (data.get('coverage',{}).get('backlog_status')!='available'
                     or data.get('state_basis')!='current_at_capture_not_historical_day_end'):continue
        schemas[tuple(sorted(axes))].append((key,row))
    candidates=[]
    for axes,incoming in schemas.items():
        pages={};population=None;invalid=False
        try:
            for key,row in incoming:
                q=row['query'];data=row['data'];p=data['pagination']
                page,size,count=p['page'],p['page_size'],p['total_groups']
                if (any(type(v) is not int for v in (page,size,count)) or page<1 or size<1
                        or not 0<=count<=10000 or page!=q.get('page') or type(p['complete']) is not bool):raise ValueError('page_shape')
                grand=measure(data['total'])
                if expected is not None and grand!=expected:raise ValueError('wrong_population')
                signature=(size,count,grand)
                if population is not None and population!=signature:raise ValueError('changing_population')
                population=signature;groups=data['groups']
                if not isinstance(groups,list) or len(groups)>size:raise ValueError('group_shape')
                normalized=[]
                for group in groups:
                    if set(group.get('group',{}))!=set(axes):raise ValueError('group_axes')
                    names=tuple(group['group'][axis] for axis in axes)
                    if any(not isinstance(x,str) for x in names):raise ValueError('group_label')
                    normalized.append((names,measure(group)))
                normalized.sort()
                page_value=(normalized,p['complete'])
                if page in pages and pages[page][0]!=page_value:raise ValueError('conflicting_page')
                if page not in pages:pages[page]=(page_value,[])
                pages[page][1].append(key)
            size,count,grand=population;last=max(1,(count+size-1)//size)
            if set(pages)!=set(range(1,last+1)) or any(pages[p][0][1]!=(p==last) for p in pages):continue
            tuples={};references=[]
            for page in range(1,last+1):
                values,complete=pages[page][0];references+=pages[page][1]
                if len(values)!=(min(size,count-(page-1)*size) if count else 0):raise ValueError('short_page')
                for names,value in values:
                    if names in tuples:raise ValueError('overlapping_groups')
                    tuples[names]=value
            if len(tuples)!=count or tuple(sum((v[i] for v in tuples.values()),Decimal(0)) for i in (0,1))!=grand:
                raise ValueError('unreconciled_population')
            marginal=defaultdict(lambda:[Decimal(0),Decimal(0)]);position=axes.index(dimension)
            for names,value in tuples.items():
                for i in (0,1):marginal[names[position]][i]+=value[i]
            candidates.append((dict(marginal),references))
        except (KeyError,ValueError,TypeError,ArithmeticError):invalid=True
        if invalid:return None
    if not candidates:return None
    signatures={json.dumps({k:[str(x) for x in v] for k,v in values.items()},sort_keys=True) for values,_ in candidates}
    if len(signatures)!=1:return None
    values=candidates[0][0]
    return ({name:{'revenue_usd':str(v[0]),'orders':int(v[1]),'unpriced_orders':0} for name,v in values.items()},
            list(dict.fromkeys(key for _,ids in candidates for key in ids)))


def estimated_profit(evidence,anchor,lo,hi,main,eligible):
    """User's temporary estimate; a period rate takes precedence over daily rates.

    Each period stands alone. Never average rates or borrow another date's rate.
    Source definitions stay immutable; this policy does not certify settlement.
    """
    out={'status':'missing','period':{'start':lo,'end':hi},'currency':'USD','amount_usd':None,
         'method':None,'sources':[],'evidence_ids':[],'policy_effective':'2026-10-15T05:52:43Z',
         'label':'主站预估利润（临时口径，非实际结算）'}
    def missing(reason):
        return dict(out,reason=reason)
    if not main:return missing('未取得该期完整主站金额，预估利润保持缺失。')
    days=[(date.fromisoformat(lo)+timedelta(days=i)).isoformat()
          for i in range((date.fromisoformat(hi)-date.fromisoformat(lo)).days+1)]
    def stamp(value):
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:raise ValueError('reference_timestamp')
        return value
    def bounds(a,b):
        return {'start':a+' 00:00','end':(date.fromisoformat(b)+timedelta(days=1)).isoformat()+' 00:00'}
    def source(key,record,scope):
        return {'evidence_id':key,'system':'order.p2pah.cn','captured_at':stamp(record['capturedAt']),
                'source_data_as_of':record.get('sourceDataAsOf'),'period':record.get('period'),
                'scope':scope,'currency':'USD','margin_unit':'percent'}
    rates=[]
    for key,row in sorted(evidence.items()):
        q=row.get('query',{});data=row.get('data',{})
        if (row.get('analysis_anchor_id')!=anchor or row.get('project')!='FC27'
                or row.get('timezone')!='Asia/Shanghai' or q!={'profile':'FC27','start':lo,'end':hi}
                or data.get('status')!='available'
                or data.get('source_contract')!='admin-main-order-labelled-supplement-v1'):continue
        records=data.get('source_records',{})
        if not isinstance(records,dict):continue
        for record in records.values():
            try:
                if (record.get('system')!='order.p2pah.cn' or record.get('status')!='available'
                        or record.get('stale') is not False or record.get('currency')!='USD'
                        or record.get('period')!=bounds(lo,hi)):continue
                metric=record['metrics']['profitMarginPct']
                if metric.get('status')!='available' or metric.get('unit')!='percent':continue
                rate=numeric(metric['value'])
                channels=record.get('dimensions',{}).get('channels')
                names=[c['name'] for c in channels if isinstance(c,dict) and isinstance(c.get('name'),str)] if isinstance(channels,list) else []
                scope={'query':q,'reported_channels':names,'scope_note':'Order原生查询范围；可见渠道不代表完整渠道清单，与Admin主站范围可能不同'}
                detail=source(key,record,scope);detail['reference_margin_percent']=str(rate)
                rates.append((rate,detail))
            except (KeyError,ValueError,TypeError,AttributeError,ArithmeticError):continue
    if rates:
        signatures={json.dumps([str(rate),{k:v for k,v in detail.items() if k!='evidence_id'}],sort_keys=True) for rate,detail in rates}
        if len(signatures)!=1:return missing('该期完整参考率或版本/范围冲突，未自动挑选；预估利润保持缺失。')
        rate=rates[0][0];amount=main[1]*rate/100
        return dict(out,status='estimated',amount_usd=str(amount.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)),
                    amount_unrounded_usd=str(amount),main_revenue_usd=str(main[1]),reference_margin_percent=str(rate),
                    method='period_amount_times_period_reference_percent',
                    formula='主站订单金额 × 对应该期参考利润率 ÷ 100',sources=[detail for _,detail in rates],
                    evidence_ids=list(dict.fromkeys([main[0]]+[d['evidence_id'] for _,d in rates])))
    daily=({lo:{'revenue_usd':str(main[1]),'orders':str(main[2])}},[main[0]]) if len(days)==1 and eligible(main[3]) and main[3].get('query',{}).get('start')==lo and main[3].get('query',{}).get('end')==hi else complete_projection(evidence,'day',lo,hi,main[3]['captured_at'],eligible,(main[1],main[2]))
    if not daily or set(daily[0])!=set(days):return missing('缺该期有效参考率，且无完整同日期主站金额可逐日估算；缺失不补零。')
    values={};references=[]
    for key,row in sorted(evidence.items()):
        data=row.get('data',{});q=data.get('query',row.get('query',{}));rows=data.get('rows',[])
        if (not row.get('source','').startswith('Order参考利润') or row.get('analysis_anchor_id')!=anchor
                or data.get('status')!='available' or data.get('reference_only') is not True or data.get('missingDays')!=[]
                or q.get('profile')!='FC27'):continue
        try:
            first,last=date.fromisoformat(q['start']),date.fromisoformat(q['end'])
            requested={(first+timedelta(days=i)).isoformat() for i in range((last-first).days+1)}
            if not requested or not requested<=set(days) or len(rows)!=len(requested) or {v['date'] for v in rows}!=requested:continue
            checked=[]
            for record in rows:
                day=record['date']
                if (record.get('status')!='available' or record.get('stale') is not False or record.get('currency')!='USD'
                        or record.get('source')!='order.p2pah.cn' or record.get('profileKey')!='FC27'
                        or record.get('timezone')!='Asia/Shanghai' or record.get('marginUnit')!='percent'
                        or record.get('period')!=bounds(day,day)
                        or record.get('scope')!={'orderGameId':'1322','orderProductType':'','orderStatus':'','sites':'all-websites'}):
                    raise ValueError('daily_reference_contract')
                rate=numeric(record['profitMarginPct']);detail=source(key,record,record['scope'])
                detail['reference_margin_percent']=str(rate)
                checked.append((day,rate,detail))
            for day,rate,detail in checked:
                signature=(rate,json.dumps({k:v for k,v in detail.items() if k!='evidence_id'},sort_keys=True))
                if day in values and values[day][2]!=signature:return missing('同日参考率或版本/范围冲突，预估利润保持缺失。')
                values[day]=(rate,detail,signature)
            references.append(key)
        except (KeyError,ValueError,TypeError,AttributeError,ArithmeticError):continue
    if set(values)!=set(days):return missing('缺完整同日期参考率；不跨日期借用、不补零。')
    terms=[{'date':day,'main_revenue_usd':daily[0][day]['revenue_usd'],
            'reference_margin_percent':str(values[day][0]),
            'estimated_profit_unrounded_usd':str(numeric(daily[0][day]['revenue_usd'])*values[day][0]/100)} for day in days]
    amount=sum((numeric(t['estimated_profit_unrounded_usd']) for t in terms),Decimal(0))
    return dict(out,status='estimated',amount_usd=str(amount.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)),
                amount_unrounded_usd=str(amount),main_revenue_usd=str(main[1]),
                method='sum_matching_daily_amount_times_reference_percent',formula='Σ（同日主站订单金额 × 同日参考利润率 ÷ 100）',
                daily_terms=terms,reference_margin_percent=str(values[days[0]][0]) if len(days)==1 else None,sources=[values[day][1] for day in days],
                evidence_ids=list(dict.fromkeys([main[0]]+daily[1]+references)))


def native_envelope(text):
    """Read one complete envelope after prose; reject trailing or multiple objects."""
    match=re.search(r'(?m)^[ \t]*\{',text)
    if not match:return None
    body=text[match.start():].lstrip()
    try:value,end=json.JSONDecoder().raw_decode(body)
    except (ValueError,TypeError):return None
    if body[end:].strip() or not isinstance(value,dict) or value.get('report_contract')!='fs-report-v2':return None
    return value


def narrative(text):
    """Recover Markdown following one fs-report-v2 envelope; never drop raw text."""
    value=native_envelope(text)
    if value and isinstance(value.get('research_text'),str) and value['research_text'].strip():return value['research_text']
    for match in re.finditer(r'(?ms)^```(?:json)?\s*\n(.*?)^```\s*$',text):
        try:value=json.loads(match[1])
        except (ValueError,TypeError):continue
        after=text[match.end():].strip()
        if isinstance(value,dict) and value.get('report_contract')=='fs-report-v2' and re.search(r'(?m)^#{1,3}\s+',after):
            return after
    return text


def constraints(content,evidence):
    period=content['report']['period'];anchor=content['report']['snapshot_id'];captured=content['report']['business_data_captured_at']
    def eligible(row):
        return (row.get('source')=='Admin FC支付明细' and row.get('scope')=='main' and row.get('snapshot_id')==anchor
                and row.get('captured_at')==captured and row.get('data',{}).get('status')=='available')
    # Joint evidence must actually carry the joint axes. Two marginal tables are
    # never accepted as a relational join. Filtered/partial series do not qualify.
    joint_ids=[]
    joint_candidates={k:r for k,r in evidence.items() if eligible(r) and {'product','status'}<=set(r.get('query',{}).get('group_by',[]))}
    joint=complete_projection(joint_candidates,'product',period['start'],period['end'],captured,eligible)
    if joint:joint_ids=joint[1]
    unit_ids=[]
    for key,row in evidence.items():
        data=row.get('data',{})
        if (row.get('analysis_anchor_id',row.get('snapshot_id'))==anchor
                and data.get('contract')=='fc-verified-order-lines-v1' and data.get('coverage',{}).get('complete') is True
                and data.get('definitions',{}).get('quantity_unit_verified') is True
                and data.get('definitions',{}).get('discount_and_specification_verified') is True):unit_ids.append(key)
    # No registered current adapter supplies stable, verified cohort-key joins.
    # A marginal or unbound joint grouping must not certify individual identity.
    return {'contract':'fc-report-evidence-constraints-v1','joint_product_status':bool(joint_ids),'joint_evidence_ids':joint_ids,
            'stable_order_intersection_verified':False,
            'verified_quantity_price_discount':bool(unit_ids),'unit_evidence_ids':unit_ids,
            'payment_delta':{r['label']:r['delta'] for r in content['payment']},'payment_evidence_ids':content['payment_evidence_ids'],
            'limits':['Joint grouping establishes aggregate intersections, not stable order identity or longitudinal cohort events.',
                      'Passing these checks is not causal, commercial or policy approval.']}


def review_paragraph(text,bounds,payment_context=''):
    reasons=[];ids=[]
    # shortcut: wording checks cover named Chinese claim patterns, not arbitrary source or causal verification.
    cautious=re.compile(r'不能|无法|不足以|尚未|未证|待证|未知|未验证|未闭合|未核实|不证明|不等于|不推断|不采用|不应|交集未知|撤回|不做关联|不用.{0,60}(?:推断|断言|证明)|不以.{0,60}(?:推断|断言|证明)')
    proposed=re.compile(r'^\s*(?:[-*>#\d.、 ]|\*\*)*(?:建议|假说|假设|需(?:要)?(?:核|补|查|验证))|(?:核实|核对|核清|确认|补齐|补证|检查|验证).{0,35}(?:数量|单位|单件|多件|规格|优惠|订单行|交集|关联)')
    for sentence in re.split(r'[。；\n]|[，,](?!\d{3}(?:\D|$))',text):
        proposal=proposed.search(sentence);claim=re.search(r'Items|商品|品类|单件|多件|数量|同\s*SKU',sentence,re.I)
        if cautious.search(sentence) or (proposal and (not claim or proposal.start()<=claim.start())):continue
        if not bounds['verified_quantity_price_discount'] and re.search(r'单件|多件\s*(?:Items|商品|道具)|件数叠加|数量(?:叠加|堆叠)|(?:无|非|不是|排除).{0,10}(?:多件|捆绑)|同\s*SKU.{0,12}(?:涨价|提价|单价)',sentence,re.I):
            reasons.append(('quantity_mechanism_unbound','数量、规格与优惠缺少已验证订单行定义；不能证明单件或排除多件/捆绑。'))
    # Coreference ("those Items ..., they are all ...") crosses commas but
    # does not cross independent paragraphs. Keep its sentence scope intact.
    for sentence in re.split(r'[。；\n]',text):
        proposal=proposed.search(sentence);claim=re.search(r'Items|商品|品类',sentence,re.I)
        if cautious.search(sentence) or (proposal and (not claim or proposal.start()<=claim.start())):continue
        if (not bounds.get('stable_order_intersection_verified',False) and re.search(r'Items|商品|品类',sentence,re.I)
                and re.search(r'问题状态|问题订单|未交付|未完成|挂在',sentence)
                and re.search(r'它们|那.{0,18}(?:笔|单)|这.{0,18}(?:笔|单)|均|全部|都',sentence)):
            reasons.append(('cohort_intersection_unbound','未取得所声明对象的可核订单交集；边际或未绑定对象的交叉不能冒充逐单关联。'))
    payments=bounds['payment_delta']
    if not payments and re.search(r'(?:其余|其他)[^。\n；]{0,35}?\$',text):
        reasons.append(('payment_partition_unavailable','缺完整同范围支付分组，无法核该余数；保持待证，未替换为猜测值。'))
    for match in re.finditer(r'(?:其余|其他)[^。\n；]{0,35}?([−–－+＋-]?)\s*\$\s*([\d,]+(?:\.\d+)?)',text):
        clause=re.split(r'[。；\n]',text[:match.start()])[-1]
        if re.search(r'撤回|不采用|不写',clause):continue
        before=payment_context+text[:match.start()];selected={name for name in payments if re.search(r'(?<![A-Za-z])'+re.escape(name)+r'(?![A-Za-z])',before,re.I)}
        if not selected:continue
        expected=sum((numeric(delta) for name,delta in payments.items() if name not in selected),Decimal(0))
        sign=-1 if match[1] in ('−','–','－','-') else 1;observed=numeric(match[2].replace(',',''))*sign
        if observed!=expected:
            code='payment_residual_direction_conflict' if observed*expected<0 else 'payment_residual_mismatch'
            reasons.append((code,'排除 '+', '.join(sorted(selected))+' 后的支付差额余数应为 $'+format(expected,',.2f')+'；原句'+('方向相反，不能作为事实。' if code.endswith('direction_conflict') else '余数未核平，仅供参考，金额影响待核。')))
            ids+=bounds['payment_evidence_ids']
    return list(dict.fromkeys(reasons)),list(dict.fromkeys(ids))


def reviewed_text(text,bounds,ledger,location):
    text=narrative(text);out=[];line=1
    for block in re.split(r'\n\s*\n',text):
        original_lines=block.count('\n')+2
        reasons,ids=review_paragraph(block,bounds)
        if reasons:
            hard_codes={'quantity_mechanism_unbound','cohort_intersection_unbound','payment_residual_direction_conflict'}
            hard=[r for r in reasons if r[0] in hard_codes]
            soft=[r for r in reasons if r[0] not in hard_codes]
            entry={'location':location,'line':line,'original_sha256':hashlib.sha256(block.encode()).hexdigest(),
                   'evidence_ids':ids}
            if hard:
                ledger.append(dict(entry,codes=[c for c,_ in hard],reasons=[r for _,r in hard],severity='error',
                                   status='assertion_withheld_original_preserved'))
                # Preserve independent conclusions and actions sharing the same block.
                parts=[];context=''
                for sentence in re.split(r'(?<=[。；\n])',block):
                    found,_=review_paragraph(sentence,bounds,context)
                    blocked=[r for c,r in found if c in hard_codes]
                    parts.append('【本句待证，不作事实结论：'+' '.join(blocked)+'】' if blocked else sentence)
                    context+=sentence
                block=''.join(parts)
            if soft:
                ledger.append(dict(entry,codes=[c for c,_ in soft],reasons=[r for _,r in soft],severity='warning',
                                   status='visible_with_uncertainty'))
                block+='\n\n> **局部待核，保留参考。** '+' '.join(r for _,r in soft)
            out.append(block)
        else:out.append(block)
        line+=original_lines
    return '\n\n'.join(out)


def apply_constraints(content,evidence):
    """Constrain every visible narrative surface, preserve immutable originals."""
    bounds=constraints(content,evidence);ledger=[]
    if content['metrics'][0].get('status')!='fact':
        ledger.append({'location':'primary_facts','codes':['primary_population_unavailable'],
            'reasons':['未取得可核平的主源完整汇总，相关自动审核未能完成，不能视为通过。'],
            'evidence_ids':[],'status':'not_evaluable'})
    content['reviewed_research_text']=reviewed_text(content['reviewed_research_text'],bounds,ledger,'research_text')
    content['executive']['summary']=reviewed_text(content['executive']['summary'],bounds,ledger,'summary')
    for i,row in enumerate(content['key_findings']):row['statement']=reviewed_text(row['statement'],bounds,ledger,'findings/'+str(i))
    for i,row in enumerate(content['hypotheses']):row['text']=reviewed_text(row['text'],bounds,ledger,'hypotheses/'+str(i))
    for i,action in enumerate(content['actions']):
        fields=' '.join(action.get(k,'') for k in ('trigger','steps','metric','stop'))
        threshold=re.search(r'[≥≤<>]\s*\$?\d|超\s*\d+\s*(?:小时|天)|\d+\s*(?:日|天|小时)内|(?:高于|低于|收窄至)\s*\d|持续.{0,8}\d+(?:[-–]\d+)?\s*%',fields)
        policy_ids=[key for key in action.get('evidence_ids',[]) if evidence.get(key,{}).get('data',{}).get('contract')=='fc-approved-policy-v1'
                    and evidence[key]['data'].get('status')=='approved']
        if threshold and not policy_ids:
            ledger.append({'location':'actions/'+str(i),'codes':['threshold_policy_unbound'],
                'reasons':['观察筛选、样本覆盖及复查排期可保留为研究建议；涉及业务执行的数值门槛仍待负责人确认，不代替现行政策。'],'evidence_ids':[],
                'severity':'warning','status':'proposal_visible_pending_policy_confirmation'})
            action['risk']+='；数值为研究建议，非已批准业务政策；不得据此自动改价、限售、退款或调整权限。'
        if (re.search(r'池|账龄|over14d',action.get('title','')+' '+action.get('metric',''),re.I)
                and re.search(r'占比下降|数量不降|存量减少|总量下降|数量下降|数量.{0,16}(?:净减少|减少)',action.get('metric',''))):
            ledger.append({'location':'actions/'+str(i),'codes':['pool_outcome_unbound'],
                'reasons':['单点总池或高龄占比变化不能判定处置成功；缺固定队列真实退出/再入池及新流入事件。'],
                'evidence_ids':action.get('evidence_ids',[]),'severity':'warning','status':'outcome_visible_pending_cohort_events'})
            action['risk']+='；总池变化仅作观察信号，处置成效须用固定队列退出、再入池与新流入复核。'
        for key in ('title','trigger','steps','metric','stop','risk'):
            action[key]=reviewed_text(action[key],bounds,ledger,'actions/'+str(i)+'/'+key)
        action['review_status']='proposal_not_executed_policy_and_evidence_review_required'
    if ledger:
        content['corrections']+=list(dict.fromkeys(reason for row in ledger for reason in row['reasons']))
        content['report']['status']='已成稿 · 供经营参考，局部待核'
        content['executive']['confidence_unknown']='局部未核平与研究建议已标记，不代表主判断自动失效；硬冲突仅拦相关断言。未测得整体覆盖率或90%置信度，完整原文保留。'
    content['executive']['now']=[{'title':a['title'],'text':'待确认：'+a['steps']} for a in content['actions'][:3]]
    content['evidence_constraints']=bounds
    content['quality_review']={'contract':'fc-report-review-v1','status':'not_evaluable' if any(i['status']=='not_evaluable' for i in ledger) else 'issues_withheld' if any(i.get('severity')=='error' for i in ledger) else 'warnings_visible' if ledger else 'bounded_checks_passed_not_business_approval',
        'error_count':sum(i.get('severity')=='error' for i in ledger),
        'warning_count':sum(i.get('severity')=='warning' for i in ledger),
        'issues':ledger,'original_preserved':True,'actions_executed':False,
        'scope':'完整分组核平、支付余数、聚合交集、数量/优惠定义与建议门槛；局部待核保留参考，硬冲突仅拦相关句。不是任意数字、来源或因果的全量证明，也未测得整体覆盖率或置信度。'}
    return content
