import unittest
from test_probe_legacy import P

class OrderMemory(unittest.TestCase):
    def memory(self,**change):
        value=dict(running=True,oom_killed=False,limit=1000,rss_bytes=200,cache_bytes=700,usage_bytes=900)
        value.update(change);return value
    def test_cache_does_not_misreport_rss_pressure(self):
        value=P.add_order_memory({'issues':['rpg_pricing_partial:original']},self.memory())
        self.assertEqual(value['issues'],['rpg_pricing_partial:original'])
        self.assertEqual(value['order_memory']['rss_bytes'],200)
    def test_threshold_and_recovery_use_current_rss(self):
        for rss,high in [(699,False),(700,True),(900,True),(200,False)]:
            value=P.add_order_memory({'issues':[]},self.memory(rss_bytes=rss))
            self.assertEqual('fc_pricing_order_browser_memory_high' in value['issues'],high)
    def test_oom_and_stopped_retained_with_existing_price_failures(self):
        value=P.add_order_memory({'issues':['rpg_pricing_unknown:original']},self.memory(running=False,oom_killed=True))
        self.assertIn('rpg_pricing_unknown:original',value['issues'])
        self.assertIn('fc_pricing_order_browser_oom',value['issues'])
        self.assertIn('fc_pricing_order_browser_stopped',value['issues'])
    def test_unknown_limit_is_not_a_fake_threshold(self):
        self.assertEqual(P.add_order_memory({'issues':[]},self.memory(limit=0))['issues'],[])

if __name__=='__main__':unittest.main()
