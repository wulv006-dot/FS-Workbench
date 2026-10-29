"""Synthetic contract fixture; no live order or customer data."""
import json
from datetime import datetime,timedelta
from pathlib import Path
_DATA=json.loads(Path(__file__).with_name('fixture.json').read_text(encoding='utf-8-sig'))
NOW=datetime.fromisoformat(_DATA['now'])
def fixture(*,legacy=False):
    value=json.loads(json.dumps(_DATA['fixture']))
    if not legacy:
        set_console_cost(value[0])
        from fc_pricing_v3.financial import HISTORY_WINDOW_CONTRACT,history_period,fingerprint
        mix=value[0]['historical_discount_mix'];mix['period']=history_period(NOW);mix['history_window_contract']=HISTORY_WINDOW_CONTRACT
        mix['sha256']=fingerprint({k:v for k,v in mix.items() if k!='sha256'})
    return value


def set_console_cost(data):
    """Keep synthetic price edits consistent with the six-source production contract."""
    from fc_pricing_v3.financial import CONSOLE_COST_CONTRACT,instant
    ps=dict(data['costs']['PS'],unit='CNY/K',genre='1',delivery_type='订单发货')
    samples=[dict(ps,record_id=str(10000+i) if i else ps['record_id'],
                  trade_at=(instant(ps['trade_at'])-timedelta(minutes=i)).isoformat()) for i in range(6)]
    selected=samples[0]
    checked=instant(ps['checked_at'])
    boundary=dict(complete=True,start=(checked-timedelta(days=7)).isoformat(),end=(checked+timedelta(days=1)).isoformat())
    for platform in ('PS','XBOX'):
        data['costs'][platform]=dict(selected,platform=platform,source_platform='PS',sample_complete=True,
                                    sample_contract=CONSOLE_COST_CONTRACT,sample_records=samples,sample_boundary=boundary)
