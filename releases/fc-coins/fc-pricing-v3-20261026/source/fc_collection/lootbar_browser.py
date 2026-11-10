"""Fixed anonymous FC task for the existing qd-render worker, never its RPG config."""
import json
from datetime import datetime, timezone
from pathlib import Path
import time
from urllib.parse import urlsplit

PLATFORMS = {'PS':('PS4/5',''), 'XBOX':('Xbox','?platform=xbox'), 'PC':('PC','?platform=pc')}
BASE = 'https://www.lootbar.com/game-coins/fc27'


class RequestGate:
    def __init__(self, limit):
        self.limit, self.used, self.reason = limit, 0, None

    def allow(self, url, method):
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            return False
        if (self.reason or method not in ('GET','HEAD') or parsed.scheme != 'https'
                or not parsed.hostname or not (parsed.hostname == 'lootbar.com' or parsed.hostname.endswith('.lootbar.com'))
                or port not in (None,443) or parsed.username or parsed.password):
            return False
        if self.used >= self.limit:
            self.reason = 'request_budget_exhausted'
            return False
        self.used += 1
        return True

    def response(self, status, *, critical=True):
        if critical and status in (401,403,429):
            self.reason = 'http_'+str(status)


def validate_task(task):
    if (not isinstance(task, dict) or set(task) != {'platforms','request_limit','timeout_seconds'}
            or not isinstance(task['platforms'], list) or not task['platforms']
            or len(task['platforms']) != len(set(task['platforms'])) or set(task['platforms'])-set(PLATFORMS)
            or type(task['request_limit']) is not int or task['request_limit'] != 128
            or type(task['timeout_seconds']) is not int or not 1 <= task['timeout_seconds'] <= 75):
        raise ValueError('lootbar_render_task_invalid')
    return task


def read_parser():
    source = Path(__file__).with_name('lootbar_background.js').read_text(encoding='utf-8')
    start = source.index('function readVisibleOffer() {')
    end = source.index('\n\nasync function collectOne(target)', start)
    return source[start:end]


def collect(task):
    validate_task(task)
    from playwright.sync_api import sync_playwright
    reader = read_parser()
    end = time.monotonic() + task['timeout_seconds']
    gate = RequestGate(task['request_limit'])
    snapshots, errors = {}, {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            # A new context owns no RPG cookies/pages and is the only context we close.
            context = browser.new_context(locale='en-US', service_workers='block')
            try:
                def route(request_route):
                    request = request_route.request
                    if time.monotonic() >= end or not gate.allow(request.url, request.method):
                        request_route.abort()
                    else:
                        request_route.continue_()
                context.route('**/*', route)
                page = context.new_page()
                for platform in task['platforms']:
                    if gate.reason or time.monotonic() >= end:
                        errors[platform] = gate.reason or 'deadline_expired'
                        continue
                    label, query = PLATFORMS[platform]
                    try:
                        remaining = max(1, min(15000, int((end-time.monotonic())*1000)))
                        response = page.goto(BASE+query, wait_until='domcontentloaded', timeout=remaining)
                        # Account/avatar, image and analytics denials are not a public-price refusal.
                        if response is not None:
                            gate.response(response.status)
                        if gate.reason:
                            raise ValueError(gate.reason)
                        if response is None or response.status != 200 or urlsplit(page.url).hostname != 'www.lootbar.com':
                            raise ValueError('lootbar_page_unverified')
                        title = page.title()
                        if isinstance(title,str) and any(marker in title.lower() for marker in ('just a moment','verify you are human','security verification')):
                            gate.reason = 'challenge'
                            raise ValueError('challenge')
                        selected = page.evaluate('() => { '+reader+'; return readVisibleOffer(); }')
                        if selected.get('selected') != [label]:
                            selector = {'PS':'a.icon-ps','XBOX':'a.icon-xbox','PC':'a.icon-pc'}[platform]
                            page.locator(selector).click(timeout=max(1,min(8000,int((end-time.monotonic())*1000))))
                        previous, stable = None, 0
                        while time.monotonic() < end:
                            raw = page.evaluate('() => { '+reader+'; return readVisibleOffer(); }')
                            # Reuse the actual visible parser; anonymous auth is retained, never forged.
                            signature = json.dumps(raw, sort_keys=True)
                            stable = stable+1 if signature == previous else 1
                            previous = signature
                            if (raw.get('selected') == [label] and raw.get('currencyState') == 'ready'
                                    and raw.get('priceState') == 'ready' and raw.get('tierState') == 'ready'
                                    and raw.get('giftState') == 'ready' and stable >= 3):
                                raw['stable_reads'] = stable
                                raw['observed_at'] = datetime.now(timezone.utc).isoformat()
                                snapshots[platform] = raw
                                break
                            page.wait_for_timeout(min(300, max(1, int((end-time.monotonic())*1000))))
                        else:
                            raise ValueError('lootbar_fields_unverified')
                    except Exception as exc:
                        reason = gate.reason or (str(exc) if isinstance(exc, ValueError) else 'lootbar_page_timeout')
                        errors[platform] = reason
                return dict(snapshots=snapshots, platform_errors=errors, browser_requests_allowed=gate.used)
            finally:
                context.close()
        finally:
            browser.close()
