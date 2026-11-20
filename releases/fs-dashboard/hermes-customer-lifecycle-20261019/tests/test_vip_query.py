from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'user-analytics-20261022'/'source'))
from vip_query import query

NOW = datetime(2026,11,20,12,tzinfo=timezone(timedelta(hours=8)))
BASE = {'start':['2026-10-21'],'end':['2026-11-19']}
def reader():
    buyers = [dict(buyerId=str(i),history=[],lastOrder={'observedRefund':i==0,'credentials':'private'},
                   identity={'otherPrivate':'skip'},followUpStatus='due' if i<21 else 'recent')
              for i in range(23)]
    return Mock(return_value=dict(status='partial',asOfShanghai=NOW.isoformat(),coverage={'complete':False},
                                  windows={},summary={'buyers':23},buyers=buyers))
class VipQueryTest(unittest.TestCase):
    def test_projection_filter_and_reproducible_paging(self):
        source=reader()
        args={**BASE,'segment':['due'],'as_of':[NOW.isoformat()]}
        first=query(source,args,NOW)
        self.assertEqual((first['total'],len(first['items']),first['next_offset']),(21,20,20))
        self.assertNotIn('identity',first['items'][0])
        self.assertNotIn('credentials',first['items'][0]['lastOrder'])
        last=query(source,{**args,'offset':['20']},NOW)
        self.assertEqual(([row['buyerId'] for row in last['items']],last['next_offset']),(['20'],None))
        self.assertEqual(query(source,{**BASE,'segment':['refund']},NOW)['total'],1)
        self.assertEqual(last['status'],'partial')
    def test_reject_future_naive_and_unknown_filter(self):
        for extra in [{'as_of':['2030-12-01T00:00:00+08:00']},{'as_of':['2026-11-19']},{'segment':['foo']},
                      {'offset':['-1']},{'scope':['all']},{'queue_write':['true']}]:
            source=reader()
            with self.assertRaises(ValueError):query(source,{**BASE,**extra},NOW)
            source.assert_not_called()

    def test_preferred_projection_retains_latest_negative_evidence_and_leaves_default_alone(self):
        source, preferred = reader(), reader()
        buyer = preferred.return_value['buyers'][0]
        buyer.update(quality={'effectivePurchaseDays':2}, lastObservedOrder={'observedRefund':True,'credentials':'private'})
        result = query(source, {**BASE, 'scope':['global_preferred'], 'segment':['refund']}, NOW, preferred)
        source.assert_not_called()
        preferred.assert_called_once()
        self.assertEqual((result['scope'], result['total']), ('global_preferred', 1))
        self.assertEqual(result['items'][0]['quality']['effectivePurchaseDays'], 2)
        self.assertNotIn('credentials', result['items'][0]['lastObservedOrder'])
        self.assertEqual(query(source, BASE, NOW)['scope'], 'uk_us')
