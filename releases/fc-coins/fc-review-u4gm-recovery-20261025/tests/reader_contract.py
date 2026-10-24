from datetime import datetime, timezone
from decimal import Decimal
import json, time


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

def checked_offer(source, platform, url, price, base, bonus, *, conditional=False):
    amount = positive(price)
    if Decimal(str(base)) != 100:
        raise ValueError("not_100k")
    try:
        bonus_value = Decimal(str(bonus))
    except (InvalidOperation, TypeError):
        raise ValueError("invalid_bonus") from None
    if not bonus_value.is_finite() or bonus_value < 0:
        raise ValueError("invalid_bonus")
    return {"source": source, "platform": platform,
            "captured_at": datetime.now(timezone.utc).isoformat(), "url": url,
            "currency": "USD", "purchase_k": "100", "bonus_k": str(bonus_value),
            "gross_usd": str(amount),
            "effective_usd_per_k": str(amount / (Decimal(100) + bonus_value)),
            "coupon_excluded": True, "auth_state": "public",
            "conditional": conditional, "comparable": not conditional,
            "status": "valid", "reason": None}

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

def timeout_diagnostic(error):return type(error).__name__, {}
