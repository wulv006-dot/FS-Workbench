import copy
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mmoexp_google_data.seo import metrics, runtime, snapshot, store
from mmoexp_google_data.seo.contracts import GAME_IDS
from mmoexp_google_data.seo.order_source import OrderSource, CONTRACT

DAY = '2026-11-04'
NIGHT = dt.datetime(2026,11,4,19,20,tzinfo=dt.timezone.utc)


def facts(scope='FC27', day=DAY, channel='SEO', revenue='50'):
    return dict(private=True, status='available', version='same-order-facts-20261113-v1',
        input_scope=dict(start=day,end=day,site_id='266',gid=GAME_IDS[scope]),
        source_coverage=dict(admin_complete=True,admin_date_basis='paytime',source_revision='admin-r1',
            attribution=dict(source_revision='publication-r1',data_revision='3',status='available',
                effective_scope=dict(start=day,end=day,site_verified=False))),
        coverage=dict(unlinked_admin_rows=0),
        orders=[dict(site_id='266',order_no='private-order-number',gid=GAME_IDS[scope],
            paid_at=day+' 10:00:00',admin_paid_usd=revenue,channel=channel)])


def page(value):
    return next(OrderSource(lambda scope, day:value).pages('FC27',DAY))


class OrderSourceTests(unittest.TestCase):
    def config(self, tmp):
        gb=1024**3
        return dict(data_root=tmp,sources={'orders':{'enabled':True}},
            resource_policy=dict(warning_bytes=gb,operating_ceiling_bytes=2*gb,emergency_stop_bytes=3*gb,host_reserve_bytes=1024,measured_basis='fixture'),
            memory_policy={'fixture':True},temporary_reserve_bytes=4096,publication_finish_seconds=0,
            http=dict(response_emergency_bytes=1048576,connect_seconds=1,idle_seconds=1))

    def test_private_parent_projection_preserves_revision_scope_without_raw_identifiers(self):
        value=facts();original=copy.deepcopy(value)
        result=page(value);computed=metrics.compute_metrics([r['metrics'] for r in result['rows']],'orders')
        self.assertEqual(value,original)
        self.assertNotIn('private-order-number',str(result))
        self.assertEqual(computed['seo_orders'],1)
        self.assertEqual(computed['seo_revenue_usd'],'50')
        self.assertEqual(computed['revenue_basis'],'admin_paid_amount_not_net')
        self.assertEqual(result['source_timezone'],'Asia/Shanghai')
        self.assertEqual(result['quality']['source_revision'],'admin-r1')
        self.assertEqual(result['quality']['attribution_source_revision'],'publication-r1')
        self.assertEqual(result['quality']['data_revision'],'3')
        self.assertEqual(result['quality']['date_basis'],'paytime')

    def test_duplicate_parent_does_not_double_income_and_conflicts_fail(self):
        value=facts();value['orders']*=2
        result=page(value)
        self.assertEqual(len(result['rows']),1)
        self.assertEqual(metrics.compute_metrics([r['metrics'] for r in result['rows']]*2,'orders')['seo_revenue_usd'],'50')
        value['orders'][1]=dict(value['orders'][0],admin_paid_usd='51')
        with self.assertRaisesRegex(ValueError,'REVISION_CONFLICT'):page(value)

    def test_unknown_channel_and_missing_income_are_not_zero(self):
        unknown=metrics.compute_metrics([r['metrics'] for r in page(facts(channel='unknown'))['rows']],'orders')
        self.assertIsNone(unknown['seo_orders']);self.assertIsNone(unknown['seo_revenue_usd'])
        missing=metrics.compute_metrics([r['metrics'] for r in page(facts(revenue=None))['rows']],'orders')
        self.assertEqual(missing['seo_orders'],1);self.assertIsNone(missing['seo_revenue_usd'])
        self.assertEqual(missing['missing_seo_revenue_orders'],1)

    def test_scope_or_time_mismatch_and_missing_source_are_not_empty_success(self):
        for field, value in [('site_id','320'),('gid','456'),('start','2026-11-03')]:
            bad=facts();bad['input_scope'][field]=value
            with self.assertRaisesRegex(ValueError,'SCOPE_MISMATCH'):page(bad)
        bad=facts();bad['orders'][0]['paid_at']='2026-11-03 10:00:00'
        with self.assertRaisesRegex(ValueError,'MEMBER_SCOPE_MISMATCH'):page(bad)
        with self.assertRaisesRegex(ValueError,'UNAVAILABLE'):page(None)
        with self.assertRaisesRegex(ValueError,'AMOUNT_INVALID'):page(facts(revenue='invalid'))

    def test_empty_complete_retains_new_contract_and_missing_stays_none_in_snapshot(self):
        value=facts();value['orders']=[]
        with tempfile.TemporaryDirectory() as tmp:
            core=store.Store(tmp)
            with core.db() as db:
                self.assertIsNone(snapshot.daily_metrics(db,'FC27',DAY)['metrics']['orders'])
            core.ingest_page('orders','FC27',DAY,page(value),NIGHT.isoformat())
            with core.db() as db:
                result=snapshot.daily_metrics(db,'FC27',DAY)['metrics']['orders']
            self.assertEqual(result['contract'],CONTRACT)
            self.assertEqual(result['paid_orders'],0);self.assertEqual(result['seo_orders'],0)
            self.assertEqual(result['seo_revenue_usd'],'0')
        value['source_coverage']['admin_complete']=False
        with self.assertRaisesRegex(ValueError,'EMPTY_PARTIAL'):page(value)

    def test_known_subset_is_not_total_attribution_and_has_no_session_conversion(self):
        value=facts()
        value['orders'].append(dict(value['orders'][0],order_no='other',channel='unknown',admin_paid_usd='150'))
        result=metrics.compute_metrics([r['metrics'] for r in page(value)['rows']],'orders')
        self.assertEqual(result['seo_orders'],1)
        self.assertEqual(result['attribution_status'],'partial')
        self.assertEqual(result['attribution_coverage'],'0.5')
        self.assertEqual(result['attribution_amount_coverage'],'0.25')
        self.assertEqual(result['order_session_link'],'unavailable')
        self.assertEqual(result['fee_coverage'],'unknown')

    def test_legacy_order_contract_cannot_be_mixed_into_new_rows(self):
        rows=[r['metrics'] for r in page(facts())['rows']]
        rows.append(dict(order_ref='legacy',line_ref='x',paid=True,attribution='A',revenue_usd='20'))
        with self.assertRaisesRegex(ValueError,'MIXED_ORDER'):metrics.compute_metrics(rows,'orders')

    def test_runtime_registers_reader_and_snapshot_consumes_actual_order_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.config(tmp)
            calls=[]
            def read(scope,day):
                calls.append((scope,day));return facts(scope,day)
            with patch.object(runtime,'memory_admission',return_value=dict(allowed=True,state='normal',rss_bytes=1024)),\
                 patch.object(store.Store,'slices',return_value=[(DAY,0)]):
                receipt=runtime.run(config,clock=lambda:NIGHT,order_reader=read)
            self.assertEqual(receipt['status'],'published');self.assertEqual(len(calls),4)
            data=snapshot.read(Path(tmp),receipt['snapshot_id'],'history','FC27')
            row=next(r for r in data['rows'] if r['source_date']==DAY)
            self.assertEqual(row['metrics']['orders']['seo_revenue_usd'],'50')
            self.assertEqual(row['source_status']['orders']['quality']['data_revision'],'3')
            self.assertIsNone(row['estimate']['revenue_usd'])

    def test_missing_order_binding_does_not_block_gsc_or_fill_order_zero(self):
        ended_day='2026-11-03'  # GSC's Los Angeles Nov 4 is still open at NIGHT.
        class Gsc:
            name='gsc'
            timezone='America/Los_Angeles'
            def pages(self,scope,day,cursor=0):
                yield dict(rows=[dict(key=day,metrics=dict(clicks='1',impressions='10',position='3'))],
                    next_cursor=None,source_timezone=self.timezone,status='available',quality={})
        with tempfile.TemporaryDirectory() as tmp:
            config=self.config(tmp);config['sources']['gsc']={'resource':'fixture','timezone':'America/Los_Angeles'}
            with patch.object(runtime,'memory_admission',return_value=dict(allowed=True,state='normal',rss_bytes=1024)),\
                 patch.object(store.Store,'slices',return_value=[(ended_day,0)]),\
                 patch.object(runtime,'GoogleSource',return_value=Gsc()):
                receipt=runtime.run(config,clock=lambda:NIGHT)
            self.assertEqual(receipt['status'],'published');self.assertIn('orders',receipt['missing_sources'])
            data=snapshot.read(Path(tmp),receipt['snapshot_id'],'history','FC27')
            row=next(r for r in data['rows'] if r['source_date']==ended_day)
            self.assertEqual(row['metrics']['gsc']['clicks'],'1')
            self.assertIsNone(row['metrics']['orders'])


if __name__ == '__main__':
    unittest.main()
