"""Select an analysis method; this adds no data or execution authority."""
PRICING_MARKER = '【竞品与定价研究】'


from traffic_contract import campaign_scope, content_match_basis, RULE_VERSION


def fc27_match_basis(value):
    return content_match_basis(value)


def fc27_name(value):return fc27_match_basis(value) is not None


def fc27_marketing_view(data):
    """User-confirmed name attribution; retain account currencies and coverage."""
    from decimal import Decimal,InvalidOperation
    def total(rows,key):
        if not rows:return None
        try:
            values=[Decimal(str((r.get('metrics') or {}).get(key))) for r in rows]
            return str(sum(values,Decimal(0))) if all(v.is_finite() for v in values) else None
        except (InvalidOperation,ValueError,TypeError):return None
    accounts=[]
    for account in data.get('ads_accounts',[]):
        campaigns=account.get('campaigns') or {};rows=campaigns.get('rows') or []
        selected=[{**r,'match_basis':fc27_match_basis(r.get('campaign_name'))} for r in rows if campaign_scope(r.get('campaign_name'))['game_target']=='FC27']
        metrics={k:total(selected,k) for k in ('cost','impressions','clicks','conversions','conversionsValue','interactions')}
        for key,numerator,denominator in (('ctr','clicks','impressions'),('cpa','cost','conversions'),('platformRoas','conversionsValue','cost')):
            a,b=metrics[numerator],metrics[denominator]
            metrics[key]=str(Decimal(a)/Decimal(b)) if a is not None and b is not None and Decimal(b) else None
        amount=total(rows,'cost');source_amount=(account.get('metrics') or {}).get('cost')
        try:reconciled=amount is not None and Decimal(amount)==Decimal(str(source_amount))
        except (InvalidOperation,ValueError,TypeError):reconciled=False
        complete=(campaigns.get('output_capped') is False and campaigns.get('rejected_rows',0)==0 and
                  ((campaigns.get('status') or {}).get('quality') or {}).get('pagination_complete') is True and reconciled)
        if complete and not selected:metrics={key:'0' if key in ('cost','impressions','clicks','conversions','conversionsValue','interactions') else None for key in metrics}
        global_rows=[r for r in rows if campaign_scope(r.get('campaign_name'))['campaign_scope']=='global_brand']
        metrics['nativeCvr']=selected[0]['metrics'].get('nativeCvr') if len(selected)==1 else None
        group_table=account.get('ad_groups') or {}
        selected_ids={r['campaign_id'] for r in selected};global_ids={r['campaign_id'] for r in global_rows}
        group_rows=group_table.get('rows') or []
        accounts.append({'global_brand_campaigns':global_rows,'fc_allocated_brand_cost':None,**account,'ad_groups':{**group_table,'rows':[r for r in group_rows if r.get('campaign_id') in selected_ids],'calculation_complete':group_table.get('calculation_complete') is True and complete},'global_brand_ad_groups':[r for r in group_rows if r.get('campaign_id') in global_ids],'metrics':metrics,'campaigns':{**campaigns,'rows':selected},'selection_complete':complete,
                         'selection_basis':'本来源完整系列汇总' if complete else '仅已返回系列小计，不能称FC项目全量'})
    search=(data.get('sources',{}).get('gsc') or {}).get('fc27_name_rows') or {}
    return {'rule':'2026-10-17修订：google-FC27-PMAX-Coins-US为主站全局品牌，优先排除FC专属费用与转化价值；不生成FC分摊ROAS。其余FC27、FC 27、FC-27、FC_27及独立Coins词条归入FC项目；投放分类与搜索词/页面内容匹配分开；保留原名和命中依据。明确其他游戏名称（如Madden、NBA2K、MLB等）的Coins系列排除；普通Coins仍归FC。明确其他FC年份不因Coins混入FC27，FC270不纳入。',
            'rule_version':RULE_VERSION,'ads_accounts':accounts,'search':search,'search_terms_status':'搜索词及页面按FC27名称筛选，保留已发布Top表范围，未返回项不推造。' if search else '当前证据未包含逐条搜索词；不能用全站搜索总量冒充FC筛选结果。'}


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
