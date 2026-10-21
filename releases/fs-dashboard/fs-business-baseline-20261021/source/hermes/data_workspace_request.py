"""Typed workspace-to-Hermes request; never accepts URLs or raw customer keys."""
import json
import re


def checked_request(value):
    if not isinstance(value,dict) or set(value)!={'kind','query'}:raise ValueError('workspace_request_fields')
    kind=value['kind'];args=value['query']
    if not isinstance(args,dict):raise ValueError('workspace_query')
    ident=args.get('evidence_id')
    source_args={k:v for k,v in args.items() if k!='evidence_id'}
    if kind=='cohort_observation':
        from cohort_reader import checked_query
        if args.get('action','read')!='read':raise ValueError('workspace_report_is_read_only')
        query=checked_query(args)
    elif kind=='product_orders':
        from admin_product_orders import checked_query
        query=checked_query(source_args)
    elif kind=='discount_analysis':
        from es_order_structure import checked_query
        if not isinstance(args,dict):raise ValueError('workspace_discount_fields')
        group=source_args.get('group_by','new_customer')
        if group not in ('new_customer','type','day','channel'):raise ValueError('workspace_discount_group')
        checked_query(dict(source_args,group_by='discount_'+group));query=dict(source_args,group_by=group)
    else:raise ValueError('workspace_request_kind')
    if ident is not None:
        if not isinstance(ident,str) or not re.fullmatch(r'(?:ws_|cohort_)[a-f0-9]{24}',ident):raise ValueError('workspace_evidence_id')
        query['evidence_id']=ident
    return {'kind':kind,'query':query}


def request_context(value):
    value=checked_request(value)
    return ('\n用户从FS数据专区提交的确切分析请求：'+json.dumps(value,ensure_ascii=False)+
            '\n请调用fc.query_'+value['kind']+'取冻结证据。参数日期是该来源自己的范围；cohort日期是获取窗，ES新客标记私有关联已付款且有稳定匿名客户键的子群，缺uid订单计排除覆盖，不是全站新客。7/14/30天只用成熟分母，不等于已验证首购资格/净留存/活动因果。'+
            '单品关联整单USD不是SKU收入，原币商品行分币种；优惠ES全局与游戏/主站范围分开。请自主分析并呈现，FS不代写结论。')
