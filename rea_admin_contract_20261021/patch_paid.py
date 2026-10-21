"""Prepare a narrow module patch without exporting the original production source."""
import ast


def transform(source):
    replacements = (
        ('expected=None;seen=set();previous_id=', 'expected=None;seen=set();excluded_refunded=0;previous_id='),
        ("str(row.get('pay_status'))!='1'", "str(row.get('pay_status')) not in ('1','2')"),
        ("            customer_key=hashlib.sha256", "            if str(row['pay_status'])=='2':\n                excluded_refunded+=1\n                continue\n            customer_key=hashlib.sha256"),
        ("'paid_complete':complete,'source_total':expected,'received':len(seen),",
         "'paid_complete':complete,'source_total':len(out['orders']) if complete else None,'received':len(out['orders']),\n        'source_scanned_total':expected,'source_scanned_received':len(seen),'excluded_refunded':excluded_refunded,"),
        ("'source_scope':'Admin paid orders; exact gid + main site 266; site-local UID'",
         "'source_scope':'Admin exact gid + main site 266; complete enumeration; only pay_status=1 emitted; pay_status=2 Refunded excluded; site-local UID'"),
    )
    for old, new in replacements:
        if source.count(old) != 1:
            raise RuntimeError('cohort_paid_scope_source_changed')
        source = source.replace(old, new, 1)
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'collect')
    lines = source.splitlines(keepends=True)
    old = lines[node.lineno - 1]
    if old.strip() != 'def collect(request,args):':
        raise RuntimeError('cohort_paid_source_changed')
    lines[node.lineno - 1] = old.replace('def collect(', 'def _single_month_collect(', 1)
    result = ''.join(lines) + '''

def collect(request,args):
    from monthly_paid import collect as collect_months
    return collect_months(request, checked_query(args), _single_month_collect)
'''
    compile(result, '<cohort-month-split>', 'exec')
    return result
