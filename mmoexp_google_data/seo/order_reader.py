"""Read the shared Admin/ES facts once per date in the existing nightly batch."""
import datetime as dt
import sys

from .contracts import GAME_IDS, SITE_ID, game, make_daily_context, source_day_ended
from .sources import SourceError


class NativeOrderFactsReader:
    def __init__(self, clock=lambda: dt.datetime.now(dt.timezone.utc), *, collect_many=None):
        self.clock, self.collect_many = clock, collect_many
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
            values = self.collect_many(scopes)
            if not make_daily_context(self.clock()).publication_allowed:
                raise SourceError('NIGHT_DEADLINE')
            if len(values) != len(scopes):
                raise SourceError('ORDER_FACTS_BATCH_INCOMPLETE')
            self.values = dict(zip(GAME_IDS, values))
            self.day = day
        return self.values[scope]
