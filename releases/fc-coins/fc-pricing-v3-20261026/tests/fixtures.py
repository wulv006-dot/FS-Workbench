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
        set_platform_history(value[0],NOW)
        for offers in value[0]['offers'].values():
            for offer in offers.values():offer['currency']='USD'
        for platform in ('PS','XBOX','PC'):
            value[0]['storefront']['rows'][platform]['bonus_k']='0'
            for tier in value[0]['promotion_envelope']['packages'][platform]['tiers']:
                if str(tier['base_k'])=='100':tier['bonus_k']='0'
        envelope=value[0]['promotion_envelope']
        envelope['sha256']=fingerprint({k:v for k,v in envelope.items() if k not in ('sha256','checked_at')})
    return value


def set_platform_history(data,now):
    """Synthetic each-platform cohorts; never an adapter for production pooled data."""
    from copy import deepcopy
    from decimal import Decimal
    from fc_pricing_v3.financial import HISTORY_WINDOW_CONTRACT,history_period,fingerprint
    original=data['historical_discount_mix']
    if original.get('platform_contract')=='fc27_history_platform_v1':return data
    cohorts={}
    for platform in ('PS','XBOX','PC'):
        mix=deepcopy(original)
        mix.update(platform=platform,period=history_period(now),history_window_contract=HISTORY_WINDOW_CONTRACT)
        mix['sha256']=fingerprint({k:v for k,v in mix.items() if k!='sha256'});cohorts[platform]=mix
    aggregate={key:sum(row[key] for row in cohorts.values()) for key in ('observed_orders','eligible_orders')}
    aggregate.update({key:str(sum(Decimal(row[key]) for row in cohorts.values())) for key in ('net_order_usd','actual_discount_usd','undiscounted_order_usd')})
    root=dict(status='available',period=history_period(now),history_window_contract=HISTORY_WINDOW_CONTRACT,
              platform_contract='fc27_history_platform_v1',by_platform=cohorts,aggregate=aggregate,
              source_coverage=dict(unknown_platform_orders=0,platform_identity_complete=True,
                                   by_platform_orders={p:r['eligible_orders'] for p,r in cohorts.items()}))
    root['sha256']=fingerprint(root);data['historical_discount_mix']=root
    for region in data.get('region_rules',[])+data.get('regional_controls',[]):
        history=region.get('history')
        if history and 'by_platform' not in history:
            region['history']=dict(by_platform={p:deepcopy(history) for p in region['platforms']})
    return data


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
