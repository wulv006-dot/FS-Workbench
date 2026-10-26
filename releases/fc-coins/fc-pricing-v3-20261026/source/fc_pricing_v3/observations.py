"""Retain same-run market evidence without an extra browser or collection."""
from datetime import datetime,timezone
def observe(run_id):
    from .runtime import ledger
    from .financial import fingerprint
    db=ledger();existing=db.get('market_observations',run_id)
    if existing and existing.get('status')=='observed':return existing
    snapshot=db.get('pricing_snapshots',run_id)
    if not snapshot:raise ValueError('pricing_observation_snapshot_missing')
    evidence=snapshot['evidence']
    captured=datetime.now(timezone.utc).isoformat()
    result=dict(schema_version='fc-pricing-v3-20261026',run_id=run_id,status='started',started_at=captured,
                source_snapshot_sha256=fingerprint(evidence),production_rule_changed=False,price_write_performed=False,model_requests=0)
    db.put('market_observations',run_id,result)
    result.update(retired_automatic_sources=['ELD','U4GM','IGGM','U7Buy'],reference_market=evidence.get('reference_market'),
                  arab_ut_status=evidence.get('arab_ut_status'),status='observed',completed_at=datetime.now(timezone.utc).isoformat(),
                  authority='independent_observation_only_no_old_weighted_scenarios')
    db.put('market_observations',run_id,result)
    return result
