"""Read the existing quote/job/execution ledgers without collecting or writing prices."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from pricing_v2 import VERSION,MARGIN_BASIS,POSITION_VERSION,fresh
from fc_pricing_v3.selective_sources import CATALOG_CONTRACT,input_ratio

ROOT=Path('/var/lib/fc27-cloud')


def evaluate(data,policy,root=ROOT):
    from fc_pricing_v3.api import post
    from decimal import Decimal
    if set(data)!={'run_id','console_usd','pc_usd','reason'}:
        raise ValueError('pricing_evaluate_fields')
    # The legacy 100K adapter is read-only and performs the explicit unit round trip.
    for key in ('console_usd','pc_usd'):
        value=Decimal(str(data[key]))
        if value/100*100!=value:
            raise ValueError('pricing_unit_roundtrip_invalid')
    raise ValueError('pricing_legacy_candidate_retired_use_v3_evaluate')




def owned_review(root,owner):
    if not owner:return None
    paths=sorted((root/'evidence').glob('hermes-pricing-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    values=[json.loads(path.read_text('utf-8')) for path in paths[:60]]
    # The API can read existing jobs, but cannot list the worker's private evidence directory.
    for path in sorted((root/'jobs').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:120]:
        job=json.loads(path.read_text('utf-8'))
        value=job.get('hermes_review') if job.get('kind')=='auto_cycle' else job.get('result') if job.get('kind')=='hermes_review' else None
        if isinstance(value,dict) and value.get('owner')==owner:values.append(value)
    for value in sorted(values,key=lambda v:v.get('created_at',''),reverse=True):
        if value.get('owner')!=owner:continue
        if value.get('conversation_id'):
            try:
                from hermes_pricing_bridge import request
                detail=request(owner,'/api/hermes/conversations/'+value['conversation_id'],timeout=3)
                turn=next((t for t in detail.get('turns',[]) if t['turn_id']==value.get('turn_id')),None)
                if turn is None and value.get('input_sha256'):
                    matches=[t for t in detail.get('turns',[]) if hashlib.sha256(t.get('text','').encode()).hexdigest()==value['input_sha256']]
                    if len(matches)==1:turn=matches[0]
                if turn:
                    value.update(turn_id=turn['turn_id'],turn={k:turn.get(k) for k in ('turn_id','state','run_id','progress','error')},
                                 live_receipt='original_owned_turn_identified')
                    if turn['state'] in {'queued','preparing','running','stopping'}:value['phase']='submitted'
                    if turn['state'] in {'completed','failed','cancelled','interrupted'}:
                        value['phase']='completed' if turn['state']=='completed' else 'failed'
            except (OSError,ValueError,KeyError,__import__('sqlite3').Error):
                value['live_receipt']='temporarily_unavailable_original_intent_preserved'
        return value
    return None


def state(root=ROOT,owner=None):
    now=datetime.now(timezone.utc)
    latest=max((root/'quotes').glob('*.json'),key=lambda p:p.stat().st_mtime,default=None)
    quote=json.loads(latest.read_text('utf-8')) if latest else None
    valid=False;reason='尚无本轮报价'
    if quote:
        try:
            fresh(quote['created_at'],now)
            fresh(quote['evidence']['checked_at'],now)
            fresh(quote['evidence']['fx']['checked_at'],now)
            for platform in ('PS','XBOX','PC'):
                fresh(quote['evidence']['costs'][platform]['checked_at'],now)
                fresh(quote['evidence']['storefront']['rows'][platform]['checked_at'],now)
            if quote['evidence']['promotion_envelope'].get('contract')==CATALOG_CONTRACT:
                input_ratio(quote['evidence']['promotion_envelope'],now)
            else:fresh(quote['evidence']['promotion_envelope']['checked_at'],now,900)
            valid=(quote['result'].get('strategy_version')==VERSION and
                   (quote['result'].get('decision_receipt') or {}).get('margin_basis')==MARGIN_BASIS and
                   (quote['result'].get('decision_receipt') or {}).get('schema_version')==VERSION)
            reason='本轮来源有效' if valid else '历史策略报价，须新采集'
        except (KeyError,ValueError):reason='来源已过期或仍属历史报价'
    recent=[]
    for path in sorted((root/'jobs').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:120]:
        item=json.loads(path.read_text('utf-8'))
        if item.get('kind') not in {'auto_cycle','collect','execute','restore','recalculate','preview','hermes_review'}:continue
        recent.append({k:item.get(k) for k in ('job_id','kind','actor','status','created_at','completed_at','error','error_detail','result','public_page_readback','cache_refresh','blocked_platforms','reconciliation')})
        if len(recent)>=30:break
    ready=bool(valid and (quote['evidence']['promotion_envelope'].get('contract')==CATALOG_CONTRACT or
        quote['evidence']['promotion_envelope'].get('coupon_other_benefits_contract') in {'not_applicable','verified_mutually_exclusive','verified_included_in_envelope'}))
    return dict(version=VERSION,observed_at=now.isoformat(),hard_minimum_margin_pct='20',margin_basis=MARGIN_BASIS,
                execution_ready=ready,execution_block_reason=None if ready else ('本轮优惠适用合同未核定，不能执行。' if valid else reason+'，须重新采集核算，不能执行。'),
                quote=quote,quote_usable=valid,quote_status=reason,recent=recent,hermes_review=owned_review(root,owner),
                execution_authority='original_writer_locks_CAS_UNKNOWN_and_hard_floor',
                effect_status='observation_required_not_a_causal_profit_claim')
