"""Read the selected U4GM checkout preview through an ordinary Chrome session."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import re
from threading import Lock
from urllib.parse import urlsplit
from uuid import UUID

from .package_reader import LABELS, QUANTITIES, U4GM, amount, row

BROWSER_PLATFORMS = ('PS', 'XBOX')
_collection_lock = Lock()
_blocked = False
_MONEY = re.compile(r'\$\s*([0-9]+(?:\.[0-9]{1,2})?)')


def preview_offer(platform, quantity, selected, amount_text, price, stamp, url=U4GM):
    """A price belongs to the quantity and platform confirmed by the visible summary."""
    if selected != LABELS[platform][1]:
        raise ValueError('browser_platform_mismatch')
    display = re.fullmatch(r'([0-9]+)\s*K(?:\s*\+\s*([0-9]+)\s*K\s+Free)?', ' '.join(amount_text.split()))
    price = _MONEY.fullmatch(price.strip())
    if not display or display[1] != quantity or not price or not amount(price[1]):
        raise ValueError('browser_package_mismatch')
    offer = row('U4GM', platform, quantity, amount(price[1]), display[2] or '0',
                url, stamp, 'selected_native_price')
    offer.update(delivery_method='default_storefront', delivery_tier='standard')
    return offer


def collect(wanted):
    offers, errors = [], []
    if any(platform not in BROWSER_PLATFORMS for platform, _ in wanted):
        errors.append('browser_platform_unavailable')
    if not any(platform in BROWSER_PLATFORMS for platform, _ in wanted):
        return offers, errors
    from playwright.sync_api import Error, expect, sync_playwright

    restrictions = []
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel='chrome', headless=False, chromium_sandbox=True, timeout=6000)
        except Error:
            return offers, errors + ['browser_runtime_unavailable']
        try:
            page = browser.new_page()
            page.set_default_timeout(3500)

            def record_navigation(response):
                if (urlsplit(response.url)[:2] == urlsplit(U4GM)[:2]
                        and response.request.resource_type in ('document','xhr','fetch')
                        and response.status in (401, 403, 429)):
                    restrictions.append('http_' + str(response.status))

            def field(label):
                return page.locator('#pjax-container').get_by_text(label, exact=True).last.locator('xpath=following-sibling::*[1]')

            page.on('response', record_navigation)
            try:
                response = page.goto(U4GM, wait_until='domcontentloaded', timeout=7500)
                if not response or response.status != 200 or page.url != U4GM:
                    return offers, errors + (restrictions or ['browser_product_unavailable'])
                currency = page.get_by_role('button', name='currency rate')
                expect(currency).to_have_text('USD', timeout=3500)
                reject = page.get_by_role('button', name='Reject All')
                if reject.is_visible():
                    reject.click()
                for platform in BROWSER_PLATFORMS:
                    quantities = [quantity for quantity in QUANTITIES if (platform, quantity) in wanted]
                    if not quantities:
                        continue
                    label = LABELS[platform][1]
                    if field('Platform').inner_text().strip() != label:
                        page.locator('#js-option-change').get_by_text(label, exact=True).click()
                    expect(field('Platform')).to_have_text(label, timeout=3500)
                    expect(currency).to_have_text('USD', timeout=3000)
                    if restrictions:
                        break
                    if urlsplit(page.url)[:3] != urlsplit(U4GM)[:3]:
                        raise ValueError('browser_platform_url_mismatch')
                    expect(page.locator('h1')).to_have_text('FC 27 Coins', timeout=2500)
                    unit = amount(page.locator('#pjax-container input[name="id"][data-unit-price]').get_attribute('data-unit-price'))
                    rules = json.loads(page.locator('#pjax-container .js-product-level').text_content())
                    for quantity in quantities:
                        rule = rules[quantity]
                        if ((rule.get('type'), rule.get('feature')) != ('bonus', 'fixed')
                                or amount(rule.get('extra_value', 0)) != 0):
                            raise ValueError('browser_nonstandard_tier')
                        page.locator('.js-level-list .js-level-' + quantity).click()
                        expect(field('Amount')).to_have_text(re.compile(r'^' + quantity + r'\s*K(?:\s|$)'), timeout=3000)
                        expected_price = (unit * Decimal(quantity)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
                        expect(field('Price')).to_have_text(
                            re.compile(r'^\s*\$\s*' + re.escape(str(expected_price)) + r'\s*$'), timeout=2500)
                        if restrictions:
                            break
                        summary = field('Amount').locator('xpath=..').inner_text()
                        amount_display = summary.removeprefix('Amount').strip()
                        offer = preview_offer(platform, quantity, field('Platform').inner_text().strip(),
                                              amount_display, field('Price').inner_text(),
                                              datetime.now(timezone.utc).isoformat(), page.url)
                        if amount(offer['regular_price']) != expected_price or amount(offer['bonus_k']) != amount(rule['value']):
                            raise ValueError('browser_preview_changed')
                        offers.append(offer)
                    if restrictions:
                        break
            except (AssertionError, Error, ValueError, KeyError, TypeError) as exc:
                if not restrictions:
                    if page.locator('#challenge-form, #challenge-stage').count():
                        restrictions.append('challenge')
                    elif isinstance(exc, ValueError) and str(exc).startswith('browser_'):
                        errors.append(str(exc))
                    else:
                        errors.append('browser_preview_unverified')
        finally:
            browser.close()
    return offers, errors + restrictions


def validate(request):
    if (not isinstance(request, dict) or set(request) != {'source', 'run_id', 'wanted'}
            or request['source'] != 'U4GM' or str(UUID(request['run_id'])) != request['run_id']
            or not isinstance(request['wanted'], list) or not 1 <= len(request['wanted']) <= 6):
        raise ValueError('browser_observation_scope')
    wanted = {tuple(slot) for slot in request['wanted'] if isinstance(slot, list) and len(slot) == 2
              and all(isinstance(part, str) for part in slot)}
    if len(wanted) != len(request['wanted']) or any(p not in LABELS or q not in QUANTITIES for p, q in wanted):
        raise ValueError('browser_observation_slots')
    return wanted


def run_request(request):
    global _blocked
    wanted = validate(request)
    result = dict(source='U4GM', run_id=request['run_id'], offers=[], errors=[], retry_after_seconds=0)
    if not _collection_lock.acquire(blocking=False):
        return dict(result, errors=['browser_observation_busy'])
    try:
        if _blocked:
            return dict(result, errors=['source_blocked'])
        offers, errors = collect(wanted)
        _blocked = bool(set(errors) & {'http_401', 'http_403', 'http_429', 'challenge'})
        return dict(result, offers=[dict(offer, run_id=request['run_id']) for offer in offers], errors=errors)
    finally:
        _collection_lock.release()
