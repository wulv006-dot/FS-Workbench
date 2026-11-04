"""Small regularized Poisson fit over real, price-bound exposure intervals."""
from datetime import datetime,timezone
from decimal import Decimal
import math

from .financial import fingerprint,number


def fit(observations):
    groups={}
    rejected=0
    for row in observations:
        if (row.get('mode')!='production' or row.get('origin')!='actual_order_and_price_window' or
                not row.get('price_window_id') or row.get('assignment_probability') is None):
            rejected+=1
            continue
        offset=row.get('offset_kind')
        if offset not in ('effective_hours','qualified_exposure'):
            raise ValueError('pricing_model_offset_unverified')
        exposure=number(row['exposure'],zero=True)
        orders=number(row['paid_orders'],zero=True)
        if not exposure:
            if orders:
                raise ValueError('pricing_model_zero_exposure_with_orders')
            continue
        groups.setdefault(row['price_group'],[]).append(row)
    model_groups={}
    for group,rows in groups.items():
        if len({r['offset_kind'] for r in rows})!=1:
            raise ValueError('pricing_model_offset_mixed')
        if len(rows)<3 or len({r['effective_price_usd'] for r in rows})<2 or not sum(number(r['paid_orders'],zero=True) for r in rows):
            continue
        reference=number(rows[-1]['effective_price_usd'])
        best=None
        profile=[]
        # Penalized Poisson profile likelihood, with a stated cold-start center at two.
        for index in range(81):
            elasticity=index/10
            features=[float(number(r['exposure']))*(float(number(r['effective_price_usd'])/reference)**(-elasticity)) for r in rows]
            total=sum(float(number(r['paid_orders'],zero=True)) for r in rows)
            rate=(total+1)/(sum(features)+1)
            loss=sum(rate*x-float(number(r['paid_orders'],zero=True))*math.log(max(rate*x,1e-300)) for x,r in zip(features,rows))+(elasticity-2)**2/2
            profile.append((loss,elasticity))
            if best is None or loss<best[0]:
                best=(loss,elasticity,rate)
        best_loss,elasticity,rate=best
        supported=[value for loss,value in profile if loss<=best_loss+1.92]
        randomized=all(r.get('randomization_verified') is True for r in rows)
        model_groups[group]=dict(elasticity=str(elasticity),reference_regular_usd=str(reference),
            orders_per_block=str(Decimal(str(rate))*6) if rows[0]['offset_kind']=='effective_hours' else None,
            offset_kind=rows[0]['offset_kind'],observations=len(rows),boundary_hit=elasticity in (0,8),
            status='real_price_window_regularized_fit',training_end=max(r['as_of'] for r in rows),
            elasticity_support_interval=[str(min(supported)),str(max(supported))],
            uncertainty_basis='penalized_profile_loss_delta_1.92_not_causal_interval',
            source_design='randomized_assignment_observations' if randomized else 'observational_price_windows',
            causal_effect_estimated=False,total_paid_orders=str(sum(number(r['paid_orders'],zero=True) for r in rows)),
            exposure=str(sum(number(r['exposure'],zero=True) for r in rows)))
    return dict(model_version='fc-poisson-'+fingerprint(observations)[:20],status='real_price_window_regularized_fit' if model_groups else 'central_prior_no_qualified_price_variation_yet',
                groups=model_groups,segments=[],rejected_unbound_observations=rejected,
                training_origin='real_only',prior_elasticity='2',domain=['0','8'],
                created_at=datetime.now(timezone.utc).isoformat(),sample_sha256=fingerprint(observations))
