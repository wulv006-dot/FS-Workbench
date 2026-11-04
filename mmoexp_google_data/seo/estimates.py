"""User-approved estimate using GA4 event counts and the existing Admin price."""
from decimal import Decimal, ROUND_HALF_UP

from .metrics import number


def calculate(ga4, admin):
    events = (ga4 or {}).get('purchase_events')
    price = (admin or {}).get('admin_customer_price_usd')
    result = dict(status='missing', revenue_usd=None, purchase_events=events,
                  admin_customer_price_usd=price, price_field='customer_price',
                  price_basis='admin_native_paying_customer_mean', count_basis='ga4_ecommercePurchases',
                  attribution='estimated_not_order_linked', currency='USD')
    if events is not None and price is not None:
        count, unit = number(events), number(price)
        if count and not unit:
            result['reason'] = 'ADMIN_PRICE_UNAVAILABLE_FOR_PURCHASES'
        else:
            result.update(status='estimated', revenue_usd=str((count*unit).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)))
    return result
