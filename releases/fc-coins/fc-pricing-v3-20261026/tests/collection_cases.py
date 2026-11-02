from copy import deepcopy
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 11, 2, 9, tzinfo=timezone.utc)


def context():
    return dict(requested_platforms=['PS', 'XBOX', 'PC'], region_scope=[0],
                quantity_scope=dict(purchase_quantity='100', quantity_unit='K'),
                discount_scope='coupon_excluded', currency='USD',
                policy_version='test-policy-1', adapter_version='test-adapter-1',
                assignment_generation=1, total_attempt_limit=3, total_request_budget=6)


def job():
    from fc_collection.contracts import build_job
    return build_job(dict(run_id='run-1', created_at=NOW.isoformat()), 'ItemD2R',
                     context(), (NOW + timedelta(minutes=10)).isoformat())


def identity(node='183', boot='boot-1'):
    return dict(node_id=node, node_boot_id=boot)


def observation(task, captured=NOW):
    keys = ('job_id', 'parent_run_id', 'source_id', 'task_context_hash', 'policy_version',
            'adapter_version', 'assignment_generation', 'attempt_id', 'lease_epoch',
            'node_id', 'node_boot_id')
    body = {key: deepcopy(task[key]) for key in keys}
    body.update(schema_version=1, observation_id='observation-1', status='ok', reason_code=None,
                request_budget_used=1, evidence_hash='a' * 64,
                capture_started_at=captured.isoformat(), capture_finished_at=captured.isoformat(),
                offers=[dict(platform=platform, region_id=0, currency='USD', settlement_currency='USD',
                    conversion_source='not_required', purchase_quantity='100', bonus_quantity='0',
                    delivered_quantity='100', quantity_unit='K', amount='10.00',
                    price_basis='visible_public_sale_price', delivery_method='AI 4.0 Automated Delivery',
                    discount_source='visible_no_coupon', coupon_excluded=True, auth_state='public',
                    conditional=False, comparable=True, observed_at=captured.isoformat(),
                    selection_verified=True, sanitized_evidence_ref='sha256:' + 'a' * 64)
                    for platform in task['requested_platforms']])
    return body


def policy():
    # Synthetic timings, never live source limits.
    return dict(origin='https://www.itemd2r.com', nodes=['183', '187'], mode='consume',
                generation=1, adapter_version='test-adapter-1', policy_version='test-policy-1',
                lease_seconds=20, request_timeout_seconds=30, clock_margin_seconds=2,
                stable_seconds=5, window_seconds=60, max_requests=6, concurrency=1,
                retry_after_seconds=60)


def coordinator(path):
    from fc_collection.coordinator import Coordinator
    instance = Coordinator(path)
    instance.configure_source('ItemD2R', policy())
    instance.register_node(identity(), ['ItemD2R'], NOW - timedelta(seconds=6))
    instance.register_node(identity('187'), ['ItemD2R'], NOW - timedelta(seconds=6))
    instance.enqueue(job())
    return instance
