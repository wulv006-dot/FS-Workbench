"""Read current FC27 Game Coins procurement records in server Chrome."""
from __future__ import annotations
from isolated_backend import open_backend, close_backend

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
import re
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

BASE = "https://order.p2pah.cn/order/admin_delivery/index.html"
PLATFORMS = ("PS", "XBOX", "PC")
SHANGHAI = ZoneInfo("Asia/Shanghai")


def cost_url(page: int) -> str:
    today = datetime.now(SHANGHAI).date()
    query = {"gid": "1322", "aid": "0", "cid": "1",
             "start": str(today - timedelta(days=7)) + " 00:00",
             "end": str(today + timedelta(days=1)) + " 00:00",
             "show_ccy": "-1", "genre": "1", "status": "-1", "op_id": "0",
             "is_stock": "", "keyword": "", "sn": "", "page": str(page)}
    return BASE + "?" + urlencode(query)


READ_ROWS = r"""() => ({
  login:location.pathname.includes('login.html'),
  page:new URLSearchParams(location.search).get('page'),
  game:document.querySelector('#lot-game')?.value,
  genre:document.querySelector('#lot-genre')?.value,
  typeHeader:document.querySelector('table.table-list thead th:nth-child(3)')?.innerText.trim(),
  product:document.querySelector('#lot-type')?.value,
  table:!!document.querySelector('table.table-list'),
  hasDataRows:[...document.querySelectorAll('tr')].some(tr=>tr.querySelector('td')),
  empty:document.body?.innerText.includes('暂无数据')||false,
  rows:[...document.querySelectorAll('tr')].map(tr=>{
    const c=[...tr.children].filter(x=>x.tagName==='TD');
    const platform=c[6]?.innerText?.trim().match(/^FC\s*27\s*▶\s*(PS|XBOX|PC)$/i)?.[1];
    return platform?{platform:platform.toUpperCase(),record_id:c[1]?.innerText.trim(),
      delivery_type:c[2]?.innerText.trim(),trade_at:c[5]?.innerText.trim(),cny_per_1k:c[9]?.innerText.trim()}:null;
  }).filter(Boolean)
})"""


ORDER_DELIVERY = "\u8ba2\u5355\u53d1\u8d27"
NON_COST_TYPES = {"\u91c7\u8d2d\u6253\u6b3e", "\u9500\u552e\u8865\u53d1", "\u9500\u552e\u8d60\u9001"}


def valid_record(raw: dict):
    if raw.get("platform") not in PLATFORMS:
        return None
    delivery_type = raw.get("delivery_type")
    if delivery_type in NON_COST_TYPES:
        return None
    if delivery_type != ORDER_DELIVERY:
        # Missing or unknown type cannot fall back to an older cost or be retried as a timeout.
        raise ValueError("cost_delivery_type_unverified")
    record_id = str(raw.get("record_id") or "")
    if not re.fullmatch(r"\d+", record_id):
        return None
    try:
        cost = Decimal(str(raw.get("cny_per_1k")))
        trade_text = str(raw.get("trade_at")).strip()
        if re.fullmatch(r"\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", trade_text):
            traded = datetime.strptime(trade_text, "%y-%m-%d %H:%M:%S")
        else:
            traded = datetime.fromisoformat(trade_text.replace("/", "-"))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not cost.is_finite() or cost <= 0 or traded.tzinfo is not None:
        return None
    trade_time = traded.replace(tzinfo=SHANGHAI)
    now = datetime.now(timezone.utc)
    if trade_time > now + timedelta(minutes=5) or trade_time < now - timedelta(days=8):
        return None
    return trade_time, {"game": "FC27", "product": "Game Coins",
                        "platform": raw["platform"], "record_id": record_id,
                        "traded_at": raw["trade_at"], "trade_at": raw["trade_at"],
                        "cny_per_k": str(cost), "cny_per_1k": str(cost),
                        "unit": "CNY/K", "status": "valid",
                        "delivery_type": ORDER_DELIVERY, "genre": "1"}


CollectorTimeoutError = PlaywrightTimeoutError


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


class CostPageError(ValueError):
    def __init__(self, reason, diagnostic):
        super().__init__(reason)
        self.diagnostic = diagnostic


def read_page(page, number, observations=None):
    diagnostic = {"requested_page": number, "http_status": None,
                  "checked_at": datetime.now(timezone.utc).isoformat()}
    try:
        response = page.goto(cost_url(number), wait_until="commit", timeout=35000)
    except PlaywrightTimeoutError:
        raise CostPageError(f"order_page_navigation_timeout:{number}", diagnostic) from None
    diagnostic["http_status"] = response.status if response is not None else None
    if diagnostic["http_status"] is not None and diagnostic["http_status"] >= 400:
        raise CostPageError(f"order_page_http_error:{number}:{response.status}", diagnostic)
    # A committed navigation may still be rendering. The page/filter checks below
    # ensure that no previous page or incomplete table can be treated as evidence.
    for _ in range(40):
        try:
            data = page.evaluate(READ_ROWS)
        except PlaywrightTimeoutError:
            raise CostPageError(f"order_page_read_timeout:{number}", diagnostic) from None
        diagnostic["observed"] = {k: data.get(k) for k in
                                  ("login", "page", "game", "product", "genre", "typeHeader", "table", "hasDataRows", "empty")}
        if data.get("login"):
            raise CostPageError("login_expired", diagnostic)
        if (data.get("page") == str(number) and data.get("game") == "1322"
                and data.get("product") == "1" and data.get("genre") == "1"
                and data.get("typeHeader") == "\u4ea4\u8d27\u7c7b\u578b" and data.get("table") is True
                and (data["hasDataRows"] or data["empty"])):
            if observations is not None:
                observations.append(diagnostic)
            return data
        page.wait_for_timeout(500)
    raise CostPageError(f"filter_or_rows_unverified:{number}", diagnostic)


def collect():
    with sync_playwright() as playwright:
        # The owned context already has the verified shared identity; do not fetch it twice.
        browser = open_backend(playwright)
        if len(browser.contexts) != 1:
            raise ValueError("browser_context_ambiguous")
        tab = browser.contexts[0].new_page()
        primary_error = None
        try:
            found = {}
            observations = []
            for number in range(1, 16):
                data = read_page(tab, number, observations)
                for raw in data["rows"]:
                    valid = valid_record(raw)
                    if not valid:
                        continue
                    traded, record = valid
                    platform = record["platform"]
                    if platform not in found or traded > found[platform][0]:
                        found[platform] = (traded, record)
                if not data["hasDataRows"] or data["empty"]:
                    break
            checked_at = datetime.now(timezone.utc).isoformat()
            records = []
            for platform in PLATFORMS:
                if platform in found:
                    records.append({**found[platform][1], "checked_at": checked_at})
                else:
                    records.append({"platform": platform, "status": "missing",
                                    "reason": "no_valid_recent_record"})
            return {"status": "valid" if all(r["status"] == "valid" for r in records) else "incomplete",
                    "checked_at": checked_at, "costs": records, "page_observations": observations}
        except Exception as exc:
            primary_error = exc
            raise
        finally:
            try:
                close_backend(tab)
            except Exception:
                if primary_error is None:
                    raise


def failure_result(exc):
    # Preserve only machine reason codes and frame names; never print cookies or exception text.
    frames = []
    tb = exc.__traceback__
    while tb is not None:
        frames.append((tb.tb_frame.f_code.co_filename.rsplit('/', 1)[-1].rsplit('\\', 1)[-1], tb.tb_frame.f_code.co_name))
        tb = tb.tb_next
    session = str(exc) if isinstance(exc, RuntimeError) else ''
    is_session = bool(re.fullmatch(r'global_order_unavailable(?::[A-Za-z][A-Za-z0-9_]{0,79})?', session))
    stage = ('shared_order_session' if is_session or any(f == 'fs_order_client.py' for f, _ in frames) else
             'backend_startup' if any(n == 'open_backend' for _, n in frames) else
             'cost_page' if any(n == 'read_page' for _, n in frames) else
             'backend_cleanup' if any(n == 'close_backend' for _, n in frames) else 'cost_collection')
    value = str(exc)
    reason = session if is_session else value if isinstance(exc, ValueError) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_:,.-]{0,119}', value) else type(exc).__name__
    result = {'status': 'missing', 'reason': reason[:120],
              'diagnostic': {'stage': stage, 'exception_type': type(exc).__name__}}
    if isinstance(exc, CollectorTimeoutError):
        result['reason'], detail = timeout_diagnostic(exc)
        result['diagnostic'].update(detail)
    if isinstance(exc, CostPageError):
        result['diagnostic'].update(exc.diagnostic)
    return result


if __name__ == "__main__":
    try:
        result = collect()
        print(json.dumps(result))
        raise SystemExit(0 if result["status"] == "valid" else 1)
    except Exception as exc:
        result = failure_result(exc)
        print(json.dumps(result))
        raise SystemExit(1)
