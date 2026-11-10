from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

from _paths import ROOT, RELEASE
from customer_tracking import AdminService, DEFAULT_CONFIG, Store, candidate_rows, checked_config, verified_identity


def es(order='ORDER-1',**changes):
    row={'游戏':'FC 27','产品类型':'货币(Gold)','订单号':order,
        '订单金额（美元）':'500.01','实付金额':'440','实付币种':'EUR',
        '折扣金额':'24.99','是否新客户':'是','付款时间':'2026-10-17 12:00:00'}
    return dict(row,**changes)


def admin(order='ORDER-1',**changes):
    return dict({'order_no':order,'gid':1327,'site_id':266,'pay_status':1,
        'email':'guest@example.invalid','uid':0,'amount':'500.01'},**changes)


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(self.temp.name)
        self.now=datetime(2026,10,18,12,tzinfo=timezone.utc)
    def tearDown(self):self.temp.cleanup()

    def test_phase_one_fc_only_and_numeric_amount_equivalence(self):
        with self.assertRaisesRegex(ValueError,'phase_one_fc_only'):
            checked_config(dict(DEFAULT_CONFIG,profile='D4'))
        items,_=candidate_rows([es()],{'ORDER-1':admin(amount='500.010')},DEFAULT_CONFIG)
        self.assertFalse(items[0]['amount_conflict'])
        self.assertEqual(self.store.config()['enabled_profiles'],['FC27'])

    def test_multi_line_order_combines_types_but_conflicting_money_excludes(self):
        coin=es()
        item=es(**{'产品类型':'物品(Items)'})
        rows,coverage=candidate_rows([coin,item],{'ORDER-1':admin()},DEFAULT_CONFIG)
        self.assertEqual(len(rows),1)
        self.assertEqual(set(rows[0]['product_types']),{'货币(Gold)','物品(Items)'})
        self.assertEqual(coverage['conflicts'],0)
        changed=es(**{'产品类型':'物品(Items)','折扣金额':'24.98'})
        rows,coverage=candidate_rows([coin,changed],{'ORDER-1':admin()},DEFAULT_CONFIG)
        self.assertEqual(rows,[])
        self.assertEqual(coverage['excluded']['conflicting_order_rows'],1)
        high_discount=es(**{'产品类型':'物品(Items)','折扣金额':'30'})
        rows,coverage=candidate_rows([coin,high_discount],{'ORDER-1':admin()},DEFAULT_CONFIG)
        self.assertEqual(rows,[])
        self.assertEqual(coverage['conflicts'],1)

    def test_history_observation_exact_email_guest_cross_game_and_whitelist(self):
        candidate=self.store.save_candidates('2026-10-17',candidate_rows([es()],{'ORDER-1':admin()},DEFAULT_CONFIG)[0])['items'][0]
        track=self.store.track(candidate['candidate_id'],'f'*32,now=self.now)
        rows=[dict(order_no='NEXT-1',email='guest@example.invalid',uid=0,gid=1327,site_id=266,
                   paid_at='2026-10-20 12:00:00',pay_status=1,current_status='paid',order_usd='60',secret='never-store'),
              dict(order_no='NEXT-2',email='guest@example.invalid',uid=44,gid=891,site_id=266,
                   paid_at='2026-10-21 12:00:00',pay_status=1,current_status='paid',order_usd='40'),
              dict(order_no='OTHER-1',email='payer@example.invalid',uid=0,gid=1327,site_id=266,
                   paid_at='2026-10-21 12:00:00',pay_status=1,current_status='paid',order_usd='90')]
        result=self.store.observe(track['tracking_id'],rows)
        self.assertEqual(result['matched_source_orders'],2)
        detail=self.store.detail(track['tracking_id'])
        orders={row['order_no']:row for row in detail['orders']}
        self.assertEqual(orders['NEXT-1']['uid'],0)
        self.assertFalse(orders['NEXT-2']['selected_game'])
        self.assertNotIn('OTHER-1',orders)
        self.assertNotIn('never-store',json.dumps(detail))

    def test_strict_thresholds_and_separate_money(self):
        rows=[es(),es('ORDER-2',**{'订单金额（美元）':'500'}),
            es('ORDER-3',**{'折扣金额':'25'}),es('ORDER-4',**{'实付金额':'100000','实付币种':'JPY','是否新客户':'?'})]
        matches,coverage=candidate_rows(rows,{'ORDER-1':admin(),'ORDER-2':admin('ORDER-2',amount='500'),
            'ORDER-3':admin('ORDER-3'),'ORDER-4':admin('ORDER-4',amount='500.01')},DEFAULT_CONFIG)
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0]['order_usd'],'500.01')
        self.assertEqual(matches[0]['payment'],{'amount':'440','currency':'EUR'})
        self.assertEqual(matches[0]['discount_usd'],'24.99')
        self.assertEqual(coverage['excluded']['criteria_not_met'],3)
        selected,_=candidate_rows(rows,{'ORDER-4':admin('ORDER-4',amount='500.01')},
            dict(DEFAULT_CONFIG,customer_flags=['unknown']))
        self.assertEqual(selected[0]['customer_flag'],'unknown')
        self.assertEqual(selected[0]['payment']['currency'],'JPY')

    def test_guest_email_verified_payment_email_never_substitutes(self):
        item,_=candidate_rows([es()],{'ORDER-1':admin()},DEFAULT_CONFIG)
        self.assertEqual(item[0]['identity_status'],'verified')
        self.assertEqual(item[0]['uid'],0)
        missing=verified_identity(item[0],dict(admin(),email=None,payment_email='payer@example.invalid'))
        self.assertEqual(missing['identity_status'],'unavailable')
        self.assertEqual(missing['identity_reason'],'email_missing_or_invalid')
        self.assertNotIn('email',missing)
        mismatch=verified_identity(item[0],admin(amount='501'))
        self.assertEqual(mismatch['identity_status'],'verified')
        self.assertEqual(mismatch['admin_order_usd'],'501')

    def test_same_buyer_different_admin_emails_cannot_be_tracked_as_one(self):
        rows=[es('ORDER-1',buyer_id='buyer-a'),es('ORDER-2',buyer_id='buyer-a')]
        admin_rows={'ORDER-1':admin('ORDER-1'),
                    'ORDER-2':admin('ORDER-2',email='different@example.invalid')}
        items,coverage=candidate_rows(rows,admin_rows,DEFAULT_CONFIG)
        self.assertEqual(len(items),2)
        self.assertEqual(coverage['buyer_email_conflicts'],1)
        self.assertTrue(all(item['identity_status']=='unavailable' for item in items))
        self.assertTrue(all('email' not in item for item in items))

    def test_unmatched_or_wrong_site_order_never_enters_main_site_candidates(self):
        rows=[es('ORDER-1'),es('ORDER-2'),es('ORDER-3')]
        items,coverage=candidate_rows(rows,{'ORDER-2':admin('ORDER-2',site_id=999),
            'ORDER-3':admin('ORDER-3',email=None)},DEFAULT_CONFIG)
        self.assertEqual([item['order_no'] for item in items],['ORDER-3'])
        self.assertEqual(items[0]['identity_status'],'unavailable')
        self.assertEqual(coverage['excluded']['order_no_unmatched'],1)
        self.assertEqual(coverage['excluded']['admin_scope_mismatch'],1)

    def test_historical_pending_scan_recovers_and_config_change_fences_old_job(self):
        self.store.begin_scan('2026-10-01','1'*32)
        self.store.begin_scan('2026-10-04','2'*32)
        self.assertEqual(self.store.pending_scans(),['2026-10-01','2026-10-04'])
        self.store.save_config(dict(DEFAULT_CONFIG,enabled=False),1,'3'*32)
        self.assertEqual(self.store.pending_scans(),[])
        with self.store.db() as db:
            rows=db.execute('SELECT state,reason FROM scan_jobs ORDER BY day').fetchall()
        self.assertEqual([(row['state'],row['reason']) for row in rows],
            [('failed','scan_config_changed'),('failed','scan_config_changed')])

    def test_admin_only_manual_tracking_idempotent_and_email_across_uids(self):
        entries,_=candidate_rows([es(),es('ORDER-2')],
            {'ORDER-1':admin(),'ORDER-2':admin('ORDER-2',uid=123)},DEFAULT_CONFIG)
        ids=self.store.save_candidates('2026-10-17',entries)['items']
        service=AdminService(self.store,lambda user:user=='admin')
        with self.assertRaises(PermissionError):service.get('ordinary','candidates',date='2026-10-17')
        with self.assertRaises(PermissionError):service.post('ordinary',{'kind':'hermes_customer_tracking',
            'action':'track','candidate_id':ids[0]['candidate_id'],'request_id':'a'*32})
        first=service.post('admin',{'kind':'hermes_customer_tracking','action':'track',
            'candidate_id':ids[0]['candidate_id'],'request_id':'a'*32})
        again=service.post('admin',{'kind':'hermes_customer_tracking','action':'track',
            'candidate_id':ids[0]['candidate_id'],'request_id':'a'*32})
        self.assertEqual(first['tracking_id'],again['tracking_id'])
        self.assertFalse(first['reused']);self.assertTrue(again['reused'])
        self.assertEqual(service.get('admin','request',id='a'*32)['result']['tracking_id'],first['tracking_id'])
        second=self.store.track(ids[1]['candidate_id'],'b'*32,now=self.now+timedelta(days=1))
        self.assertEqual(second['tracking_id'],first['tracking_id'])
        self.assertEqual(second['tracked_at'],first['tracked_at'])
        self.assertEqual(len(self.store.listed()['items']),1)
        milestones=self.store.detail(first['tracking_id'])['milestones']
        self.assertEqual([m['days'] for m in milestones],[0,7,14,30])
        self.assertTrue(all(m['state']=='scheduled' for m in milestones))
        for milestone in milestones:
            self.assertEqual(datetime.fromisoformat(milestone['due_at'])-datetime.fromisoformat(first['tracked_at']),timedelta(days=milestone['days']))

    def test_empty_complete_scan_is_not_missing_and_identity_unavailable_cannot_track(self):
        self.assertEqual(self.store.candidates('2026-10-17')['status'],'unavailable')
        self.store.save_candidates('2026-10-17',[],{'es_rows':12,'criteria_matches':0})
        self.assertEqual(self.store.candidates('2026-10-17')['status'],'available')
        self.assertEqual(self.store.candidates('2026-10-17')['items'],[])
        entries,_=candidate_rows([es()],{'ORDER-1':admin(email=None,payment_email='payer@example.invalid')},DEFAULT_CONFIG)
        item=self.store.save_candidates('2026-10-18',entries)['items'][0]
        with self.assertRaises(ValueError):self.store.track(item['candidate_id'],'c'*32)

    def test_config_cas_and_request_conflict(self):
        config=self.store.config();value={k:v for k,v in config.items() if k in DEFAULT_CONFIG}
        changed=dict(value,min_order_usd_exclusive='600')
        result=self.store.save_config(changed,1,'d'*32)
        self.assertEqual(result['version'],2)
        self.assertEqual(self.store.config()['last_request_id'],'d'*32)
        self.assertEqual(self.store.save_config(changed,1,'d'*32),result)
        with self.assertRaises(ValueError):self.store.save_config(value,1,'d'*32)
        with self.assertRaises(ValueError):self.store.save_config(value,1,'e'*32)
        with self.assertRaises(ValueError):checked_config(dict(value,site_id=1))

    def test_rescan_preserves_trigger_audit_but_uses_current_membership_and_config(self):
        first,_=candidate_rows([es()],{'ORDER-1':admin()},DEFAULT_CONFIG)
        saved=self.store.save_candidates('2026-10-17',first,{'complete':True})
        ident=saved['items'][0]['candidate_id']
        changed=[dict(first[0],order_usd='510',admin_order_usd='510')]
        self.store.save_candidates('2026-10-17',changed,{'complete':True})
        self.assertEqual(self.store.candidates('2026-10-17')['items'][0]['order_usd'],'510')
        with self.store.db() as db:
            row=db.execute('SELECT first_body,latest_body FROM candidates WHERE id=?',(ident,)).fetchone()
            audit=db.execute('SELECT COUNT(*) FROM candidate_history WHERE id=?',(ident,)).fetchone()[0]
        self.assertEqual(json.loads(row['first_body'])['order_usd'],'500.01')
        self.assertEqual(json.loads(row['latest_body'])['order_usd'],'510')
        self.assertEqual(audit,1)
        self.store.save_candidates('2026-10-17',[],{'complete':True})
        self.assertEqual(self.store.candidates('2026-10-17')['items'],[])
        config={k:v for k,v in self.store.config().items() if k in DEFAULT_CONFIG}
        self.store.save_config(dict(config,min_order_usd_exclusive='600'),1,'f'*32)
        self.assertEqual(self.store.candidates('2026-10-17')['status'],'unavailable')
        with self.assertRaises(ValueError):self.store.track(ident,'1'*32)

    def test_negative_refund_like_values_never_auto_qualify(self):
        rows=[es('NEGATIVE-DISCOUNT',**{'折扣金额':'-1'}),
            es('NEGATIVE-ORDER',**{'订单金额（美元）':'-600'}),
            es('NEGATIVE-PAID',**{'实付金额':'-1'})]
        items,coverage=candidate_rows(rows,{},DEFAULT_CONFIG)
        self.assertEqual(items,[])
        self.assertEqual(coverage['excluded']['order_or_money_missing'],3)

    def test_rescan_conflicting_customer_email_disables_tracking(self):
        first,_=candidate_rows([es()],{'ORDER-1':admin()},DEFAULT_CONFIG)
        ident=self.store.save_candidates('2026-10-17',first)['items'][0]['candidate_id']
        second,_=candidate_rows([es()],{'ORDER-1':admin(email='different@example.invalid')},DEFAULT_CONFIG)
        self.store.save_candidates('2026-10-17',second)
        value=self.store.candidates('2026-10-17')['items'][0]
        self.assertEqual(value['identity_reason'],'customer_email_conflict')
        self.assertNotIn('email',value)
        with self.assertRaises(ValueError):self.store.track(ident,'2'*32)


if __name__=='__main__':unittest.main()
