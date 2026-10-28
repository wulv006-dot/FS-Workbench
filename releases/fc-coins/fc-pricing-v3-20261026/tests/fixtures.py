"""Synthetic contract fixture; no live order or customer data."""
import json
from datetime import datetime
from pathlib import Path
_DATA=json.loads(Path(__file__).with_name('fixture.json').read_text(encoding='utf-8-sig'))
NOW=datetime.fromisoformat(_DATA['now'])
def fixture(*,legacy=False):
    value=json.loads(json.dumps(_DATA['fixture']))
    if not legacy:
        from fc_pricing_v3.financial import HISTORY_WINDOW_CONTRACT,history_period,fingerprint
        mix=value[0]['historical_discount_mix'];mix['period']=history_period(NOW);mix['history_window_contract']=HISTORY_WINDOW_CONTRACT
        mix['sha256']=fingerprint({k:v for k,v in mix.items() if k!='sha256'})
    return value
