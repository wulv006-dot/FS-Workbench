"""Recovery decisions only; never copy files, initialize facts or recollect sources."""


def decision(kind,*,mode='fresh',proof=None,query=None,history_inputs=False,consistent_backup=False,accept_new_baseline=False,identity_available=None,fixture=False):
    if kind not in ('cache_miss','empty_read_model','authoritative_store_missing','frozen_inputs_missing'):raise ValueError('recovery_kind')
    if kind=='frozen_inputs_missing' or mode=='frozen' and not history_inputs:
        return dict(status='missing_history',action='restore_designated_pinned_inputs',fresh_fallback=False,promises_original_asof=False)
    if kind=='authoritative_store_missing':
        if consistent_backup:return dict(status='recovery_required',action='isolated_consistent_restore_then_business_checks',automatic=False)
        if accept_new_baseline:
            return dict(status='recovery_required',action='explicit_bounded_new_baseline',automatic=False,promises_original_asof=False,lost_capabilities=['unretained_old_asof','unretained_old_recipe_inputs'],
                        identity_plan='reuse_verified_mapping' if identity_available is True else 'explicit_new_namespace_and_permission_required',identity_mutation_authorized=False,l0='existing_designated_recovery_chain_only')
        return dict(status='unavailable',action='recover_identity_and_authoritative_state',automatic=False,promises_original_asof=False)
    if mode!='fresh':return dict(status='local_history_only',action='read_retained_archive',fresh_fallback=False)
    if not isinstance(query,dict) or not all(query.get(k) for k in ('start','end_exclusive','scope_hash','dataset_id')):return dict(status='date_and_scope_required',automatic=False)
    from eviction_policy import proof_valid
    try:proof_valid(proof,query,fixture=fixture)
    except Exception:return dict(status='regeneration_not_proven',automatic=False)
    bounded={key:query[key] for key in ('dataset_id','scope_hash','start','end_exclusive','fields','source_contract','mode') if key in query}
    return dict(status='bounded_plan_required',action='reuse_facts_then_missing_slices_only',query=bounded,full_import=False,whole_database_backup=False,complete=False)


def rollback_read_configuration(current,previous_read_route):
    # This pure proposal touches only a route setting, never copies a backup DB.
    from copy import deepcopy
    value=deepcopy(current);value['read_route']=previous_read_route
    return value
