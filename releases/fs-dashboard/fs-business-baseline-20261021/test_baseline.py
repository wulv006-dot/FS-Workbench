import importlib.util,json,sys,tempfile,unittest,hashlib
from pathlib import Path

SOURCE=Path(__file__).parent/'source'
sys.path[:0]=[str(SOURCE/'hermes'),str(SOURCE),str(Path(__file__).parent/'fixtures')]
from coupon_channels import classify,retained,mapping
from price_ending import package_ending
import es_order_structure as es


class BaselineTests(unittest.TestCase):
    def test_mapping_source(self):
        codes,version=mapping()
        self.assertEqual(len(codes),373)
        self.assertEqual(classify({'折扣码':' TOMYJOHN '})[:2],('分销','matched'))
        self.assertEqual(classify({'折扣码':'tomyjohn'})[:2],('有码未映射','unmatched'))
        self.assertEqual(classify({'折扣码':''})[:2],('无码','no_code'))
        self.assertEqual(classify({'_has_discount_code':False})[:2],('码字段未保留','not_retained'))
        self.assertEqual(classify({'_coupon_mapping_version':'old'})[:2],('码字段未保留','not_retained'))

    def test_private_classification_drops_codes(self):
        row={v:'' for v in es.COLUMNS.values()}
        row.update({'订单号':'D_SYNTHETIC','折扣码':'TOMYJOHN','付款时间':'2026/10/20 12:00:00','游戏':'FC 27','订单状态':'已完成','是否新客户':'否','折扣金额':'0','订单金额（美元）':'10','订单来源':'original-source'})
        dataset=es.make_dataset([row,row],['a'*64],0,1,0)
        safe=dataset['rows'][0]
        self.assertNotIn('折扣码',safe)
        self.assertNotIn('TOMYJOHN',json.dumps(dataset))
        self.assertEqual(safe['订单来源'],'original-source')
        self.assertEqual(classify(safe)[:2],('分销','matched'))
        args=dict(profile='FC27',start='2026-10-20',end='2026-10-20',group_by='discount_channel')
        value=es.aggregate_rows(dataset['rows'],dataset['hashes'],0,args,1,0)
        self.assertEqual(value['discount_totals']['orders'],1)
        self.assertEqual(value['discount_totals']['discount_amount_usd'],'0')
        self.assertEqual(value['groups'][0]['label'],'分销')
        self.assertFalse(value['quality']['coupon_channel_is_site'])
        self.assertEqual(value['quality']['coupon_coverage']['matched'],1)
        self.assertNotIn('TOMYJOHN',json.dumps(value))

    def test_raw_and_private_projection_agree(self):
        rows=[]
        for i,(code,discount) in enumerate([('22cor','1'),('','0'),('not-a-mapped-code',''),('1','-2')]):
            row={v:'' for v in es.COLUMNS.values()}
            row.update({'订单号':str(i),'付款时间':'2026/10/20 12:00:00','游戏':'FC 27','折扣码':code,'折扣金额':discount,'订单金额（美元）':'10','订单状态':'已完成'})
            rows.append(row)
        args=dict(profile='FC27',start='2026-10-20',end='2026-10-20',group_by='discount_channel')
        private=es.make_dataset(rows,['b'*64],0,1,0)
        a=es.aggregate_rows(rows,['b'*64],0,args,1,0)
        b=es.aggregate_rows(private['rows'],['b'*64],0,args,1,0)
        self.assertEqual(a['groups'],b['groups'])
        self.assertEqual(a['discount_totals']['discount_amount_usd'],'-1')
        self.assertEqual(a['discount_totals']['unknown_discount_orders'],1)
        self.assertEqual(sum(g['orders'] for g in a['groups']),4)

    def test_channel_query_reads_original_archive_without_network(self):
        from unittest.mock import patch
        row={v:'' for v in es.COLUMNS.values()}
        row.update({'订单号':'test-order','付款时间':'2026/10/20 12:00:00','游戏':'FC 27','折扣码':'22cor','折扣金额':'1','订单金额（美元）':'10'})
        dataset=es.make_dataset([row],['d'*64],0,1,0)
        dataset['captured_at']='2026-10-20T23:00:00+00:00'
        query=dict(profile='FC27',start='2026-10-20',end='2026-10-20',group_by='discount_channel')
        with patch.object(es,'archived_dataset',return_value=dataset),patch.object(es,'_server_bundle',side_effect=AssertionError('network source must not run')):
            result=es.server_bundle(query)
        self.assertEqual(result['snapshots'][0]['value']['groups'][0]['label'],'KOL')
        self.assertEqual(result['snapshots'][0]['value']['captured_at'],dataset['captured_at'])
        self.assertIn('aggregated_at',result['snapshots'][0]['value']['quality'])
        with patch.object(es,'archived_dataset',return_value=dict(dataset,captured_at=None)):
            self.assertIsNone(es.server_bundle(query)['snapshots'][0]['value']['captured_at'])
        with patch.object(es,'archived_dataset',return_value=None),patch.object(es,'_server_bundle',side_effect=AssertionError('network source must not run')):
            self.assertEqual(es.server_bundle(query)['reason'],'coupon_period_export_unavailable')

    def test_exact_navigation_change_keeps_auth_and_old_assets(self):
        from unittest.mock import patch
        sys.path.insert(0,str(Path(__file__).parent/'deploy'))
        import navigation_patch as nav
        routes={'/dashboard/data-tools/index.html':'workspace-native-20261006-afff372192a3/tools-index.html','/dashboard/data-tools/page.js':'workspace-native-20261006-afff372192a3/page.js','/dashboard/fs-home/hermes/customer-tracking/page.js':'workspace-native-20261006-346f59eea565/page.js','/dashboard/workspace-assets/workspace-native-20261006-afff372192a3/page.js':'workspace-native-20261006-afff372192a3/page.js'}
        raw=b'\n'.join(('location = '+uri+' {\n    alias /var/lib/fs-navigation-formal-static/'+p+';\n}').encode() for uri,p in routes.items())
        raw+=b'\nlocation = /dashboard/workspace-assets/workspace-native-20261006-916087de9ef6/data-workspace.js {\n    if ($request_method !~ ^(GET|HEAD)$) { return 405; }\n    auth_request /__nav_formal_native_session;\n    alias /var/lib/fs-navigation-formal-static/workspace-native-20261006-916087de9ef6/data-workspace.js;\n}\n'
        with patch.object(nav,'BEFORE',hashlib.sha256(raw).hexdigest()):
            new=nav.candidate(raw,'workspace-native-20261006-4f4a56f7a335')
            self.assertEqual(new.count(b'auth_request /__nav_formal_native_session;'),2)
            self.assertEqual(new.count(b'{'),new.count(b'}'))
            self.assertIn(b'workspace-native-20261006-916087de9ef6/data-workspace.js',new)
            self.assertEqual(new.count(b'alias /var/lib/fs-navigation-formal-static/workspace-native-20261006-afff372192a3/page.js;'),1)
            with self.assertRaises(ValueError):nav.candidate(raw+b'changed','workspace-native-20261006-4f4a56f7a335')

    def test_package_ending_boundaries_and_margin(self):
        for p in ('10.00','10.09'):
            self.assertEqual(package_ending(p,'8','10')['package_usd'],'9.99')
        for p,c in (('10.10','8'),('9.99','8'),('0.01','0.005')):
            self.assertEqual(package_ending(p,c,'10')['package_usd'],p)
        self.assertEqual(package_ending('10.00','9','10')['reason'],'margin_floor')
        self.assertEqual(package_ending('10.00','8.991','10')['reason'],'applied')
        self.assertEqual(package_ending('10.09','9','10')['package_usd'],'10.09')
        self.assertEqual(package_ending('100.80','80','10')['package_usd'],'99.99')
        for p,c in (('100.99','80'),('199.99','100')):
            ending=package_ending(p,c,'10')
            self.assertEqual(ending['package_usd'],p)
            self.assertEqual(ending['reduction_usd'],'0.00')
            self.assertEqual(ending['reason'],'already_99')
        for args in [('NaN','8','10'),('10','-1','10'),('10','0','10'),('10','8','100')]:
            with self.assertRaises(ValueError):package_ending(*args)

    def test_release_manifest_cannot_expand_targets_or_writes(self):
        import copy
        sys.path.insert(0,str(Path(__file__).parent/'deploy'))
        import release
        manifest={'scope':release.SCOPE,'businessWrites':False,'timersChanged':False,
            'files':[dict(candidate=k,target=v,beforeSha256=None if k in release.NEW else 'a'*64,owner='0:0',mode='0o644') for k,v in release.TARGETS.items()]}
        release.checked_manifest(manifest)
        for key,value in [('businessWrites',True),('timersChanged',True)]:
            bad=copy.deepcopy(manifest);bad[key]=value
            with self.assertRaises(ValueError):release.checked_manifest(bad)
        bad=copy.deepcopy(manifest);bad['files'][0]['target']='/etc/other'
        with self.assertRaises(ValueError):release.checked_manifest(bad)

    def test_business_input_replaces_stale_business_memories(self):
        import business_context as bc
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);skills=root/'profile/skills';skills.mkdir(parents=True)
            (root/'profile/memories').mkdir()
            (root/'desktop-business-context.md').write_text('STALE-DESKTOP-COST-RULE',encoding='utf-8')
            (root/'profile/memories/MEMORY.md').write_text('STALE-MEMORY-COST-RULE',encoding='utf-8')
            (root/'profile/memories/USER.md').write_text('USER-PREFERENCE-KEPT',encoding='utf-8')
            text,_,files=bc.learning_bundle(root,skills)
            self.assertNotIn('STALE-DESKTOP-COST-RULE',text)
            self.assertNotIn('STALE-MEMORY-COST-RULE',text)
            self.assertIn('USER-PREFERENCE-KEPT',text)
            self.assertIn('business-baseline-20261021-v1',text)
            self.assertEqual(files[-1]['path'],'runtime/business-baseline.md')


if __name__=='__main__':unittest.main()
