"""Read the shared Admin/ES facts once per date in the existing nightly batch."""
import datetime as dt
import sys

from .contracts import GAME_IDS, SITE_ID, game, make_daily_context, source_day_ended
from .sources import SourceError


class NativeOrderFactsReader:
    def __init__(self, clock=lambda: dt.datetime.now(dt.timezone.utc), *, collect_many=None, request=None):
        self.clock, self.collect_many, self.request = clock, collect_many, request
        self.calls = 0
        self.day = None
        self.values = {}

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
            if self.collect_many is None or self.request is None:
                sys.path[:0] = [p for p in ('/opt/fs-exact-range-20261001', '/opt/fs-hermes-fc', '/opt/sales-dashboard/collector') if p not in sys.path]
                try:
                    if self.collect_many is None:
                        from order_facts_runtime import collect_many
                        self.collect_many = collect_many
                    if self.request is None:
                        from summary_bridge import dc_request
                        self.request = dc_request
                except ImportError:
                    error = SourceError('ORDER_FACTS_READER_NOT_INSTALLED')
                    error.stop_source = True
                    raise error from None
            def request(*args, **kwargs):
                if not make_daily_context(self.clock()).publication_allowed:
                    raise SourceError('NIGHT_DEADLINE')
                self.calls += 1
                return self.request(*args, **kwargs)
            scopes = [dict(start=day, end=day, site_id=SITE_ID, gid=gid) for gid in GAME_IDS.values()]
            values = self.collect_many(scopes, request=request)
            if len(values) != len(scopes):
                raise SourceError('ORDER_FACTS_BATCH_INCOMPLETE')
            self.values = dict(zip(GAME_IDS, values))
            self.day = day
        return self.values[scope]
