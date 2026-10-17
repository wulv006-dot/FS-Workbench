"""Select an analysis method; this adds no data or execution authority."""
PRICING_MARKER = '【竞品与定价研究】'


def fc27_match_basis(value):
    import re
    if not isinstance(value,str):return None
    if re.search(r'fc[\s_-]*27(?!\d)',value,re.I):return 'FC27名称'
    # shortcut: explicit game names; extend when a source introduces a verified alias.
    if re.search(r'(?<![a-z0-9])(?:madden(?:[\s_-]*nfl)?|nba[\s_-]*2k|mlb|nhl|cfb|diablo|d[234]|path[\s_-]*of[\s_-]*exile|poe|aion|wow|world[\s_-]*of[\s_-]*warcraft|osrs|runescape|eso|lost[\s_-]*ark|maplestory|albion|new[\s_-]*world|ffxiv)(?:[\s_-]*\d+)?(?![a-z0-9])',value,re.I):return None
    if not re.search(r'fc[\s_-]*\d+',value,re.I) and re.search(r'(?<![a-z0-9])coins(?![a-z0-9])',value,re.I):return 'Coins词条'
    return None


def fc27_name(value):return fc27_match_basis(value) is not None


def fc27_marketing_view(data):
    """User-confirmed name attribution; retain account currencies and coverage."""
    from decimal import Decimal,InvalidOperation
    def total(rows,key):
        try:
            values=[Decimal(str((r.get('metrics') or {}).get(key))) for r in rows]
            return str(sum(values,Decimal(0))) if all(v.is_finite() for v in values) else None
        except (InvalidOperation,ValueError,TypeError):return None
    accounts=[]
    for account in data.get('ads_accounts',[]):
        campaigns=account.get('campaigns') or {};rows=campaigns.get('rows') or []
        selected=[{**r,'match_basis':fc27_match_basis(r.get('campaign_name'))} for r in rows if fc27_name(r.get('campaign_name'))]
        metrics={k:total(selected,k) for k in ('cost','impressions','clicks','conversions','conversionsValue')}
        for key,numerator,denominator in (('ctr','clicks','impressions'),('cpa','cost','conversions'),('platformRoas','conversionsValue','cost')):
            a,b=metrics[numerator],metrics[denominator]
            metrics[key]=str(Decimal(a)/Decimal(b)) if a is not None and b is not None and Decimal(b) else None
        amount=total(rows,'cost');source_amount=(account.get('metrics') or {}).get('cost')
        try:reconciled=amount is not None and Decimal(amount)==Decimal(str(source_amount))
        except (InvalidOperation,ValueError,TypeError):reconciled=False
        complete=(campaigns.get('output_capped') is False and campaigns.get('rejected_rows',0)==0 and
                  ((campaigns.get('status') or {}).get('quality') or {}).get('pagination_complete') is True and reconciled)
        accounts.append({**account,'metrics':metrics,'campaigns':{**campaigns,'rows':selected},'selection_complete':complete,
                         'selection_basis':'本来源完整系列汇总' if complete else '仅已返回系列小计，不能称FC项目全量'})
    search=(data.get('sources',{}).get('gsc') or {}).get('fc27_name_rows') or {}
    return {'rule':'2026-10-16用户确认：FC27、FC 27、FC-27、FC_27及独立Coins词条归入FC项目；同样筛选搜索词等文本，记录命中依据。明确其他游戏名称（如Madden、NBA2K、MLB等）的Coins系列排除；普通Coins仍归FC。明确其他FC年份不因Coins混入FC27，FC270不纳入。',
            'ads_accounts':accounts,'search':search,'search_terms_status':'搜索词及页面按FC27名称筛选，保留已发布Top表范围，未返回项不推造。' if search else '当前证据未包含逐条搜索词；不能用全站搜索总量冒充FC筛选结果。'}


def track_for_question(question, mode=None):
    if not isinstance(question, str):
        raise ValueError('report_question_required')
    return 'pricing' if mode == 'pricing' or question.lstrip().startswith(PRICING_MARKER) else 'operations'


def request_report_kind(body):
    from datetime import date
    from calendar import monthrange
    if body.get('mode') in ('pricing','daily','kpi'):return body['mode']
    question=body.get('question','')
    if any(w in question for w in ('月报','月度','自然月')):return 'monthly'
    if any(w in question for w in ('周报','自然周')):return 'weekly'
    lo,hi=body.get('start'),body.get('end')
    if lo and hi:
        a,b=date.fromisoformat(lo),date.fromisoformat(hi)
        if a==b:return 'daily'
        if a.day==1 and a.year==b.year and a.month==b.month and b.day==monthrange(b.year,b.month)[1]:return 'monthly'
        if a.weekday()==0 and (b-a).days==6:return 'weekly'
    return 'investigation'


def report_title(period, kind=None, project='FC27'):
    lo,hi=period.get('start'),period.get('end')
    if not kind or kind=='operations':kind=request_report_kind(period)
    label={'daily':'日报','weekly':'周报','monthly':'月报','pricing':'定价策略研究','kpi':'经营目标分析','management':'经营管理分析','investigation':'经营分析'}.get(kind,'经营分析')
    span=(lo if lo==hi else lo+' 至 '+hi) if lo and hi else '日期未提供'
    return project+' '+span+' '+label
