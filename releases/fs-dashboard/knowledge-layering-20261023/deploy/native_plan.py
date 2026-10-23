"""Offline service-isolation checklist; this module never executes a publisher or service."""
PLUGIN='/var/lib/fs-hermes-fc/profile/plugins/fs-readonly/'
POLICY='/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json'
TARGETS={PLUGIN+'__init__.py',PLUGIN+'knowledge.py',POLICY,'/etc/systemd/system/fs-hermes-desktop.service'}
NATIVE_UNITS={'fs-hermes-desktop.service','hermes-dingtalk.service'}


def plan(targets, requested_units):
    if set(targets)!=TARGETS or not set(requested_units)<=NATIVE_UNITS:
        raise ValueError('native_exact_scope_required')
    return dict(status='offline_adapter_implemented_not_approved',targets=sorted(TARGETS),
                requested_units=sorted(requested_units),forbidden_units=['fs-hermes-fc.service','fs-business-range.service'],
                must_preserve=['publisher_lock','before_sha_CAS','full_prevalue_backup','original_operation_id',
                               'existing_admission_fence','native_session_and_gateway_drain','existing_collector_locks'],
                blockers=['native_image_build_and_service_readback_not_approved_or_executed',
                          'actual_new_FS_session_and_profile_route_not_selected',
                          'no_model_budget_or_actual_test_approved'],
                rollback='Restore only this batch exact plugin/policy prevalues using existing publisher CAS; retain all messages, sessions, DBs, queues, pins and receipts.',
                production_actions_allowed=False)
