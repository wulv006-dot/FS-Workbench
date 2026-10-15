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
    if 'comparison_period' in value:
        from datetime import date
        period=value['comparison_period']
        if not isinstance(period,dict) or set(period)!={'start','end'}:raise ValueError('semantic_comparison_period')
        if date.fromisoformat(period['end'])<date.fromisoformat(period['start']):raise ValueError('semantic_comparison_period')
    for name in ('findings','actions','reviews','limitations','hypotheses','context','intel','decisions','timeline'):
        rows=value.get(name,[])
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
    headings = list(re.finditer(r"(?m)^#{1,2}\s+(.+)$", text))
    return [{"heading": m[1], "text": text[m.end():headings[i+1].start() if i+1 < len(headings) else len(text)].strip(),
             "line": text.count("\n", 0, m.start())+1}
            for i, m in enumerate(headings)]


def blocks(text):
    return [plain(v) for v in re.split(r"\n\s*\n|\n(?=\s*(?:\d+[.、]|[-*])\s)", text) if v.strip() and not v.lstrip().startswith("#") and not re.fullmatch(r'\s*[-*_]{3,}\s*',v)]


def field(text, names, default):
    for name in names:
        match = re.search(r"(?m)^\s*[-*]?\s*(?:\*\*)?"+name+r"(?:\*\*)?\s*[:：]\s*(.+)", text)
        if match:
            return plain(re.split(r'[。；]\s*(?:成功|停止)\s*[=：:]',match[1],maxsplit=1)[0])
    return default


def inline_field(text, name, default):
    match=re.search(name+r'\s*[=：:]\s*([^\n；）)]+)',text)
    return plain(match[1]) if match else default


def markdown_actions(parts, evidence):
    actions = []
    for part in parts:
        title = plain(part["heading"])
        if not re.search(r"建议|行动|Actions|Recommendations", title, re.I) or re.search(r"缺口|Gap", title, re.I):
            continue
        text = part["text"]
        marks = list(re.finditer(r"(?m)^(?:#{2,4}\s*)?(?:\*\*)?([RA]\d+)(?=[（(｜|:： .])([^\n]*)", text))
        for i, mark in enumerate(marks):
            body = text[mark.end():marks[i+1].start() if i+1 < len(marks) else len(text)]
            body = re.split(r"(?m)^\*\*R\d+[–—-]R?\d+", body)[0]
            body = body.split("\n|", 1)[0]
            target = plain(mark[2]).strip("* ｜|:：")
            target = re.sub(r"^[（(].*?[）)]\s*[｜|]?\s*", "", target)
            target = re.sub(r"^对象[:：]\s*", "", target)
            target = re.sub(r'[（(]角色\s*[:：].*?[）)]\s*$','',target).strip()
            full = mark[0]+body
            actions.append({"target": target or mark[1], "action": field(body, ["最小动作", "动作", "建议动作"], plain(body)),
                            "condition": field(body, ["触发条件", "触发", "条件"], "待补：触发条件"),
                            "cost_risk": field(body, ["成本/风险", "风险", "风险提示", "投入"], "待补：成本/风险"),
                            "review_at": field(body, ["复查时间", "何时复查", "复查"], "待补：复查日期"),
                            "success_check": field(body, ["复查标准", "成功标准", "验收指标"], inline_field(body,'成功','待补：成功/失败标准')),
                            "stop_condition": field(body, ["停止条件", "停止"], inline_field(body,'停止','待补：停止条件')),
                            "role": field(body, ["责任角色", "负责人"], inline_field(full,'角色','待补：责任角色')),
                            "evidence_ids": refs(full, evidence), "source_section": title+" / "+mark[1], "original_text": full.strip()})
        headers = None
        for line in text.splitlines():
            if not line.strip().startswith("|"):
                headers = None
                continue
            cells = [plain(x) for x in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r"[:\-\s]+", x or "-") for x in cells):
                continue
            if "对象" in cells and "动作" in cells:
                headers = cells
                continue
            if not headers or len(cells) != len(headers):
                continue
            row = dict(zip(headers, cells))
            actions.append({"target": row["对象"], "action": row["动作"], "condition": row.get("触发/复查", "原文未明确"),
                            "cost_risk": row.get("风险提示", "原文未明确"), "review_at": "原文未明确复查日期",
                            "success_check": row.get("触发/复查", "原文未明确"), "stop_condition": "原文未明确停止条件，执行前补齐",
                            "role": "责任角色待确认", "evidence_ids": refs(line, evidence), "source_section": title+" / 表格", "original_text": line})
    return actions


def index(result, evidence):
    text = result.get("research_text") or result.get("raw_model_text", "")
    parts = sections(text) if not text.lstrip().startswith(("{", "```json")) else []
    findings = []
    for part in parts:
        if re.search(r"关键判断|核心结论|结论先行|主要发现|核心判断|执行摘要|Key findings|Executive summary", part["heading"], re.I):
            findings += [{"statement": value, "claim_type": "unreviewed", "evidence_ids": refs(value, evidence), "source_section": part["heading"]}
                         for value in blocks(part["text"])]
    typed=[dict(row,evidence_ids=[x for x in row.get('evidence_ids',[]) if isinstance(x,str) and x in evidence]) for row in result.get('findings',[])
           if isinstance(row,dict) and isinstance(row.get('statement'),str) and row.get('claim_type') in ('fact','hypothesis','unreviewed')]
    if (typed and result.get('report_format','').startswith('structured')) or not findings:
        findings = typed
    summary = "\n".join(row["statement"] for row in findings[:3])
    if result.get("report_format",'').startswith("structured") and result.get("summary"):
        summary = result["summary"]
    if not summary:
        candidate = result.get("summary", "")
        summary = candidate if candidate and not candidate.lstrip().startswith("#") else "未识别独立结论；完整原文保留，请先复核正文。"
    actions = [dict(row,**{key:row.get(key) or '待补：'+key for key in ACTION_FIELDS},source_section=row.get('source_section','/actions/'+str(i)))
               for i,row in enumerate(result.get('actions',[])) if isinstance(row,dict) and (row.get('action') or row.get('target'))] or markdown_actions(parts, evidence)
    hypotheses = [{"title": "竞争解释（待证）", "text": plain(line), "evidence_ids": refs(line, evidence)}
                  for part in parts for line in part["text"].splitlines() if re.search(r"竞争解释|替代解释|待证假设", line)]
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
