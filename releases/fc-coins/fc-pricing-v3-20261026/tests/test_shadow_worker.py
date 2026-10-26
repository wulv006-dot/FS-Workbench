import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path.insert(0, str(SOURCE))
from fc_pricing_v3 import api, runtime, shadow_worker, simulation
from fc_pricing_v3 import scheduler


def evidence(at):
    return dict(checked_at=at.isoformat(),
        storefront=dict(rows={p:dict(package_usd='10') for p in ('PS','XBOX','PC')}),
        historical_discount_mix=dict(retained_ratio='.9',net_order_usd='630',undiscounted_order_usd='700'),
        promotion_envelope=dict(packages={p:dict(tiers=[dict(base_k=100,bonus_k=0,retained_ratio='1')]) for p in ('PS','XBOX','PC')}),
        region_rules=[],monthly_target=dict(amount='1000',mtd='100'),
        demand_model=dict(groups={g:dict(orders_per_block='1',reference_regular_usd='10',
            new_customer_ratio='.2',delivered_k_per_order='100') for g in ('console','pc')}),
        daily_net_revenue_7d=dict(console='100',pc='100'),backlog_k='0',capacity_k_per_block='200')


def evaluate(*args, **kwargs):
    action=dict(base_prices=dict(console='10',pc='10'),region_coefficients={})
    groups={g:dict(orders='1',revenue='10',contribution='5',concession='0',
                   negative_contribution='0',new_customers='.2') for g in ('console','pc')}
    choice=dict(action=action,score=dict(groups=groups,regional_predictions=[],absolute_forecast_available=True))
    return dict(status='READY',candidates=[choice],selected=choice,failures=[])


class ShadowWorkerContracts(unittest.TestCase):
    def test_live_snapshot_uses_final_creation_asof_after_later_sources(self):
        at=datetime(2026,10,26,tzinfo=timezone.utc)
        final=at+timedelta(minutes=3)
        observed=evidence(at)
        observed['fx']=dict(checked_at=(at+timedelta(minutes=2)).isoformat())
        observed['historical_orders_coverage']=dict(available_at=(at+timedelta(minutes=2,seconds=55)).isoformat())
        snapshot=dict(snapshot_id='live',origin='live_collector',created_at=final.isoformat(),evidence=observed)
        with tempfile.TemporaryDirectory() as folder, patch.object(simulation,'evaluate',side_effect=evaluate):
            shadow=simulation.Shadow(Path(folder)/'shadow.db')
            shadow.snapshot(snapshot,cursor=1)
            with shadow.connect() as db:
                rows=[json.loads(item[0]) for item in db.execute('SELECT body FROM runs')]
                row=next(item for item in rows if item.get('simulation_kind')=='same_real_snapshot')
                cursor=db.execute("SELECT value FROM cursor WHERE id='production'").fetchone()[0]
            self.assertEqual(row['as_of'],final.isoformat())
            self.assertEqual(cursor,1)
            with self.assertRaisesRegex(ValueError,'pricing_shadow_snapshot_before_history_available'):
                shadow.snapshot(dict(snapshot,created_at=(at+timedelta(minutes=2)).isoformat()),cursor=2)
            with shadow.connect() as db:
                self.assertEqual(db.execute("SELECT value FROM cursor WHERE id='production'").fetchone()[0],1)

    def test_worker_paths_match_runtime_writer_store_and_api_reader(self):
        self.assertEqual(shadow_worker.PRODUCTION,scheduler.SHADOW_EXPORT)
        self.assertEqual(scheduler.SHADOW_EXPORT.parent,runtime.STORE)
        self.assertNotEqual(shadow_worker.PRODUCTION,runtime.STORE/'control.sqlite3')
        self.assertEqual(shadow_worker.SHADOW,api.SHADOW_DB)

    def test_missing_snapshot_failure_duplicate_and_process_restart_keep_one_cursor(self):
        at=datetime(2026,10,26,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/'control.db'
            owner=sqlite3.connect(source)
            try:
                owner.execute('PRAGMA journal_mode=WAL')
                owner.execute('CREATE TABLE event_outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT,body TEXT)')
                owner.execute('CREATE TABLE pricing_snapshots(id TEXT PRIMARY KEY,body TEXT)')
                owner.execute('INSERT INTO event_outbox(kind,body) VALUES (?,?)',('snapshot_ready',json.dumps(dict(snapshot_id='first'))))
                owner.commit()
                shadow_path=root/'shadow.db'
                shadow=simulation.Shadow(shadow_path)
                with shadow.connect() as db:
                    self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'delete')
                missing,last=shadow_worker.tick(shadow,source,at)
                self.assertEqual(missing['status'],'source_snapshot_missing')
                self.assertEqual(missing['cursor'],0)
                owner.execute('INSERT INTO pricing_snapshots VALUES (?,?)',('first',json.dumps(dict(snapshot_id='first',evidence=evidence(at)))))
                owner.commit()
                with patch.object(simulation,'evaluate',side_effect=evaluate):
                    first,last=shadow_worker.tick(shadow,source,at)
                    self.assertEqual(first['cursor'],1)
                    owner.execute('INSERT INTO event_outbox(kind,body) VALUES (?,?)',('snapshot_ready',json.dumps(dict(snapshot_id='first'))))
                    owner.commit()
                    duplicate,last=shadow_worker.tick(shadow,source,at,last)
                self.assertEqual(duplicate['cursor'],2)
                with shadow.connect() as db:
                    self.assertEqual(db.execute("SELECT value FROM cursor WHERE id='production'").fetchone()[0],2)
                    self.assertEqual(json.loads(db.execute("SELECT body FROM paths WHERE id='daily'").fetchone()[0])['sequence'],1)
                restarted=simulation.Shadow(shadow_path)
                idle,_=shadow_worker.tick(restarted,source,at,last)
                self.assertEqual(idle['events'],0)
                next_at=at+timedelta(hours=6)
                owner.execute('INSERT INTO pricing_snapshots VALUES (?,?)',('second',json.dumps(dict(snapshot_id='second',evidence=evidence(next_at)))))
                owner.execute('INSERT INTO event_outbox(kind,body) VALUES (?,?)',('snapshot_ready',json.dumps(dict(snapshot_id='second'))))
                owner.commit()
                with patch.object(simulation,'evaluate',side_effect=RuntimeError('injected_failure')):
                    with self.assertRaisesRegex(RuntimeError,'injected_failure'):
                        shadow_worker.tick(restarted,source,next_at,last)
                with restarted.connect() as db:
                    self.assertEqual(db.execute("SELECT value FROM cursor WHERE id='production'").fetchone()[0],2)
                with patch.object(simulation,'evaluate',side_effect=evaluate):
                    recovered,_=shadow_worker.tick(simulation.Shadow(shadow_path),source,next_at,last)
                self.assertEqual(recovered['cursor'],3)
                history=dict(simulation_id='00000000-0000-4000-8000-000000000060',kind='actual_reconstruction',
                             closed_days=7,requested_at=(next_at+timedelta(days=1)).isoformat())
                owner.execute('INSERT INTO event_outbox(kind,body) VALUES (?,?)',('simulation_requested',json.dumps(history)))
                owner.commit()
                first_history,_=shadow_worker.tick(simulation.Shadow(shadow_path),source,next_at,last)
                self.assertEqual(first_history['cursor'],4)
                owner.execute('INSERT INTO pricing_snapshots VALUES (?,?)',('late',json.dumps(dict(snapshot_id='late',evidence=evidence(at+timedelta(hours=2))))))
                owner.execute('INSERT INTO event_outbox(kind,body) VALUES (?,?)',('simulation_requested',json.dumps(history)))
                owner.commit()
                repeated,_=shadow_worker.tick(simulation.Shadow(shadow_path),source,next_at,last)
                self.assertEqual(repeated['cursor'],5)
                with shadow.connect() as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM history').fetchone()[0],1)
            finally:
                owner.close()

    def test_daily_summary_and_prune_use_fixed_local_cutoff(self):
        now=datetime(2026,10,26,16,11,tzinfo=timezone.utc)
        shadow=Mock()
        shadow.consume.return_value=dict(status='processed',events=0,cursor=0)
        shadow.summary.return_value=[dict(policy='daily')]
        first,cutoff=shadow_worker.tick(shadow,'readonly.db',now)
        self.assertEqual(cutoff,datetime(2026,10,26,16,0,tzinfo=timezone.utc))
        shadow_worker.tick(shadow,'readonly.db',now+timedelta(minutes=1),cutoff)
        self.assertEqual(shadow.summary.call_count,1)
        self.assertEqual(shadow.prune.call_count,1)
        self.assertEqual(first['status'],'processed')

    def test_service_confines_network_code_and_production_data(self):
        unit=(SOURCE/'systemd'/'fc-pricing-v3-shadow.service').read_text(encoding='utf-8')
        for requirement in ('User=nobody','Group=fc27cloud','PrivateNetwork=yes',
                            'CPUQuota=25%','MemoryLimit=512M','ProtectSystem=full',
                            'ExecStart=/opt/python39/bin/python3 -I ',
                            'ReadOnlyDirectories=/var/lib/fc27-cloud',
                            'ReadWriteDirectories=/var/lib/fc-pricing-v3-shadow',
                            'InaccessibleDirectories=-/run/fs-order-session -/run/secrets -/etc/fc27-cloud'):
            self.assertIn(requirement,unit)
        self.assertNotIn('ReadWriteDirectories=/var/lib/fc27-cloud',unit)


if __name__=='__main__':
    unittest.main()
