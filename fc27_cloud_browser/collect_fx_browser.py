"""Read the same Bank of China USD/CNY field as the existing workbench."""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from playwright.sync_api import sync_playwright, TimeoutError as CollectorTimeoutError

URL = "https://www.bankofchina.com/sourcedb/whpj/"

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


try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            os.environ.get("FC27_CDP_ENDPOINT", "http://127.0.0.1:9225"),
            timeout=8000, no_defaults=True)
        if len(browser.contexts) != 1:
            raise ValueError("browser_context_ambiguous")
        page = browser.contexts[0].new_page()
        try:
            response = page.goto(URL, wait_until="domcontentloaded", timeout=35000)
            if response is None or response.status != 200:
                raise ValueError("fx_page_unavailable")
            cells = None
            for _ in range(20):
                cells = page.evaluate("""() => {
                  const row=[...document.querySelectorAll('tr')].find(tr=>tr.querySelector('td')?.innerText.trim()==='美元');
                  return row?[...row.querySelectorAll('td')].map(e=>e.innerText.trim()):null;
                }""")
                if cells and len(cells) >= 7:
                    break
                page.wait_for_timeout(500)
            if not cells or len(cells) < 7:
                raise ValueError("fx_row_missing")
            try:
                rate = Decimal(cells[5]) / Decimal(100)
            except (InvalidOperation, TypeError):
                raise ValueError("fx_value_invalid") from None
            if not rate.is_finite() or rate <= 0 or not cells[6]:
                raise ValueError("fx_value_invalid")
            print(json.dumps({"status": "valid", "cny_per_usd": str(rate),
                              "published_at": cells[6],
                              "checked_at": datetime.now(timezone.utc).isoformat(),
                              "url": URL}))
        finally:
            page.close()
except Exception as exc:
    reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    diagnostic = {}
    if isinstance(exc, CollectorTimeoutError):
        reason, diagnostic = timeout_diagnostic(exc)
    print(json.dumps({"status": "missing", "reason": reason[:60], "diagnostic": diagnostic}))
    raise SystemExit(1)
