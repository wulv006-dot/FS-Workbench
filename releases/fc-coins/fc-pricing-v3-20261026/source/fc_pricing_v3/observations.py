"""Completion-event observations; original ELD reader, no production price policy."""
from datetime import datetime,timezone
from pathlib import Path
import json
import subprocess

APP=Path('/opt/fc27-price-observer')

def eldorado_read(run_id):
    """Separate capped anonymous Chrome; no FC/Admin/Order browser/profile/locks."""
    name='fc-eld-observe-'+run_id
    image='sha256:cf34b99c7434b73743c4004b88b57a713333081811c0c88befc4cfe90453b381'
    command=['docker','run','--rm','--pull=never','--init','--name',name,'--user','fc27chrome',
             '--cap-drop=ALL','--security-opt=no-new-privileges','--memory=768m','--pids-limit=256',
             '--cpus=0.5','--shm-size=128m','--network=bridge','-i','--entrypoint','python3',image,'-B','-']
    try:
        result=subprocess.run(command,input=(APP/'eldorado.py').read_text(),text=True,capture_output=True,timeout=80)
        if result.returncode:raise ValueError('eld_isolated_reader_failed')
        if len(result.stdout.encode())>2_000_000:raise ValueError('eld_response_size')
        payload=json.loads(result.stdout)
        if payload.get('source')!='ELD' or [r.get('platform') for r in payload.get('platforms',[])]!=['PS','XBOX','PC']:
            raise ValueError('eld_platform_coverage_invalid')
        count=sum(r.get('status')=='observed' for r in payload['platforms'])
        return dict(payload,status='observed' if count==3 else 'partial' if count else 'failed',
                    run_id=run_id,direct_pricing_weight='0',business_effect='none',reader='isolated_768m_0.5cpu_ephemeral_no_profile')
    except subprocess.TimeoutExpired:
        # The deterministic container belongs only to this reserved observation.
        try:
            cleanup=subprocess.run(['docker','kill',name],capture_output=True,timeout=8)
            cleanup_state='kill_confirmed' if cleanup.returncode==0 else 'cleanup_needs_reconcile'
        except (OSError,subprocess.TimeoutExpired):
            cleanup_state='cleanup_needs_reconcile'
        return dict(status='failed',reason='eld_read_timeout',cleanup_state=cleanup_state,platforms=[],run_id=run_id,direct_pricing_weight='0')
    except (OSError,ValueError) as error:
        return dict(status='failed',reason=str(error) if isinstance(error,ValueError) else type(error).__name__,platforms=[],run_id=run_id,direct_pricing_weight='0')



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
    result.update(eldorado=eldorado_read(run_id),reference_market=evidence.get('reference_market'),
                  arab_ut_status=evidence.get('arab_ut_status'),status='observed',completed_at=datetime.now(timezone.utc).isoformat(),
                  authority='independent_observation_only_no_old_weighted_scenarios')
    db.put('market_observations',run_id,result)
    return result
