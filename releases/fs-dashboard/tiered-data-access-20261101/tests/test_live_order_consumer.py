import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from live_order_consumer import iter_pages

class Consumer(unittest.TestCase):
 def test_splits_range_and_follows_cursors_without_claiming_snapshot(self):
  calls=[]
  def fetch(query):
   calls.append(dict(query));cursor=query.get('cursor')
   return {'status':'partial','complete':False,'semantics':'live_non_snapshot','data':[],'next_cursor':'next' if len(calls)==1 else None,'limitation':'live_pagination_not_snapshot'}
  pages=list(iter_pages(fetch,site_id='266',game_id='1327',start='2026-10-01',end_exclusive='2026-11-01',max_pages=5))
  self.assertEqual(len(pages),3);self.assertEqual(calls[1]['cursor'],'next')
  self.assertEqual(calls[0]['end_exclusive'],'2026-10-29');self.assertEqual(calls[2]['start'],'2026-10-29')
  self.assertTrue(all(not p['complete'] for p in pages))
 def test_budget_and_repeated_cursor_stop_explicitly(self):
  def fetch(query):return {'status':'partial','complete':False,'semantics':'live_non_snapshot','data':[],'next_cursor':'same','limitation':'live_pagination_not_snapshot'}
  with self.assertRaisesRegex(ValueError,'repeated_cursor'):list(iter_pages(fetch,site_id='266',game_id='1327',start='2026-10-01',end_exclusive='2026-10-02',max_pages=5))
  with self.assertRaisesRegex(ValueError,'page_budget_exhausted'):list(iter_pages(fetch,site_id='266',game_id='1327',start='2026-10-01',end_exclusive='2026-10-02',max_pages=1))
 def test_source_limit_is_not_mistaken_for_end(self):
  def fetch(query):return {'status':'partial','complete':False,'semantics':'live_non_snapshot','data':[],'next_cursor':None,'limitation':'page_limit_reached'}
  with self.assertRaisesRegex(ValueError,'page_limit_reached'):list(iter_pages(fetch,site_id='266',game_id='1327',start='2026-10-01',end_exclusive='2026-10-02',max_pages=5))
 def test_can_resume_saved_cursor_after_budget(self):
  calls=[]
  def fetch(query):
   calls.append(dict(query));return {'status':'partial','complete':False,'semantics':'live_non_snapshot','data':[],'next_cursor':None,'limitation':'live_pagination_not_snapshot'}
  list(iter_pages(fetch,site_id='266',game_id='1327',start='2026-10-01',end_exclusive='2026-10-02',max_pages=1,resume_cursor='saved'))
  self.assertEqual(calls[0]['cursor'],'saved')
 def test_customer_filter_is_preserved_in_every_window_and_page(self):
  calls=[]
  def fetch(query):
   calls.append(dict(query));return {'status':'partial','complete':False,'semantics':'live_non_snapshot','data':[],'next_cursor':'next' if len(calls)==1 else None,'limitation':'live_pagination_not_snapshot'}
  list(iter_pages(fetch,site_id='266',game_id='1327',start='2026-10-01',end_exclusive='2026-11-01',max_pages=5,customer_email='fixture@example.test'))
  self.assertEqual(len(calls),3);self.assertTrue(all(q['customer_email']=='fixture@example.test' for q in calls))

if __name__=='__main__':unittest.main()
