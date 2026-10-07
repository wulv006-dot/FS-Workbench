"""Create invented inputs only. Never read production snapshots/caches or secrets."""
from pathlib import Path
from datetime import date, timedelta
import ast
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'source'))
from profit_daily import normalise
from profit_reader_adapter import expected_contracts, adapt_reader

def contracts():
    tree=ast.parse((ROOT/'source/collector.py').read_text(encoding='utf-8'))
    node=next(n for n in tree.body if isinstance(n,ast.Assign)
              and any(isinstance(t,ast.Name) and t.id=='PROFILES' for t in n.targets))
    return expected_contracts(ast.literal_eval(node.value))

def source(key,day,expected,orders=80,revenue=4800.0,margin=12.5):
    c=expected[key]
    period={'start':str(day)+' 00:00','end':str(day+timedelta(days=1))+' 00:00'}
    return dict(system='order.p2pah.cn',endpoint='/stats/admin_order/index.html',
                normalisedScope='all-websites',timezone='Asia/Shanghai',currency='USD',
                period=period,filters=dict(gid=c['gid'],tid=c['tid'],status=c['status'],
                start_paytime=period['start'],end_paytime=period['end']),
                capturedAt='2021-10-06T14:21:27+00:00',status='available',orders=orders,
                revenueUsd=revenue,labelsVerified=True,
                metrics=dict(profitMarginPct=dict(value=margin,status='available',source='primary',unit='percent',field='利润率')))

def build():
    expected=contracts();today=date(2021,10,6)
    sample={'synthetic':True,'purpose':'Invented single-day adapter input, never a captured upstream response',
            'source':source('POE2',today-timedelta(days=1),expected)}
    rows=[]
    # Preserve only the coverage topology of the former 13-row regression input.
    # No historical business numeric values or capturedAt are read/copied.
    for profile,days in [('MMOEXP',range(7,0,-1)),('FC27',range(5,0,-1)),('AION2',[3])]:
        for n in days:
            day=today-timedelta(days=n)
            value=source(profile,day,expected,orders=20+n,revenue=(20+n)*15.0,
                         margin=(-4.25 if profile=='AION2' else 11.0+n/10))
            raw=adapt_reader(value,dict(profileKey=profile,date=str(day)),expected)
            rows.append(normalise(raw,expected))
    history={'synthetic':True,'purpose':'Invented 13-point coverage topology; no production seed/cache',
             'daily':sorted(rows,key=lambda r:(r['profileKey'],r['date']))}
    return {'synthetic-single-day.json':sample,'synthetic-history.json':history}

if __name__=='__main__':
    destination=ROOT/'tests/fixtures'
    for name,value in build().items():
        (destination/name).write_bytes((json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8'))
