"""Read-only source and HTTP dispatch seams, with synthetic source records."""
import ast
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
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
        self.assertEqual((evidence['channel'],evidence['basis']),('Referral','promotion'))
        evidence=effective_attribution(base,{'discount_code':''},dict(cached,project='运营',code=''),mapping)
        self.assertEqual((evidence['channel'],evidence['promotion_project']),('pending_classification','运营'))

    def test_direct_only_explicit_and_referrer_code_stays_a_detail(self):
        from channel_effects import Attribution
        from order_facts_runtime import effective_attribution
        mapping=Attribution({'entries':[dict(code='known',channel='KOL')]},[],{})
        order=dict(site_id='266',gid='1327',pay_status='1',status='已完成',order_no='synthetic',
                   channel='Direct',marketing_attribution={'channel_raw':'Direct','source_raw':'(direct)'})
        for code, detail in (('Known','KOL'),('Unknown','待归类'),('', '(direct)')):
            result=effective_attribution(order,{'discount_code':code},None,mapping)
            self.assertEqual((result['channel'],result['detail']),('Direct',detail))
        order.update(channel='unknown',marketing_attribution={})
        self.assertEqual(effective_attribution(order,{},None,mapping)['channel'],'unknown')
        result=effective_attribution(dict(order,pinned_order_source='direct'),{'discount_code':'Known'},None,mapping)
        self.assertEqual((result['channel'],result['basis'],result['detail']),('Direct','order_source','KOL'))
        for patch in (dict(pinned_order_source='unmapped-source'),dict(marketing_attribution={'channel_raw':'Other'})):
            self.assertEqual(effective_attribution(dict(order,**patch),{},None,mapping)['channel'],'pending_classification')

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
