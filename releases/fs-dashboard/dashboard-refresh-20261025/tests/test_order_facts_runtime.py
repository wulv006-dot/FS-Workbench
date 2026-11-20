"""Read-only source and HTTP dispatch seams, with synthetic source records."""
import ast
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'source'),str(ROOT.parent/'cache-archive-retention-20261025/source')]
from order_facts_runtime import admin_orders, collect_live_diagnostic, publication, existing_costs

SCOPE=dict(start='2026-11-10',end='2026-11-10',site_id='266',gid='1327')
def row(i=2,site=266,**kw):
    return dict(id=i,site_id=site,site={'full_title':'www.mmoexp.com' if site==266 else 'www.rsorders.com'},
        order_no='O'+str(i),paytime='2026-11-10 10:00:00',pay_status='1',gid=1327,
        amount_usd_format='50',amount_rmb_format='350',status_format='已完成',**kw)
def response(rows,total=None):
    return 200,json.dumps({'code':1,'data':{'list':rows,'total':len(rows) if total is None else total}}).encode()

class Runtime(unittest.TestCase):
    def test_shared_period_reads_once_and_preserves_distinct_game_facts(self):
        d4 = row(1);d4['gid'] = 456
        request = Mock(return_value=response([row(), d4]))
        with tempfile.TemporaryDirectory() as root:
            values = collect_live_diagnostic([SCOPE, dict(SCOPE,gid='456')], request=request,
                db=Path(root)/'absent.db', costs=Path(root)/'absent.json', dataset_reader=Mock())
        request.assert_called_once()
        self.assertEqual([v['totals']['orders'] for v in values], [1,1])
        self.assertEqual([v['orders'][0]['gid'] for v in values], ['1327','456'])
        self.assertEqual(values[0]['source_coverage']['source_revision'],values[1]['source_coverage']['source_revision'])
        self.assertEqual(values[0]['coverage']['unlinked_cost_records'],0)

    def test_batch_rejects_mixed_dates_before_read(self):
        request = Mock()
        with self.assertRaisesRegex(ValueError,'batch_period'):
            collect_live_diagnostic([SCOPE,dict(SCOPE,end='2026-11-11')],request=request)
        request.assert_not_called()

    def test_all_site_pagination_keeps_identity_catalog(self):
        request=Mock(side_effect=[response([row()],2),response([row(1,320)],2)])
        result=admin_orders(SCOPE,request)
        self.assertEqual(len(result),2)
        self.assertNotIn('email',result[0])
        qs=parse_qs(urlsplit(request.call_args_list[0].args[0]).query)
        self.assertEqual(qs['search[0][field]'],['pay_status'])
        self.assertEqual(qs['search[0][val]'],['1'])
        self.assertEqual(qs['search[1][field]'],['paytime'])
        self.assertEqual(qs['search[1][val]'],['2026-11-10 00:00:00,2026-11-10 23:59:59'])
        self.assertNotIn('site_id',qs)
    def test_pagination_scope_conflicts_and_denial_fail(self):
        bad=row();bad['paytime']='2026-11-11 00:00:00'
        for replies in ([response([bad])],[response([row()],2),response([row()],2)],
                        [response([row()],2),response([row(1)],3)],[(403,b'{}')]):
            with self.subTest(replies=len(replies)),self.assertRaises((ValueError,PermissionError)):
                admin_orders(SCOPE,Mock(side_effect=replies))
    def test_database_read_does_not_initialize_or_write(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/'existing.db'
            self.assertIsNone(publication(db));self.assertFalse(db.exists())
            with closing(sqlite3.connect(db)) as connection:
                connection.execute('CREATE TABLE meta(key TEXT,value TEXT)')
                connection.execute('INSERT INTO meta VALUES (?,?)',('weekly_publication',json.dumps({'cutoff':'x'})))
                connection.commit()
            before=db.read_bytes()
            self.assertEqual(publication(db),{'cutoff':'x'})
            self.assertEqual(db.read_bytes(),before)
    def test_cost_cache_retains_observed_only(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'cost.json'
            self.assertEqual(existing_costs(p)[0],[])
            p.write_text(json.dumps(dict(contract='channel-order-deliveries-v1',complete=True,rows=[],period={})))
            _,proof=existing_costs(p)
            self.assertTrue(proof['shipment_window_complete']);self.assertFalse(proof['order_cost_complete'])
    def test_collect_filters_local_membership_and_keeps_cost_missing(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/'absent.db';cost=Path(root)/'cost.json'
            cost.write_text(json.dumps(dict(contract='channel-order-deliveries-v1',complete=True,rows=[
                dict(source='www.mmoexp.com',sn='O2',delivery_id='D',genre=1,cost_total='100'),
                dict(source='www.rsorders.com',sn='O1',delivery_id='D-other',genre=1,cost_total='500') ])))
            reader=Mock()
            [data]=collect_live_diagnostic([SCOPE],request=Mock(return_value=response([row(),row(1,320)])),
                db=db,costs=cost,dataset_reader=reader)
            self.assertEqual(data['totals']['orders'],1)
            self.assertEqual(data['totals']['observed_cost_cny'],'100')
            self.assertEqual(data['totals']['missing_cost_orders'],1)
            self.assertEqual(data['totals']['unknown_channel_orders'],1)
            self.assertEqual(data['coverage']['unlinked_cost_records'],0)
            reader.assert_not_called()
    def test_dashboard_uses_same_order_pmax_and_coupon_without_new_admin_request(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root); (root/'days').mkdir()
            day=SCOPE['start']; cache=root/'days'/f'{day}.json'
            record=dict(orderNo='O2',gid='1327',paidAt=day+' 10:00:00',day=day,
                sourceStatus='available',sourceRaw='google-FC27-PMAX-Coins-US',
                code='Known',project='谷歌广告',conflict=False,promoterUid='42',coupons=[dict(title='Launch')])
            cache.write_text(json.dumps(dict(contract='channel-day-v1',period=dict(start=day,end=day),
                sources=dict(orders=dict(status='complete',site='MMOEXP'),coupons=dict(status='complete')),
                orders=[record])))
            request=Mock(return_value=response([row(discount_code='Known'),row(1,320)]))
            settings=dict(request=request,db=root/'absent.db',costs=root/'absent.json',dataset_reader=Mock())
            [result]=collect_live_diagnostic([dict(SCOPE,site_id='all')],channel_archive=root,**settings)
            request.assert_called_once()
            main, other=result['orders']
            self.assertEqual(main['channel'],'unknown')
            self.assertEqual(main['effective_attribution']['channel'],'PPC')
            self.assertEqual(main['effective_attribution']['basis'],'order_source')
            self.assertTrue(main['effective_attribution']['coupon'])
            self.assertEqual(main['effective_attribution']['coupon_templates'],['Launch'])
            self.assertIsNone(other['effective_attribution']['coupon'])
            self.assertEqual(other['effective_attribution']['channel'],'unknown')
            [shared]=collect_live_diagnostic([SCOPE],**settings)
            self.assertNotIn('effective_attribution',shared['orders'][0])
            self.assertEqual(result['source_coverage']['source_revision'],shared['source_coverage']['source_revision'])

    def test_priority_keeps_native_then_exact_order_source_then_mapped_promotion(self):
        from channel_effects import Attribution
        from order_facts_runtime import effective_attribution
        mapping=Attribution({'entries':[dict(code='known',channel='KOL'),dict(code='seo',channel='SEO')]},[],{})
        base=dict(site_id='266',gid='1327',pay_status='1',status='已完成',order_no='synthetic',
                  channel='SEO',marketing_attribution={'source_raw':'Google organic'})
        cached=dict(sourceStatus='available',sourceRaw='google-FC27-PMAX-Coins-US',coupons=[],project='KOL')
        evidence=effective_attribution(base,{'discount_code':'KNOWN'},cached,mapping)
        self.assertEqual((evidence['channel'],evidence['basis'],evidence['detail']),('SEO','native_channel','Google organic'))
        self.assertTrue(evidence['conflict'])
        self.assertEqual(evidence['order_source'],'google-FC27-PMAX-Coins-US')
        self.assertEqual(evidence['promotion_project'],'KOL')
        base['channel']='unknown'
        evidence=effective_attribution(base,{'discount_code':'known'},cached,mapping)
        self.assertEqual((evidence['channel'],evidence['basis']),('PPC','order_source'))
        cached['sourceRaw']='google'
        evidence=effective_attribution(base,{'discount_code':'KNOWN'},cached,mapping)
        self.assertEqual((evidence['channel'],evidence['basis'],evidence['detail']),('Direct','mapped_discount_code','KOL'))
        evidence=effective_attribution(base,{'discount_code':''},dict(cached,project='运营',code=''),mapping)
        self.assertEqual((evidence['channel'],evidence['promotion_project']),('pending_classification','运营'))

    def test_google_paid_campaigns_keep_safe_label_and_higher_priority_attribution(self):
        from channel_effects import Attribution
        from order_facts import build_order_facts
        from order_facts_api import detail_csv, public
        from order_facts_runtime import effective_attribution
        mapping=Attribution({'entries':[]},[],{})
        native=row(i=1,discount_code='',recommend_uid='0')
        source='google-D4-SN-Items&private-key=PRIVATE-QUERY'
        data=build_order_facts([native],[],[],sites={'266':'www.mmoexp.com'},scope=SCOPE,
                              source_coverage={'admin_complete':True})
        order=data['orders'][0]
        evidence=effective_attribution(dict(order,pinned_order_source=source),native,None,mapping)
        self.assertEqual((evidence['channel'],evidence['detail'],evidence['order_source']),
                         ('PPC','google-D4-SN-Items','google-D4-SN-Items'))
        self.assertEqual(evidence['order_source_raw'],source)
        order['effective_attribution']=evidence
        detail=[]
        result=public(data,dict(SCOPE,channel='PPC'),detail_rows=detail)
        self.assertEqual(result['breakdown']['rows'][0]['label'],'google-D4-SN-Items')
        self.assertEqual(detail[0]['source'],'google-D4-SN-Items')
        self.assertNotIn('PRIVATE-QUERY',json.dumps(result))
        self.assertNotIn('PRIVATE-QUERY',detail_csv(detail))
        for label in ('google-FC27-SN-UK-Coins','google-A2-PMAX-Kinah-US','google-FC27-VIDEO-DEM-EN',
                      'google-POE2-US-Discovery-NB','google-ARCR-Items','google-ARCR-Blueprints'):
            self.assertEqual(effective_attribution(dict(order,pinned_order_source=label),native,None,mapping)['channel'],'PPC')
        for label in ('Google','google organic','https://www.google.com/search','google-unknown-campaign',
                      'bing-D4-SN-Bing','youtube-Krasikol'):
            self.assertEqual(effective_attribution(dict(order,pinned_order_source=label),native,None,mapping)['channel'],'pending_classification')
        for higher in ('SEO','Direct','Campaign'):
            value=effective_attribution(dict(order,channel=higher,pinned_order_source=source),native,None,mapping)
            self.assertEqual((value['channel'],value['basis']),(higher,'native_channel'))

    def test_same_google_campaign_parameters_are_not_a_source_conflict(self):
        from channel_effects import Attribution
        from order_facts import build_order_facts
        from order_facts_runtime import effective_attribution
        mapping=Attribution({'entries':[]},[],{})
        native=row(i=1,discount_code='',recommend_uid='0')
        order=build_order_facts([native],[],[],sites={'266':'www.mmoexp.com'},scope=SCOPE,
                               source_coverage={'admin_complete':True})['orders'][0]
        order['pinned_order_source']='google-D4-SN-Items&token=NEW'
        archived=dict(sourceRaw='google-D4-SN-Items&token=OLD',sourceStatus='available')
        for uid in ('0','123'):
            value=effective_attribution(order,dict(native,recommend_uid=uid),archived,mapping)
            self.assertEqual((value['channel'],value['source_conflict']),('PPC',False))
        different=dict(archived,sourceRaw='google-POE2-SN-Currency&token=OLD')
        self.assertTrue(effective_attribution(order,native,different,mapping)['source_conflict'])
        self.assertTrue(effective_attribution(dict(order,pinned_order_source_conflict=True),
                                             native,archived,mapping)['source_conflict'])
        self.assertEqual(effective_attribution(dict(order,channel='SEO'),native,archived,mapping)['channel'],'SEO')

    def test_direct_only_explicit_and_referrer_code_stays_a_detail(self):
        from channel_effects import Attribution
        from order_facts_runtime import effective_attribution
        mapping=Attribution({'entries':[dict(code='known',channel='KOL')]},[],{})
        order=dict(site_id='266',gid='1327',pay_status='1',status='已完成',order_no='synthetic',
                   channel='Direct',marketing_attribution={'channel_raw':'Direct','source_raw':'(direct)'})
        for code, detail in (('Known','KOL'),('Unknown','运营'),('', '(direct)')):
            result=effective_attribution(order,{'discount_code':code},None,mapping)
            self.assertEqual((result['channel'],result['detail']),('Direct',detail))
        order.update(channel='unknown',marketing_attribution={})
        self.assertEqual(effective_attribution(order,{},None,mapping)['channel'],'unknown')
        result=effective_attribution(dict(order,pinned_order_source='direct'),{'discount_code':'Known'},None,mapping)
        self.assertEqual((result['channel'],result['basis'],result['detail']),('Direct','order_source','KOL'))
        for patch in (dict(pinned_order_source='unmapped-source'),dict(marketing_attribution={'channel_raw':'Other'})):
            self.assertEqual(effective_attribution(dict(order,**patch),{},None,mapping)['channel'],'pending_classification')

    def test_admin_discount_operator_fills_direct_only_and_keeps_legacy_map_first(self):
        from channel_effects import Attribution
        from order_facts_runtime import effective_attribution
        from order_facts_api import public
        from order_facts import build_order_facts
        mapping=Attribution({'entries':[dict(code='old',channel='KOL')]},[],{})
        native=row(discount_code='new-code', recommend_uid='0')
        result=build_order_facts([native],[],[],sites={'266':'www.mmoexp.com'},scope=SCOPE,
                                 source_coverage=dict(admin_complete=True))
        fact=result['orders'][0]
        for project in ('KOL','广告投放','分销','TikTok','SEO','运营'):
            evidence=effective_attribution(fact,native,dict(discountOperatorProject=project,coupons=[]),mapping)
            self.assertEqual((evidence['channel'],evidence['basis'],evidence['detail']),
                             ('Direct','mapped_discount_code',project))
        fact['effective_attribution']=evidence
        value=public(result,dict(SCOPE,channel='Direct'))
        self.assertEqual(value['breakdown']['denominator_orders'],1)
        self.assertEqual(value['breakdown']['rows'][0]['label'],'运营')
        fallback=effective_attribution(fact,native,{},mapping)
        self.assertEqual((fallback['channel'],fallback['basis'],fallback['detail']),('Direct','unmapped_discount_code','运营'))
        self.assertEqual(effective_attribution(fact,dict(native,discount_code='old'),
                         dict(discountOperatorProject='运营'),mapping)['detail'],'KOL')
        self.assertEqual(effective_attribution(dict(fact,pinned_order_source='google-FC27-PMAX-Coins-US'),native,
                         dict(discountOperatorProject='SEO'),mapping)['channel'],'PPC')
        self.assertEqual(effective_attribution(dict(fact,channel='Referral'),native,
                         dict(discountOperatorProject='SEO'),mapping)['channel'],'Referral')

    def test_only_coupon_fills_direct_but_code_and_higher_sources_keep_priority(self):
        from channel_effects import Attribution
        from order_facts_runtime import effective_attribution
        mapping=Attribution({'entries':[dict(code='known',channel='KOL')]},[],{})
        order=dict(site_id='266',gid='1327',pay_status='1',status='已完成',order_no='synthetic',
                   channel='unknown',marketing_attribution={})
        observed={'coupons':[{'title':'Launch'}]}
        for updates,native,channel,detail in (
                ({},{},'Direct','新人/活动'),
                ({},{'discount_code':'unknown'},'Direct','运营'),
                ({},{'discount_code':'Known'},'Direct','KOL'),
                ({'channel':'SEO','marketing_attribution':{'source_raw':'Organic'}},{'discount_code':'Known'},'SEO','Organic'),
                ({'pinned_order_source':'google-FC27-PMAX-Coins-US'},{'discount_code':'unknown'},'PPC','google-FC27-PMAX-Coins-US')):
            with self.subTest(channel=channel,detail=detail):
                evidence=effective_attribution(dict(order,**updates),native,observed,mapping)
                self.assertEqual((evidence['channel'],evidence['detail'],evidence['coupon']),(channel,detail,True))
        for device, expected in ((None,None),(0,'PC'),(1,'移动端'),(2,None),(False,None)):
            evidence=effective_attribution(order,{'device':device},observed,mapping)
            self.assertEqual(evidence['device'],expected)

    def test_conflicting_discount_code_is_direct_pending_review_not_operations(self):
        from channel_effects import Attribution
        from order_facts_runtime import effective_attribution
        mapping=Attribution({'entries':[dict(code='both',channel='KOL'),dict(code='both',channel='分销')]},[],{})
        order=dict(site_id='266',gid='1327',pay_status='1',status='已完成',order_no='synthetic',
                   channel='unknown',marketing_attribution={})
        coupons={'coupons':[{'title':'Launch'}],'discountOperatorProject':'运营'}
        for patch,channel,detail in (
                ({},'Direct','待核'),({'channel':'Direct'},'Direct','待核'),
                ({'pinned_order_source':'direct'},'Direct','待核'),
                ({'pinned_order_source':'google-FC27-PMAX-Coins-US'},'PPC','google-FC27-PMAX-Coins-US')):
            with self.subTest(patch=patch):
                result=effective_attribution(dict(order,**patch),{'discount_code':'both'},coupons,mapping)
                self.assertEqual((result['channel'],result['detail'],result['conflict']),(channel,detail,True))
        unmapped=effective_attribution(order,{'discount_code':'unknown'},None,mapping)
        self.assertEqual((unmapped['channel'],unmapped['detail'],unmapped['conflict']),('Direct','运营',False))

    def test_pending_with_promoter_moves_to_direct_distribution_in_all_outputs(self):
        from channel_effects import Attribution
        from order_facts import build_order_facts
        from order_facts_api import detail_csv, public
        from order_facts_runtime import ATTRIBUTION_RULE, effective_attribution
        mapping=Attribution({'entries':[dict(code='both',channel='KOL'),dict(code='both',channel='分销')]},[],{})
        natives=[row(i=i,recommend_uid=uid,discount_code=code) for i,uid,code in (
            (1,'42',''),(2,'0',''),(3,'42',''),(4,'42',''),(5,'42','both'),(6,'42',''))]
        attrs=[{'site_id':'266','order_no':'O3','归因渠道':'SEO'}]
        data=build_order_facts(natives,attrs,[],sites={'266':'www.mmoexp.com'},scope=SCOPE,
            source_coverage={'admin_complete':True,'effective_attribution':{'rule':ATTRIBUTION_RULE}})
        for order,native in zip(data['orders'],natives):
            ident=native['id']
            if ident==4:order['pinned_order_source']='google-FC27-PMAX-Coins-US'
            if ident==6:order['pinned_order_source_conflict']=True
            archived={'sourceStatus':'available','sourceRaw':'unmapped'} if ident!=4 else None
            order['effective_attribution']=effective_attribution(order,native,archived,mapping)
        expected=[('Direct','分销'),('pending_classification','unmapped'),('SEO',None),
                  ('PPC','google-FC27-PMAX-Coins-US'),('Direct','待核'),('Direct','分销')]
        effective=[r['effective_attribution'] for r in data['orders']]
        self.assertEqual([(r['channel'],r['detail']) for r in effective],expected)
        self.assertTrue(effective[-1]['source_conflict'] and effective[-1]['conflict'])
        self.assertEqual(effective[-1]['promoter_uid'],'42')
        self.assertEqual(effective[0]['basis'],'pending_promoter_distribution')
        self.assertFalse(effective[1]['promoter'])
        summary=public(data,dict(SCOPE,channel='all'))
        self.assertEqual({r['channel']:r['orders'] for r in summary['channels']},
                         {'Direct':3,'SEO':1,'PPC':1,'pending_classification':1})
        details=[]
        direct=public(data,dict(SCOPE,channel='Direct'),detail_rows=details)
        self.assertEqual({r['label']:r['orders'] for r in direct['breakdown']['rows']},{'分销':2,'待核':1})
        self.assertEqual({r['orderNo']:r['source'] for r in details},{'O1':'分销','O5':'待核','O6':'分销'})
        self.assertIn('分销',direct['aggregate_csv'])
        self.assertIn('分销',detail_csv(details))

    def test_dashboard_delivery_reuses_closed_day_and_refreshes_duplicate_id(self):
        from order_facts_runtime import dashboard_deliveries
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            archive=root/'delivery-days'
            archive.mkdir()
            day=SCOPE['start']
            day_cache=archive/(day+'.json')
            current=root/'order-deliveries.json'
            member=dict(delivery_id='10',sn='one',trade_at=day+' 10:00:00',sale_total='100')
            def cache(observed, rows):
                return json.dumps(dict(contract='channel-order-deliveries-v1',complete=True,
                    generatedAt=day+'T'+observed+'+08:00',period=dict(start=day,end=day),rows=rows))
            day_cache.write_text(cache('11:00:00',[member]))
            current.write_text(cache('15:00:00',[dict(member,sale_total='120')]))
            records, proof=dashboard_deliveries(SCOPE,current)
            self.assertEqual([(item['delivery_id'],item['sale_total']) for item in records],[('10','120')])
            self.assertEqual(proof['status'],'observed_only')
            current.unlink()
            records, proof=dashboard_deliveries(SCOPE,current)
            self.assertEqual(records[0]['sale_total'],'100')

    def test_mapped_code_owner_counts_as_promoter_with_native_zero_uid(self):
        from channel_effects import Attribution
        from order_facts_runtime import effective_attribution
        mapping=Attribution({'entries':[dict(code='known',channel='KOL')]},[],
                            {'by_code':{'known':{'uid':'42','name':'Known promoter'}}})
        native={'discount_code':'Known','recommend_uid':0}
        order=dict(site_id='266',gid='1327',pay_status='1',status='已完成',order_no='synthetic',
                   channel='unknown',marketing_attribution={})
        evidence=effective_attribution(order,native,None,mapping)
        self.assertTrue(evidence['promoter'])
        self.assertEqual(evidence['promoter_uid'],'42')
        self.assertEqual(evidence['filter_row']['promoter'],'Known promoter')
        self.assertEqual(evidence['promoter_basis'],'promoter_directory')
        self.assertEqual(native['recommend_uid'],0)

    def test_current_empty_promotion_does_not_restore_archived_project(self):
        from channel_effects import Attribution
        from order_facts_runtime import effective_attribution
        mapping=Attribution({'entries':[dict(code='known',channel='KOL')]},[],{})
        order=dict(site_id='266',gid='1327',pay_status='1',status='已完成',order_no='synthetic',
                   channel='unknown',marketing_attribution={})
        archived=dict(code='',promoterUid='42',promoter='Old promoter',project='KOL',coupons=[])
        evidence=effective_attribution(order,{'discount_code':'','recommend_uid':'0'},archived,mapping)
        self.assertEqual(evidence['channel'],'unknown')
        self.assertFalse(evidence['promoter'])
        self.assertIsNone(evidence['filter_row']['promoter'])
        self.assertIsNone(evidence['promotion_project'])

    def test_different_order_source_needs_comparable_revision_for_override(self):
        from channel_effects import Attribution
        from order_facts_runtime import effective_attribution
        mapping=Attribution({'entries':[]},[],{})
        order=dict(site_id='266',gid='1327',pay_status='1',status='已完成',order_no='synthetic',
            channel='unknown',marketing_attribution={},pinned_order_source='google-FC27-PMAX-Coins-US')
        archived=dict(sourceStatus='available',sourceRaw='Google organic',coupons=[])
        evidence=effective_attribution(order,{},archived,mapping)
        self.assertEqual(evidence['channel'],'pending_classification')
        self.assertTrue(evidence['conflict'])
        corrected=dict(order,pinned_order_source_revision='uw_fixed',pinned_order_source_at='2026-11-12T00:00:00+08:00')
        evidence=effective_attribution(corrected,{},dict(archived,sourceCapturedAt='2026-11-11T00:00:00+08:00'),mapping)
        self.assertEqual((evidence['channel'],evidence['basis']),('PPC','order_source'))

    def test_conflicts_at_same_priority_cannot_fall_back_to_lower_evidence(self):
        from channel_effects import Attribution
        from order_facts import build_order_facts
        from order_facts_runtime import effective_attribution
        mapping=Attribution({'entries':[dict(code='known',channel='KOL')]},[],{})
        order=dict(site_id='266',gid='1327',pay_status='1',status='已完成',order_no='synthetic',
            channel='unknown',marketing_attribution={'status':'conflict'})
        archived=dict(sourceStatus='available',sourceRaw='google-FC27-PMAX-Coins-US',coupons=[])
        for patch in ({}, {'marketing_attribution':{'status':'empty'},'pinned_order_source_conflict':True}):
            with self.subTest(patch=patch):
                evidence=effective_attribution(dict(order,**patch),{'discount_code':'known'},archived,mapping)
                self.assertEqual(evidence['channel'],'pending_classification')
                self.assertTrue(evidence['conflict'])
                self.assertEqual(evidence['promotion_project'],'KOL')
        rows=[{'site_id':'266','order_no':'O2','订单来源':source} for source in ('first','second')]
        facts=build_order_facts([row()],rows,[],sites={'266':'www.mmoexp.com'},scope=SCOPE,source_coverage={})
        self.assertEqual(facts['orders'][0]['marketing_attribution']['status'],'field_absent')
        self.assertTrue(facts['orders'][0]['pinned_order_source_conflict'])

    def test_shared_reader_projects_only_scoped_rows_without_live_or_archive_calls(self):
        from order_facts_runtime import collect, collect_dashboard, collect_many
        response = dict(status='available',rows=[row(discount_code='Known', tracking=dict(
            sourceStatus='available',sourceRaw='google-FC27-PMAX-Coins-US',coupons=[]))],dataset=None,
            identity_catalog=None,coverage=dict(complete=True,admin_complete=True,admin_date_basis='paytime',
                admin_snapshot=True,source_revision='revision-4',publication_id='uw_fixed',day_revisions={},missing_days=[]))
        reader=Mock(return_value=response)
        legacy_transport=Mock(side_effect=AssertionError('legacy transport must not run'))
        with tempfile.TemporaryDirectory() as folder, patch('order_facts_runtime.admin_orders') as native, \
                patch('order_facts_runtime.dashboard_evidence') as legacy:
            kwargs=dict(reader=reader,db=Path(folder)/'shared.db',costs=Path(folder)/'absent.json',publication_id='uw_fixed')
            value=collect_dashboard(SCOPE,**kwargs)
            plain=collect(SCOPE,dataset_reader=legacy_transport,**kwargs)
            [batch]=collect_many([SCOPE],request=legacy_transport,**kwargs)
        native.assert_not_called();legacy.assert_not_called()
        legacy_transport.assert_not_called()
        self.assertEqual(reader.call_args.args,(SCOPE,))
        self.assertEqual(reader.call_args.kwargs['publication_id'],'uw_fixed')
        self.assertEqual(value['orders'][0]['channel'],'unknown')
        self.assertEqual(value['orders'][0]['effective_attribution']['channel'],'PPC')
        self.assertFalse(value['orders'][0]['effective_attribution']['coupon'])
        self.assertTrue(value['source_coverage']['admin_snapshot'])
        self.assertNotIn('effective_attribution',plain['orders'][0])
        self.assertEqual(plain,batch)

    def test_channel_profit_reads_rolling_order_cost_only_for_the_channel(self):
        from channel_effects import ChannelService
        from order_facts_runtime import dashboard_deliveries

        raw = [row(), row(3, game_format='Aion2')]
        shared = dict(status='available', rows=raw, dataset=None, identity_catalog=None,
            coverage=dict(admin_complete=True, publication_id='uw_cost', captured_at='2026-11-11T00:15:00+08:00'))
        generated_at = '2026-11-11T00:15:00+08:00'
        period = {key: SCOPE[key] for key in ('start', 'end')}
        rolling_row = dict(delivery_id='51', sn='O2', source='www.mmoexp.com', genre=1,
            trade_at='2026-11-10 11:00:00', cost_total='100', sale_total='999')
        supplement_row = dict(rolling_row, delivery_id='52', cost_total='200')
        sales_row = dict(rolling_row, delivery_id='53', sn='O3', cost_total='75')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sales = root / 'sales'
            sales.mkdir()
            rolling = root / 'order-deliveries.json'
            supplement = root / 'order-supplements.json'
            capture = dict(contract='channel-order-deliveries-v1', complete=True,
                generatedAt=generated_at, period=period, rows=[rolling_row])
            rolling.write_text(json.dumps(capture), encoding='utf-8')
            supplement.write_text(json.dumps(dict(capture, period=None, scope='exact_orders',
                orderNos=['O2'], generatedAt='2026-11-11T00:20:00+08:00', rows=[supplement_row])), encoding='utf-8')
            (sales / 'deliveries.json').write_text(json.dumps([sales_row]), encoding='utf-8')
            reads = []
            read_text = Path.read_text

            def record_read(path, *args, **kwargs):
                if path in (rolling, supplement):
                    reads.append(path.name)
                return read_text(path, *args, **kwargs)

            service = ChannelService(root, lambda user: user == 'admin', shared=True)
            self.addCleanup(service.pool.shutdown)
            es_read = Mock(return_value=shared)
            with patch.dict(sys.modules, shared_es_facts=SimpleNamespace(read=es_read)), \
                    patch('channel_source.ROOT', root), patch('channel_source.SALES', sales), \
                    patch('order_delivery_index.read_orders', return_value={'status': 'unavailable'}) as archive_read, \
                    patch('order_facts_runtime.dashboard_deliveries', side_effect=lambda scope, _: dashboard_deliveries(scope, rolling)), \
                    patch.object(Path, 'read_text', record_read):
                code, output = service.get(dict(start=[period['start']], end=[period['end']], mode=['profit']), 'admin')
            self.assertEqual((code, output['status']), (200, 'partial'))
            self.assertEqual(output['sources']['orders']['publication_id'], 'uw_cost')
            totals = output['denominator']
            values = tuple(totals[name] for name in ('orders', 'coveredOrders', 'saleCny', 'costCny', 'profitCny'))
            self.assertEqual(values, (2, 2, 700, 275, 425))
            es_read.assert_called_once()
            self.assertEqual(reads.count(rolling.name), 2)
            self.assertEqual(reads.count(supplement.name), 1)
            archive_read.assert_not_called()

    def test_channel_facts_uses_index_only_when_existing_reader_scope_is_preserved(self):
        from order_facts_runtime import collect_dashboard
        import types
        raw=row()
        response=dict(status='available',rows=[raw],dataset=None,identity_catalog=None,
            coverage=dict(admin_complete=True,publication_id='uw_fixed',day_revisions={},missing_days=[]))
        delivery=dict(delivery_id='71',source='www.mmoexp.com',sn='O2',genre=1,
                      trade_at='2026-11-10 11:00:00',cost_total='200')
        window=dict(source='www.mmoexp.com',since='2026-11-10 00:00:00',until='2026-11-10 23:59:59',
                    capturedAt='2026-11-11T00:01:00+08:00',revision='capture')
        record=dict(status='available',legacyCompatible=True,rollingWindow=None,rows=[delivery],
                    revision='index-r1',generatedAt=window['capturedAt'],windows=[window])
        read=Mock(return_value=record)
        module=types.SimpleNamespace(read_orders=read,covers_window=lambda *a,**kw:True)
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules,{'order_delivery_index':module}), \
             patch('order_facts_runtime.dashboard_deliveries',return_value=([],{'status':'unavailable'})) as legacy:
            path=Path(folder)/'order-deliveries.json'
            output=collect_dashboard(SCOPE,reader=Mock(return_value=response),costs=path,publication_id='uw_fixed')
            legacy.assert_not_called()
            self.assertEqual(output['orders'][0]['observed_cost_cny'],'200')
            self.assertEqual(output['source_coverage']['cost']['source_revision'],'index-r1')
            self.assertFalse(output['source_coverage']['cost']['order_cost_complete'])
            self.assertEqual(read.call_args.args[0],{('www.mmoexp.com','O2')})
            record['rollingWindow']=dict(window,since='2026-11-09 00:00:00')
            fallback=collect_dashboard(SCOPE,reader=Mock(return_value=response),costs=path,publication_id='uw_fixed')
            legacy.assert_called_once()
            self.assertEqual(fallback['source_coverage']['cost']['status'],'unavailable')

    def test_channel_facts_real_index_matches_legacy_and_stale_reverts(self):
        from order_facts_runtime import collect_dashboard
        from order_delivery_index import sync
        raw=row()
        response=dict(status='available',rows=[raw],dataset=None,identity_catalog=None,
            coverage=dict(admin_complete=True,publication_id='uw_fixed',day_revisions={},missing_days=[]))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); daydir=root/'delivery-days';daydir.mkdir()
            dayfile=daydir/'2026-11-10.json'
            dayfile.write_text(json.dumps(dict(contract='channel-order-deliveries-v1',complete=True,
                generatedAt='2026-11-11T00:01:00+08:00',period=dict(start='2026-11-10',end='2026-11-10'),
                rows=[dict(delivery_id='71',source='www.mmoexp.com',sn='O2',genre=1,
                           trade_at='2026-11-10 11:00:00',cost_total='200')])),encoding='utf8')
            kw=dict(reader=Mock(return_value=response),costs=root/'order-deliveries.json',publication_id='uw_fixed')
            legacy=collect_dashboard(SCOPE,**kw)
            revision=sync(root)
            indexed=collect_dashboard(SCOPE,**kw)
            self.assertEqual(indexed['orders'],legacy['orders'])
            self.assertEqual(indexed['totals'],legacy['totals'])
            self.assertEqual(indexed['source_coverage']['cost']['source_revision'],revision)
            self.assertFalse(indexed['source_coverage']['cost']['order_cost_complete'])
            dayfile.write_text(dayfile.read_text(encoding='utf8')+' ',encoding='utf8')
            stale=collect_dashboard(SCOPE,**kw)
            self.assertEqual(stale['orders'],legacy['orders'])
            self.assertNotEqual(stale['source_coverage']['cost']['source_revision'],revision)

    def test_shared_reader_missing_coverage_and_batch_revision_drift_are_explicit(self):
        from order_facts_runtime import collect_shared_many
        unavailable=dict(status='unavailable',rows=[],dataset=None,identity_catalog=None,
            coverage=dict(complete=False,admin_complete=False,admin_date_basis='paytime',admin_snapshot=True,
                source_revision='revision-4',publication_id=None,day_revisions={},missing_days=[SCOPE['start']]))
        first=dict(unavailable,coverage=dict(unavailable['coverage'],publication_id='se_pinned'))
        scoped=dict(first,coverage=dict(first['coverage'],source_revision='other-scope-revision'))
        drift=dict(scoped,coverage=dict(scoped['coverage'],publication_id='se_changed'))
        with tempfile.TemporaryDirectory() as folder:
            kwargs=dict(db=Path(folder)/'shared.db',costs=Path(folder)/'absent.json')
            [value]=collect_shared_many([SCOPE],reader=Mock(return_value=unavailable),**kwargs)
            self.assertEqual(value['status'],'unavailable')
            self.assertEqual(value['source_coverage']['missing_days'],[SCOPE['start']])
            reader=Mock(side_effect=[first,scoped])
            a,b=collect_shared_many([SCOPE,dict(SCOPE,site_id='all')],reader=reader,**kwargs)
            self.assertNotEqual(a['source_coverage']['source_revision'],b['source_coverage']['source_revision'])
            self.assertEqual(reader.call_args.kwargs['publication_id'],'se_pinned')
            with self.assertRaisesRegex(ValueError,'order_facts_shared_revision_changed'):
                collect_shared_many([SCOPE,dict(SCOPE,gid='456')],reader=Mock(side_effect=[first,drift]),**kwargs)
    def test_existing_http_route_dispatches_facts_without_changing_old_modes(self):
        tree=ast.parse((ROOT/'source/range_api.py').read_text(encoding='utf-8'))
        handler=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Handler')
        method=next(n for n in handler.body if isinstance(n,ast.FunctionDef) and n.name=='do_GET')
        env=dict(urlsplit=urlsplit,parse_qs=parse_qs,CONVERSATION_PREFIX='/conversations',
                 CHANNELS=Mock(),ACTUAL_PROFITS=Mock(),ORDER_FACTS=Mock())
        exec(compile(ast.Module(body=[method],type_ignores=[]),'handler','exec'),env)
        for mode,name in [('order-facts','ORDER_FACTS'),('actual-profit','ACTUAL_PROFITS'),('profit','CHANNELS')]:
            service=env[name];service.get.return_value=(200,{'ok':name})
            h=Mock(path='/channels?mode='+mode,headers={'X-Auth-User':'actor'})
            env['do_GET'](h);service.get.assert_called_once_with({'mode':[mode]},'actor')
            h.reply.assert_called_with(200,{'ok':name})
        h=Mock(path='/channels?mode=order-facts',headers={})
        env['do_GET'](h);h.reply.assert_called_once_with(401,{'error':'login_required'})

if __name__=='__main__':unittest.main()
