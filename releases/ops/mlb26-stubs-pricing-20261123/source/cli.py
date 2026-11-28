"""Read-only MLB26 Eldorado collector and hourly pricing preview CLI."""

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import re
from pathlib import Path
import subprocess

from .eldorado import collect_eldorado, is_access_challenge
from .hourly import PLATFORMS, QuoteUnavailable, preview_hour
from .iggm import load_iggm_receipt
from .order_preview import order_readback_preview
from .quotes import EldoradoOffer


def _from_browser(context, platform):
    from playwright.sync_api import Error, TimeoutError

    if context is None:
        raise QuoteUnavailable("browser_unavailable")
    try:
        with context.new_page() as page:
            try:
                return collect_eldorado(page, platform)
            except TimeoutError:
                reason = "challenge" if is_access_challenge(page) else "browser_timeout"
                raise QuoteUnavailable(reason) from None
    except Error:
        raise QuoteUnavailable("browser_unavailable") from None
    except ValueError as error:
        raise QuoteUnavailable(str(error).removeprefix("eldorado_")) from None


def _read_worker(executable, platform, node):
    try:
        result = subprocess.run(
            [str(executable), platform], capture_output=True, timeout=30, check=False,
        )
    except subprocess.TimeoutExpired:
        raise QuoteUnavailable("collector_timeout") from None
    except OSError:
        raise QuoteUnavailable("collector_worker_unavailable") from None
    if result.returncode or len(result.stdout) > 8192:
        raise QuoteUnavailable("collector_worker_failed")

    try:
        receipt = json.loads(result.stdout)
        if (receipt["node"] != node or receipt["platform"] != platform or receipt["currency"] != "USD"
                or receipt["product"] != "MLB26_STUBS" or receipt["source"] != "Eldorado"):
            raise ValueError
        observed = datetime.fromisoformat(receipt["observed_at"])
        age = datetime.now(timezone.utc) - observed
        if not timedelta(0) <= age <= timedelta(minutes=2):
            raise ValueError
        if "error" in receipt:
            reason = receipt["error"]
            if not isinstance(reason, str) or not re.fullmatch(r"[a-z0-9_]{1,80}", reason):
                raise ValueError
            raise QuoteUnavailable(reason)
        data = receipt["offer"]
        rate = Decimal(data["usd_per_k"])
        minimum = Decimal(data["minimum_k"])
        stock = Decimal(data["stock_k"])
        seller = data["seller"]
        if (not all(value.is_finite() for value in (rate, minimum, stock))
                or rate <= 0 or minimum <= 0 or stock < minimum
                or not isinstance(seller, str) or not seller.strip()):
            raise ValueError
    except QuoteUnavailable:
        raise
    except (InvalidOperation, KeyError, TypeError, ValueError, OverflowError):
        raise QuoteUnavailable("collector_receipt_invalid") from None
    return EldoradoOffer(seller, rate, minimum, stock)


def _worker_result(context, platform, node):
    receipt = {
        "node": node, "platform": platform, "currency": "USD",
        "product": "MLB26_STUBS", "source": "Eldorado",
    }
    try:
        receipt["offer"] = asdict(_from_browser(context, platform))
    except QuoteUnavailable as error:
        receipt["error"] = error.reason
    receipt["observed_at"] = datetime.now(timezone.utc).isoformat()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    preview = subcommands.add_parser("preview")
    preview.add_argument("--state-dir", type=Path, required=True)
    preview.add_argument("--primary-worker", type=Path)
    preview.add_argument("--backup-worker", type=Path)
    preview.add_argument("--iggm-receipt", type=Path)
    preview.add_argument("--order-snapshot", type=Path)
    preview.add_argument("--chrome", action="store_true", help="Use installed Google Chrome")
    main_worker = subcommands.add_parser("primary")
    main_worker.add_argument("platform", choices=PLATFORMS)
    main_worker.add_argument("--chrome", action="store_true", help="Use installed Google Chrome")
    worker = subcommands.add_parser("backup")
    worker.add_argument("platform", choices=PLATFORMS)
    worker.add_argument("--chrome", action="store_true", help="Use installed Google Chrome")
    args = parser.parse_args()

    if args.command == "preview":
        for executable in (args.primary_worker, args.backup_worker):
            if executable is not None and not executable.is_absolute():
                parser.error("workers must be absolute local executable paths")

    backup = None
    if args.command == "preview" and args.backup_worker is not None:
        def backup(platform):
            return _read_worker(args.backup_worker, platform, "183")

    iggm = None
    if args.command == "preview" and args.iggm_receipt is not None:
        iggm = load_iggm_receipt(args.iggm_receipt)

    if args.command == "preview" and args.primary_worker is not None:
        result = preview_hour(
            args.state_dir,
            lambda platform: _read_worker(args.primary_worker, platform, "187"),
            backup=backup, read_iggm=iggm,
        )
    else:
        result = _browser_result(args, backup, iggm)

    if args.command == "preview" and args.order_snapshot is not None:
        try:
            snapshot = json.loads(args.order_snapshot.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            result["order_preview"] = {"status": "unavailable", "reason": "mlb_order_snapshot_unreadable"}
        else:
            try:
                result["order_preview"] = order_readback_preview(snapshot, result["targets"])
            except ValueError as error:
                result["order_preview"] = {"status": "unavailable", "reason": str(error)}

    print(json.dumps(result, default=str, ensure_ascii=False))


def _browser_result(args, backup, iggm):
    from playwright.sync_api import Error, sync_playwright

    with sync_playwright() as driver:
        options = {"channel": "chrome"} if args.chrome else {}
        browser = None
        try:
            browser = driver.chromium.launch(headless=True, **options)
            context = browser.new_context(locale="en-US", service_workers="block")
        except Error:
            context = None

        try:
            if args.command in ("primary", "backup"):
                result = _worker_result(context, args.platform, "187" if args.command == "primary" else "183")
            else:
                result = preview_hour(
                    args.state_dir, lambda platform: _from_browser(context, platform),
                    backup=backup, read_iggm=iggm,
                )
        finally:
            if browser is not None:
                browser.close()
    return result


if __name__ == "__main__":
    main()
