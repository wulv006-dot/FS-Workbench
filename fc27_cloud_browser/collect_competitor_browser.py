"""Read current FC27 public offers in the server Chrome profile only."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright, TimeoutError as CollectorTimeoutError


URLS = {
    "IGGM": "https://www.iggm.com/ea-sports-fc/fc-27-coins",
    "U4GM": "https://www.u4gm.com/fc-27/coins",
    "U7Buy": "https://www.u7buy.com/fc27/coins",
}
PLATFORMS = ("PS", "XBOX", "PC")


def positive(value) -> Decimal:
    try:
        number = Decimal(str(value).replace(",", ""))
    except (InvalidOperation, TypeError):
        raise ValueError("invalid_price") from None
    if not number.is_finite() or number <= 0:
        raise ValueError("invalid_price")
    return number


def stable(page, reader, attempts=12, arg=None):
    prior = None
    count = 0
    for _ in range(attempts):
        data = page.evaluate(reader, arg)
        if data and data.get("ready"):
            signature = json.dumps(data, sort_keys=True)
            count = count + 1 if signature == prior else 1
            if count >= 2:
                return data
            prior = signature
        else:
            count, prior = 0, None
        page.wait_for_timeout(500)
    raise ValueError("selector_or_value_unstable")


def checked_offer(source, platform, url, price, base, bonus, *, conditional=False, quantities=(100,)):
    amount = positive(price)
    purchase = Decimal(str(base))
    if purchase not in {Decimal(str(v)) for v in quantities} or purchase not in (100,1000,2000,5000):
        raise ValueError("unsupported_native_quantity")
    try:
        bonus_value = Decimal(str(bonus))
    except (InvalidOperation, TypeError):
        raise ValueError("invalid_bonus") from None
    if not bonus_value.is_finite() or bonus_value < 0:
        raise ValueError("invalid_bonus")
    return {"source": source, "platform": platform,
            "captured_at": datetime.now(timezone.utc).isoformat(), "url": url,
            "currency": "USD", "purchase_k": str(purchase), "bonus_k": str(bonus_value),
            "gross_usd": str(amount),
            "effective_usd_per_k": str(amount / (purchase + bonus_value)),
            "coupon_excluded": True, "auth_state": "public",
            "conditional": conditional, "comparable": not conditional,
            "status": "valid", "reason": None}


def iggm_visible_price(data):
    """Use the visible USD amount only when IGGM's lkr attribute agrees with it."""
    display = str(data.get("display") or "").strip()
    match = re.fullmatch(r"\$\s*([0-9]+(?:\.[0-9]{1,2})?)", display)
    if not match:
        raise ValueError("iggm_display_price_invalid")
    visible = positive(match.group(1))
    attribute = positive(data.get("price"))
    if abs(attribute - visible) > Decimal("0.000000001"):
        raise ValueError("iggm_display_attribute_mismatch")
    return str(visible)


def iggm_bonus_k(data):
    label = str(data.get("label") or "").strip()
    match = re.fullmatch(r"100\s*K(?:\s*\+\s*([0-9]+(?:\.[0-9]{1,6})?)\s*K)?", label, re.I)
    if not match:
        raise ValueError("iggm_package_label_invalid")
    return str(Decimal(match.group(1) or "0"))


def challenge(page) -> bool:
    return page.evaluate("""() => /just a moment|checking your browser|access denied|verify you are human/i.test(document.title+' '+document.body.innerText.slice(0,500))""")


def open_page(context, url):
    page = context.new_page()
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=35000)
        if response is None or response.status in (401, 403, 429):
            raise ValueError("http_blocked")
        page.wait_for_timeout(1000)
        if challenge(page):
            raise ValueError("challenge")
        return page
    except Exception:
        page.close()
        raise


IGGM_READ = r"""() => {
  const active=document.querySelector('li[data-device_id].active')?.getAttribute('data-device_id');
  const tier=document.querySelector('span[data-num].active')?.getAttribute('data-num');
  const prices=[...document.querySelectorAll('.golds__price .true__price')].filter(e=>{
    const r=e.getBoundingClientRect(),s=getComputedStyle(e);
    return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';
  });
  const values=prices.map(e=>e.getAttribute('lkr'));
  const price=values.length>0&&values.every(x=>x&&x===values[0])?values[0]:null;
  const displays=prices.map(e=>e.innerText.trim());
  const display=displays.length>0&&displays.every(x=>x&&x===displays[0])?displays[0]:null;
  const label=document.querySelector('span[data-num].active')?.innerText||'';
  const currency_ok=prices.length>0&&prices.every(e=>e.innerText.includes('$'));
  const label_ok=/^100\s*K(?:\s*\+\s*\d+(?:\.\d{1,6})?\s*K)?$/i.test(label.trim());
  return {ready:!!active&&tier==='100'&&label_ok&&!!price&&!!display&&currency_ok,active,tier,price,display,label,label_ok,currency_ok};
}"""


def collect_iggm(context):
    page = open_page(context, URLS["IGGM"])
    try:
        rows = []
        for platform, device in (("PS", "8"), ("XBOX", "10"), ("PC", "1")):
            page.locator(f'li[data-device_id="{device}"]').click(timeout=5000)
            page.wait_for_function("d => document.querySelector('li[data-device_id].active')?.getAttribute('data-device_id')===d", arg=device, timeout=8000)
            page.locator('span[data-num="100"]').click(timeout=5000)
            data = stable(page, IGGM_READ)
            if data["active"] != device:
                raise ValueError("platform_mismatch")
            rows.append(checked_offer("IGGM", platform, URLS["IGGM"],
                                      iggm_visible_price(data), 100, iggm_bonus_k(data)))
        return rows
    finally:
        page.close()


U4GM_READ = """() => {
  const tier=document.querySelector('[data-qty="100"]');
  const label=tier?.innerText?.trim()||'';
  const box=[...document.querySelectorAll('*')].filter(e=>e.children.length===0&&e.textContent.trim()==='Platform').at(-1)?.parentElement?.innerText||'';
  const amount=document.querySelector('.js-amount')?.innerText?.trim()||'';
  const price=amount.match(/\\$\\s*([\\d,.]+)/)?.[1]||null;
  const gift=label.match(/\\+\\s*(\\d+(?:\\.\\d+)?)\\s*K/i);
  return {ready:!!tier?.classList.contains('btn-buy')&&/^100\\s*K(?:\\s*\\+\\s*\\d+(?:\\.\\d+)?\\s*K)?$/i.test(label)&&!!price,
    platformText:box,price,bonus:gift?.[1]||'0',label};
}"""


def collect_u4gm(context):
    rows = []
    for platform, label, suffix in (("PS", "PS 4/5", ""),
                                    ("XBOX", "Xbox One/Series", "?server_code=xbox_one_series"),
                                    ("PC", "PC", "?server_code=pc")):
        url = URLS["U4GM"] + suffix
        page = open_page(context, url)
        try:
            page.locator('[data-qty="100"]').click(timeout=5000)
            data = stable(page, U4GM_READ)
            if label not in data["platformText"]:
                raise ValueError("platform_mismatch")
            rows.append(checked_offer("U4GM", platform, url,
                                      data["price"], 100, data["bonus"]))
        finally:
            page.close()
    return rows


U7BUY_READ = """label => {
  const active=[...document.querySelectorAll('.radio-select.active')].map(e=>e.textContent.trim());
  const cards=[...document.querySelectorAll('.players-reactive-table-content-wrapper')].filter(card=>
    [...card.querySelectorAll('.coins-name')].some(e=>e.innerText.trim()===`100K Safe Coins ${label}`));
  const card=cards.length===1?cards[0]:null;
  const text=card?.innerText||'';
  const price=text.match(/([\\d,.]+)\\s*USD/)?.[1]||null;
  const gift=text.match(/Newcomer\\s*\\+\\s*(\\d+(?:\\.\\d+)?)K/i);
  return {ready:active.length===1&&active[0]===label&&!!card&&!!price,
    active,price,bonus:gift?.[1]||'0',conditional:!!gift};
}"""


def collect_u7buy(context):
    page = open_page(context, URLS["U7Buy"])
    try:
        rows = []
        for platform, label in (("PS", "PS4/PS5"), ("XBOX", "XBOX"), ("PC", "PC")):
            page.locator('.radio-select').filter(has_text=label).click(timeout=5000)
            data = stable(page, U7BUY_READ, arg=label)
            if data["active"] != [label]:
                raise ValueError("platform_mismatch")
            rows.append(checked_offer("U7Buy", platform, URLS["U7Buy"],
                                      data["price"], 100, data["bonus"],
                                      conditional=data["conditional"]))
        return rows
    finally:
        page.close()


U7BUY_QUANTITIES_READ = """({label,quantities}) => {
  const active=[...document.querySelectorAll('.radio-select.active')].map(e=>e.textContent.trim());
  const offers=[],missing=[];
  for(const quantity of quantities){
    const cards=[...document.querySelectorAll('.players-reactive-table-content-wrapper')].filter(card=>
      [...card.querySelectorAll('.coins-name')].some(e=>e.innerText.trim()===`${quantity}K Safe Coins ${label}`));
    const content=cards.length===1?cards[0].innerText:'';
    const prices=[...content.matchAll(/([\\d,.]+)\\s*USD/g)].map(m=>m[1]);
    if(cards.length!==1||prices.length!==1){missing.push({purchase_k:quantity,reason:cards.length>1||prices.length>1?'native_card_ambiguous':'native_quantity_not_observed'});continue;}
    const gift=content.match(/Newcomer\\s*\\+\\s*(\\d+(?:\\.\\d+)?)K/i);
    offers.push({purchase_k:quantity,price:prices[0],bonus:gift?.[1]||'0',conditional:!!gift});
  }
  return {ready:active.length===1&&active[0]===label,active,offers,missing};
}"""


def collect_u7buy_quantities(context, quantities):
    """One native page read per platform; absent large cards remain unknown."""
    requested=tuple(str(v) for v in quantities)
    if not requested or len(set(requested))!=len(requested) or set(requested)-{'100','1000','2000','5000'}:
        raise ValueError('unsupported_native_quantity')
    page=open_page(context,URLS['U7Buy'])
    try:
        offers=[];missing=[]
        for platform,label in (('PS','PS4/PS5'),('XBOX','XBOX'),('PC','PC')):
            page.locator('.radio-select').filter(has_text=label).click(timeout=5000)
            data=stable(page,U7BUY_QUANTITIES_READ,arg=dict(label=label,quantities=requested))
            if data['active']!=[label]:raise ValueError('platform_mismatch')
            for raw in data['offers']:
                row=checked_offer('U7Buy',platform,URLS['U7Buy'],raw['price'],raw['purchase_k'],raw['bonus'],
                    conditional=raw['conditional'],quantities=requested)
                displayed = row.pop('gross_usd')
                row.pop('effective_usd_per_k')
                newcomer = raw['conditional']
                row.update(promotion_eligibility=dict(status='unknown', advertised_for='new_customer') if newcomer else 'all_customers',
                    display_price=displayed, regular_price=None if newcomer else displayed,
                    eligible_net_price=None,coupon_cap=None,usage_limit=None,
                    necessary_fees=None,tax_bearer=None,delivery_method=None,delivery_tier=None,
                    selection_verified=True,observation_basis='native_visible_card')
                offers.append(row)
            missing.extend(dict(source='U7Buy',platform=platform,**row) for row in data['missing'])
        return dict(source='U7Buy',status='valid',offers=offers,missing=missing,quantity_scope=list(requested))
    finally:page.close()


COLLECTORS = {"IGGM": collect_iggm, "U4GM": collect_u4gm, "U7Buy": collect_u7buy}


def timeout_diagnostic(exc):
    # Inspect only the API name; never emit exception text, URLs or page content.
    methods = ("BrowserType.connect_over_cdp", "BrowserContext.new_page",
               "Page.goto", "Page.evaluate", "Locator.click", "Page.close")
    method = next((name for name in methods if str(exc).startswith(name + ":")), None)
    codes = {"BrowserType.connect_over_cdp": "browser_connection_timeout",
             "BrowserContext.new_page": "page_create_timeout", "Page.goto": "page_navigation_timeout",
             "Page.evaluate": "page_read_timeout", "Locator.click": "platform_click_timeout",
             "Page.close": "page_close_timeout"}
    return codes.get(method, "collection_timeout"), {"api_method": method or "unrecorded"}


def main() -> int:
    source = sys.argv[1]
    if source not in COLLECTORS:
        raise SystemExit(2)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(
                os.environ.get("FC27_CDP_ENDPOINT", "http://127.0.0.1:9225"),
                timeout=8000, no_defaults=True)
            if len(browser.contexts) != 1:
                raise ValueError("browser_context_ambiguous")
            quantities=sys.argv[2].split(',') if len(sys.argv)>2 else None
            if quantities is not None:
                if source!='U7Buy':raise ValueError('quantity_collector_not_supported')
                result=collect_u7buy_quantities(browser.contexts[0],quantities)
                print(json.dumps(result));return 0
            rows = COLLECTORS[source](browser.contexts[0])
        if [row["platform"] for row in rows] != list(PLATFORMS):
            raise ValueError("platform_coverage_incomplete")
        print(json.dumps({"source": source, "status": "valid", "offers": rows}))
        return 0
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        diagnostic = {}
        if isinstance(exc, CollectorTimeoutError):
            reason, diagnostic = timeout_diagnostic(exc)
        print(json.dumps({"source": source, "status": "missing", "reason": reason[:60], "diagnostic": diagnostic}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
