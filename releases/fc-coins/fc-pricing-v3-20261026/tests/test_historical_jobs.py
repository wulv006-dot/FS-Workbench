from contextlib import closing
from datetime import datetime,timedelta,timezone
import json,sqlite3,subprocess,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'source';sys.path.insert(0,str(SOURCE))
from fc_pricing_v3 import api,history,scheduler,simulation,shadow_worker
from fc_pricing_v3.ledger import Ledger
from fc_pricing_v3.financial import fingerprint

NOW=datetime(2026,10,26,15,59,tzinfo=timezone.utc)


class HistoricalJobs(unittest.TestCase):
    def test_daily_dispatch_reads_actual_two_mode_worker_reply_and_ignores_legacy_report(self):
        date=(datetime.now(timezone.utc)-timedelta(days=3)).date().isoformat()
        for legacy_exists in (False,True):
          with self.subTest(legacy_exists=legacy_exists),tempfile.TemporaryDirectory() as folder:
            root=Path(folder);db=Ledger(root/'control.db')
            if legacy_exists:
                (root/('daily-'+date+'.json')).write_text(json.dumps(dict(local_date=date,legacy_five=True)))
            result=shadow_worker.run_daily(root/'control.db',root/'shadow.db',date)
            self.assertTrue(all(set(p['results'])=={'daily','revenue_sprint'} for p in result['periods']))
            with patch.object(history,'STATE',root),patch.object(history.subprocess,'run') as commands:
                received=history.ensure_shadow(db,'daily','original',date)
                repeated=history.ensure_shadow(db,'daily','original',date)
            self.assertEqual(received,dict(status='completed',result=result))
            self.assertEqual(repeated,received)
            commands.assert_not_called()
            self.assertEqual(db.all('operations'),[])

    def test_request_reused_across_midnight_freezes_original_paid_window(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.db')
            data=dict(request_key='one',kind='actual_reconstruction',closed_days='month')
            with patch.object(api,'ledger',return_value=db),patch.object(api,'clock',return_value=NOW):first=api.post('simulations',data,'wulv')
            with patch.object(api,'ledger',return_value=db),patch.object(api,'clock',return_value=NOW+timedelta(minutes=2)):again=api.post('simulations',data,'wulv')
            self.assertEqual(first,again)
            self.assertEqual(first['paid_window'],dict(start='2026-09-01',end_exclusive='2026-10-01',timezone='Asia/Shanghai'))
            with db.connect() as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM durable_jobs WHERE kind='history'").fetchone()[0],1)
                self.assertEqual(conn.execute("SELECT count(*) FROM event_outbox").fetchone()[0],0)

    def test_private_provider_runs_once_and_public_outbox_contains_only_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);db=Ledger(root/'control.db');output=root/'shadow';output.mkdir()
            with patch.object(api,'ledger',return_value=db),patch.object(api,'clock',return_value=NOW):
                request=api.post('simulations',dict(request_key='one',kind='actual_reconstruction',closed_days=7),'wulv')
            private=dict(period_selector='explicit_closed_period',paid_window=request['paid_window'],as_of=NOW.isoformat(),available_at=NOW.isoformat(),source_sha256='a'*64,
                historical_orders=[dict(order_key='private-original',paid_at='2026-10-20T10:00:00+08:00',available_at=NOW.isoformat(),paid_usd='10',source_sha256='b'*64)],
                historical_orders_coverage=dict(period_selector='explicit_closed_period',period=dict(start='2026-10-19',end='2026-10-25'),status='partial',eligible_count=1,
                    paid_window_start='2026-10-19T00:00:00+08:00',paid_window_end_exclusive='2026-10-26T00:00:00+08:00',as_of=NOW.isoformat(),source_sha256='a'*64,gaps={}))
            process=SimpleNamespace(returncode=0,stdout=json.dumps(private))
            with patch.object(history,'ledger',return_value=db),patch.object(history.subprocess,'run',return_value=process) as collect,patch.object(history,'ensure_shadow',return_value=dict(status='completed',result=dict(cursor=1))),patch.object(scheduler,'export_shadow_snapshot'):
                first=history.run(dict(simulation_id=request['simulation_id']));again=history.run(dict(simulation_id=request['simulation_id']))
            self.assertEqual(collect.call_count,1);self.assertEqual(first,again)
            stored=db.get('historical_inputs',first['historical_input_id'])
            self.assertEqual(stored['historical_orders'][0]['order_key'],'private-original')
            self.assertEqual(stored['period_selector'],'7d')
            with db.connect() as conn:
                raw=conn.execute('SELECT body FROM event_outbox').fetchone()[0]
                self.assertNotIn('private-original',raw);self.assertNotIn('paid_usd',raw)
                self.assertEqual(json.loads(raw)['historical_input_id'],first['historical_input_id'])

    def test_original_shadow_failure_does_not_restart_forever(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);db=Ledger(root/'control.db')
            def runner(command,**kwargs):return SimpleNamespace(returncode=0,stdout='ActiveState=inactive\n')
            def save(path,value):path.write_text(json.dumps(value))
            with patch.object(history,'STATE',root),patch.object(history,'write_json',side_effect=save),patch.object(history.subprocess,'run',side_effect=runner) as calls:
                self.assertEqual(history.ensure_shadow(db,'historical','original')['status'],'pending')
                self.assertEqual(history.ensure_shadow(db,'historical','original')['status'],'failed')
                self.assertEqual(history.ensure_shadow(db,'historical','original')['status'],'failed')
            starts=[c for c in calls.call_args_list if c.args[0][1]=='start']
            self.assertEqual(len(starts),1);self.assertEqual(len(db.all('incidents')),1)

    def test_unknown_start_reconciles_original_without_a_second_submit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);db=Ledger(root/'control.db')
            def runner(command,**kwargs):
                if command[1]=='start':raise subprocess.TimeoutExpired(command,15)
                return SimpleNamespace(stdout='ActiveState=inactive\n')
            with patch.object(history,'STATE',root),patch.object(history,'write_json',side_effect=lambda p,v:p.write_text(json.dumps(v))),patch.object(history.subprocess,'run',side_effect=runner) as calls:
                first=history.ensure_shadow(db,'historical','original');again=history.ensure_shadow(db,'historical','original')
                self.assertEqual((first['status'],again['status']),('unknown','unknown'))
            self.assertEqual(sum(c.args[0][1]=='start' for c in calls.call_args_list),1)

    def test_daily_and_history_use_independent_cursors_and_manual_history_does_not_run_five(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.db';destination=root/'shadow.db'
            with closing(sqlite3.connect(source)) as db,db:
                db.executescript('CREATE TABLE pricing_snapshots(id TEXT PRIMARY KEY,body TEXT);CREATE TABLE event_outbox(id INTEGER PRIMARY KEY,kind TEXT,body TEXT);')
                db.execute('INSERT INTO pricing_snapshots VALUES (?,?)',('future',json.dumps(dict(snapshot_id='future',created_at='2026-10-27T12:00:00+00:00',evidence={}))))
                db.execute('INSERT INTO event_outbox VALUES (1,?,?)',('snapshot_ready',json.dumps(dict(snapshot_id='future'))))
                db.execute('INSERT INTO event_outbox VALUES (2,?,?)',('simulation_requested',json.dumps(dict(simulation_id='original',requested_at=NOW.isoformat(),kind='actual_reconstruction',closed_days=7))))
            shadow=simulation.Shadow(destination)
            with patch.object(shadow,'historical',return_value=dict(status='available')) as calculate,patch.object(shadow,'snapshot') as five:
                result=shadow.consume(source,historical_only=True)
            self.assertEqual(result['cursor'],2);calculate.assert_called_once();five.assert_not_called()
            with shadow.connect() as db:
                self.assertEqual(db.execute("SELECT value FROM cursor WHERE id='historical'").fetchone()[0],2)
                self.assertIsNone(db.execute("SELECT value FROM cursor WHERE id='production'").fetchone())

    def test_missing_original_history_result_is_not_reported_completed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);shadow=simulation.Shadow(root/'shadow.db')
            with patch.object(shadow_worker,'Shadow',return_value=shadow),patch.object(shadow,'consume',return_value=dict(status='processed',events=0,cursor=0)):
                with self.assertRaisesRegex(ValueError,'shadow_original_history_result_missing'):
                    shadow_worker.run_historical(root/'production.db',root/'shadow.db','original')
            self.assertFalse((root/'history-original.json').exists())

    def test_shadow_response_keeps_original_hash_without_repeated_private_proofs(self):
        row=dict(policy='daily',revenue='25',result=dict(status='READY',selected=dict(action={'base_prices':{'console':'8.51'}},score={'revenue':'25'}),
            candidates=[dict(financial_proof={'private_order_rows':['secret']*10000}) for _ in range(93)]),gaps=['gap']*30)
        original=fingerprint(row)
        projected=api.shadow_projection(row)
        self.assertEqual(projected['original_record_sha256'],original)
        self.assertEqual(projected['result']['candidate_count'],93)
        self.assertEqual(projected['result']['action'],row['result']['selected']['action'])
        self.assertEqual(len(projected['gaps']),10)
        self.assertLess(len(json.dumps(projected).encode()),10000)
        self.assertNotIn('secret',json.dumps(projected))
        self.assertEqual(fingerprint(row),original)


if __name__=='__main__':unittest.main()
