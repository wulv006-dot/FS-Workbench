import datetime as dt
import unittest
from mmoexp_google_data.seo import rules


class Rules(unittest.TestCase):
    def history(self):
        start=dt.date(2026,10,20)
        return [dict(source_date=(start+dt.timedelta(days=n)).isoformat(),metrics=dict(gsc=dict(clicks='100' if n<7 else '60'))) for n in range(14)]

    def test_comparable_click_decline_is_deterministic(self):
        result=rules.evaluate(self.history())
        self.assertEqual(result[0]['kind'],'click_decline')
        self.assertEqual(result[0]['change'],'-0.4')
        self.assertEqual(result[0]['previous_clicks'],'700')

    def test_missing_day_is_quality_message_not_seo_decline(self):
        rows=self.history();rows[4]['metrics']['gsc']=None
        self.assertEqual(rules.evaluate(rows)[0]['kind'],'insufficient_comparable_history')

    def test_no_invented_baseline_at_zero(self):
        rows=self.history()
        for row in rows:row['metrics']['gsc']['clicks']='0'
        self.assertEqual(rules.evaluate(rows),[])


if __name__=='__main__':unittest.main()
