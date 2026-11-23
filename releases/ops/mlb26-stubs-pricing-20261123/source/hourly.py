"""Generate one immutable MLB26 pricing preview per UTC hour."""

from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .pricing import PlatformQuotes, plan_prices


PLATFORMS = ("PS", "XBOX")
_ACCESS_LIMITS = {"http_401", "http_403", "http_429", "challenge"}


class QuoteUnavailable(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _collect_eldorado(platform, primary, backup):
    attempts = []
    for node, read in (("187", primary), ("183", backup)):
        if read is None:
            continue
        try:
            offer = read(platform)
        except QuoteUnavailable as error:
            attempts.append({"node": node, "reason": error.reason})
            if error.reason in _ACCESS_LIMITS:
                break
        else:
            return offer, {"node": node, "offer": asdict(offer), "attempts": attempts}
    return None, {"node": None, "offer": None, "attempts": attempts}


def _collect_iggm(platform, eldorado, read):
    if read is None:
        return None, {"status": "not_connected"}
    try:
        offer = read(platform, eldorado)
    except QuoteUnavailable as error:
        return None, {"status": "unavailable", "reason": error.reason}
    return offer.total_usd / offer.purchase_k, {"status": "observed", "offer": asdict(offer)}


def _save_first(path, preview):
    encoded = json.dumps(preview, indent=2, default=str) + "\n"
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as target:
        target.write(encoded)
    temporary = Path(target.name)
    try:
        # Publish only a complete receipt and keep the winner if two callers overlap.
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        temporary.unlink()
    return json.loads(path.read_text(encoding="utf-8"))


def preview_hour(directory, primary, *, backup=None, read_iggm=None, now=None):
    now = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    hour = now.replace(minute=0, second=0, microsecond=0)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (hour.strftime("%Y%m%dT%HZ") + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    evidence = {}
    rates = {}
    for platform in PLATFORMS:
        eldorado, eldorado_evidence = _collect_eldorado(platform, primary, backup)
        iggm, iggm_evidence = _collect_iggm(platform, eldorado, read_iggm)
        evidence[platform] = {"eldorado": eldorado_evidence, "iggm": iggm_evidence}
        rates[platform] = PlatformQuotes(eldorado.usd_per_k if eldorado else None, iggm)

    plan = plan_prices(playstation=rates["PS"], xbox=rates["XBOX"])
    targets = {platform: asdict(target) if target is not None else None
               for platform, target in plan.items()}
    preview = {
        "status": "preview_only",
        "hour_utc": hour.isoformat(),
        "started_at": now.isoformat(),
        "quotes": evidence,
        "targets": targets,
    }
    return _save_first(path, preview)
