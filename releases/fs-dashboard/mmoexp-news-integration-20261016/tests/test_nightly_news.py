from pathlib import Path
import sys,unittest
from datetime import datetime,timezone
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
import game_intelligence as intel
import mmoexp_news as news
class HookTests(unittest.TestCase):
 def test_existing_official_collection_runs_before_single_shared_refresh(self):
  events=[];at=datetime(2026,10,15,tzinfo=timezone.utc)
  with patch.object(intel,'SOURCES',[dict(source_id='official',url='https://official.example/news',games=['ea-sports-fc'],hosts=['official.example'])]),patch.object(intel,'fetch',side_effect=lambda *a,**k:(events.append('official') or (b'page','text/html','https://official.example/news'))),patch.object(intel,'parse',return_value=[]),patch.object(news,'refresh',side_effect=lambda *a,**k:events.append('seo') or dict(status='available',version='shared-v1',documents=[{}])) as run:
   batch=intel.collect(at,deadline_at=at)
  self.assertEqual(events,['official','seo']);self.assertEqual(run.call_count,1)
  self.assertEqual(batch['seo_news'],dict(status='available',version='shared-v1',documents=1));self.assertEqual(batch['documents'],[])
 def test_seo_status_write_failure_does_not_stop_official_batch(self):
  with patch.object(intel,'SOURCES',[]),patch.object(news,'refresh',side_effect=OSError('read only')):
   batch=intel.collect(datetime.now(timezone.utc))
  self.assertEqual(batch['seo_news']['status'],'unavailable');self.assertIn('source_status',batch)
if __name__=='__main__':unittest.main()
