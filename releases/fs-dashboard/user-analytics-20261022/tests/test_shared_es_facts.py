"""Shared closed-day publication and indexed scope reads against the existing Store."""
from contextlib import closing
from hashlib import sha256
from pathlib import Path
import sqlite3
import json
import sys
import tempfile
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
import shared_es_facts as facts
import user_weekly as weekly
from user_contract import digest, stamp
from user_store import Store

D1, D2, D3 = '2026-11-10', '2026-11-11', '2026-11-12'


def order(number, day, site='266', gid='1327'):
    return dict(id=1, order_no=number, site_id=site, gid=gid, paytime=day + ' 13:15:14',
                pay_status=1, status_format='已完成', amount_usd_format='5.42',
                site={'full_title': site + '.example.test'}, email='private@example.test')


def line(number, day, product='gold'):
    return {'订单号': sha256(number.encode()).hexdigest(), '付款时间': day + ' 13:15:14',
            '_signature': digest([number, day, product]), '产品类型': product,
            'marketing_attribution': {'channel': 'SEO', 'status': 'available'}}


def archive(*lines):
    return dict(_private_dataset=True, revision_selection='published_pins',
                status='available', hashes=['a' * 64], failed_files=0, parse_failures=0, rows=list(lines))


def scope(start=D1, end=D1, site='266', gid='1327'):
    return dict(start=start, end=end, site_id=site, gid=gid)


def publication(cutoff, suffix='a'):
    value = dict(contract=weekly.CONTRACT, cutoff=stamp(cutoff).isoformat(),
                 published_at=stamp(cutoff + 'T04:22:00+08:00').isoformat(), captured_at=None,
                 cadence='daily', data_version='1', config={'sites': {'266': {}}}, jobs=[],
                 flag_manifests=[{'name': suffix * 64 + '.json', 'sha256': suffix * 64}],
                 refresh_health={}, coverage_context={}, source_status_rule_versions=[])
    value['publication_id'] = 'uw_' + digest(value)[:32]
    return value


class SharedFacts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store.__new__(Store)
        self.store.root = Path(tmp.name)
        self.store.path = Path(tmp.name) / 'customers.sqlite3'
        self.store.read_only = False
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
            db.execute("INSERT INTO meta VALUES('revision','1')")

    def stage(self, day, dataset, *orders, ref='test', tracking=None):
        return facts.stage_day(self.store, day, ref, dataset, orders, tracking or {},
                               day + 'T14:00:00+08:00')

    def read(self, query=None, ident=None):
        return facts.read(query or scope(), db=self.store.path, publication_id=ident)

    def test_fc27_quantity_supplement_keeps_original_pin_and_exact_source_members(self):
        from unittest.mock import patch
        from user_source import fc27_coins_projection
        old = publication(D2)
        rev = self.stage(D1,archive(),order('existing',D1),order('missing',D1),
                         order('other-site',D1,site='300'))
        weekly.write_publication(self.store,old,None,shared_revisions={D1:rev})
        previous = self.read()
        raw = order('existing',D1)
        raw.update(aid='21587',content='<span class="item">1000K Coins + 30K Free x1 = $50</span>',
                   is_region_price='0',before_discount='50',discount='100',points='0')
        with patch.object(sys,'path',[str(Path(__file__).resolve().parents[4]/
                    'releases/fc-coins/fc-pricing-v3-20261026/source'),*sys.path]):
            coins = fc27_coins_projection(raw,D2+'T05:00:00+08:00')
            self.assertIsNone(fc27_coins_projection(dict(raw,site_id='300'),D2+'T05:00:00+08:00'))
        self.assertEqual((coins['platform'],coins['purchase_k'],coins['bonus_k'],coins['delivered_k']),
                         ('PS','1000','30','1030'))
        row = dict(id=raw['id'],order_no=raw['order_no'],paid_at=raw['paytime'],fc27_coins=coins)
        args = dict(publication_id=old['publication_id'],source_revision=previous['coverage']['source_revision'],
                    scope=scope())
        with self.assertRaisesRegex(ValueError,'shared_es_fc27_identity_mismatch'):
            facts.store_fc27_projection(self.store,rows=[row,dict(row,order_no='missing',id=9)],**args)
        self.assertEqual(facts.latest_publication(db=self.store.path)['publication_id'],old['publication_id'])
        result = facts.store_fc27_projection(self.store,rows=[row],**args)
        after = self.read()
        self.assertEqual(after['coverage']['source_revision'],previous['coverage']['source_revision'])
        self.assertEqual(after['coverage']['publication_id'],result['publication_id'])
        self.assertIsNotNone(after['coverage']['fc27_projection_revision'])
        by_no = {r['order_no']:r for r in after['rows']}
        self.assertEqual(by_no['existing']['fc27_coins'],coins)
        self.assertNotIn('content',by_no['existing'])
        self.assertNotIn('fc27_coins',by_no['missing'])
        self.assertNotIn('fc27_coins',self.read(ident=old['publication_id'])['rows'][0])
        self.assertTrue(all('fc27_coins' not in r for r in self.read(scope(gid='all'))['rows']))
        self.assertEqual(facts.store_fc27_projection(self.store,rows=[row],**args)['status'],'reused')
        second = self.stage(D2,archive(),dict(order('normal-daily',D2),fc27_coins=coins))
        next_pub = publication(D3,'b')
        weekly.write_publication(self.store,next_pub,old['publication_id'],shared_revisions={D2:second})
        later = self.read(scope(D1,D2))
        self.assertEqual(sum('fc27_coins' in r for r in later['rows']),2)
        self.assertNotEqual(later['coverage']['fc27_projection_revision'],after['coverage']['fc27_projection_revision'])

    def test_existing_channel_history_is_main_site_only_and_keeps_formal_revisions(self):
        formal = self.stage(D2, archive(line('fresh', D2)), order('fresh', D2))
        pub = publication(D3)
        weekly.write_publication(self.store, pub, None, shared_revisions={D2: formal})
        root = self.store.root / 'channel-days'
        root.mkdir()
        legacy = dict(contract='channel-day-v1',period=dict(start=D1,end=D1),
            generatedAt=D2+'T01:00:00+08:00',sources=dict(
                orders=dict(status='complete',site='MMOEXP',dateBasis='paytime',currency='USD',rows=1),
                coupons=dict(status='complete',rows=1)),
            orders=[dict(orderNo='old',day=D1,paidAt=D1+' 12:30:00',gid='1327',game='FC27',
                salesUsd=4.75,adminSaleCny=None,code='alpha',promoterUid='23',customerType='老客',
                status='已完成',payStatus='1',country='US',payment='PayPal',
                sourceStatus='available',sourceRaw='google-FC27-PMAX-Coins-US',
                coupons=[dict(templateId='9',title='Launch',batch='batch1')])])
        (root / (D1+'.json')).write_text(json.dumps(legacy),encoding='utf-8')
        # A previously indexed formal day always wins, even if an old local file changed.
        (root / (D2+'.json')).write_text('{}',encoding='utf-8')
        before = self.store.path.read_bytes()
        options = dict(root=root,now=D3+'T15:00:00+08:00')
        preview = facts.import_channel_history(self.store,pub['publication_id'],**options)
        self.assertEqual((preview['selected_days'],preview['already_indexed'],preview['orders'],preview['coupons']),
                         ([D1],[D2],1,1))
        self.assertEqual(self.store.path.read_bytes(),before)
        with self.assertRaisesRegex(ValueError,'shared_es_history_source_changed'):
            facts.import_channel_history(self.store,pub['publication_id'],apply=True,expected_source='wrong',**options)
        self.assertEqual(self.store.path.read_bytes(),before)
        result = facts.import_channel_history(self.store,pub['publication_id'],apply=True,
                                              expected_source=preview['source_revision'],**options)
        main = self.read(scope(D1,D2))
        self.assertEqual(main['status'],'partial')
        self.assertTrue(main['coverage']['admin_complete'])
        self.assertEqual(main['coverage']['historical_channel_days'],[D1])
        self.assertEqual(main['identity_catalog']['verified_days'],[D2])
        self.assertFalse(main['identity_catalog']['complete'])
        self.assertEqual(main['coverage']['publication_id'],result['publication_id'])
        self.assertEqual(main['rows'][0]['amount_usd_format'],'4.75')
        self.assertEqual(main['rows'][0]['tracking']['customerType'],'老客')
        self.assertEqual(main['rows'][0]['tracking']['coupons'][0]['title'],'Launch')
        self.assertEqual(len(main['dataset']['rows']),1)
        self.assertEqual(self.read(scope(D1,D2,site='all'))['coverage']['missing_days'],[D1])
        self.assertEqual(self.read(scope(D1,D1,site='300'))['status'],'unavailable')
        self.assertEqual(self.read(scope(D1,D1),ident=pub['publication_id'])['status'],'unavailable')
        self.assertEqual(self.read(scope(D1,D1,gid='456'))['rows'],[])
        with self.assertRaisesRegex(ValueError,'shared_es_history_publication_changed'):
            facts.import_channel_history(self.store,pub['publication_id'],**options)
        replacement = self.stage(D1, archive(line('formal-old',D1)), order('formal-old',D1,site='300'))
        newer = publication('2026-11-13','b')
        weekly.write_publication(self.store,newer,pub['publication_id'],shared_window=(D1,D2,None))
        with patch('shared_es_facts.prepare_publication',return_value={D1:replacement}) as prepare:
            weekly.retry_shared_es(self.store,lambda:False)
        self.assertEqual(prepare.call_args.args[2:4],(D1,D1))
        self.assertEqual(self.read(scope(D1,D1,site='all',gid='all'))['rows'][0]['order_no'],'formal-old')
        self.assertEqual(self.read(scope(D1,D1),ident=result['publication_id'])['rows'][0]['order_no'],'old')

    def test_central_discount_catalog_is_once_per_day_and_pinned_to_order_publication(self):
        promo = lambda sn, code, gid='1327': dict(order(sn,D1,gid=gid),discount_code=code)
        rev = self.stage(D1,archive(),promo('good','Case'),promo('miss','Missing'),
                         promo('clash','Clash'),promo('scope','Case','456'))
        original=publication(D2)
        weekly.write_publication(self.store,original,None,shared_revisions={D1:rev})
        def discount(code, owner, **extra):
            return dict(site_id=266,code=code,gid='1327',admin_id=41,
                        admins=dict(id=41,nickname=owner) if owner else None,**extra)
        rows=[discount(' Case ','董文鑫',exclude_gids='456'),discount('Missing',None),
              discount('Clash','张玲玲'),discount('Clash','陈宝')]
        clock=D2+'T04:25:00+08:00'
        reader=Mock(return_value=rows)
        first=facts.refresh_discounts_due(self.store,clock,reader=reader)
        self.assertEqual(first['code_count'],3)
        self.assertEqual(facts.refresh_discounts_due(self.store,clock,reader=reader),{'status':'reused'})
        reader.assert_called_once()
        def selected(ident=None):
            result=self.read(scope(D1,D1,gid='all'),ident=ident)
            return {r['order_no']:(r.get('tracking') or {}).get('discountOperatorProject') for r in result['rows']}
        self.assertEqual(selected(),{'good':'广告投放','miss':None,'clash':None,'scope':None})
        self.assertEqual(set(selected(original['publication_id']).values()),{None})
        bad=Mock(side_effect=PermissionError())
        failed=facts.refresh_discounts_due(self.store,D3+'T04:20:00+08:00',reader=bad)
        self.assertEqual(failed['status'],'partial')
        self.assertEqual(self.read()['coverage']['publication_id'],first['publication_id'])
        rows=[discount('Case','王修权')]
        second=facts.refresh_discount_catalog(self.store,reader=Mock(return_value=rows),now=D3+'T04:35:00+08:00')
        self.assertNotEqual(first['discount_revision'],second['discount_revision'])
        self.assertEqual(selected()['good'],'SEO')
        self.assertEqual(selected(first['publication_id'])['good'],'广告投放')

    def test_scoped_read_retains_multiline_and_cross_site_identity_but_no_private_fields(self):
        rev1 = self.stage(D1, archive(line('same', D1), line('same', D1, 'item'),
                                      line('only-d4', D1)), order('same', D1),
                          order('only-d4', D1, gid='456'),
                          tracking={('266', 'same'): {'coupons': []}})
        rev2 = self.stage(D2, archive(line('same', D2)), order('same', D2, site='300', gid='456'))
        self.assertEqual(self.read()['status'], 'unavailable')
        pub = publication(D3)
        weekly.write_publication(self.store, pub, None, shared_revisions={D1: rev1, D2: rev2})
        result = self.read(scope(D1, D2))
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['rows'][0]['tracking'], {'coupons': []})
        self.assertNotIn('email', result['rows'][0])
        self.assertEqual({row['产品类型'] for row in result['dataset']['rows']}, {'gold', 'item'})
        self.assertEqual({row['site_id'] for row in result['identity_catalog']['rows']}, {'266', '300'})
        self.assertEqual(result['coverage']['source_revision'],
                         self.read(scope(D1, D2, gid='456'))['coverage']['source_revision'])

    def test_update_reuses_previous_days_and_keeps_fixed_publication(self):
        old_rev = self.stage(D1, archive(line('old', D1)), order('old', D1))
        first = publication(D2)
        weekly.write_publication(self.store, first, None, shared_revisions={D1: old_rev})
        new_rev = self.stage(D1, archive(line('corrected', D1)), order('corrected', D1), ref='new')
        next_day = self.stage(D2, archive())
        next_pub = publication(D3, 'b')
        weekly.write_publication(self.store, next_pub, first['publication_id'],
                                 shared_revisions={D1: new_rev, D2: next_day})
        self.assertEqual(self.read()['rows'][0]['order_no'], 'corrected')
        self.assertEqual(self.read(ident=first['publication_id'])['rows'][0]['order_no'], 'old')
        self.assertEqual(self.read(scope(D2, D2))['status'], 'available')
        self.assertEqual(self.read(scope(D1, D3))['coverage']['missing_days'], [D3])
        self.assertEqual(self.read(scope(D3, D3))['status'], 'unavailable')

    def test_bad_stage_rolls_back_whole_publication(self):
        rev = self.stage(D1, archive(line('old', D1)), order('old', D1))
        first = publication(D2)
        weekly.write_publication(self.store, first, None, shared_revisions={D1: rev})
        second = publication(D3, 'b')
        with self.assertRaisesRegex(ValueError, 'shared_es_publication_stage_mismatch'):
            weekly.write_publication(self.store, second, first['publication_id'],
                                     shared_revisions={D1: rev, D2: 'missing'})
        self.assertEqual(self.read()['coverage']['publication_id'], first['publication_id'])
        self.assertEqual(self.read(ident=second['publication_id'])['status'], 'unavailable')

    def test_prepare_resumes_existing_day_without_second_native_pull(self):
        pub = publication(D3)
        reader = Mock(side_effect=[([order('one', D1)], {}), ([order('two', D2)], {})])
        workbooks = Mock(return_value=archive(line('one', D1), line('two', D2)))
        self.assertIsNone(facts.prepare_publication(self.store, pub, D1, D2, reader=reader,
                                                   archive=workbooks,
                                                   checkpoint=Mock(side_effect=[False, True])))
        revisions = facts.prepare_publication(self.store, pub, D1, D2, reader=reader, archive=workbooks)
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(set(revisions), {D1, D2})
        self.assertEqual(facts.prepare_publication(self.store, pub, D1, D2, reader=reader,
                                                   archive=workbooks), revisions)
        self.assertEqual(workbooks.call_count, 2)

    def test_current_month_review_rule_keeps_old_inflight_bounds(self):
        cutoff = stamp('2026-11-16')
        self.assertEqual(weekly.calendar_review_start(cutoff, weekly.REVIEW_POLICY), stamp('2026-09-01'))
        self.assertEqual(weekly.calendar_review_start(cutoff, weekly.CURRENT_MONTH_POLICY), stamp('2026-11-01'))

    def test_seed_uses_existing_files_and_leaves_user_publication_unchanged(self):
        first = publication(D2)
        weekly.write_publication(self.store, first, None)
        root = self.store.path.parent
        manifest = root / ('a' * 64 + '.json')
        manifest.write_text('{"query":{"profile":"ALL","status":"all","start":"2026-11-10","end":"2026-11-10"},'
                            '"captured_at":"2026-11-11T05:00:00+08:00","file_sha256":["source"],'
                            '"file_set":{"failed_files":0,"declared_files":1}}', encoding='utf-8')
        # Manifest selection already has private file mode/owner coverage in its own tests.
        pin = dict(name=manifest.name, sha256=sha256(manifest.read_bytes()).hexdigest())
        reader = Mock(return_value=([order('one', D1)], {}))
        workbook = Mock(return_value=archive(line('one', D1)))
        with patch('user_customer_types.manifest_inventory', return_value=[pin]):
            opts = dict(now='2026-11-13T04:00:00+08:00', archive_root=root, reader=reader, archive=workbook)
            preview = facts.seed(self.store, D1, D2, **opts)
            self.assertEqual(preview['missing_es_days'], [D2])
            self.assertEqual(preview['needs_native_identity_days'], [D1])
            reader.assert_not_called()
            applied = facts.seed(self.store, D1, D2, apply=True, **opts)
            reused = facts.seed(self.store, D1, D2, apply=True, **opts)
        self.assertEqual(applied['status'], 'partial')
        self.assertTrue(applied['publication_id'].startswith('se_'))
        self.assertEqual(reused['already_indexed'], [D1])
        reader.assert_called_once_with(D1)
        self.assertEqual(weekly.stored_publication(self.store), first)
        self.assertEqual(self.read()['coverage']['publication_id'], applied['publication_id'])

    def test_daily_publication_survives_independent_shared_mapping_failure(self):
        pub = publication(D2)
        weekly.write_publication(self.store, pub, None, shared_window=(D1, D2, None))
        with patch('shared_es_facts.prepare_publication', side_effect=OSError('fixture')):
            result = weekly.retry_shared_es(self.store, lambda: False)
        self.assertEqual(result[pub['publication_id']], {'status': 'pending', 'reason': 'OSError', 'retryable': True})
        self.assertEqual(weekly.stored_publication(self.store), pub)
        self.assertEqual(self.read()['status'], 'unavailable')

    def test_shared_publish_resume_after_commit_does_not_move_newer_active_pin(self):
        rev = self.stage(D1, archive(line('first', D1)), order('first', D1))
        first = publication(D2)
        weekly.write_publication(self.store, first, None, shared_window=(D1, D2, None))
        with self.store.db() as db:
            facts.bind_publication(db, first, None, {D1: rev})
        with patch('shared_es_facts.prepare_publication', side_effect=AssertionError('shared day already committed')):
            result = weekly.retry_shared_es(self.store, lambda: False)
            self.assertEqual(result[first['publication_id']]['status'], 'complete')
            self.assertEqual(weekly.retry_shared_es(self.store, lambda: False), {})
        later = publication(D3, 'b')
        with self.store.db() as db:
            facts.bind_publication(db, later, None, {})
            facts.bind_publication(db, first, None, {D1: rev})
            with self.assertRaisesRegex(ValueError, 'shared_es_publication_replay_conflict'):
                facts.bind_publication(db, first, None, {D1: 'different'})
            with self.assertRaisesRegex(ValueError, 'shared_es_publication_replay_conflict'):
                facts.bind_publication(db, dict(first, data_version='2'), None, {D1: rev})
        self.assertEqual(facts.latest_publication(db=self.store.path)['publication_id'], later['publication_id'])
        self.assertEqual(self.read(ident=first['publication_id'])['rows'][0]['order_no'], 'first')

    def test_cross_month_failed_days_keep_pins_and_catch_up_after_new_publication(self):
        old_day, start, cutoff = '2026-10-31', '2026-11-01', '2026-11-02'
        old = publication(start)
        new = publication(cutoff, 'b')
        weekly.write_publication(self.store, old, None, shared_window=(old_day, start, None))
        old_rev = self.stage(old_day, archive(line('old', old_day)), order('old', old_day))
        new_rev = self.stage(start, archive(line('new', start)), order('new', start))

        def failed_old(store, value, start_day, end_day, **_):
            if start_day == old_day:
                self.assertEqual(value['flag_manifests'], old['flag_manifests'])
                raise OSError('fixture')
            self.assertEqual(value['flag_manifests'], new['flag_manifests'])
            return {start: new_rev}

        with patch('shared_es_facts.prepare_publication', side_effect=failed_old):
            weekly.retry_shared_es(self.store, lambda: False)
            weekly.write_publication(self.store, new, old['publication_id'], shared_window=(start, cutoff, None))
            weekly.retry_shared_es(self.store, lambda: False)
        self.assertEqual(weekly.stored_publication(self.store), new)
        self.assertEqual(self.read(scope(old_day, start))['coverage']['missing_days'], [old_day])
        self.assertEqual([pending['pin']['publication_id'] for pending in facts.pending_publications(self.store)],
                         [old['publication_id']])
        from user_customer_types import archive_reference_state
        refs = archive_reference_state(self.store, self.store.root)
        self.assertEqual(set(refs['manifests']), {old['flag_manifests'][0]['name'], new['flag_manifests'][0]['name']})
        with patch('shared_es_facts.prepare_publication', return_value={old_day: old_rev}):
            weekly.retry_shared_es(self.store, lambda: False)
        current = self.read(scope(old_day, start))
        self.assertEqual(current['status'], 'available')
        self.assertEqual(current['coverage']['data_revision'], new['data_version'])
        self.assertEqual(self.read(scope(old_day, start), ident=new['publication_id'])['coverage']['missing_days'], [old_day])
        self.assertEqual(facts.pending_publications(self.store), [])

    def test_multi_day_run_prepares_all_missing_dates_from_publication_start(self):
        cutoff = '2026-11-13'
        old = publication(D1)
        candidate = publication(cutoff, 'b')
        weekly.write_publication(self.store, old, None)
        state = dict(contract='fs-users-weekly-work-v1', phase='publish', cadence='daily',
                     start=stamp(D1).isoformat(), cutoff=stamp(cutoff).isoformat(), base_publication=old['publication_id'])
        revisions = {day: self.stage(day, archive(line(day, day)), order(day, day)) for day in (D1, D2, D3)}
        self.store.config = {'sites': {'266': {}}}
        with patch.dict(sys.modules, user_jobs=Mock()), \
                patch.object(self.store, 'coverage', return_value=[]), patch('user_lifecycle.covered', return_value=True), \
                patch.object(weekly, 'snapshot_candidate', return_value=(candidate, {})), \
                patch('shared_es_facts.prepare_publication', return_value=revisions) as prepare, \
                patch('user_source.shared_discount_catalog',side_effect=PermissionError()) as discounts:
            result = weekly.run(self.store, state, old, stamp(cutoff + 'T04:18:00+08:00'), lambda: 0, shared_es=True)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(prepare.call_args.args[2:4], (D1, D3))
        self.assertEqual(self.read(scope(D1, D3))['coverage']['missing_days'], [])
        self.assertEqual(result['shared_es']['discount_catalog']['status'],'partial')
        discounts.assert_called_once()

    def test_closed_day_old_archive_receipt_uses_one_original_fresh_cycle(self):
        from user_customer_types import closed_period_bundle
        root = self.store.root
        index, attempt, legacy = (root / name for name in ('old.json', 'orig.attempt', 'legacy.attempt'))
        index.touch()
        snapshot = dict(value=dict(captured_at=D1 + 'T15:48:00+08:00', quality=dict(source_origin='private_archive_reuse')))
        es = SimpleNamespace(checked_query=lambda q: q, SERVER_LOCK=RLock(),
                             _receipt_paths=Mock(return_value=(index, attempt, legacy)),
                             _read_receipt=Mock(return_value=(dict(value=dict(status='available', snapshots=[snapshot])), 'fixture')),
                             _server_bundle=Mock(), server_bundle_after=Mock(return_value={'status': 'pending'}))
        query, cutoff = dict(start=D1, end=D1), stamp(D2)
        with patch.dict(sys.modules, es_order_structure=es):
            closed_period_bundle(query, cutoff, root)
            first = es.server_bundle_after.call_args
            closed_period_bundle(query, cutoff, root)
            self.assertEqual(es.server_bundle_after.call_args, first)
            es._server_bundle.assert_not_called()
            attempt.touch()
            closed_period_bundle(query, cutoff, root)
        self.assertEqual(es.server_bundle_after.call_count, 2)
        es._server_bundle.assert_called_once()

