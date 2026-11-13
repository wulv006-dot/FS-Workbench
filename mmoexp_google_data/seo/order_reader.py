"""Read the shared Admin/ES facts once per date in the existing nightly batch."""
import datetime as dt
import sqlite3
import sys
import time

from .contracts import BUSINESS_TZ, GAME_IDS, SITE_ID, game, make_daily_context, source_day_ended
from .sources import SourceError


class NativeOrderFactsReader:
    def __init__(self, clock=lambda: dt.datetime.now(dt.timezone.utc), *, collect_many=None,
                 readiness=None, wait=time.sleep):
        self.clock, self.collect_many = clock, collect_many
        self.readiness = readiness if readiness is not None else self.shared_day_ready if collect_many is None else None
        self.wait = wait
        self.day = None
        self.values = {}

    @staticmethod
    def shared_day_ready(day):
        sys.path[:0] = [p for p in ('/opt/fs-exact-range-20261001', '/opt/fs-hermes-fc') if p not in sys.path]
        from shared_es_facts import read
        # Match the published full-site/day evidence without loading order membership.
        coverage = read(dict(start=day,end=day,site_id='all',gid='0'))['coverage']
        return coverage['admin_complete']

    def defer_day(self, day):
        if self.readiness is None or self.clock().astimezone(BUSINESS_TZ).time() >= dt.time(5,5):
            return False
        try:
            return not self.readiness(day)
        except (ImportError,OSError,ValueError,sqlite3.Error):
            return False

    def wait_for_day(self, day, remaining):
        while remaining():
            try:
                if self.readiness(day):
                    return
            except (ImportError,OSError,ValueError,sqlite3.Error):
                # The original read records the actual source failure and coverage.
                return
            now = self.clock().astimezone(BUSINESS_TZ)
            seconds = (now.replace(hour=5,minute=5,second=0,microsecond=0)-now).total_seconds()
            if seconds <= 0:
                return
            self.wait(min(seconds,30))

    def __call__(self, scope, day):
        game(scope)
        dt.date.fromisoformat(day)
        now = self.clock()
        if not make_daily_context(now).publication_allowed:
            raise SourceError('NIGHT_DEADLINE')
        if not source_day_ended(day, 'Asia/Shanghai', now):
            raise SourceError('SOURCE_DAY_NOT_ENDED')
        if self.day != day:
            self.day, self.values = None, {}
            # Same installed module roots as NativeSummaryReader; no new transport.
            if self.collect_many is None:
                sys.path[:0] = [p for p in ('/opt/fs-exact-range-20261001', '/opt/fs-hermes-fc') if p not in sys.path]
                try:
                    from order_facts_runtime import collect_shared_many
                    from shared_es_facts import read
                    self.collect_many = lambda scopes: collect_shared_many(scopes,reader=read)
                except ImportError:
                    error = SourceError('ORDER_FACTS_READER_NOT_INSTALLED')
                    error.stop_source = True
                    raise error from None
            scopes = [dict(start=day, end=day, site_id=SITE_ID, gid=gid) for gid in GAME_IDS.values()]
            try:
                values = self.collect_many(scopes)
            except sqlite3.Error:
                raise SourceError('ORDER_FACTS_SHARED_DATABASE_UNAVAILABLE') from None
            if not make_daily_context(self.clock()).publication_allowed:
                raise SourceError('NIGHT_DEADLINE')
            if len(values) != len(scopes):
                raise SourceError('ORDER_FACTS_BATCH_INCOMPLETE')
            self.values = dict(zip(GAME_IDS, values))
            self.day = day
        return self.values[scope]
