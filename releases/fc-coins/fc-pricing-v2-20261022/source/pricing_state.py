"""Read the existing quote/job/execution ledgers without collecting or writing prices."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from pricing_v2 import VERSION,fresh

ROOT=Path('/var/lib/fc27-cloud')


def evaluate(data,policy,root=ROOT):
    import re
    from pricing_v2 import verify_quote
    from fc27_quote_engine import calculate
    if not isinstance(data,dict) or set(data)!={'run_id','console_usd','pc_usd','reason'} or not re.fullmatch(r'[a-f0-9-]{36}',str(data['run_id'])):
        raise ValueError('pricing_evaluate_fields')
    from pricing_v2 import number
    console,pc=number(data['console_usd']),number(data['pc_usd'])
    if any(v!=v.quantize(__import__('decimal').Decimal('.01')) for v in (console,pc)):
        raise ValueError('pricing_package_cents_required')
    newest=max((root/'quotes').glob('*.json'),key=lambda p:p.stat().st_mtime,default=None)
    if newest is None or newest.stem!=data['run_id']:raise ValueError('pricing_newer_run_exists')
    quote=json.loads(newest.read_text('utf-8'));verify_quote(quote,policy,['PS','XBOX','PC'])
    edits=dict(quotes={'PS':str(console/100),'XBOX':str(console/100),'PC':str(pc/100)},
               reason=str(data['reason'])[:200],minimum_gross_margin_pct=policy['minimum_gross_margin_pct'])
    result=calculate(quote['evidence'],edits)
    return dict(run_id=data['run_id'],write_performed=False,execution_authorized=False,
                canonical_quote_sha256=hashlib.sha256(json.dumps(quote,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                base_quote_sha256=hashlib.sha256(newest.read_bytes()).hexdigest(),result=result)


def owned_review(root,owner):
    if not owner:return None
    paths=sorted((root/'evidence').glob('hermes-pricing-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    for path in paths[:60]:
        value=json.loads(path.read_text('utf-8'))
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
            fresh(quote['evidence']['promotion_envelope']['checked_at'],now,900)
            valid=quote['result'].get('strategy_version')==VERSION
            reason='本轮来源有效' if valid else '历史策略报价，须新采集'
        except (KeyError,ValueError):reason='来源已过期或仍属历史报价'
    recent=[]
    for path in sorted((root/'jobs').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:120]:
        item=json.loads(path.read_text('utf-8'))
        if item.get('kind') not in {'auto_cycle','collect','execute','restore','recalculate','preview','hermes_review'}:continue
        recent.append({k:item.get(k) for k in ('job_id','kind','actor','status','created_at','completed_at','error','error_detail','result','public_page_readback','cache_refresh','blocked_platforms')})
        if len(recent)>=30:break
    ready=bool(valid and quote['evidence']['promotion_envelope'].get('coupon_other_benefits_contract') in {'not_applicable','verified_mutually_exclusive','verified_included_in_envelope'})
    return dict(version=VERSION,observed_at=now.isoformat(),hard_minimum_margin_pct='10',
                execution_ready=ready,execution_block_reason=None if ready else '报价过期或优惠券与VIP/积分叠加合同尚未核定，不能执行。',
                quote=quote,quote_usable=valid,quote_status=reason,recent=recent,hermes_review=owned_review(root,owner),
                execution_authority='original_writer_locks_CAS_UNKNOWN_and_hard_floor',
                effect_status='observation_required_not_a_causal_profit_claim')
