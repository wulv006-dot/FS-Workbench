"""Read MMOEXP's public FC27 Coins 100K offer; never submits an order or price change."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlencode


PAGE_URL = "https://www.mmoexp.com/Fc-27/Coins.html"
GOODS_URL = "https://www.mmoexp.com/ajax/goods"
STATE_FILE = Path(os.environ.get("FC27_STOREFRONT_STATE",
                                 "/var/lib/fc27-cloud/monitor/storefront.json"))
PLATFORMS = {"ps": "PS", "xbox": "XBOX", "pc": "PC"}


class ProductPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cid = None
        self.servers = {}

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "div" and attrs.get("id") == "container":
            self.cid = attrs.get("data-cid")
        if tag == "li" and attrs.get("data-code") in PLATFORMS:
            code = attrs["data-code"]
            if code in self.servers:
                raise ValueError("platform_mapping_ambiguous")
            self.servers[code] = attrs


def fetch(url, form=None, limit=2000000, cookie_jar=None):
    command = ["curl", "--fail", "--silent", "--show-error", "--location",
               "--max-time", "18", "--max-filesize", str(limit),
               "--proto", "=https", "--proto-redir", "=https",
               "--user-agent", "Mozilla/5.0 (compatible; FC27-price-monitor/1.0)",
               "--header", "Accept: text/html,application/json",
               "--header", "Cache-Control: no-cache", "--header", "Pragma: no-cache"]
    if cookie_jar is not None:
        command += ["--cookie-jar", str(cookie_jar)]
        if cookie_jar.exists():
            command += ["--cookie", str(cookie_jar)]
    if form is not None:
        command += ["--referer", PAGE_URL, "--header", "Content-Type: application/x-www-form-urlencoded",
                    "--data", urlencode(form)]
    result = subprocess.run(command + [url], capture_output=True, timeout=22)
    if result.returncode or not result.stdout or len(result.stdout) > limit:
        raise ValueError("source_unavailable")
    return result.stdout.decode("utf-8", "strict")


def page_mapping(html):
    if html.startswith('"'):
        try:
            html = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            raise ValueError("product_page_invalid") from None
        if not isinstance(html, str):
            raise ValueError("product_page_invalid")
    if "Buy FC 27 Coins" not in html:
        raise ValueError("product_page_invalid")
    parser = ProductPage()
    parser.feed(html)
    site = re.search(r"\bconst\s+site_id\s*=\s*`([0-9]+)`", html)
    if (parser.cid != "9623" or not site or site.group(1) != "266"
            or set(parser.servers) != set(PLATFORMS)):
        raise ValueError("product_mapping_changed")
    for code, row in parser.servers.items():
        if (row.get("data-gid") != "1327" or row.get("data-sign") != "$"
                or not str(row.get("data-id", "")).isdigit()):
            raise ValueError("product_mapping_changed")
    return {"cid": parser.cid, "site_id": site.group(1),
            "servers": {code: row["data-id"] for code, row in parser.servers.items()}}


def positive(value, code):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(code) from None
    if not number.is_finite() or number <= 0:
        raise ValueError(code)
    return number


def offer_from_response(payload):
    try:
        goods = payload["goods"]["index"]["list"]
        if not isinstance(goods, list) or len(goods) != 1 or goods[0]["unit"] != "K":
            raise ValueError("offer_mapping_changed")
        options = goods[0]["goods_list"]
        if not isinstance(options, dict):
            raise ValueError("offer_mapping_changed")
        matches = [item for item in options.values() if str(item.get("num")) == "100"]
        if len(matches) != 1:
            raise ValueError("offer_mapping_changed")
        item = matches[0]
        total = positive(item["price_discount"], "offer_price_invalid")
        bonus = Decimal(str(item["give"]))
        if not bonus.is_finite() or bonus < 0 or bonus > 100:
            raise ValueError("offer_bonus_invalid")
        sku = str(goods[0]["id"])
        if not sku.isdigit():
            raise ValueError("offer_mapping_changed")
    except (KeyError, TypeError, AttributeError):
        raise ValueError("offer_mapping_changed") from None
    effective = (total / (Decimal("100") + bonus)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return {"package_usd": str(total), "base_k": "100", "bonus_k": str(bonus),
            "usd_per_k": str(effective), "sku_id": sku}


def previous_rows():
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return payload.get("rows", {}) if isinstance(payload.get("rows"), dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def atomic_json(payload):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".storefront-", dir=STATE_FILE.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, STATE_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def collect(run_id=None):
    now = datetime.now(timezone.utc).isoformat()
    rows = {platform: dict(previous_rows().get(platform) or {}) for platform in PLATFORMS.values()}
    with tempfile.TemporaryDirectory(prefix="fc27-public-session-") as directory:
        jar = Path(directory) / "cookies.txt"
        try:
            mapping = page_mapping(fetch(PAGE_URL, cookie_jar=jar))
        except (ValueError, UnicodeError, subprocess.TimeoutExpired):
            mapping = None
        refreshed = 0
        for code, platform in PLATFORMS.items():
            try:
                if mapping is None:
                    raise ValueError("product_page_unavailable")
                form = {"Game_id": "1327", "top_cid": "1", "aid": mapping["servers"][code],
                        "cid": mapping["cid"], "site_id": mapping["site_id"]}
                offer = offer_from_response(json.loads(fetch(GOODS_URL, form, 100000, jar)))
                rows[platform] = {"platform": platform, **offer, "status": "ok",
                                  "checked_at": datetime.now(timezone.utc).isoformat(), "error": None}
                refreshed += 1
            except (ValueError, KeyError, TypeError, UnicodeError, subprocess.TimeoutExpired):
                rows[platform] = {**rows[platform], "platform": platform,
                                  "status": "unavailable", "error": "source_unavailable"}
    payload = {"source": PAGE_URL, "currency": "USD", "locale": "US/USD public page",
               "package_k": 100, "collection_run_id": run_id, "last_attempt_at": now,
               "status": "ok" if refreshed == 3 else "partial" if refreshed else "unavailable",
               "rows": rows}
    atomic_json(payload)
    return payload


if __name__ == "__main__":
    result = collect(sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps({"status": result["status"], "last_attempt_at": result["last_attempt_at"],
                      "refreshed_platforms": [name for name, row in result["rows"].items()
                                              if row["status"] == "ok"]}))
