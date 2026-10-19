import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mmoexp_google_data/details'))
from game_dimensions import classify_campaign, classify_page, project, aggregate
class Games(unittest.TestCase):
 def test_global_overrides_fc_name(self):self.assertEqual(classify_campaign('google-FC27-PMAX-Coins-US')['game'],'GLOBAL')
 def test_explicit_mapping(self):self.assertEqual(classify_campaign('A2-SN-Kinah-US')['game'],'AION2')
 def test_conflict_retained(self):self.assertEqual(classify_campaign('MG-SN-Stickers-EN-US')['game'],'UNKNOWN')
 def test_old_source_not_guessed(self):self.assertEqual(classify_campaign('google-FC27-SN-UK-Coins')['game'],'UNKNOWN')
 def test_language(self):self.assertEqual(classify_page('/fr/Fc-27/Coins.html?x=123')['game'],'FC27')
 def test_news_hint(self):self.assertEqual(classify_page('/News/aion-2-cleric-guide.html')['basis'],'news_slug_hint')
 def test_generic_coins_not_fc(self):self.assertEqual(classify_page('/Coins/Buy.html')['game'],'UNKNOWN')
 def test_missing_not_zero(self):self.assertEqual(project(None,'ga4','landingPage')['status'],'unavailable')
 def test_empty_not_missing(self):self.assertEqual(project({'rows':[],'quality':{'pagination_complete':True}},'ga4','landingPage')['status'],'available')
 def test_users_not_summed(self):self.assertNotIn('activeUsers',aggregate([{'metrics':{'sessions':2,'activeUsers':2}},{'metrics':{'sessions':3,'activeUsers':2}}],'ga4'))
 def test_weighted_position(self):
  m=aggregate([{'metrics':{'clicks':1,'impressions':10,'position':2}},{'metrics':{'clicks':2,'impressions':30,'position':6}}],'gsc');self.assertEqual(float(m['position']),5);self.assertEqual(float(m['ctr']),.075)
 def test_capped_not_complete(self):self.assertEqual(project({'rows':[],'quality':{'pagination_complete':False}},'ga4','landingPage')['status'],'partial')
 def test_joint(self):
  r={'quality':{'pagination_complete':True},'rows':[{'dimensions':{'landingPage':'/Fc-27/Coins.html','country':'US'},'metrics':{'sessions':'3'}}]}
  a=project(r,'ga4','landingPage','country')['rows'][0];self.assertEqual((a['game'],a['dimension'],a['metrics']['sessions']),('FC27','US','3'))
if __name__=='__main__':unittest.main()
