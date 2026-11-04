"""SEO-only scope and source dates; no model or runtime dependencies."""
import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

GAMES = ('FC27', 'D4', 'AION2', 'WOW_FOREVER')
BUSINESS_TZ = ZoneInfo('Asia/Shanghai')
SCHEMA = 'seo_daily_core_v2'


def game(value):
    if value not in GAMES:
        raise ValueError('INVALID_SEO_GAME')
    return value


@dataclass(frozen=True)
class DailyContext:
    now: dt.datetime
    publication_date: str
    report_date: str
    history_start: str
    collection_allowed: bool
    publication_allowed: bool


def make_daily_context(now, tz=BUSINESS_TZ):
    if now.tzinfo is None:
        raise ValueError('AWARE_TIME_REQUIRED')
    local = now.astimezone(tz)
    report = local.date() - dt.timedelta(days=1)
    return DailyContext(now, local.date().isoformat(), report.isoformat(),
                        (report - dt.timedelta(days=29)).isoformat(),
                        local.hour < 7, local.time().replace(tzinfo=None) < dt.time(6, 30))


def source_day_ended(source_date, source_timezone, now):
    day = dt.date.fromisoformat(source_date)
    return day < now.astimezone(ZoneInfo(source_timezone)).date()


def eligible_observations(records, report_date):
    day = dt.date.fromisoformat(report_date)
    return [r for r in records if dt.datetime.fromisoformat(r['observed_at']).astimezone(BUSINESS_TZ).date() == day]

# Verified MMOEXP main-site game bindings, 2026-11-05.
GAME_IDS = dict(FC27='1327', D4='456', AION2='891', WOW_FOREVER='1367')
SITE_ID = '266'
