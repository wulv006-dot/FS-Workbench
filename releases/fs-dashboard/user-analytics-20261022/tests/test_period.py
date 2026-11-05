"""Selected-period buyers, original ES entry flag, yesterday cutoff and repeat filters."""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from user_contract import checked_query, stamp, aggregate_only
from user_query import Service
from user_store import Store
from user_tools import invoke
from test_users import order

NOW=stamp('2026-10-23T12:00:00+08:00')


class Period(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'private'
        self.config=json.loads((Path(__file__).resolve().parents[1]/'source/user_config.json').read_text())
        self.store=Store(self.root,b'x'*32,self.config)
        self.flags={};self.flag_version=['v1']
        self.reader=lambda q:(dict(self.flags),dict(status='complete',source='fixture original ES flag',sourceVersion=self.flag_version[0]))
        self.service=Service(self.store,lambda u,q,p:u=='admin' or u=='reader' and not p,clock=lambda:NOW,customer_type_reader=self.reader)

    def load(self,rows,start='2026-07-01',end='2026-10-24'):
        self.store.replace_window('266',start,end,rows,NOW.isoformat())

    def flag(self,n,value):
        self.flags[hashlib.sha256(('test-'+str(n)).encode()).hexdigest()]=value

    def query(self,start='2026-07-01',**extra):
        return self.service.query(dict(start=start,**extra),'admin')

    def test_auto_yesterday_and_outside_customers_do_not_enter(self):
        self.load([order(1,'2026-09-01',email='before@example.test'),order(2,'2026-10-22',email='within@example.test'),order(3,'2026-10-23',email='today@example.test')])
        result=self.query('2026-10-01')
        self.assertEqual(result['query']['end_exclusive'],'2026-10-23T00:00:00+08:00')
        self.assertEqual(result['observation_date'],'2026-10-22')
        self.assertEqual(result['metrics']['known_pool']['value'],1)
        self.assertEqual(result['metrics']['waiting']['value'],1)
        self.assertEqual(result['repeat_rate']['denominator'],1)
        with self.assertRaisesRegex(ValueError,'ends_yesterday'):
            self.query(end_exclusive='2026-07-31')
        with self.assertRaisesRegex(ValueError,'ends_yesterday'):
            self.query(as_of='2026-10-22',state_basis='period_cohort')
        facts=self.store.read(analytics=True,start='2026-10-01',end='2026-10-23')[1]
        self.assertEqual(len(facts),1)

    def test_observation_policy_boundaries_and_frozen_consumers(self):
        from user_contract import OBSERVATION_POLICIES, POLICIES, state
        old = self.query('2026-07-01', policy_version='fc-v1')
        for version, points in OBSERVATION_POLICIES.items():
            with self.subTest(version=version):
                self.assertEqual(tuple(self.config['policies'][version]), points)
                self.assertEqual(POLICIES[version], points)
                a, b, c = points
                ages = (0, a-1, a, b-1, b, c-1, c)
                expected = ('recent', 'recent', 'silent', 'silent', 'lost', 'lost', 'long_lost')
                rows = []
                for n, (days, stage) in enumerate(zip(ages, expected), 1):
                    paid = NOW.replace(hour=0) - timedelta(days=days+1)
                    self.assertEqual(state(paid, (NOW-timedelta(days=1)).date(), points), stage)
                    rows.append(order(n, paid.isoformat(), email=f'boundary-{n}@example.test'))
                self.load(rows)
                result = self.query(policy_version=version)
                self.assertEqual(result['lifecycle_policy']['thresholds_days'], list(points))
                for stage, count in [('waiting',2), ('silent',2), ('lost',2), ('long_lost',1)]:
                    self.assertEqual(result['metrics'][stage]['value'], count)
                    args = dict(snapshot_id=result['snapshot_id'], group=stage)
                    self.assertEqual(self.service.members(args,'admin')['total'], count)
                    exported = self.service.export(args,'admin')
                    self.assertEqual(len(exported['rows']), count)
                self.assertEqual(result['trend'][-1]['stock']['long_lost'], 1)
                self.assertTrue(result['projects'])
                self.assertTrue(all(p['policy_version']==version for p in result['projects']))
                tool = invoke(self.service,'reader',dict(snapshot_id=result['snapshot_id']))
                self.assertEqual(tool['lifecycle_policy'], result['lifecycle_policy'])
                self.assertEqual(tool['metrics'], result['metrics'])
                self.assertEqual(self.service.query(dict(snapshot_id=old['snapshot_id']),'reader'), old)

    def test_observation_policy_keeps_selected_thresholds_for_project_matrix(self):
        self.load([order(1,'2026-10-02'),order(2,'2026-10-03',gid='2000')])
        for version in ('short-term-v1','long-term-v1'):
            for mode in ('per_project','uniform'):
                with self.subTest(version=version,mode=mode):
                    value = self.query(policy_version=version, policy_mode=mode, scope='project', scope_id='1327')
                    self.assertTrue(all(p['policy_version']==version for p in value['projects']))
                    self.assertEqual(value['metrics']['lost']['value'], int(version=='short-term-v1'))
                    self.assertEqual(value['metrics']['silent']['value'], int(version=='long-term-v1'))

    def test_email_search_is_exact_private_and_frozen(self):
        from user_http import search
        email='Case+tag@example.test'
        self.load([order(1,'2026-09-01',email=email),order(2,'2026-10-02',email=email),order(3,'2026-10-04',email=email),order(4,'2026-10-23',email=email)])
        snapshot=self.query('2026-10-01');args=dict(snapshot_id=snapshot['snapshot_id'],email=' '+email+' ')
        result=self.service.search(args,'admin')
        self.assertTrue(result['found']);self.assertEqual(len(result['orders']),2)
        self.assertEqual(result['timeline'][0]['days_from_observed_first'],0)
        self.assertEqual(search(self.service,args,'reader')[0],403)
        self.assertEqual(search(self.service,args,None)[0],401)
        self.assertFalse(self.service.search(dict(args,email=email.lower()),'admin')['found'])
        self.assertFalse(self.service.search(dict(args,email='Case@example.test'),'admin')['found'])
        with self.store.db() as db:before=db.execute('SELECT count(*) FROM identities').fetchone()[0]
        self.assertFalse(self.service.search(dict(args,email='absent@example.test'),'admin')['found'])
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM identities').fetchone()[0],before)
        self.load([order(9,'2026-10-05',email=email)])
        self.assertEqual(self.service.search(args,'admin')['orders'],result['orders'])
        for invalid in ('x','a@b\n','a'*321+'@b',None):
            self.assertEqual(search(self.service,dict(args,email=invalid),'admin')[0],422)

    def test_email_search_respects_project_and_long_email(self):
        email='a'*170+'@example.test'
        self.load([order(1,'2026-10-02',email=email),dict(order(2,'2026-10-03',email=email),gid='999')])
        snapshot=self.query(scope='project',scope_id='1327')
        result=self.service.search(dict(snapshot_id=snapshot['snapshot_id'],email=email),'admin')
        self.assertTrue(result['found']);self.assertEqual(len(result['orders']),1)
        self.assertEqual(result['orders'][0]['project_id'],'1327')

    def test_search_miss_does_not_claim_missing_identity_or_complete_data(self):
        self.load([order(1,'2026-09-01',email='before@example.test')])
        snapshot=self.query('2026-10-01')
        result=self.service.search(dict(snapshot_id=snapshot['snapshot_id'],email='before@example.test'),'admin')
        self.assertFalse(result['found']);self.assertTrue(result['period_complete'])

    def test_entry_flag_and_repeat_are_period_specific(self):
        self.load([dict(order(1,'2026-07-01'),isNew=True),dict(order(2,'2026-10-10'),isNew=True),order(3,'2026-10-11',email='b@example.test'),order(4,'2026-10-12',email='b@example.test')])
        self.flag(2,'old');self.flag(3,'new');self.flag(4,'old')
        result=self.query('2026-10-01')
        self.assertEqual([result['metrics'][k]['value'] for k in ('purchasers','new_purchasers','old_flag_purchasers','repeat_purchasers','waiting','recent')],[2,1,1,1,1,1])
        self.assertEqual(result['repeat_rate']['rate'],.5)
        row=self.service.members(dict(snapshot_id=result['snapshot_id'],group='waiting'),'admin')['rows'][0]
        self.assertEqual(row['period_first_paid_at'],'2026-10-10T00:00:00+08:00')
        self.assertFalse(row['period_repeated'])
        self.assertEqual(row['period_entry_customer_type'],'old')
        detail=self.service.detail(dict(snapshot_id=result['snapshot_id'],customer_id=row['customer_id']),'admin')
        self.assertEqual(len(detail['orders']),1)
        self.assertEqual(detail['timeline'][0]['days_from_observed_first'],0)
        self.assertEqual(detail['timeline'][0]['stage'],'waiting')

    def test_same_second_entry_uses_original_order_id(self):
        self.load([order(2,'2026-10-01 12:00:00'),order(1,'2026-10-01 12:00:00')])
        self.flag(1,'new');self.flag(2,'old')
        value=self.query()
        self.assertEqual(value['metrics']['new_purchasers']['value'],1)
        self.assertEqual(value['metrics']['repeat_purchasers']['value'],1)

    def test_repeat_buyers_can_sleep_and_filters_export_same_rows(self):
        self.load([order(1,'2026-08-01',email='repeat@example.test'),order(2,'2026-09-01',email='repeat@example.test'),order(3,'2026-09-01',email='once@example.test')])
        self.flag(1,'old');self.flag(3,'new')
        value=self.query();sid=value['snapshot_id']
        self.assertEqual(value['metrics']['silent']['value'],2)
        row=next(r for r in value['repeat_states'] if r['stage']=='silent')
        self.assertEqual((row['repeated'],row['not_repeated']),(1,1))
        args=dict(snapshot_id=sid,group='silent',repeat_status='repeated',customer_type='old')
        members=self.service.members(args,'admin');export=self.service.export(args,'admin')
        self.assertEqual(members['total'],1);self.assertEqual(members['rows'],export['rows'])
        self.assertEqual(self.service.members(dict(args,customer_type='new'),'admin')['total'],0)
        with self.assertRaises(PermissionError):self.service.members(args,'reader')
        with self.assertRaises(ValueError):self.service.members(dict(args,repeat_status='maybe'),'admin')

    def test_missing_and_conflicting_es_flags_are_not_old(self):
        self.load([order(1,'2026-10-01'),order(2,'2026-10-02',email='b@example.test')])
        self.flag(1,'conflict')
        value=self.query()
        self.assertEqual(value['metrics']['customer_type_unknown']['value'],2)
        self.assertEqual(value['metrics']['old_flag_purchasers']['value'],0)
        self.assertEqual(self.service.members(dict(snapshot_id=value['snapshot_id'],group='purchasers',customer_type='unknown'),'admin')['total'],2)

    def test_es_failure_leaves_flags_unknown_and_other_metrics_available(self):
        self.load([order(1,'2026-10-01')])
        def failed(query):raise ValueError('unsafe_private_archive')
        self.service.customer_type_reader=failed
        value=self.query()
        self.assertEqual(value['customer_type_source']['status'],'unavailable')
        self.assertEqual(value['metrics']['purchasers']['value'],1)
        self.assertEqual(value['metrics']['customer_type_unknown']['value'],1)
        self.assertEqual(value['metrics']['old_flag_purchasers']['value'],0)

    def test_mature_horizon_starts_at_period_entry_for_old_and_new(self):
        self.load([order(1,'2026-10-01'),order(2,'2026-10-08'),order(3,'2026-10-21',email='late@example.test')])
        self.flag(1,'old');self.flag(3,'new')
        value=self.query('2026-10-01')
        self.assertEqual(value['cohort']['denominator'],1)
        self.assertEqual(value['cohort']['numerator'],0)  # exactly D0+7 is outside [D0,D0+7).
        self.assertEqual(value['cohort']['observing'],1)
        self.assertEqual(value['cohort']['first_unverified'],0)

    def test_flag_revision_and_today_change_keep_original_snapshot(self):
        self.load([order(1,'2026-09-01')]);self.flag(1,'new')
        before=self.query()
        self.flag(1,'old');self.flag_version[0]='v2'
        after=self.query()
        self.assertNotEqual(before['snapshot_id'],after['snapshot_id'])
        self.assertEqual(self.service.query(dict(snapshot_id=before['snapshot_id']),'reader'),before)
        tool=invoke(self.service,'reader',dict(snapshot_id=before['snapshot_id']))
        self.assertEqual(tool['metrics'],before['metrics']);self.assertIn('Only purchasing emails',tool['interpretation']['stock'])
        aggregate_only(tool)
        self.assertLess(len(json.dumps(tool)),20000)

    def test_daily_waiting_becomes_repeated_and_matches_final(self):
        self.load([order(1,'2026-10-20'),order(2,'2026-10-22')])
        value=self.query('2026-10-20')
        self.assertEqual(value['trend'][0]['stock']['waiting'],1)
        self.assertEqual(value['trend'][-1]['stock']['waiting'],0)
        self.assertEqual(value['trend'][-1]['stock']['recent'],1)
        self.assertEqual(sum(r['period_entries'] for r in value['trend']),1)

    def test_archive_reader_reuses_only_all_profile_closed_day_exports(self):
        from user_customer_types import read_flags
        root=self.root/'es';root.mkdir(mode=0o700)
        for name,profile,end,capture in [('good','ALL','2026-10-21','2026-10-22T00:01:00+08:00'),('open','ALL','2026-10-22','2026-10-22T12:00:00+08:00'),('project','FC27','2026-10-21','2026-10-22T01:00:00+08:00')]:
            p=root/(name+'.json');p.write_text(json.dumps(dict(query=dict(profile=profile,status='all',start='2026-10-01',end=end),captured_at=capture)));p.chmod(0o600)
        called=[]
        def original(start,end,names,archive):
            called.append(names);return {'hashed-order':'\u65b0\u5ba2'},dict(status='complete',sourceVersion='fixture',orderSources={'private':'must not leave'})
        module=types.ModuleType('channel_source');module.customer_types=original
        before_path=list(sys.path)
        dashboard=Path(__file__).resolve().parents[2]
        dependencies=[str(dashboard/'cache-archive-retention-20261025/source'),str(dashboard/'fs-business-baseline-20261021/source')]
        with patch.object(sys,'path',[*sys.path,*dependencies]),patch.dict(sys.modules,channel_source=module):
            flags,meta=read_flags(dict(start='2026-10-01',end_exclusive='2026-10-22'),root)
        self.assertEqual(sys.path,before_path)
        self.assertEqual(called,[('good.json',)]);self.assertEqual(flags['hashed-order'],'new');self.assertNotIn('orderSources',meta)

    def test_original_timer_only_reuses_or_polls_existing_es_source(self):
        import user_customer_types as flags
        source=types.ModuleType('es_order_structure');calls=[]
        source.server_bundle=lambda q:(calls.append(q) or dict(status='pending'))
        with patch.object(flags,'read_flags',return_value=({},dict(status='complete',sourceVersion='v'))),patch.dict(sys.modules,es_order_structure=source):
            self.assertEqual(flags.ensure_closed_month(NOW)['status'],'reused');self.assertEqual(calls,[])
        with patch.object(flags,'read_flags',return_value=({},dict(status='partial'))),patch.dict(sys.modules,es_order_structure=source):
            self.assertEqual(flags.ensure_closed_month(NOW)['status'],'pending')
        self.assertEqual(calls,[dict(profile='ALL',start='2026-10-01',end='2026-10-22',group_by='new_customer',status='all')])


if __name__=='__main__':unittest.main()
