"""Legacy import adapter: finance retained, all production selection is FC Pricing V3."""
from fc_pricing_v3.financial import *
from fc_pricing_v3 import VERSION
from fc_pricing_v3.runtime import verify_quote
POSITION_VERSION = VERSION
TEMPORARY_ITEMD2R_PARITY = False

def apply_decision(rows,evidence,edits,*,now=None):
    from fc_pricing_v3.runtime import calculate
    result=calculate(evidence,edits)
    rows[:]=result['rows']
    return result['decision_receipt']
