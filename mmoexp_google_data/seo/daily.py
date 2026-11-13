"""Single nightly base batch. Optional AI has no import or synchronous callback here."""
import datetime as dt
from itertools import chain

from .contracts import BUSINESS_TZ, GAMES, make_daily_context, source_day_ended
from .order_reader import NativeOrderFactsReader
from .order_source import OrderSource
from . import snapshot


def run_daily(store, sources, clock=lambda: dt.datetime.now(dt.timezone.utc), admit=lambda: True, finish_margin_seconds=0):
    context = make_daily_context(clock())
    if not context.collection_allowed:
        return dict(status='outside_night_window')
    with snapshot.batch_lock(store.root):
        existing = store.root / 'snapshots' / ('seo-' + context.publication_date + '.json')
        if existing.exists():
            db, manifest = snapshot.open_snapshot(store.root, 'seo-' + context.publication_date)
            db.close()
            active=snapshot.current(store.root)
            if active and active.get('base_snapshot_id')==manifest['snapshot_id']:
                db,active=snapshot.open_snapshot(store.root,active['snapshot_id']);db.close()
                return dict(active,status='published')
            if snapshot.current(store.root) != manifest:
                snapshot.atomic_json(store.root/'current.json', manifest)
            return dict(manifest, status='published')
        tasks = []
        for index, source in enumerate(sources):
            for scope in GAMES:
                if getattr(source,'is_observation',False):
                    import json
                    with store.db() as db:
                        coverage=db.execute('SELECT quality FROM coverage WHERE source=? AND game=? AND source_date=?',(source.name,scope,context.publication_date)).fetchone()
                        cursor=db.execute('SELECT cursor FROM cursors WHERE source=? AND game=? AND source_date=?',(source.name,scope,context.publication_date)).fetchone()
                    slices=[] if coverage and json.loads(coverage[0]).get('attempt_complete') else [(context.publication_date,cursor[0] if cursor else 0)]
                else:slices=store.slices(source.name, scope, context)
                tasks.extend((day, index, scope, cursor) for day,cursor in slices)
        blocked = set()
        # One batch, latest dates first across all games; no game's old backfill monopolizes the night.
        tasks.sort(key=lambda item: (bool(getattr(sources[item[1]],'is_observation',False)),-dt.date.fromisoformat(item[0]).toordinal(),item[1],GAMES.index(item[2])))
        deferred_indices = {index for index,source in enumerate(sources)
            if isinstance(source,OrderSource) and isinstance(source.read,NativeOrderFactsReader)
            and any(day==context.report_date and i==index for day,i,_,_ in tasks)
            and source.read.defer_day(context.report_date)}
        deferred = [task for task in tasks if task[0] == context.report_date and task[1] in deferred_indices]
        if deferred:
            immediate = [task for task in tasks
                         if task not in deferred and task[0] >= context.report_date]
            backlog = [task for task in tasks if task[0] < context.report_date]
        else:
            immediate, backlog = tasks, []
        def may_continue():
            now = clock()
            local = now.astimezone(BUSINESS_TZ)
            remaining = (local.replace(hour=6, minute=30, second=0, microsecond=0)-local).total_seconds()
            return make_daily_context(now).publication_allowed and remaining > finish_margin_seconds and admit()
        def deferred_orders():
            checked = set()
            for task in deferred:
                day,index,_,_ = task
                if index not in checked:
                    if not may_continue():
                        return
                    sources[index].read.wait_for_day(day,may_continue)
                    checked.add(index)
                yield task
        for day, index, scope, cursor in chain(immediate,deferred_orders(),backlog):
            source = sources[index]
            if source.name in blocked:
                continue
            if not may_continue():
                break
            if not getattr(source, 'is_observation', False) and not source_day_ended(day, source.timezone, clock()):
                store.mark(source.name, scope, day, source.timezone, 'pending', clock().isoformat(), 'SOURCE_DAY_NOT_ENDED')
                continue
            try:
                pages=iter(source.pages(scope,day,cursor))
                while may_continue():
                    try:page=next(pages)
                    except StopIteration:break
                    store.ingest_page(source.name, scope, day, page, clock().isoformat())
            except (OSError, ValueError, RuntimeError) as error:
                # Persist only error class/codes, never provider response bodies or credentials.
                code = getattr(error, 'code', type(error).__name__)
                store.mark(source.name, scope, day, source.timezone, 'failed', clock().isoformat(), code)
                if isinstance(error, PermissionError) or getattr(error,'stop_source',False):
                    blocked.add(source.name)
                    for other in GAMES:
                        if other != scope:
                            store.mark(source.name, other, day, source.timezone, 'failed', clock().isoformat(), code)
        with store.db() as db:
            usable = db.execute('SELECT 1 FROM facts WHERE source_date BETWEEN ? AND ? LIMIT 1',
                                (context.history_start, context.report_date)).fetchone()
            if not usable:
                import json
                usable = any(json.loads(r[0]).get('expected_total') == 0 for r in db.execute(
                    "SELECT quality FROM coverage WHERE source='orders' AND status='available' AND source_date BETWEEN ? AND ?", (context.history_start,context.report_date)))
        if not usable:
            return dict(status='no_usable_data')
        if not make_daily_context(clock()).publication_allowed:
            return dict(status='publication_deadline', retained_work=True)
        candidate, meta = snapshot.build(store, context, source_names=[s.name for s in sources])
        if not make_daily_context(clock()).publication_allowed:
            candidate.unlink(missing_ok=True)
            return dict(status='publication_deadline', retained_work=True)
        return dict(snapshot.publish_once(store.root, candidate, meta), status='published')
