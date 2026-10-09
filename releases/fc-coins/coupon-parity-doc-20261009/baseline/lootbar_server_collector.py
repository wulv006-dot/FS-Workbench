"""Read FC27 100K Lootbar offers from the already logged-in Chrome via CDP.

This prototype never logs in, reads browser storage, or writes a quote. It reuses
the exact readVisibleOffer() function from adjacent background.js. It switches
platforms within the one existing tab and restores PS before returning.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import argparse
import json
import os
from pathlib import Path
import queue
import re
import threading
import time
from urllib.parse import urlsplit


CDP_ENDPOINT = os.environ.get("FC27_CDP_ENDPOINT", "http://127.0.0.1:9223")
BASE_URL = "https://www.lootbar.com/game-coins/fc27"
READER_SOURCE = Path(__file__).with_name("background.js")
COLLECT_TIMEOUT_SECONDS = 65
TARGETS = (
    ("PS", "PS4/5", "a.icon-ps"),
    ("XBOX", "Xbox", "a.icon-xbox"),
    ("PC", "PC", "a.icon-pc"),
)


class CollectionError(RuntimeError):
    """Safe-to-display failure with no page text or URL attached."""


def emit(stage: str, **fields) -> None:
    # ASCII JSON survives remote SSH consoles with a non-UTF-8 code page.
    print(json.dumps({"stage": stage, **fields}, ensure_ascii=True), flush=True)


def load_reader(source_path: Path = READER_SOURCE) -> str:
    """Extract the extension's self-contained parser without copying its logic."""
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CollectionError("Lootbar 解析规则文件不可用") from exc
    start_marker = "function readVisibleOffer() {"
    end_marker = "\n\nasync function collectOne(target)"
    start = source.find(start_marker)
    end = source.find(end_marker, start + len(start_marker)) if start >= 0 else -1
    if start < 0 or end < 0:
        raise CollectionError("无法从 background.js 定位稳定的 Lootbar 解析函数")
    return source[start:end].strip()


def _positive_decimal(value, *, allow_zero: bool = False) -> Decimal | None:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    raw = str(value)
    if not re.fullmatch(r"\d+(?:\.\d{1,6})?", raw):
        return None
    try:
        number = Decimal(raw)
    except InvalidOperation:
        return None
    if not number.is_finite() or (number < 0 if allow_zero else number <= 0):
        return None
    return number


def _cents(value) -> int | None:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    raw = str(value)
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", raw):
        return None
    try:
        return int(Decimal(raw) * 100)
    except (InvalidOperation, ValueError):
        return None


def snapshot_error(snapshot: dict, selected_label: str, stable_reads: int = 3) -> str | None:
    """Fail closed on any missing or ambiguous parser field."""
    if not isinstance(snapshot, dict):
        return "Lootbar 页面未能读取"
    if snapshot.get("selected") != [selected_label]:
        return f"{selected_label} 平台未唯一核实"
    if snapshot.get("loggedIn") is not True:
        return "Lootbar 登录状态未核实"
    if snapshot.get("currencyState") != "ready":
        return "币种或页面语言未核实为 EN / USD"
    if snapshot.get("tierState") != "ready" or _positive_decimal(snapshot.get("baseK")) != Decimal("100"):
        return "100K Safe Coins 商品规格未唯一核实"
    if snapshot.get("priceState") != "ready" or _positive_decimal(snapshot.get("usdPrice")) is None:
        return "当前 USD 售价缺失或格式不清"
    if snapshot.get("giftState") != "ready" or _positive_decimal(snapshot.get("bonusK"), allow_zero=True) is None:
        return "赠送量缺失或格式不清，未按 0 处理"

    coupon_state = snapshot.get("couponState")
    if coupon_state == "excluded":
        original = _cents(snapshot.get("usdPrice"))
        coupon_price = _cents(snapshot.get("observedCouponPrice"))
        discount = _cents(snapshot.get("excludedCouponDiscount"))
        if original is None or coupon_price is None or discount is None or discount <= 0:
            return "新客券前原价、券后价或减免金额无法精确核实"
        if original - coupon_price != discount:
            return "新客券前原价、券后价与减免金额关系不符"
    elif coupon_state == "none":
        if snapshot.get("observedCouponPrice") is not None or snapshot.get("excludedCouponDiscount") is not None:
            return "优惠券字段与普通价状态冲突"
    else:
        return "优惠券或划线原价信息缺失或有歧义"
    if stable_reads < 3:
        return "报价信息未能连续稳定读取"
    return None


def _offer(platform: str, snapshot: dict) -> dict:
    coupon_excluded = snapshot["couponState"] == "excluded"
    result = {
        "platform": platform,
        "base_k": "100",
        "usd_price": str(snapshot["usdPrice"]),
        "bonus_k": str(snapshot["bonusK"]),
        "coupon_excluded": coupon_excluded,
        "price_basis": "券前原价（已排除账号新客券）" if coupon_excluded else "当前无券商品价",
    }
    if coupon_excluded:
        result["observed_coupon_price"] = str(snapshot["observedCouponPrice"])
        result["excluded_coupon_discount"] = str(snapshot["excludedCouponDiscount"])
    return result


def _platform_controls(page) -> list[dict]:
    return page.evaluate(r"""() => {
      const visible=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();
        return s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'&&r.width>0&&r.height>0;};
      const norm=e=>String(e.innerText||'').replace(/\s+/g,' ').trim().toLowerCase();
      const known=new Set(['ps4/5','xbox','pc']);
      return [...document.querySelectorAll('a,button,[role="button"]')]
        .map((el,index)=>({index,label:norm(el),visible:visible(el)}))
        .filter(item=>item.visible&&known.has(item.label));
    }""")


def _read_snapshot(page, reader_source: str) -> dict | None:
    return page.evaluate(f"() => ({reader_source})()")


def _stable_offer(page, reader_source: str, platform: str, label: str) -> tuple[dict, int]:
    prior = None
    stable = 0
    last = None
    for attempt in range(1, 25):
        emit("offer_read_started", platform=platform, attempt=attempt)
        last = _read_snapshot(page, reader_source)
        validation_error = snapshot_error(last, label, stable_reads=3)
        if validation_error is None:
            signature = json.dumps(last, sort_keys=True, ensure_ascii=False)
            stable = stable + 1 if signature == prior else 1
            prior = signature
            emit("offer_read_finished", platform=platform, fields_ready=True,
                 stable_reads=stable)
            if stable >= 3:
                return _offer(platform, last), stable
        else:
            prior, stable = None, 0
            emit("offer_read_finished", platform=platform, fields_ready=False,
                 reason=validation_error)
        time.sleep(0.4)
    reason = snapshot_error(last, label, stable_reads=stable)
    raise CollectionError(f"{platform}：{reason or '报价信息未能连续稳定读取'}")


def _is_product_page(page) -> bool:
    parsed = urlsplit(page.url)
    return parsed.hostname == "www.lootbar.com" and parsed.path.rstrip("/") == "/game-coins/fc27"


def _collect_attached(*, single_ps: bool = False) -> dict:
    """Attach to one existing tab and read each platform sequentially."""
    reader_source = load_reader()
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CollectionError("当前 Python 环境未安装 Playwright") from exc

    emit("cdp_connecting")
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            CDP_ENDPOINT, timeout=8000, no_defaults=True)
        emit("cdp_connected")
        if len(browser.contexts) != 1:
            raise CollectionError("Chrome 默认登录上下文未唯一核实")
        context = browser.contexts[0]
        context.set_default_timeout(4000)
        context.set_default_navigation_timeout(12000)
        emit("inspecting_product_tabs")
        original_pages = [page for page in context.pages if _is_product_page(page)]
        if len(original_pages) != 1:
            raise CollectionError("请在已登录 Chrome 中只保留一个 FC27 Coins 商品页")
        original = original_pages[0]
        emit("checking_login_marker")
        original_state = _read_snapshot(original, reader_source)
        if not isinstance(original_state, dict) or original_state.get("loggedIn") is not True:
            raise CollectionError("当前 FC27 Coins 页的登录头像标记未核实")
        emit("checking_platform_controls")
        controls = _platform_controls(original)
        labels = {item["label"] for item in controls}
        if not {"ps4/5", "xbox", "pc"}.issubset(labels):
            raise CollectionError("PS4/5、Xbox、PC 平台控件未全部显示")
        emit("cdp_ready", product_page_count=1, login_marker=True, platform_controls=3)

        offers = {}
        # The operator's existing PS page is already rendered. Read it first so
        # the smallest server can validate one platform without opening a tab.
        emit("platform_starting", platform="PS")
        try:
            ps_offer, ps_reads = _stable_offer(original, reader_source, "PS", "PS4/5")
        except PlaywrightTimeoutError as exc:
            raise CollectionError("PS：现有商品页读取超时") from exc
        offers["PS"] = ps_offer
        emit("platform_collected", platform="PS", fields_ready=True,
             coupon_excluded=ps_offer["coupon_excluded"], stable_reads=ps_reads)

        if not single_ps:
            try:
                for platform, label, selector in TARGETS[1:]:
                    emit("platform_starting", platform=platform)
                    try:
                        emit("platform_click_started", platform=platform)
                        original.locator(selector).click(timeout=4000)
                        emit("platform_click_finished", platform=platform)
                        offer, stable_reads = _stable_offer(
                            original, reader_source, platform, label)
                    except PlaywrightTimeoutError as exc:
                        raise CollectionError(f"{platform}：平台切换或读取超时") from exc
                    except CollectionError:
                        raise
                    except Exception as exc:
                        raise CollectionError(f"{platform}：采集失败（{type(exc).__name__}）") from exc
                    offers[platform] = offer
                    emit("platform_collected", platform=platform, fields_ready=True,
                         coupon_excluded=offer["coupon_excluded"], stable_reads=stable_reads)
            finally:
                emit("ps_restore_started")
                try:
                    original.locator(TARGETS[0][2]).click(timeout=4000)
                    for _ in range(12):
                        restored = _read_snapshot(original, reader_source)
                        if isinstance(restored, dict) and restored.get("selected") == ["PS4/5"]:
                            emit("ps_restored")
                            break
                        time.sleep(0.25)
                    else:
                        raise CollectionError("PS 页面未能恢复到原平台")
                except Exception as exc:
                    emit("ps_restore_failed", reason=type(exc).__name__)
                    raise CollectionError("PS 页面恢复失败") from exc

        return {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "offers": offers, "read_only": True}


def collect(*, single_ps: bool = False) -> dict:
    """Run the complete CDP pass under a hard wall-clock deadline.

    Playwright does not expose per-call timeouts for every CDP operation
    (notably evaluate). A daemon worker bounds those calls as a group.
    """
    result_queue: queue.Queue = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            result_queue.put((True, _collect_attached(single_ps=single_ps)))
        except Exception as exc:
            result_queue.put((False, exc))

    worker = threading.Thread(target=run, name="lootbar-cdp-reader", daemon=True)
    worker.start()
    worker.join(COLLECT_TIMEOUT_SECONDS)
    if worker.is_alive():
        raise CollectionError(
            f"采集超过 {COLLECT_TIMEOUT_SECONDS} 秒总时限；停止等待，当前临时页可能仍保留")
    try:
        ok, value = result_queue.get_nowait()
    except queue.Empty as exc:
        raise CollectionError("采集线程未返回结果") from exc
    if ok:
        return value
    raise value


def main() -> int:
    parser = argparse.ArgumentParser(description="Read Lootbar offers from the existing Chrome session")
    parser.add_argument("--existing-ps-only", action="store_true",
                        help="validate the existing PS page without switching platform")
    args = parser.parse_args()
    try:
        result = collect(single_ps=args.existing_ps_only)
        emit("complete", **result)
        return 0
    except CollectionError as exc:
        emit("failed", reason=str(exc))
        return 1
    except Exception as exc:
        # Never print exception text: it may contain a URL or page details.
        emit("failed", reason=type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
