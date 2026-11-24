"""Retain core evidence and collect auxiliary quotes outside the pricing path."""
from datetime import datetime,timezone
import re


def collect_package_observations(run_id, snapshot_time):
    import sys
    from pathlib import Path
    from .competitor_offers import CURRENT_QUANTITIES, PLATFORMS
    from .financial import instant
    control = Path('/opt/fs-fc-control/code')
    if control.is_dir() and str(control) not in sys.path:
        sys.path.insert(0, str(control))
    from fc_collection.package_routes import collect_missing, read_node
    wanted = [(p,q) for p in PLATFORMS for q in CURRENT_QUANTITIES]
    offers, status = [], {}
    for source in ('U4GM','IGGM'):
        started = datetime.now(timezone.utc)
        if not 0 <= (started - instant(snapshot_time)).total_seconds() <= 900:
            status[source] = dict(status='missing', reason='snapshot_expired')
            continue
        rows, attempts = collect_missing(source, run_id, wanted, lambda node, req:read_node(node,req,started),
                                        lambda:datetime.now(timezone.utc))
        offers.extend(rows)
        status[source] = dict(status='captured' if len(rows)==len(wanted) else 'partial' if rows else 'missing',
                              errors=sorted({error for attempt in attempts for error in attempt['errors']}),
                              attempts=[dict(node=attempt['node'], errors=attempt['errors'],
                                             response_received=attempt.get('response_received'),
                                             requested=[list(slot) for slot in attempt['requested']],
                                             accepted=[list(slot) for slot in attempt['accepted']])
                                        for attempt in attempts])
    return dict(package_offers=offers, package_status=status)


def collect_reference_market(run_id):
    """Reuse the ItemD2R reader; auxiliary observations never authorize a price."""
    from itemd2r_reader import public_read
    try:
        offers = public_read()
        if (not isinstance(offers,list) or any(not isinstance(r,dict) or r.get('platform') not in ('PS','XBOX','PC') for r in offers)
                or len({r['platform'] for r in offers})!=len(offers)):
            raise ValueError('itemd2r_platform_coverage_invalid')
        return dict(status='captured',run_id=run_id,offers=[dict(r,run_id=run_id) for r in offers])
    except Exception as exc:
        # Optional reference failure remains visible; it cannot disable the original source chain.
        reason=str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'itemd2r_[a-zA-Z0-9_:]{1,100}',str(exc)) else type(exc).__name__
        failed=dict(status='unavailable',run_id=run_id,offers=[],reason=reason,captured_at=datetime.now(timezone.utc).isoformat())
        if reason=='itemd2r_cloudflare_403':
            failed.update(status='blocked',http_status=403,blocked_by='cloudflare',captured_at=datetime.now(timezone.utc).isoformat())
        return failed


def observe(run_id):
    from .runtime import ledger
    from .financial import fingerprint
    from .competitor_offers import POLICY
    db=ledger();existing=db.get('market_observations',run_id)
    if existing and existing.get('status')=='observed':return existing
    snapshot=db.get('pricing_snapshots',run_id)
    if not snapshot:raise ValueError('pricing_observation_snapshot_missing')
    evidence=snapshot['evidence']
    captured=datetime.now(timezone.utc).isoformat()
    result=dict(schema_version='fc-pricing-v3-20261026',run_id=run_id,status='started',started_at=captured,
                source_snapshot_sha256=fingerprint(evidence),production_rule_changed=False,price_write_performed=False,model_requests=0)
    db.put('market_observations',run_id,result)
    reference=evidence.get('reference_market')
    if 'ItemD2R' in (evidence.get('source_plan') or {}).get('auxiliary_markets',[]):
        reference=collect_reference_market(run_id)
    if evidence.get('competitor_policy') == POLICY:
        result.update(collect_package_observations(run_id, snapshot['created_at']))
    result.update(retired_automatic_sources=(evidence.get('source_plan') or {}).get('retired_automatic_sources',['ELD','U4GM','IGGM','U7Buy']),reference_market=reference,
                  arab_ut_status=evidence.get('arab_ut_status'),status='observed',completed_at=datetime.now(timezone.utc).isoformat(),
                  authority='independent_observation_only_no_old_weighted_scenarios')
    db.put('market_observations',run_id,result)
    return result
