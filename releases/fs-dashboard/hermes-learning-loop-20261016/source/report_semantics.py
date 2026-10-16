"""Index original narrative without treating extraction as business verification."""
import re
import json

CONTRACT = 'fs-report-v2'
ACTION_FIELDS = ('target','action','condition','cost_risk','review_at','success_check','stop_condition','role')


def structured(value, evidence):
    """Validate a narrative envelope, not the truth of its causal or numeric claims."""
    if not isinstance(value,dict) or value.get('report_contract')!=CONTRACT:raise ValueError('semantic_contract')
    allowed={'report_contract','summary','research_text','comparison_period','findings','actions','reviews','limitations','hypotheses','context','intel','decisions','timeline'}
    if set(value)-allowed:raise ValueError('semantic_fields')
    if set(re.findall(r'\bev_[a-f0-9]{24}\b',json.dumps(value,ensure_ascii=False)))-set(evidence):raise ValueError('semantic_unknown_evidence')
    if not isinstance(value.get('summary'),str) or not value['summary'].strip():raise ValueError('semantic_summary')
    if not isinstance(value.get('research_text',''),str):raise ValueError('semantic_research_text')
    result=dict(value);warnings=[]
    intel=result.get('intel')
    if isinstance(intel,dict) and set(intel)=={'status','reason'} and intel['status']=='not_conducted' and isinstance(intel['reason'],str):
        result['intel']=[]
        warnings.append('模型intel状态对象已恢复为未开展说明；原格式不合数组合同：'+intel['reason'])
    if 'comparison_period' in value:
        from datetime import date
        period=value['comparison_period']
        if not isinstance(period,dict) or set(period)!={'start','end'}:raise ValueError('semantic_comparison_period')
        if date.fromisoformat(period['end'])<date.fromisoformat(period['start']):raise ValueError('semantic_comparison_period')
    for name in ('findings','actions','reviews','limitations','hypotheses','context','intel','decisions','timeline'):
        rows=result.get(name,[])
        if not isinstance(rows,list):raise ValueError('semantic_list_'+name)
        result[name]=list(rows)
    for name in ('findings','actions','reviews','hypotheses','context','intel','decisions','timeline'):
        for i,row in enumerate(result[name]):
            if not isinstance(row,dict):raise ValueError('semantic_row_'+name)
            references=row.get('evidence_ids',[])
            if not isinstance(references,list) or any(not isinstance(x,str) or x not in evidence for x in references):raise ValueError('semantic_unknown_evidence')
            if any(not isinstance(v,str) for k,v in row.items() if k!='evidence_ids'):raise ValueError('semantic_text_'+name)
            if name in ('findings','actions') and not references:warnings.append(name+'/'+str(i)+' 未逐项绑定证据，待补')
            result[name][i]=dict(row,evidence_ids=references)
    if any(not isinstance(v,str) for v in result['limitations']):raise ValueError('semantic_limitations')
    if any(row.get('claim_type','unreviewed') not in ('fact','hypothesis','unreviewed') for row in result['findings']):raise ValueError('semantic_claim_type')
    result['findings']=[dict(row,statement=row.get('statement','待补：具体判断'),claim_type=row.get('claim_type','unreviewed') if row.get('evidence_ids') else 'unreviewed') for row in result['findings']]
    result['actions']=[dict(row,**{key:row.get(key) or '待补：'+key for key in ACTION_FIELDS},source_section='/actions/'+str(i)) for i,row in enumerate(result['actions'])]
    result['limitations']=result['limitations']+warnings
    return dict(result,analysis_completed=True,business_acceptance='user_review_required',actions_executed=False,
                validation='semantic_shape_and_evidence_identity_not_numeric_or_causal_approval')


def plain(text):
    return re.sub(r"\*\*|__|`", "", text).strip()


def refs(text, evidence):
    return list(dict.fromkeys(x for x in re.findall(r"\bev_[a-f0-9]{24}\b", text) if x in evidence))


def sections(text):
    headings=list(re.finditer(r'(?m)^(#{1,6})\s+(.+?)\s*#*$',text));parts=[];parents=[]
    for i,m in enumerate(headings):
        level=len(m[1])
        while parents and parents[-1][0]>=level:parents.pop()
        parts.append({'heading':m[2],'text':text[m.end():headings[i+1].start() if i+1<len(headings) else len(text)].strip(),
                      'line':text.count('\n',0,m.start())+1,'level':level,'parents':[v[1] for v in parents]})
        parents.append((level,m[2]))
    return parts


def declared_comparison(result):
    """Read declared intent; ambiguous declarations must not select another window."""
    from datetime import date
    period=result['period'];start=date.fromisoformat(period['start'])
    explicit=result.get('comparison_period')
    if explicit is None:
        from report_constraints import native_envelope
        recovered=native_envelope(result.get('raw_model_text') or result.get('research_text',''))
        if recovered:explicit=recovered.get('comparison_period')
    if explicit is None and any(k in period for k in ('comparison_start','comparison_end')):
        explicit={'start':period.get('comparison_start'),'end':period.get('comparison_end')}
    if explicit is not None:
        try:
            a,b=(date.fromisoformat(explicit[k]) for k in ('start','end'))
            if b<a or b>=start:raise ValueError('invalid_comparison_period')
        except (KeyError,TypeError,ValueError):raise ValueError('invalid_comparison_period') from None
        return (a.isoformat(),b.isoformat()),'结构化报告明确声明的对照区间',False
    text=result.get('research_text') or result.get('raw_model_text','')
    pairs=[];primary=[];invalid=False
    token=r'(\d{4}-\d{2}-\d{2}|\d{2}-\d{2})'
    label=r'(?:主对照|主要对照|主比较|对比|环比|对照)(?:期|窗(?:口)?)?'
    preamble=text.split('\n## ',1)[0]
    declarations=re.findall(r'(?:主对照|主要对照|主比较)(?:期|窗(?:口)?)?\s*(?:为|[:：])\s*[^。；;\n]+',plain(preamble))
    for line in text.splitlines()+[d.replace('为','：',1) for d in declarations]:
        stripped=plain(line).lstrip('#-*+ ').strip()
        if not re.match(label+r'\s*[:：]',stripped):continue
        head=re.split(r'[；;]|(?:辅助|同星期|上周同日)(?:对照|比较)?',stripped,maxsplit=1)[0]
        m=re.search(label+r'[^\d\n]{0,24}?'+token+r'(?:\s*(?:～|~|—|–|至|到)\s*'+token+r')?',head)
        if not m:invalid=True;continue
        try:
            values=[]
            for value in (m[1],m[2] or m[1]):
                year=start.year-(len(value)==5 and start.month<=2 and int(value[:2])>=11)
                values.append(date.fromisoformat(value if len(value)==10 else str(year)+'-'+value))
            a,b=values
            if b<a or b>=start:raise ValueError('invalid_comparison_period')
            pair=(a.isoformat(),b.isoformat());pairs.append(pair)
            if re.match(r'(?:主对照|主要对照|主比较)',head) or re.search(r'主对照|主比较',head):primary.append(pair)
        except ValueError:invalid=True
    chosen=set(primary or pairs)
    if invalid or len(chosen)>1:return None,'原文对照声明冲突或日期不完整；仅暂停该比较',True
    if chosen:return next(iter(chosen)),'原文明确声明的主对照区间；声明不是经营证据',False
    return None,'日报/周报同星期、月报上月、其他调查前一个等长窗的默认规则',False


def blocks(text):
    values=[plain(v) for v in re.split(r"\n\s*\n|\n(?=\s*(?:\d+[.、]|[-*])\s)", text) if v.strip() and not v.lstrip().startswith("#") and not re.fullmatch(r'\s*[-*_]{3,}\s*',v)]
    return [v for v in values if not v.lstrip().startswith('|') and not re.fullmatch(r'[^。\n]{1,30}[:：]',v)]


def field(text, names, default):
    for name in names:
        match = re.search(r"(?m)^\s*[-*]?\s*(?:\*\*)?"+name+r"(?:\*\*)?\s*[:：]\s*(.+)", text)
        if match:
            return plain(re.split(r'[。；]\s*(?:成功|停止)\s*[=：:]',match[1],maxsplit=1)[0])
    return default


def inline_field(text, name, default):
    match=re.search(name+r'\s*[=：:]\s*([^\n；）)]+)',text)
    return plain(match[1]) if match else default


def article_introduction(document, result):
    """A shared evidence ID binds a bundle, never an individual article summary."""
    title=plain(str(document.get('title',''))).replace('™','')
    subject=re.split(r'\s+[|—-]\s+',title)[-1].strip()
    version=re.search(r'\bv\d+(?:\.\d+)+',subject,re.I)
    candidates=[]
    for part in sections(result.get('research_text','')):
        context=' / '.join([*part.get('parents',[]),part['heading']])
        if not re.search('官方|新闻|内容|版本|情报',context) or re.search(r'建议|行动|复查|\b[RA]\d+\b',context):continue
        headers=None
        for line in part['text'].splitlines():
            if line.strip().startswith('|'):
                cells=[plain(c) for c in line.strip().strip('|').split('|')]
                if all(re.fullmatch(r'[:\-\s]+',c or '-') for c in cells):continue
                if any(c in ('事件','文章','文章标题','标题') for c in cells):headers=cells;continue
                if not headers or len(cells)!=len(headers):continue
                title_col=next(i for i,c in enumerate(headers) if c in ('事件','文章','文章标题','标题'))
                intro_col=next((i for i,c in enumerate(headers) if c in ('内容简介','活动简介','情报简介','简介','内容要点','已核实内容')),None)
                if ' / ' in cells[title_col]:continue
                value=cells[title_col]+'：'+(cells[intro_col] if intro_col is not None else '；'.join(c for i,c in enumerate(cells) if i!=title_col))
            else:
                headers=None
                if not re.match(r'^\s*[-*]\s+',line):continue
                value=plain(re.sub(r'^\s*[-*]\s+','',line))
            if re.search('最小动作|触发条件|复查时间|责任角色|投入/风险|停止条件|需求假设|建议',value):continue
            # A version mentioned alongside another release cannot identify its contents.
            if version:
                versions=set(re.findall(r'\bv\d+(?:\.\d+)+',value,re.I))
                matched=versions=={version[0]}
            else:matched=bool(subject and subject.casefold() in value.replace('™','').casefold())
            if matched and len(re.findall(r'[\u4e00-\u9fff]',value))>=8:candidates.append(value)
    if len(candidates)==1:
        value=re.sub(r'\s*\bev_[a-f0-9]{24}\b','',candidates[0])
        return value[:420]+('…' if len(value)>420 else ''),'原报告逐篇简介；未作新增研究'
    text=re.sub(r'\s+',' ',str(document.get('text',''))).strip()
    header=re.search(r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}\b',text[:400])
    if header:text=text[header.end():].strip()
    sentences=re.split(r'(?<=[.!?。！？])\s+',text)
    excerpt=' '.join(sentences[:2])[:420]
    if len(excerpt)<len(' '.join(sentences[:2])):excerpt=excerpt.rsplit(' ',1)[0]+'…'
    return '该篇中文内容简介尚未生成，请展开来源核对原文。','中文简介待补；不以英文或行动计划代替'


def intelligence(result,evidence):
    """Keep actual source-backed intel; isolate unverified model assertions visibly."""
    from datetime import date,datetime
    from urllib.parse import urlsplit
    def strings(value):
        if isinstance(value,str):return {value}
        if isinstance(value,dict):return set().union(*(strings(v) for v in value.values())) if value else set()
        if isinstance(value,list):return set().union(*(strings(v) for v in value)) if value else set()
        return set()
    accepted=[];pending=[]
    for row in result.get('intel',[]):
        if not isinstance(row,dict):continue
        ids=[i for i in row.get('evidence_ids',[]) if i in evidence]
        facts=set().union(*(strings(evidence[i]) for i in ids)) if ids else set()
        url=row.get('url','');stamp=row.get('retrieved_at','')
        document_sources=[evidence[key].get('data',{}) for key in ids
                          if isinstance(evidence[key].get('data'),dict) and 'documents' in evidence[key]['data']]
        documents=[document for data in document_sources for document in data.get('documents',[])
                   if isinstance(document,dict)]
        document=None
        try:
            parsed=urlsplit(url);at=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            times=[]
            for value in facts:
                if len(value)<=40 and re.match(r'^\d{4}-\d{2}-\d{2}T',value):
                    try:times.append(datetime.fromisoformat(value.replace('Z','+00:00')))
                    except ValueError:pass
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or at.tzinfo is None or url not in facts or at not in times:raise ValueError('unbound_source_time')
            if document_sources:
                for candidate in documents:
                    if candidate.get('source_url')!=url:continue
                    try:observed=datetime.fromisoformat(candidate.get('observed_at','').replace('Z','+00:00'))
                    except (ValueError,TypeError,AttributeError):continue
                    if observed.tzinfo is not None and observed==at:
                        document=candidate;break
                if document is None:raise ValueError('unbound_document_observation')
        except (ValueError,TypeError,AttributeError):
            pending.append({'title':str(row.get('title','情报条目')),'fact':str(row.get('fact','')),'reason':'缺可核验来源/读取时间或未逐项绑定实际证据，待补','evidence_ids':ids});continue
        item={k:str(row.get(k) or '待补') for k in ('title','fact','hypothesis','action','source','published_at','event_at','applies')}
        if document is not None:
            item['published_at']=str(document.get('published_at') or '未知（官方未提供）')
            if len(re.findall(r'[\u4e00-\u9fff]',item['fact']))<4 or re.search('最小动作|触发条件|复查时间|责任角色|停止条件',item['fact']):
                item['fact'],item['introduction_basis']=article_introduction(document,result)
            item['source_preview']=re.sub(r'\s+',' ',str(document.get('text','')))[:420]
        item.update(url=url,retrieved_at=stamp,evidence_ids=ids,window='事件时间与适用性待复核')
        # Publication time and event time have different meanings. Never date an
        # event from a later retrospective publication.
        event=row.get('event_at','')
        if event and event in facts:
            try:
                day=date.fromisoformat(event[:10]);end=date.fromisoformat(result['period']['end'])
                item['window']='期后事件：仅作未来观察' if day>end else '事件日期不晚于报告期末；适用性待复核'
            except ValueError:pass
        accepted.append(item)
    # Older reports keep the analysis in Markdown; official tool documents still
    # provide a source-bound card without inventing an event or market effect.
    known={item['url'] for item in accepted}
    for eid,value in (evidence.items() if not result.get('intel') else []):
        data=value.get('data',{})
        if not isinstance(data,dict):continue
        for document in data.get('documents',[]):
            if not isinstance(document,dict):continue
            url=document.get('source_url','');stamp=document.get('observed_at','');text=document.get('text','')
            try:
                parsed=urlsplit(url);observed=datetime.fromisoformat(stamp.replace('Z','+00:00'))
                if (url in known or parsed.scheme!='https' or parsed.hostname!='www.ea.com' or parsed.username or parsed.password
                        or '/fc-27/news/' not in parsed.path or observed.tzinfo is None or not isinstance(text,str) or not text.strip()):continue
            except (ValueError,TypeError,AttributeError):continue
            title=str(document.get('title') or parsed.path.rstrip('/').rsplit('/',1)[-1])
            excerpt=re.sub(r'\s+',' ',text).strip()
            if len(excerpt)>320:
                short=excerpt[:320];bound=max(short.rfind('。'),short.rfind('. '),short.rfind('！'),short.rfind('？'))
                excerpt=short[:bound+1] if bound>100 else short+'…'
            published=str(document.get('published_at') or '未知（官方未提供）')
            window='官方消息 · 日期待补'
            try:
                day=date.fromisoformat(published[:10]);start=date.fromisoformat(result['period']['start']);end=date.fromisoformat(result['period']['end'])
                window='报告期内发布' if start<=day<=end else '期后发布 · 未来观察' if day>end else '期前发布 · 背景资料'
            except (ValueError,TypeError,KeyError):pass
            topic=title+' '+text[:2000]
            relevance='可与本报告的平台、商品与履约变化对照；文章本身不能证明我方需求或价格变化。'
            action='建议先核对正文中的活动资格、更新时间和现有商品关联，再由负责人决定是否准备内容或排查。'
            if re.search(r'title update|patch|service unavailable|matchmaking|connectivity',topic,re.I):
                relevance='游戏端可用性线索可与平台、发生时段及客户报错记录对照；不能认定我方商城支付或履约故障。'
                action='建议只读核对已有客户反馈与订单事件；出现相同平台、时段和错误再交负责人排查，未对应不作根因判断。'
            elif re.search(r'\bSBC\b|squad building|evolution|future stars|playstyle|ultimate team',topic,re.I):
                relevance='活动资格与阵容内容可用于筛选 Coins / Items 的内容选题；活动对我方咨询、成交与客单的影响仍需验证。'
                action='建议按官方资格核对现有商品，先准备内容草案并记录相关咨询、点击和成交；真实发布或投放由负责人确认。'
            introduction,introduction_basis=article_introduction(document,result)
            accepted.append(dict(title=title,fact=introduction,introduction_basis=introduction_basis,source_preview=excerpt,hypothesis=relevance,action=action,
                                 source='EA 官方 · 已读取正文',published_at=published,event_at='未单独核验，不以发布日期代替',
                                 applies='按官方正文范围；具体业务窗口待确认',url=url,retrieved_at=stamp,evidence_ids=[eid],window=window,
                                 extraction='官方工具正文摘录；业务联系为建议核对方向'))
            known.add(url)
    read_urls={d['source_url'] for value in evidence.values() if isinstance(value.get('data'),dict)
               for d in value['data'].get('documents',[])
               if isinstance(d,dict) and d.get('source_url') and d.get('observed_at')}
    if accepted:note='已整理 '+str(len(accepted))+' 条官方消息，具体影响作为经营判断参考。'
    elif read_urls:note='本次已实际读取 '+str(len(read_urls))+' 篇官方文章；具体内容与经营判断见报告正文，尚未单独整理成消息卡片。'
    else:note='本次尚未取得官方消息，原因见数据说明；这不表示游戏没有活动。'
    if pending:note+=' 另有 '+str(len(pending))+' 条原报告情报待补证，保留如下，不能当作已核实事实。'
    return accepted,pending,note


def resource_cost(item):
    if item.get('cost'):return item['cost']
    match=re.search(r'(?:约\s*)?\d+(?:\.\d+)?(?:[~～–—-]\d+(?:\.\d+)?)?\s*人日',item.get('cost_risk',''))
    if match:return match[0]
    match=re.search(r'(?:人工|抽样|核查|采集|投入)[^。；]{0,40}',item.get('cost_risk',''))
    return match[0]+'（原建议估计，待确认）' if match else '待补：原文未单列资源投入'


def markdown_actions(parts, evidence):
    actions=[]
    area=re.compile(r'建议|行动|Actions|Recommendations',re.I)
    def proposed(value):
        value=plain(value)
        if not value.startswith('建议') and re.search(r'^(?:核查|核对|复核|验证|检查|抽查|调查)(?:结果|发现|显示)|后(?:发现|显示|确认|未发现)|已经完成',value):return False
        return bool(re.match(r'^(?:建议\s*[:：]?\s*)?(?:核查|核对|复核|验证|补充|读取|检查|抽查|跟踪|建立|记录|比对|确认|调查|收集|对.+进行)',value))
    def emit(target,body,full,location,explicit=None):
        action=explicit or field(body,['最小动作','动作','建议动作'],None)
        if not action:return
        target=re.sub(r'^[RA]\d+[\s｜|:：.]*','',plain(target)).strip('* ｜|:：')
        target=re.sub(r'^[（(].*?[）)]\s*[｜|]?\s*','',target)
        target=re.sub(r'^对象[:：]\s*','',target)
        target=re.sub(r'[（(]角色\s*[:：].*?[）)]\s*$','',target).strip()
        actions.append({'target':field(body,['对象'],target or '待补：对象'),'action':action,
            'condition':field(body,['触发条件','触发','条件'],'待补：触发条件'),
            'cost_risk':field(body,['成本/风险','投入/风险','风险','风险提示','投入'],'待补：成本/风险'),
            'review_at':field(body,['复查时间','何时复查','复查'],'待补：复查日期'),
            'first_check':field(body,['首查时间','首查','执行窗口'],''),'priority':field(body,['优先级'],''),
            'success_check':field(body,['复查标准','成功标准','验收指标'],inline_field(body,'成功','待补：成功/失败标准')),
            'stop_condition':field(body,['停止条件','停止'],inline_field(body,'停止','待补：停止条件')),
            'role':field(body,['责任角色','负责人'],inline_field(full,'角色','待补：责任角色')),
            'evidence_ids':refs(full,evidence),'source_section':location,'original_text':full.strip()})
    for part in parts:
        title=plain(part['heading']);context=' / '.join([*part.get('parents',[]),title]);text=part['text']
        if not (area.search(context) or re.match(r'^[RA]\d+\b',title)) or re.search(r'缺口|Gap',title,re.I):continue
        location=context+' / 行'+str(part['line'])
        marks=list(re.finditer(r'(?m)^(?:\*\*)?([RA]\d+)(?=[（(｜|:： .])([^\n]*)',text))
        for i,mark in enumerate(marks):
            body=text[mark.end():marks[i+1].start() if i+1<len(marks) else len(text)]
            body=re.split(r'(?m)^\*\*[RA]\d+[–—-][RA]?\d+',body)[0].split('\n|',1)[0]
            emit(mark[2],body,mark[0]+body,location+' / '+mark[1],field(body,['最小动作','动作','建议动作'],plain(body) or None))
        headers=None;table=False
        for line in text.splitlines():
            if not line.strip().startswith('|'):headers=None;continue
            cells=[plain(x) for x in line.strip().strip('|').split('|')]
            if all(re.fullmatch(r'[:\-\s]+',x or '-') for x in cells):continue
            if '对象' in cells and '动作' in cells:headers=cells;continue
            if not headers or len(cells)!=len(headers):continue
            row=dict(zip(headers,cells));table=True
            body='\n'.join(k+'：'+v for k,v in {'对象':row['对象'],'动作':row['动作'],
                '条件':row.get('触发/复查','待补：触发条件'),'风险':row.get('风险提示','待补：成本/风险'),
                '成功标准':row.get('触发/复查','待补：成功/失败标准')}.items())
            emit(row['对象'],body,line,location+' / 表格')
        if marks or table:continue
        direct=field(text,['最小动作','动作','建议动作'],None)
        if direct:emit(title,text,title+'\n'+text,location,direct);continue
        heading=re.sub(r'^(?:[RA]\d+|\d+[.、])\s*','',title)
        heading=re.sub(r'^(?:建议|行动)\s*[:：]\s*','',heading)
        if proposed(heading):emit(title,text,title+'\n'+text,location,heading);continue
        # Only imperative list items or paragraphs in an explicitly labelled
        # action section are proposals. Descriptive observations stay narrative.
        items=[m for m in re.finditer(r'(?m)^\s*(?:[-*]|\d+[.、])\s+([^\n]+)',text) if proposed(m[1])]
        for i,m in enumerate(items):
            body=text[m.end():items[i+1].start() if i+1<len(items) else len(text)]
            emit(m[1],body,m[0]+body,location,plain(m[1]))
        if not items:
            for block in re.split(r'\n\s*\n',text):
                if proposed(block):emit(title,block,block,location,plain(block))
    return actions


def index(result, evidence):
    from report_constraints import narrative,native_envelope
    if not result.get('report_format','').startswith('structured'):
        recovered=native_envelope(result.get('raw_model_text') or result.get('research_text',''))
        if recovered:
            try:value=structured(recovered,evidence)
            except (ValueError,TypeError):pass
            else:result=dict(result,**value,report_format='structured_v2_recovered')
    text = narrative(result.get("research_text") or result.get("raw_model_text", ""))
    parts = sections(text) if not text.lstrip().startswith(("{", "```json")) else []
    findings = []
    for part in parts:
        if re.search(r"关键判断|核心结论|结论先行|主要发现|核心判断|执行摘要|Key findings|Executive summary", ' / '.join([*part.get('parents',[]),part['heading']]), re.I):
            findings += [{"statement": value, "claim_type": "unreviewed", "evidence_ids": refs(value, evidence), "source_section": part["heading"]}
                         for value in blocks(part["text"])]
    typed=[dict(row,evidence_ids=[x for x in row.get('evidence_ids',[]) if isinstance(x,str) and x in evidence]) for row in result.get('findings',[])
           if isinstance(row,dict) and isinstance(row.get('statement'),str) and row.get('claim_type') in ('fact','hypothesis','unreviewed')]
    if (typed and result.get('report_format','').startswith('structured')) or not findings:
        findings = typed
    summary = "\n".join(row["statement"] for row in findings[:3])
    if isinstance(result.get('summary'),str) and result['summary'].strip() and not re.search(r'(?m)^\s*[#|`]|\|\s*-{3}',result['summary']):
        summary = result["summary"]
    if not summary:
        candidate = result.get("summary", "")
        summary = candidate if candidate and not candidate.lstrip().startswith("#") else "未识别独立结论；完整原文保留，请先复核正文。"
    actions = [dict(row,**{key:row.get(key) or '待补：'+key for key in ACTION_FIELDS},source_section=row.get('source_section','/actions/'+str(i)))
               for i,row in enumerate(result.get('actions',[])) if isinstance(row,dict) and (row.get('action') or row.get('target'))] or markdown_actions(parts, evidence)
    hypotheses=[]
    for part in parts:
        if re.search(r'方法|Method',part['heading'],re.I):continue
        active=bool(re.search(r'竞争解释|替代解释|待证假设',part['heading']))
        for block in re.split(r'\n\s*\n',part['text']):
            value=plain(block)
            if re.match(r'^(?:竞争解释|替代解释|待证假设)',value):active=True;continue
            if re.match(r'^(?:可推翻|建议|缺口|复查)',value):active=False
            if active and value:hypotheses.append({'title':'竞争解释（待证）','text':value,'evidence_ids':refs(value,evidence)})
    hypotheses += [{"title": "竞争解释（待证）", "text": row["statement"]+"；替代解释："+row.get("alternative", "未给出"),
                    "evidence_ids": [x for x in row.get("evidence_ids", []) if x in evidence]}
                   for row in typed if row.get("claim_type") == "hypothesis"]
    hypotheses += [dict(row) for row in result.get('hypotheses',[]) if isinstance(row,dict) and isinstance(row.get('title'),str) and isinstance(row.get('text'),str)]
    return {"contract": "fs-report-semantic-index-v2", "summary": summary, "findings": findings, "actions": actions,
            "hypotheses": hypotheses, "source_format": result.get("report_format", "markdown"),
            "status": "extracted_not_business_verified", "sections": parts, "research_text":text}


def review_action(item):
    """Keep the original in the index; correct unsafe causal/operating suggestions visibly."""
    row = dict(item)
    notes = []
    condition = row.get("condition", "")
    if re.search(r"恢复.*(?:判定|证明).*(?:基数|正常化)", condition):
        row["condition"] = "按原建议双基线观察；恢复或下降阈值仅是待确认监控条件，不能据此判定基数效应或正常化。"
        notes.append("撤回恢复阈值可证明原因的推断")
    if re.search(r"两周.*(?:数量不降|不降)", condition):
        row["condition"] = "跟踪固定观察队列的真实完成、取消、退款与重新入池，同时单列新流入；总老龄池未降不能独立判定处理失败。"
        row["success_check"] = "固定队列闭环结果与处理成本；总池/新增流入/退出分别列示，保留未完成订单。"
        notes.append("以固定队列复查替代总池不降判失败")
    if "库存" in row.get("action", ""):
        row["action"] = row["action"].replace("页面/库存可用性检查", "页面可用性及供应商接单/履约能力核查").replace("库存", "供应商履约能力") + "（订单驱动，无持货库存）。"
        notes.append("按订单驱动、无持货库存模型校正调查对象")
    if re.search(r"与\s*PC\s*对照", row.get("action", "")):
        row["action"] += "；PC 仅作描述性差异参考，尚不具备因果控制组条件。"
    if re.search(r'阈值|[<>±]|高于|低于|收窄至',row.get('original_text','')+' '+condition):
        notes.append('原文阈值为未校准建议；先确认依据、代价及复查窗口，达到阈值不能单独证明原因。')
    row["review_notes"] = notes
    return row

