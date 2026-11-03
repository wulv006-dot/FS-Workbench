"""Disjoint game-order totals; customer counts and rates cannot be added."""
from decimal import Decimal, ROUND_HALF_UP

def aggregate_components(rows):
    values=dict.fromkeys(('rev','ord','prof','new','aov','rep','ful','mar'))
    numeric=lambda v:type(v) in (int,float) and v==v and abs(v)<1e15
    for key in ('rev','ord','prof'):
        items=[r.get('values',{}).get(key) for r in rows]
        if items and all(numeric(v) for v in items):
            total=sum(Decimal(str(v)) for v in items)
            values[key]=int(total) if key=='ord' else float(total.quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
    if numeric(values['rev']) and numeric(values['ord']) and values['ord']>0:
        values['aov']=float((Decimal(str(values['rev']))/values['ord']).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
    return {'values':values,'period':rows[0]['period'],'dataScope':'all-websites-v1',
        'status':'available' if all(numeric(values[k]) for k in ('rev','ord','prof')) else 'partial' if any(numeric(v) for v in values.values()) else 'unavailable',
        'freshness':'retained' if any(r.get('freshness')=='retained' for r in rows) else 'fresh',
        'notes':{k:'GTA 5 + GTA 6 同期间全站订单统计合计；客户去重及比率不可直接相加' for k in values},
        'sources':{'components':[r.get('sources',{}) for r in rows]},'components':rows}
