"""Pure scope/range pushdown plan; no network, SQL, jobs or grant creation."""
from datetime import timedelta
from date_policy import PolicyError,day,subtract
from query_contract import normalize


def plan(request,capability,dataset,budgets):
    query=normalize(request,capability,dataset)
    if query.get('cursor') is not None:
        # Host must verify signed identity/policy/watermark before a resume plan.
        raise PolicyError('cursor_requires_host_validation')
    mode=query['mode']
    budget=budgets.get(query['budget_profile'])
    if not budget or any(type(budget.get(k)) is not int or budget[k]<=0 for k in ('max_requests','max_rows','max_bytes','interactive_slices')):
        raise PolicyError('budget_not_allowed')
    if mode!='fresh':
        return dict(status='local',query=query,source='pinned_history' if mode=='frozen' else 'archive',slices=[],network_allowed=False,budget=dict(budget))
    if dataset.get('verified') is not True:
        raise PolicyError('source_requires_verification')
    start,end=day(query['start']),day(query['end_exclusive'])
    windows=[]
    if dataset['kind']=='native_summary':
        # Distinct/ratios must keep the native whole-window contract.
        windows=[(start,end)]
    elif dataset['kind']=='detail':
        span=dataset.get('source_max_slice')
        if not span:
            raise PolicyError('source_slice_unknown')
        cursor=end
        while cursor>start:
            previous=max(start,subtract(cursor,span))
            windows.append((previous,cursor)); cursor=previous
            if len(windows)>budget['max_requests']:
                raise PolicyError('budget_exhausted')
        windows.reverse()
    else:
        raise PolicyError('source_kind_not_supported')
    slices=[dict(source=dataset['source'],site_id=query['site_id'],game_id=query['game_id'],start=lo.isoformat(),end_exclusive=hi.isoformat(),fields=query['fields'],filters=query['filters'],date_semantics=dataset['date_semantics']) for lo,hi in windows]
    field_contracts={field:dict(dataset.get('field_contracts',{}).get(field,dict(required=True,nullable=False))) for field in query['fields']}
    return dict(status='queued' if len(slices)>budget['interactive_slices'] else 'planned',query=query,source=dataset['source'],slices=slices,network_allowed=True,budget=dict(budget),field_contracts=field_contracts,
                estimated_requests=None,minimum_requests=len(slices),complete=False,watermark_required=dataset['kind']=='detail')
