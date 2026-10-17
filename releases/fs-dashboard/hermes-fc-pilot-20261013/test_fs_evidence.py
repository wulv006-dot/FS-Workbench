import unittest
from fs_evidence import SourcePins

class PinTests(unittest.TestCase):
    def test_pending_can_complete_then_refresh_cannot_change_this_query(self):
        replies=[{'http_status':202,'status':'pending'},
          {'http_status':200,'status':'available','captured_at':'2026-10-13T17:00:00Z','rows':[{'revenue':'10.00'}]},
          {'http_status':200,'status':'available','captured_at':'2026-10-13T18:00:00Z','rows':[{'revenue':'999.00'}]}]
        calls=[]
        def reader(args):calls.append(dict(args));return replies[len(calls)-1]
        read=SourcePins().wrap(reader,'Order-reference');args={'start':'2026-10-05','end':'2026-10-11'}
        self.assertEqual(read(args)['status'],'pending');first=read(args);snapshot=first['source_snapshot_id']
        first['rows'][0]['revenue']='123.00'
        again=read(args);self.assertEqual(again['rows'][0]['revenue'],'10.00');self.assertEqual(again['source_snapshot_id'],snapshot);self.assertEqual(len(calls),2)
        self.assertEqual(again['captured_at'],'2026-10-13T17:00:00Z')

    def test_new_query_has_distinct_source_snapshot_and_keeps_native_asof(self):
        read=SourcePins().wrap(lambda args:{'http_status':200,'status':'available','source_records':{'primary':{'sourceDataAsOf':'2026-10-12T16:00Z','revenueUsd':1}}},'Admin-native')
        a=read({'start':'2026-10-05'});b=read({'start':'2026-09-28'})
        self.assertNotEqual(a['source_snapshot_id'],b['source_snapshot_id']);self.assertEqual(a['source_records']['primary']['sourceDataAsOf'],'2026-10-12T16:00Z')

if __name__=='__main__':unittest.main()
