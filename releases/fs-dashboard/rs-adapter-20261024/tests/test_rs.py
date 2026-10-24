import copy
from datetime import datetime,timezone,timedelta
from pathlib import Path
import sys
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
import rs_admin as rs
import live_summary as summary
import daily_archive as archive
import profit_daily as profit

class RSContracts(unittest.TestCase):
    def setUp(self):
        self.q=dict(rs_site='rsorders',rs_server='oldschool',rs_category='all')
        self.period=dict(start='2026-10-23 00:00',end='2026-10-24 00:00')
        self.row=dict(id=1,gid=506,site_id=320,pay_status=1,paytime='2026-10-23 01:00:00',amount_usd_format='12.34',device=0,country_code='US',paytype='paypal',site={'full_title':'www.rsorders.com'})
    def project(self,rows):return rs.detail_projection(rows,self.q,self.period,len(rows))
    def test_defaults(self):self.assertEqual(rs.selection({}),dict.fromkeys(rs.FIELDS,'all'))
    def test_invalid_values(self):
        for field in rs.FIELDS:
            with self.assertRaises(ValueError):rs.selection({field:'<script>'})
    def test_zero_category_is_items(self):self.assertEqual(rs.CATEGORIES['items'][0],0)
    def test_source_type_contracts_differ(self):self.assertEqual((rs.CATEGORIES['package'][0],rs.ORDER_TYPES['package']),(5,'4'))
    def test_guest_and_full_order_amount(self):
        values,dims,trend,cov=self.project([self.row])
        self.assertEqual((values['orders'],values['revenueUsd']),(1,12.34))
        self.assertEqual(trend[0]['amount'],12.34);self.assertEqual(dims['countries'][0]['orders'],1)
    def test_empty_not_missing(self):
        values,_,_,_=self.project([]);self.assertEqual(values['orders'],0);self.assertEqual(values['revenueUsd'],0);self.assertIsNone(values['averageOrderUsd'])
    def test_refund_not_paid(self):
        values,_,_,cov=self.project([dict(self.row,pay_status=2)])
        self.assertEqual(values['orders'],0);self.assertEqual(cov['excluded_refunded'],1)
    def test_unrecognised_payment_state_fails(self):
        with self.assertRaises(ValueError):self.project([dict(self.row,pay_status=9)])
    def test_unpriced_not_zero(self):
        with self.assertRaises(ValueError):self.project([dict(self.row,amount_usd_format=None)])
    def test_currency_uses_usd_field(self):
        values,_,_,_=self.project([dict(self.row,amount='99.99',currency='GBP')]);self.assertEqual(values['revenueUsd'],12.34)
    def test_wrong_site_or_game(self):
        for key,value in [('gid',1327),('site_id',266)]:
            with self.assertRaises(ValueError):self.project([dict(self.row,**{key:value})])
    def test_end_excluded(self):
        with self.assertRaises(ValueError):self.project([dict(self.row,paytime='2026-10-24 00:00:00')])
    def test_duplicate_projection_fails(self):
        with self.assertRaises(ValueError):self.project([self.row,self.row])
    def test_incomplete_fails(self):
        with self.assertRaises(ValueError):rs.detail_projection([self.row],self.q,self.period,2)
    def test_nonfinite_fails(self):
        for raw in ('NaN','Infinity',''):
            with self.assertRaises(ValueError):rs.number(raw)
    def test_native_trend_reconciles(self):
        value=dict(total=1,amount='12.34',chart_sales_arr=dict(date=['10.23 01:00'],n=[1],amount=['12.34']))
        self.assertEqual(rs.native_rows(value,self.period)[0]['date'],'2026-10-23 01:00')
        value['total']=2
        with self.assertRaises(ValueError):rs.native_rows(value,self.period)
    def test_no_customer_data_in_projection(self):
        out=self.project([dict(self.row,email='private@example.com',order_no='PRIVATE',uid=0)])
        self.assertNotIn('private',str(out).lower())
    def query(self,profile='RS',**filters):
        params={k:[v] for k,v in dict(mode='summary',profile=profile,start='2026-10-23',end='2026-10-23',**filters).items()}
        return summary.query(params,{'RS':1,'FC27':2},datetime(2026,10,24,8,tzinfo=timezone(timedelta(hours=8))))
    def test_rs_default_scope(self):self.assertEqual(self.query()['site'],'全部网站')
    def test_other_game_contract_unchanged(self):
        q=self.query('FC27');self.assertEqual(q['site'],'www.mmoexp.com');self.assertFalse(any(k in q for k in rs.FIELDS))
    def test_rs_fields_reject_other_games(self):
        with self.assertRaises(ValueError):self.query('FC27',rs_site='rsorders')
    def test_cache_and_archive_isolate_all_dimensions(self):
        base=self.query()
        for field,value in [('rs_site','rsorders'),('rs_server','rs3'),('rs_category','items')]:
            q=self.query(**{field:value});self.assertNotEqual(summary.key_of(base),summary.key_of(q));self.assertNotEqual(archive.summary_key(base),archive.summary_key(q))
    def test_area_scope_preserves_original_profit_contract(self):
        old={'RS':dict(sites='all-websites',gid='506',tid='',status='')}
        scope=dict(sites='all-websites',orderGameId='506',orderProductType='',orderStatus='')
        profit.check_scope('RS',scope,old)
        new=copy.deepcopy(old);new['RS']['aid']='12368'
        with self.assertRaises(ValueError):profit.check_scope('RS',scope,new)
        profit.check_scope('RS',dict(scope,orderAreaId='12368'),new)

if __name__=='__main__':unittest.main(verbosity=2)
