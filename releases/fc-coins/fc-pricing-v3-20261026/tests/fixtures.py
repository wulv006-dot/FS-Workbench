"""Synthetic contract fixture; no live order or customer data."""
import json
from datetime import datetime
from pathlib import Path
_DATA=json.loads(Path(__file__).with_name('fixture.json').read_text(encoding='utf-8-sig'))
NOW=datetime.fromisoformat(_DATA['now'])
def fixture():
    return json.loads(json.dumps(_DATA['fixture']))
